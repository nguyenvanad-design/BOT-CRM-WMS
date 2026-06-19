# core/session_store.py
# TOKINARC Session Memory — in-memory context store với TTL + Vision confirm state
# + History buffer 50 turns: tự summary khi đầy, reset sau summary
# ==================================================================================
# UTF-8 NO BOM

from __future__ import annotations

import logging
import re as _re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import List, Optional

log = logging.getLogger("tokinarc.session_store")

SESSION_TTL    = 30 * 60
MAX_SESSIONS   = 5_000
HISTORY_LIMIT  = 50   # số turn tối đa trước khi summary + reset


@dataclass
class TurnEntry:
    """1 turn hội thoại: query + response."""
    query:    str
    response: str
    intent:   str = ""
    parts:    List[str] = field(default_factory=list)


@dataclass
class SessionContext:
    session_id: str

    # Entities từ turn gần nhất
    last_intent:         str = ""
    last_part_nos:       List[str] = field(default_factory=list)
    last_d_part_nos:     List[str] = field(default_factory=list)
    last_p_part_nos:     List[str] = field(default_factory=list)
    last_torch_models:   List[str] = field(default_factory=list)
    last_ecosystem:      Optional[str] = None
    last_current_class:  Optional[str] = None
    last_wire_size:      Optional[float] = None
    last_categories:     List[str] = field(default_factory=list)
    last_returned_parts: List[str] = field(default_factory=list)
    last_query:           str = ""
    last_text:            str = ""
    last_filter_category: Optional[str] = None

    # ── Upsell pagination context ────────────────────────────────────────────
    # FIX (restructure): trước đây orchestrator nhét động vào ctx.__dict__
    # ("_last_upsell_pno"...) → mất khi serialize Redis. Giờ là field chính thức.
    last_upsell_pno:  str       = ""
    last_upsell_page: int       = 1
    last_upsell_cats: List[str] = field(default_factory=list)

    # ── History buffer ────────────────────────────────────────────────────────
    # Lưu tối đa HISTORY_LIMIT turn. Khi đầy: tạo summary rồi reset buffer.
    history_turns: List[TurnEntry] = field(default_factory=list)
    history_summary: str = ""          # summary của các cycle trước
    history_cycle:   int = 0           # số lần đã reset (mỗi cycle = 50 turns)

    # Vision confirm state
    pending_vision_candidates: List[str]     = field(default_factory=list)
    pending_vision_part_type:  str           = ""
    pending_vision_ecosystem:  Optional[str] = None
    vision_condition:          str           = ""
    confirmed_vision_part:     Optional[str] = None

    turn_count: int   = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_expired(self, ttl: float = SESSION_TTL) -> bool:
        return (time.time() - self.updated_at) > ttl

    def touch(self):
        self.updated_at = time.time()
        self.turn_count += 1

    # ── History helpers ───────────────────────────────────────────────────────

    def add_turn(self, query: str, response: str,
                 intent: str = "", parts: Optional[List[str]] = None):
        """Thêm 1 turn vào buffer. Khi đủ 50: gọi _rotate()."""
        self.history_turns.append(TurnEntry(
            query    = query[:300],
            response = response[:400],
            intent   = intent,
            parts    = list(parts or [])[:5],
        ))
        if len(self.history_turns) >= HISTORY_LIMIT:
            self._rotate()

    def _rotate(self):
        """
        Tạo summary compact từ 50 turns hiện tại, lưu vào history_summary,
        rồi reset buffer. Không gọi LLM — summary rule-based đủ dùng.
        """
        lines = []
        # Tổng hợp: intent counts
        from collections import Counter
        intent_counts = Counter(t.intent for t in self.history_turns if t.intent)
        if intent_counts:
            top = intent_counts.most_common(3)
            lines.append("Intents: " + ", ".join(f"{i}×{c}" for i, c in top))

        # Các part đã nhắc tới
        all_parts: List[str] = []
        for t in self.history_turns:
            all_parts.extend(t.parts)
        unique_parts = list(dict.fromkeys(all_parts))[:10]  # giữ thứ tự, dedup
        if unique_parts:
            lines.append("Parts đã tra: " + ", ".join(unique_parts))

        # Ecosystem/class từ last context
        ctx_parts = []
        if self.last_ecosystem:     ctx_parts.append(f"hệ {self.last_ecosystem}")
        if self.last_current_class: ctx_parts.append(self.last_current_class)
        if self.last_torch_models:  ctx_parts.append(f"súng {self.last_torch_models[0]}")
        if ctx_parts:
            lines.append("Ngữ cảnh: " + ", ".join(ctx_parts))

        cycle_summary = f"[Cycle {self.history_cycle + 1} / {HISTORY_LIMIT} turns] " + "; ".join(lines)

        # Append vào summary tổng (giữ tối đa 3 cycle summaries)
        existing = self.history_summary.strip()
        all_summaries = existing.split("\n") if existing else []
        all_summaries.append(cycle_summary)
        self.history_summary = "\n".join(all_summaries[-3:])  # giữ 3 cycle gần nhất

        # Reset buffer
        self.history_turns = []
        self.history_cycle += 1
        log.info(
            f"[SessionStore] session={self.session_id} "
            f"history rotated → cycle={self.history_cycle}"
        )

    def get_history_for_llm(self, max_turns: int = 10) -> List[dict]:
        """
        Trả về history dạng Gemini messages để inject vào orchestrator.
        max_turns: số turn gần nhất muốn đưa vào context window.
        """
        recent = self.history_turns[-max_turns:]
        messages = []
        for t in recent:
            messages.append({"role": "user",  "parts": [{"text": t.query}]})
            messages.append({"role": "model", "parts": [{"text": t.response}]})
        return messages

    def get_summary_hint(self) -> str:
        """Trả về summary hint để inject vào session_hint nếu có."""
        if self.history_summary and self.history_cycle > 0:
            return f"[HISTORY_SUMMARY] {self.history_summary}"
        return ""

    # ── Vision helpers ────────────────────────────────────────────────────────

    def set_vision_pending(self, candidates: list, part_type: str,
                           ecosystem: Optional[str], condition: str):
        self.pending_vision_candidates = list(candidates[:3])
        self.pending_vision_part_type  = part_type
        self.pending_vision_ecosystem  = ecosystem
        self.vision_condition          = condition
        self.confirmed_vision_part     = None

    def confirm_vision_part(self, part_no: str):
        self.confirmed_vision_part     = part_no
        self.pending_vision_candidates = []

    def clear_vision_state(self):
        self.pending_vision_candidates = []
        self.pending_vision_part_type  = ""
        self.pending_vision_ecosystem  = None
        self.vision_condition          = ""
        self.confirmed_vision_part     = None

    def update_from_result(self, intent: str, e_dict: dict, returned_parts: list,
                           query: str = "", response_text: str = ""):
        self.last_intent       = intent
        self.last_part_nos     = list(e_dict.get("part_nos") or [])
        self.last_d_part_nos   = list(e_dict.get("d_part_nos") or [])
        self.last_p_part_nos   = list(e_dict.get("p_part_nos") or [])
        self.last_torch_models = list(e_dict.get("torch_models") or [])
        self.last_categories   = list(e_dict.get("categories") or [])
        if e_dict.get("ecosystem"):
            self.last_ecosystem = e_dict["ecosystem"]
        if e_dict.get("current_class"):
            self.last_current_class = e_dict["current_class"]
        if e_dict.get("wire_size"):
            self.last_wire_size = e_dict["wire_size"]
        self.last_returned_parts = [
            p.get("tokin_part_no", "") for p in (returned_parts or [])[:5]
            if isinstance(p, dict) and p.get("tokin_part_no")
        ]
        if e_dict.get("filter_category"):
            self.last_filter_category = e_dict["filter_category"]
        if query:
            self.last_query = query[:200]
        if response_text:
            self.last_text = response_text[:200]

        # Thêm vào history buffer
        parts_for_history = list(self.last_part_nos or self.last_returned_parts)[:5]
        self.add_turn(
            query    = query[:300],
            response = response_text[:400],
            intent   = intent,
            parts    = parts_for_history,
        )

        self.touch()


# ── Pattern detectors ─────────────────────────────────────────────────────────

_PRONOUN_PAT = _re.compile(
    r'\b(n[aà]y|n[oó]|[lc][oó]\s*n[aà]y|[cC][aá]i\s+n[aà]y|'
    r'lo[aạ]i\s+[dđ][oó]|m[aã]\s+[dđ][oó]|nó|'
    r'[lL]o[aạ]i\s+n[aà]y|h[aà]ng\s+n[aà]y|this|it|that)\b',
    _re.I | _re.UNICODE,
)

_FOLLOWUP_PAT = _re.compile(
    r'\b('
    r'gi[aá](\s+bao\s+nhi[eê]u|\s+bn?hi[eê]u|\b)|b[aá]o\s+gi[aá]|bao\s+nhi[eê]u|'
    r'c[oò]n\s+lo[aạ]i|th[eê]m\s+lo[aạ]i|c[oó]\s+h[aà]ng\s+kh[oô]ng|còn\s+h[aà]ng|'
    r'mua\s+th[eê]m|l[aấ]y\s+th[eê]m|[dđ][aặ]t(\s+th[eê]m|\s+h[aà]ng)?|'
    r'cho\s+(t[oô]i|m[iì]nh|em)\s+th[eê]m|'
    r'th[eê]m\s+(ch[uụ]p|b[eé]c|c[aá]ch|th[aâ]n|liner|s[uứ]|orifice)|'
    r'[0-9]+\s*(c[aá]i|b[oộ]|h[oộ]p)|[dđ][aặ]t\s*h[aà]ng|order|'
    r'lo[aạ]i\s+n[aà]y|c[aá]i\s+n[aà]y'
    r')\b',
    _re.I | _re.UNICODE,
)
_VISION_CONFIRM_PAT = _re.compile(
    r'\b(đúng|dung|yes|ok|ừ|uh|phải|đúng rồi|dung roi|'
    r'xác nhận|xac nhan|correct|right|yep|đúng vậy)\b'
    r'|^\s*[1-3]\s*$',
    _re.I | _re.UNICODE,
)

_VISION_DENY_PAT = _re.compile(
    r'\b(không|khong|sai|no|nope|không phải|khong phai|nhầm|nham|wrong)\b',
    _re.I | _re.UNICODE,
)

_GIA_PAT = _re.compile(
    r'gi[aá](\s+bao\s+nhi[eê]u|\s+bn?hi[eê]u|\b)|b[aá]o\s+gi[aá]|bao\s+nhi[eê]u',
    _re.I | _re.UNICODE,
)


def is_pronoun_query(query: str) -> bool:
    return bool(_PRONOUN_PAT.search(query))

def is_followup_query(query: str) -> bool:
    q = query.strip()
    return len(q) < 25 and bool(_FOLLOWUP_PAT.search(q))

def is_vision_confirm(query: str) -> bool:
    return bool(_VISION_CONFIRM_PAT.search(query.strip()))

def is_vision_deny(query: str) -> bool:
    return bool(_VISION_DENY_PAT.search(query.strip()))

def extract_vision_choice(query: str) -> Optional[int]:
    m = _re.search(r'^\s*([1-3])\s*$', query.strip())
    return int(m.group(1)) if m else None


# ── SessionStore ──────────────────────────────────────────────────────────────

class SessionStore:
    def __init__(self, ttl: float = SESSION_TTL, max_sessions: int = MAX_SESSIONS):
        self._store: dict[str, SessionContext] = {}
        self._lock  = Lock()
        self._ttl   = ttl
        self._max   = max_sessions

    def get_or_create(self, session_id: Optional[str]) -> Optional[SessionContext]:
        if not session_id:
            return None
        with self._lock:
            ctx = self._store.get(session_id)
            if ctx is None or ctx.is_expired(self._ttl):
                ctx = SessionContext(session_id=session_id)
                self._store[session_id] = ctx
                self._evict_if_needed()
            return ctx

    def update(self, ctx: Optional[SessionContext], intent: str,
               e_dict: dict, returned_parts: list,
               query: str = "", response_text: str = ""):
        if ctx is None:
            return
        with self._lock:
            ctx.update_from_result(intent, e_dict, returned_parts,
                                   query=query, response_text=response_text)

    def inject_context(self, ctx: Optional[SessionContext],
                       query: str, e_dict: dict) -> dict:
        if ctx is None or ctx.turn_count == 0:
            return e_dict

        e = dict(e_dict)
        injected = []

        has_pronoun  = is_pronoun_query(query)
        has_followup = is_followup_query(query)
        has_no_parts = not (e.get("part_nos") or e.get("d_part_nos") or
                            e.get("p_part_nos") or e.get("torch_models"))
        _is_price    = bool(_GIA_PAT.search(query))
        _q_short     = len(query.strip()) <= 35
        _is_implicit_followup = (
            _q_short and has_no_parts and ctx.turn_count > 0
            and not _re.search(r'\b\d{6}\b', query)
            and not _re.search(r'\d+[.,]\d+\s*mm', query)
            and not _re.search(
                r'(s[uú]ng|m[aá]y\s*h[aà]n|torch|model|lo[aại]\s*s[uú]ng|robot)',
                query, _re.I | _re.UNICODE)
        )

        _should_inject_parts = (
            has_pronoun or _is_price or
            (has_followup and _q_short) or _is_implicit_followup
        )
        if _should_inject_parts and has_no_parts:
            inject_parts = (
                list(ctx.last_part_nos[:3]) if ctx.last_part_nos
                else list(ctx.last_returned_parts[:3])
            )
            if inject_parts:
                e["part_nos"] = inject_parts
                e["_session_injected_parts"] = True
                injected.append(f"parts={inject_parts}")

        _eco_trigger = has_pronoun or has_followup or _is_implicit_followup or _is_price
        if not e.get("ecosystem") and ctx.last_ecosystem and _eco_trigger:
            e["ecosystem"] = ctx.last_ecosystem
            e["_session_injected_eco"] = True
            injected.append(f"eco={ctx.last_ecosystem}")

        if not e.get("current_class") and ctx.last_current_class and _eco_trigger:
            e["current_class"] = ctx.last_current_class
            injected.append(f"cc={ctx.last_current_class}")

        if not e.get("wire_size") and ctx.last_wire_size and _eco_trigger:
            e["wire_size"] = ctx.last_wire_size
            injected.append(f"wire={ctx.last_wire_size}")

        if (not e.get("torch_models") and ctx.last_torch_models
                and (has_pronoun or _is_implicit_followup)):
            e["torch_models"] = list(ctx.last_torch_models[:1])
            injected.append(f"torch={ctx.last_torch_models[:1]}")

        if (not e.get("filter_category") and ctx.last_filter_category
                and (has_followup or has_pronoun)):
            e["filter_category"] = ctx.last_filter_category
            injected.append(f"filter_cat={ctx.last_filter_category}")

        if injected:
            log.info(f"[SessionStore] injected: {injected} q={query[:50]!r}")
        return e

    def clear(self, session_id: str):
        with self._lock:
            self._store.pop(session_id, None)

    def stats(self) -> dict:
        with self._lock:
            active = sum(1 for c in self._store.values() if not c.is_expired(self._ttl))
            # history stats
            total_turns   = sum(len(c.history_turns) for c in self._store.values())
            total_cycles  = sum(c.history_cycle for c in self._store.values())
            return {
                "total_sessions":  len(self._store),
                "active_sessions": active,
                "ttl_seconds":     self._ttl,
                "total_buffered_turns": total_turns,
                "total_history_cycles": total_cycles,
            }

    def _evict_if_needed(self):
        if len(self._store) <= self._max:
            return
        expired = [sid for sid, ctx in self._store.items() if ctx.is_expired(self._ttl)]
        for sid in expired:
            del self._store[sid]
        if len(self._store) > self._max:
            oldest = sorted(self._store.items(), key=lambda x: x[1].updated_at)
            for sid, _ in oldest[:len(self._store) - self._max]:
                del self._store[sid]


# ══════════════════════════════════════════════════════════════════════════════
# RedisSessionStore — drop-in replacement cho SessionStore
# ══════════════════════════════════════════════════════════════════════════════

class RedisSessionStore(SessionStore):
    """
    SessionStore backed by Redis.
    API giống hệt SessionStore — drop-in replacement.

    Key: tokinarc:session:{session_id}  TTL = SESSION_TTL
    Fallback về in-memory nếu Redis unavailable.
    """

    PREFIX = "tokinarc:session:"

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask password trong Redis URL trước khi log.
        rediss://user:password@host:port → rediss://user:***@host:port
        """
        try:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url)
            if p.password:
                netloc = f"{p.username}:***@{p.hostname}:{p.port}"
                return urlunparse(p._replace(netloc=netloc))
        except Exception:
            pass
        return url[:30] + "..."

    def __init__(self, redis_url: str = "redis://localhost:6379/0",
                 ttl: float = SESSION_TTL, max_sessions: int = MAX_SESSIONS):
        super().__init__(ttl=ttl, max_sessions=max_sessions)
        self._redis_url = redis_url
        self._redis     = None
        self._redis_ok  = False
        self._connect()

    def _connect(self):
        try:
            import redis as _redis
            self._redis = _redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            self._redis.ping()
            self._redis_ok = True
            log.info(f"[RedisSessionStore] connected → {self._mask_url(self._redis_url)}")
        except Exception as e:
            self._redis_ok = False
            log.warning(f"[RedisSessionStore] Redis unavailable → fallback in-memory: {e}")

    def _key(self, session_id: str) -> str:
        return f"{self.PREFIX}{session_id}"

    def _to_json(self, ctx: SessionContext) -> str:
        import json as _json
        d = {
            "session_id":              ctx.session_id,
            "last_intent":             ctx.last_intent,
            "last_part_nos":           ctx.last_part_nos,
            "last_d_part_nos":         ctx.last_d_part_nos,
            "last_p_part_nos":         ctx.last_p_part_nos,
            "last_torch_models":       ctx.last_torch_models,
            "last_ecosystem":          ctx.last_ecosystem,
            "last_current_class":      ctx.last_current_class,
            "last_wire_size":          ctx.last_wire_size,
            "last_categories":         ctx.last_categories,
            "last_returned_parts":     ctx.last_returned_parts,
            "last_query":              ctx.last_query,
            "last_text":               ctx.last_text,
            "last_filter_category":    ctx.last_filter_category,
            "last_upsell_pno":         ctx.last_upsell_pno,
            "last_upsell_page":        ctx.last_upsell_page,
            "last_upsell_cats":        ctx.last_upsell_cats,
            "history_turns": [
                {"query": t.query, "response": t.response,
                 "intent": t.intent, "parts": t.parts}
                for t in ctx.history_turns
            ],
            "history_summary":           ctx.history_summary,
            "history_cycle":             ctx.history_cycle,
            "pending_vision_candidates": ctx.pending_vision_candidates,
            "pending_vision_part_type":  ctx.pending_vision_part_type,
            "pending_vision_ecosystem":  ctx.pending_vision_ecosystem,
            "vision_condition":          ctx.vision_condition,
            "confirmed_vision_part":     ctx.confirmed_vision_part,
            "turn_count":                ctx.turn_count,
            "created_at":                ctx.created_at,
            "updated_at":                ctx.updated_at,
        }
        return _json.dumps(d, ensure_ascii=False)

    def _from_json(self, raw: str) -> SessionContext:
        import json as _json
        d   = _json.loads(raw)
        ctx = SessionContext(session_id=d["session_id"])
        ctx.last_intent          = d.get("last_intent", "")
        ctx.last_part_nos        = d.get("last_part_nos", [])
        ctx.last_d_part_nos      = d.get("last_d_part_nos", [])
        ctx.last_p_part_nos      = d.get("last_p_part_nos", [])
        ctx.last_torch_models    = d.get("last_torch_models", [])
        ctx.last_ecosystem       = d.get("last_ecosystem")
        ctx.last_current_class   = d.get("last_current_class")
        ctx.last_wire_size       = d.get("last_wire_size")
        ctx.last_categories      = d.get("last_categories", [])
        ctx.last_returned_parts  = d.get("last_returned_parts", [])
        ctx.last_query           = d.get("last_query", "")
        ctx.last_text            = d.get("last_text", "")
        ctx.last_filter_category = d.get("last_filter_category")
        ctx.last_upsell_pno      = d.get("last_upsell_pno", "")
        ctx.last_upsell_page     = d.get("last_upsell_page", 1)
        ctx.last_upsell_cats     = d.get("last_upsell_cats", [])
        ctx.history_turns = [
            TurnEntry(
                query    = t["query"],
                response = t["response"],
                intent   = t.get("intent", ""),
                parts    = t.get("parts", []),
            )
            for t in d.get("history_turns", [])
        ]
        ctx.history_summary           = d.get("history_summary", "")
        ctx.history_cycle             = d.get("history_cycle", 0)
        ctx.pending_vision_candidates = d.get("pending_vision_candidates", [])
        ctx.pending_vision_part_type  = d.get("pending_vision_part_type", "")
        ctx.pending_vision_ecosystem  = d.get("pending_vision_ecosystem")
        ctx.vision_condition          = d.get("vision_condition", "")
        ctx.confirmed_vision_part     = d.get("confirmed_vision_part")
        ctx.turn_count                = d.get("turn_count", 0)
        ctx.created_at                = d.get("created_at", time.time())
        ctx.updated_at                = d.get("updated_at", time.time())
        return ctx

    def get_or_create(self, session_id: Optional[str]) -> Optional[SessionContext]:
        if not session_id:
            return None
        if self._redis_ok:
            try:
                raw = self._redis.get(self._key(session_id))
                if raw:
                    ctx = self._from_json(raw)
                    if not ctx.is_expired(self._ttl):
                        with self._lock:
                            self._store[session_id] = ctx
                        return ctx
            except Exception as e:
                log.warning(f"[RedisSessionStore] get error → fallback: {e}")
                self._redis_ok = False
        return super().get_or_create(session_id)

    def update(self, ctx: Optional[SessionContext], intent: str,
               e_dict: dict, returned_parts: list,
               query: str = "", response_text: str = ""):
        if ctx is None:
            return
        with self._lock:
            ctx.update_from_result(intent, e_dict, returned_parts,
                                   query=query, response_text=response_text)
        if self._redis_ok:
            try:
                self._redis.setex(
                    self._key(ctx.session_id),
                    int(self._ttl),
                    self._to_json(ctx),
                )
            except Exception as e:
                log.warning(f"[RedisSessionStore] setex error: {e}")
                self._redis_ok = False

    def clear(self, session_id: str):
        super().clear(session_id)
        if self._redis_ok:
            try:
                self._redis.delete(self._key(session_id))
            except Exception as e:
                log.warning(f"[RedisSessionStore] delete error: {e}")

    def stats(self) -> dict:
        base = super().stats()
        base["backend"]   = "redis" if self._redis_ok else "in-memory (redis unavailable)"
        base["redis_url"] = self._redis_url
        return base

    def reconnect(self):
        if not self._redis_ok:
            self._connect()


_session_store: Optional[SessionStore] = None

def get_session_store() -> SessionStore:
    """
    Factory: auto-detect Redis từ REDIS_URL env.
    Nếu không có hoặc Redis offline → in-memory như cũ.
    """
    global _session_store
    if _session_store is None:
        import os as _os
        redis_url = _os.environ.get("REDIS_URL", "")
        if redis_url:
            _session_store = RedisSessionStore(redis_url=redis_url)
            if _session_store._redis_ok:
                log.info(f"[SessionStore] initialized (Redis, TTL=30min, url={RedisSessionStore._mask_url(redis_url)})")
            else:
                log.info("[SessionStore] Redis unavailable → in-memory fallback")
        else:
            _session_store = SessionStore()
            log.info("[SessionStore] initialized (in-memory, TTL=30min, history_limit=50)")
    return _session_store

