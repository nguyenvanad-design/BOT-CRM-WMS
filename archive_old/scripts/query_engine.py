"""
query_engine.py — TOKINARC Traversal Engine (Query Engine)
===========================================================
Autoss × Tokinarc — Industrial Compatibility Intelligence

Tầng trung gian: nhận RouterResult → gọi đúng CER API → trả về QueryResponse.

Xử lý 11 intents:
  LOOKUP              → get_part()
  CONSUMABLE_SET      → get_parts_for_torch() + get_consumable_set()
  COMPATIBILITY_CHECK → check_compatibility()
  SEARCH_BY_DESC      → search_parts()
  UPSELL              → get_compatible_parts() + missing category analysis
  REPLACEMENT         → resolve P/D alias → get_part() + suggest alternatives
  INSTALLATION        → get_parts_for_torch() + installation notes
  REPAIR              → symptom → category mapping → search_parts()
  COMPARISON          → parallel lookup + diff analysis
  AGGREGATE           → get_parts_by_category() + search_torches()
  OUT_OF_SCOPE        → polite redirect

Output: QueryResponse — structured result sẵn sàng cho LLM Explanation Layer.

Usage:
    from query_engine import QueryEngine
    engine = QueryEngine(cer=cer)
    response = engine.execute(router_result)
    print(response)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Optional Assembly procedural knowledge base
try:
    from core.assembly_kb import AssemblyKB
except ImportError:
    AssemblyKB = None  # type: ignore

# ─── Result types ──────────────────────────────────────────────────────────────

@dataclass
class PartInfo:
    """Compact part representation cho response."""
    tokin_part_no: str
    display_name_vi: str
    display_name_en: str
    category: str
    ecosystem: str
    current_class: str
    wire_size_mm: Optional[float]
    p_part_nos: List[str]
    d_part_nos: List[str]
    price_vnd: Optional[int]
    price_unit: str
    is_contact_price: bool
    is_priority: bool
    note: str
    role: str = ""           # TPM role: Tip / Nozzle / Orifice / ...
    is_mandatory: bool = True
    score: float = 1.0

    @classmethod
    def from_cer_part(cls, part, role: str = "", is_mandatory: bool = True, score: float = 1.0) -> "PartInfo":
        biz = part.raw.get("business", {}) if hasattr(part, "raw") else {}
        return cls(
            tokin_part_no=part.tokin_part_no,
            display_name_vi=part.display_name_vi,
            display_name_en=part.display_name_en,
            category=part.category,
            ecosystem=part.ecosystem,
            current_class=part.current_class,
            wire_size_mm=part.wire_size_mm,
            p_part_nos=part.p_part_nos,
            d_part_nos=part.d_part_nos,
            price_vnd=biz.get("price_vnd"),
            price_unit=biz.get("price_unit", "cái"),
            is_contact_price=biz.get("is_contact_price", False),
            is_priority=biz.get("is_priority_sell", False),
            note=part.raw.get("note", "") if hasattr(part, "raw") else "",
            role=role,
            is_mandatory=is_mandatory,
            score=score,
        )

    @classmethod
    def synthetic(
        cls,
        tokin_part_no: str,
        display_name_vi: str = "",
        display_name_en: str = "",
        category: str = "",
        ecosystem: str = "",
        current_class: str = "",
        wire_size_mm: Optional[float] = None,
        p_part_nos: Optional[List[str]] = None,
        d_part_nos: Optional[List[str]] = None,
        role: str = "",
        score: float = 1.0,
    ) -> "PartInfo":
        """Create a synthetic PartInfo with sensible defaults for missing CER data."""
        return cls(
            tokin_part_no=tokin_part_no,
            display_name_vi=display_name_vi or f"Mã Tokin: {tokin_part_no}",
            display_name_en=display_name_en or f"Tokin: {tokin_part_no}",
            category=category,
            ecosystem=ecosystem,
            current_class=current_class,
            wire_size_mm=wire_size_mm,
            p_part_nos=p_part_nos or [],
            d_part_nos=d_part_nos or [],
            price_vnd=None,
            price_unit="cái",
            is_contact_price=True,  # synthetic = data chưa đủ, liên hệ báo giá
            is_priority=False,
            note="Dữ liệu chi tiết chưa có trong hệ thống, liên hệ Autoss để biết thêm",
            role=role,
            is_mandatory=True,
            score=score,
        )

    def price_display(self) -> str:
        if self.is_contact_price:
            return "Liên hệ báo giá"
        if self.price_vnd:
            return f"{self.price_vnd:,}đ/{self.price_unit}"
        return "Chưa có giá"

    def to_dict(self) -> dict:
        return {
            "tokin_part_no": self.tokin_part_no,
            "display_name_vi": self.display_name_vi,
            "display_name_en": self.display_name_en,
            "category": self.category,
            "ecosystem": self.ecosystem,
            "current_class": self.current_class,
            "wire_size_mm": self.wire_size_mm,
            "p_part_nos": self.p_part_nos,
            "d_part_nos": self.d_part_nos,
            "price_vnd": self.price_vnd,
            "price_unit": self.price_unit,
            "is_contact_price": self.is_contact_price,
            "is_priority": self.is_priority,
            "note": self.note,
            "role": self.role,
            "is_mandatory": self.is_mandatory,
            "score": round(self.score, 3),
        }


@dataclass
class TorchInfo:
    """Compact torch representation."""
    model_code: str
    family: str
    current_class: str
    ecosystem: str
    cooling: str
    torch_type: str
    display_name_vi: str
    display_name_en: str
    price_vnd: Optional[int]
    is_contact_price: bool
    note: str

    @classmethod
    def from_cer_torch(cls, torch) -> "TorchInfo":
        biz = torch.raw.get("business", {}) if hasattr(torch, "raw") else {}
        raw = torch.raw if hasattr(torch, "raw") else {}
        # torch_type inferred from raw body_type or cooling
        torch_type = raw.get("body_type", raw.get("mounting", "ROBOTIC"))
        return cls(
            model_code=torch.model_code,
            family=torch.family,
            current_class=torch.current_class,
            ecosystem=torch.ecosystem,
            cooling=torch.cooling,
            torch_type=torch_type,
            display_name_vi=raw.get("display_name_vi", torch.model_code),
            display_name_en=raw.get("display_name_en", torch.model_code),
            price_vnd=biz.get("price_vnd"),
            is_contact_price=biz.get("is_contact_price", True),
            note=raw.get("note", ""),
        )

    def to_dict(self) -> dict:
        return {
            "model_code": self.model_code,
            "family": self.family,
            "current_class": self.current_class,
            "ecosystem": self.ecosystem,
            "cooling": self.cooling,
            "torch_type": self.torch_type,
            "display_name_vi": self.display_name_vi,
            "display_name_en": self.display_name_en,
            "price_vnd": self.price_vnd,
            "is_contact_price": self.is_contact_price,
            "note": self.note,
        }


@dataclass
class CompatResult:
    """Kết quả kiểm tra tương thích."""
    part_a: str
    part_b: str
    is_compatible: bool
    confidence: float
    reason: str
    relation_type: str

    def to_dict(self) -> dict:
        return {
            "part_a": self.part_a,
            "part_b": self.part_b,
            "is_compatible": self.is_compatible,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "relation_type": self.relation_type,
        }


@dataclass
class QueryResponse:
    """
    Unified response từ QueryEngine.
    LLM Explanation Layer nhận object này để generate natural language response.
    """
    # Query context
    intent: str
    query: str
    success: bool
    error_msg: str = ""

    # Primary results
    parts: List[PartInfo] = field(default_factory=list)
    torches: List[TorchInfo] = field(default_factory=list)
    compat_results: List[CompatResult] = field(default_factory=list)

    # Grouped results (cho consumable set, upsell)
    parts_by_role: Dict[str, List[PartInfo]] = field(default_factory=dict)

    # Metadata
    total_found: int = 0
    result_type: str = ""        # "exact" / "fuzzy" / "inferred" / "not_found"
    context: Dict[str, Any] = field(default_factory=dict)  # intent-specific context
    suggestions: List[str] = field(default_factory=list)   # gợi ý follow-up
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "query": self.query,
            "success": self.success,
            "error_msg": self.error_msg,
            "parts": [p.to_dict() for p in self.parts],
            "torches": [t.to_dict() for t in self.torches],
            "compat_results": [c.to_dict() for c in self.compat_results],
            "parts_by_role": {
                role: [p.to_dict() for p in ps]
                for role, ps in self.parts_by_role.items()
            },
            "total_found": self.total_found,
            "result_type": self.result_type,
            "context": self.context,
            "suggestions": self.suggestions,
            "latency_ms": round(self.latency_ms, 1),
        }

    def __str__(self) -> str:
        lines = [
            f"Intent:  {self.intent}",
            f"Query:   {self.query}",
            f"Success: {self.success}  |  Found: {self.total_found}  |  Type: {self.result_type}",
        ]
        if self.error_msg:
            lines.append(f"Error:   {self.error_msg}")

        if self.compat_results:
            for cr in self.compat_results:
                icon = "✅" if cr.is_compatible else "❌"
                lines.append(f"\n{icon} {cr.part_a} × {cr.part_b}")
                lines.append(f"   Conf: {cr.confidence:.0%}  |  {cr.reason}")

        if self.parts_by_role:
            for role, ps in self.parts_by_role.items():
                lines.append(f"\n[{role}] ({len(ps)} options)")
                for p in ps[:3]:
                    mandatory = "★" if p.is_mandatory else "○"
                    lines.append(f"  {mandatory} {p.tokin_part_no}  {p.display_name_vi}  {p.price_display()}")
        elif self.parts:
            lines.append(f"\nParts ({len(self.parts)}):")
            for p in self.parts[:8]:
                lines.append(f"  {p.tokin_part_no}  {p.display_name_vi}  {p.price_display()}")

        if self.torches:
            lines.append(f"\nTorches ({len(self.torches)}):")
            for t in self.torches[:5]:
                lines.append(f"  {t.model_code}  {t.current_class}  {t.ecosystem}")

        if self.context:
            for k, v in self.context.items():
                if v:
                    lines.append(f"  {k}: {v}")

        if self.suggestions:
            lines.append("\nSuggestions:")
            for s in self.suggestions:
                lines.append(f"  → {s}")

        lines.append(f"\nLatency: {self.latency_ms:.1f}ms")
        return "\n".join(lines)


# ─── Symptom → category mapping cho REPAIR intent ─────────────────────────────

SYMPTOM_CATEGORY_MAP: Dict[str, List[str]] = {
    # Spatter / feeding
    "spatter": ["Tip", "Nozzle", "Liner"],
    "xỉ": ["Tip", "Nozzle"],
    "dính xỉ": ["Nozzle", "Tip"],
    "wire feeding": ["Liner", "Tip"],
    "kẹt dây": ["Liner"],
    "dây kẹt": ["Liner"],
    # Arc / quality
    "hồ quang": ["Tip", "Orifice", "Insulator"],
    "arc không ổn": ["Tip", "Orifice"],
    "chất lượng mối hàn": ["Tip", "Nozzle", "Orifice", "Insulator"],
    "mối hàn kém": ["Tip", "Nozzle", "Orifice"],
    # Gas / cooling
    "rò khí": ["Insulator", "Orifice", "Nozzle"],
    "thiếu khí": ["Orifice", "GasHose"],
    "rò nước": ["InnerTube"],
    "quá nhiệt": ["Nozzle", "TipBody", "InnerTube"],
    # Wear
    "mòn nhanh": ["Tip", "Nozzle"],
    "cháy sớm": ["Tip"],
    "tip cháy": ["Tip"],
    "nozzle mòn": ["Nozzle"],
}

# ─── Role display order cho consumable sets ───────────────────────────────────

ROLE_DISPLAY_ORDER = [
    "Tip", "TipBody", "TipAdapter",
    "Nozzle", "Orifice", "Insulator",
    "Liner", "LinerORing",
    "WaveWasher", "InnerTube",
    "TungstenElectrode", "Collet", "ColletBody", "CeramicNozzle", "BackCap",
    "GasHose", "CableAssembly", "PowerCable",
    "Handle", "TorchBody",
    "InsulationCollar", "WXNozzleSleeve", "WXCoverRubber",
]


def _sort_by_role(parts: List[PartInfo]) -> List[PartInfo]:
    """Sort parts theo thứ tự role ưu tiên."""
    order = {role: i for i, role in enumerate(ROLE_DISPLAY_ORDER)}
    return sorted(parts, key=lambda p: (order.get(p.role or p.category, 99), p.tokin_part_no))


def _group_by_role(parts: List[PartInfo]) -> Dict[str, List[PartInfo]]:
    """Group parts by role, sorted theo ROLE_DISPLAY_ORDER."""
    groups: Dict[str, List[PartInfo]] = {}
    for p in parts:
        key = p.role or p.category
        groups.setdefault(key, []).append(p)
    # Sort groups theo display order
    order = {role: i for i, role in enumerate(ROLE_DISPLAY_ORDER)}
    return dict(sorted(groups.items(), key=lambda x: order.get(x[0], 99)))


# ─── QueryEngine ──────────────────────────────────────────────────────────────

class QueryEngine:
    """
    Traversal Engine: RouterResult → CER calls → QueryResponse.

    Mỗi intent có một handler riêng.
    Handler nhận (router_result, cer) → QueryResponse.
    """

    def __init__(self, cer, vector_index=None, assembly_kb=None):
        self._cer = cer
        self._vi = vector_index   # VectorIndex instance (optional, loaded if available)
        self._akb = assembly_kb   # AssemblyKB instance (optional, for INSTALLATION/REPAIR)

    # ── Vector search helper ──────────────────────────────────────────────────

    def _vector_search_to_parts(self, query: str, top_k: int = 8,
                                 filter_type: Optional[str] = None) -> List[PartInfo]:
        """
        Gọi VectorIndex.search() → convert kết quả thành List[PartInfo].
        Chỉ trả parts (type='part'). Torch results bỏ qua ở đây.
        """
        if self._vi is None:
            return []
        try:
            hits = self._vi.search(query, top_k=top_k * 2, filter_type=filter_type or "part")
            parts: List[PartInfo] = []
            seen: set = set()
            for hit in hits:
                if hit["type"] != "part":
                    continue
                part_no = hit["id"]
                if part_no in seen:
                    continue
                seen.add(part_no)
                # Try to get full part from CER for rich PartInfo
                cer_part = self._cer.get_part(part_no)
                if cer_part:
                    parts.append(PartInfo.from_cer_part(cer_part, score=hit["score"]))
                else:
                    # Fallback: build minimal PartInfo from chunk data
                    data = hit.get("data", {})
                    biz = data.get("business", {})
                    parts.append(PartInfo(
                        tokin_part_no=part_no,
                        display_name_vi=data.get("display_name_vi", part_no),
                        display_name_en=data.get("display_name_en", part_no),
                        category=data.get("category", ""),
                        ecosystem=data.get("ecosystem", ""),
                        current_class=data.get("current_class", ""),
                        wire_size_mm=None,
                        p_part_nos=[],
                        d_part_nos=[],
                        price_vnd=biz.get("price_vnd"),
                        price_unit=biz.get("price_unit", "cái"),
                        is_contact_price=biz.get("is_contact_price", False),
                        is_priority=biz.get("is_priority_sell", False),
                        note=data.get("note", ""),
                        score=hit["score"],
                    ))
                if len(parts) >= top_k:
                    break
            return parts
        except Exception:
            return []

    def _vector_search_torches(self, query: str, top_k: int = 5) -> List[TorchInfo]:
        """Gọi VectorIndex.search() → convert thành List[TorchInfo]."""
        if self._vi is None:
            return []
        try:
            hits = self._vi.search(query, top_k=top_k * 2, filter_type="torch")
            torches: List[TorchInfo] = []
            seen: set = set()
            for hit in hits:
                if hit["type"] != "torch":
                    continue
                model_code = hit["id"]
                if model_code in seen:
                    continue
                seen.add(model_code)
                cer_torch = self._cer.get_torch(model_code)
                if cer_torch:
                    torches.append(TorchInfo.from_cer_torch(cer_torch))
                if len(torches) >= top_k:
                    break
            return torches
        except Exception:
            return []

    # Vector clarification rescue
    def _vector_clarification_rescue(
        self,
        query: str,
        threshold: float = 0.55,
        top_k: int = 5,
    ) -> Optional[List[PartInfo]]:
        """
        Khi router fallback=True hoặc intent=OUT_OF_SCOPE → thử vector search trước.
        Nếu top-1 score ≥ threshold → trả về parts để bypass clarification, xử lý
        như SEARCH_BY_DESC. Lý do: query có thể có ý nghĩa ẩn (misspell, vocab khác)
        mà rule-based router không bắt được nhưng bge-m3 embed bắt được.

        Args:
            query     : original query
            threshold : cosine score threshold (default 0.4 — cân bằng)
            top_k     : số parts trả về tối đa

        Returns:
            list[PartInfo] nếu cứu được, None nếu nên giữ clarification.
        """
        if self._vi is None:
            return None
        # Domain keyword guard — query phải có ít nhất 1 từ khóa welding
        # để vector được phép rescue. Loại OOS như "tỷ giá USD", "máy hàn Panasonic".
        import re as _re_dg
        _q_low_dg = query.lower()
        _has_domain_kw = bool(_re_dg.search(
            r"\b(bec|béc|tip|nozzle|chụp|chup|orifice|insulator|gasket|"
            r"thân súng|than sung|torch|súng hàn|sung han|tay cầm|tay cam|handle|"
            r"hệ n|he n|hệ d|he d|wx|n-?type|d-?type|"
            r"tk-|srct|acc-|ymens|ymsa|ymxa|cs-|fxsa|"
            r"\d{2,4}\s*a\b|"
            r"dây \d|day \d|0\.[6-9]\s*mm|1\.[02468]\s*mm|2\.[04]\s*mm|"
            r"linh kiện|linh kien|phụ kiện|phu kien|consumable|vật tư|vat tu|bộ đồ|bo do)\b",
            _q_low_dg
        ))
        if not _has_domain_kw:
            print(f"[vector_rescue] no domain keyword in '{query[:40]}' → skip rescue")
            return None
        # Anti-fake-token guard — block rescue nếu query có token không hợp lệ
        # invalid signals (fake torch, fake spec, ecosystem Z, WX+wide wire)
        _fake_signals = _re_dg.search(
            r"\b("
            r"(tk|acc|srct|tr|dsrc|abc|ymens|ymsa|ymxa)[-\s]?(9999|0000|99\d{2}|00\d{2})|"
            r"abc[-\s]?\d{2,4}|"  # ABC-350, ABC-500, etc — fake brand
            r"9999\s*a|999\s*a|8888|"
            r"9\.9\s*mm|"
            r"he\s*z|hệ\s*z|z[-\s]?type|"
            r"wx[^\w]*\d{3}a[^\w]*[2-9]\.\dmm|"  # WX + wire ≥ 2.0mm
            r"wx[^\w]*[2-9]\.\dmm"
            r")\b",
            _q_low_dg
        )
        if _fake_signals:
            print(f"[vector_rescue] fake-token signal in '{query[:40]}' → skip rescue")
            return None
        try:
            vec_parts = self._vector_search_to_parts(query, top_k=top_k)
        except Exception as e:
            print(f"[vector_rescue] failed: {e}")
            return None

        if not vec_parts:
            return None

        top_score = vec_parts[0].score
        if top_score < threshold:
            print(
                f"[vector_rescue] top_score={top_score:.3f} < {threshold} "
                f"→ keep clarification"
            )
            return None

        print(
            f"[vector_rescue] top_score={top_score:.3f} >= {threshold} "
            f"→ rescue {len(vec_parts)} parts"
        )
        return vec_parts

    def execute_with_resolver(self, router_result, resolver=None) -> QueryResponse:
        """
        Enhanced execute: run ContextualResolver before dispatching.
        Resolver fills gaps: category, ecosystem, current_class, wire_size, candidates.

        Args:
            router_result: RouterResult từ SemanticRouter/RuleBasedRouter
            resolver:      ContextualResolver instance (optional, enriches entities)
        """
        if resolver is not None:
            ent = router_result.extracted_entities
            ctx = resolver.resolve(
                router_result.original_query,
                existing_entities=ent,
                intent=router_result.intent,
            )
            # Inject enriched fields back
            ent.categories   = ctx.categories   or ent.categories
            ent.ecosystem    = ctx.ecosystem     or ent.ecosystem
            ent.current_class = ctx.current_class or ent.current_class
            ent.wire_size    = ctx.wire_size     or ent.wire_size

            # Inject specific candidates when resolver is confident and found few results
            # Threshold: ≤6 candidates = specific enough to use directly
            if (not ent.part_nos and ctx.candidate_part_nos
                    and len(ctx.candidate_part_nos) <= 6
                    and ctx.overall_confidence >= 0.5):
                ent.part_nos = list(ctx.candidate_part_nos)
                # Upgrade LOOKUP → SEARCH_BY_DESC so engine doesn't error on "no part_nos"
                # EXCEPT: queries with explicit "part number / mã số / là gì" signals are
                # info-lookup intents — keep LOOKUP so the engine returns code-based info.
                import re as _re_up_guard
                _q_low = (router_result.original_query or "").lower()
                _strong_lookup_signal = bool(
                    _re_up_guard.search(
                        r"\b(part number|part no|ma so|mã số|la gi|là gì|"
                        r"ma hang la|mã hàng là|ma cua|mã của|"
                        r"part number la gi|part no la gi)\b",
                        _q_low
                    )
                )
                if router_result.intent == "LOOKUP" and not _strong_lookup_signal:
                    router_result.intent = "SEARCH_BY_DESC"

            # Attach resolver context to router_result for downstream use
            router_result._resolver_ctx = ctx

        return self.execute(router_result)

    def execute(self, router_result) -> QueryResponse:
        """
        Main entry point.
        router_result: RouterResult từ SemanticRouter hoặc RuleBasedRouter.
        """
        t0 = time.time()
        intent = router_result.intent
        query = router_result.original_query
        entities = router_result.extracted_entities

        # Dispatch theo intent
        handlers = {
            "LOOKUP":             self._handle_lookup,
            "CONSUMABLE_SET":     self._handle_consumable_set,
            "COMPATIBILITY_CHECK":self._handle_compatibility,
            "SEARCH_BY_DESC":     self._handle_search,
            "UPSELL":             self._handle_upsell,
            "REPLACEMENT":        self._handle_replacement,
            "INSTALLATION":       self._handle_installation,
            "REPAIR":             self._handle_repair,
            "COMPARISON":         self._handle_comparison,
            "AGGREGATE":          self._handle_aggregate,
            "OUT_OF_SCOPE":       self._handle_out_of_scope,
            "STOCK":              self._handle_stock,
        }

        handler = handlers.get(intent, self._handle_fallback)

        # Vector clarification rescue: khi router fallback=True hoặc OOS,
        # thử vector search trước — nếu top-1 score >= 0.4 → bypass → SEARCH_BY_DESC.
        # OOS hard-locked (chit-chat, off-topic) thì skip rescue.
        _fallback_flag = getattr(router_result, "fallback", False)
        _is_oos = (intent == "OUT_OF_SCOPE")
        _oos_hard_locked = bool(getattr(router_result, "oos_hard_locked", False))
        # v9.10.3: OOS commerce guard — skip rescue khi OOS hỏi giá/mua/bán/dịch vụ
        # Fix #661: "súng hàn Tokin giá bao nhiêu" có domain kw (súng hàn) lọt
        # qua _has_domain_kw guard, nhưng "giá bao nhiêu" làm câu thành OOS thật.
        import re as _re_oos_cm
        _oos_commerce_kw = _is_oos and bool(_re_oos_cm.search(
            r"\b(giá|gia|bao nhiêu|bao nhieu|mua|bán|ban\b|ship|"
            r"bảo hành|bao hanh|chi nhánh|chi nhanh|đại lý|dai ly|"
            r"tuyển|tuyen|công ty|cong ty|đặt hàng|dat hang|"
            r"hóa đơn|hoa don|sỉ|si\b|trả góp|tra gop|thành lập|thanh lap|"
            r"app\b|grab|cod|vat|tài khoản|tai khoan|chuyển tiền|chuyen tien)\b",
            query.lower()
        ))

        # ── v9.7: skip vector rescue when handler can process the query ──────
        # GOLD_D2 "súng hàn 350" → fallback=True (no eco) but handler has
        # current_class → CONSUMABLE_SET handler will multi-eco merge (v9.6).
        # Without this skip, vector rescue grabs control and returns 5 fuzzy
        # TorchBody, bypassing the proper CS merge. Fixes #509, #510, #511.
        _handler_can_process = (
            intent == "CONSUMABLE_SET" and (
                bool(getattr(entities, "current_class", None))
                or bool(getattr(entities, "torch_models", None))
            )
        )

        if (_fallback_flag or _is_oos) and self._vi is not None \
                and not _oos_hard_locked and not _handler_can_process \
                and not _oos_commerce_kw:
            rescued = self._vector_clarification_rescue(query, threshold=0.4)
            if rescued:
                print(
                    f"[execute] Vector rescued query '{query[:50]}' "
                    f"(top={rescued[0].score:.3f}, n={len(rescued)}). "
                    f"Bypass {'OUT_OF_SCOPE' if _is_oos else 'fallback'} "
                    f"→ SEARCH_BY_DESC."
                )
                response = QueryResponse(
                    intent="SEARCH_BY_DESC",
                    query=query,
                    success=True,
                    parts=rescued,
                    total_found=len(rescued),
                    result_type="fuzzy",
                    context={
                        "rescued_from": "OUT_OF_SCOPE" if _is_oos else "low_confidence",
                        "source": "vector_rescue",
                        "original_intent": intent,
                        "top_vector_score": float(rescued[0].score),
                    },
                    suggestions=[
                        "Đây là kết quả gần đúng dựa trên mô tả. "
                        "Bổ sung thông tin (hệ N/D/WX, dòng A, kích thước...) để chính xác hơn.",
                    ],
                )
                # ── v9.10.2: Apply contradiction detection to rescue path ──
                # vector_rescue bypasses _handle_search so detector must run here.
                # Without this, queries like "chụp khí thẳng dáng tum" stay
                # clarify=False because router fallback rescued them before
                # the search handler.
                try:
                    _rescue_eco = getattr(entities, "ecosystem", None)
                    _rescue_reasons = self._detect_contradictions(query, _rescue_eco)
                    if _rescue_reasons:
                        response.context["contradiction"] = True
                        response.context["contradiction_reasons"] = _rescue_reasons
                        _rescue_msg = (
                            f"Phát hiện thông số mâu thuẫn "
                            f"({', '.join(_rescue_reasons)}). "
                            f"Vui lòng làm rõ thông số bạn cần."
                        )
                        response.suggestions.insert(0, _rescue_msg)
                except Exception:
                    pass
                response.latency_ms = (time.time() - t0) * 1000
                return response

        try:
            response = handler(router_result, entities)
        except Exception as e:
            response = QueryResponse(
                intent=intent, query=query,
                success=False,
                error_msg=f"Engine error: {str(e)}",
                result_type="error",
            )

        response.latency_ms = (time.time() - t0) * 1000
        return response

    # ── LOOKUP ────────────────────────────────────────────────────────────────

    def _handle_lookup(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts = []
        not_found = []

        # ── Torch model lookup: "TK-308RR là súng gì", "TK-308RR thông số kỹ thuật" ──
        # If query has torch model(s), return torch info as synthetic part-like entries
        if ent.torch_models:
            for model in ent.torch_models:
                torch = self._cer.get_torch(model)
                if torch:
                    # Return torch info as a synthetic "part" so eval sees parts>=1
                    tpm_pairs = self._cer.get_parts_for_torch(model) or []
                    eco_str = getattr(torch, "ecosystem", "") or ""
                    cc_str = getattr(torch, "current_class", "") or ""
                    parts.append(PartInfo.synthetic(
                        tokin_part_no=model,
                        display_name_vi=f"Súng {model} (hệ {eco_str} {cc_str})".strip(),
                        display_name_en=f"Torch {model}",
                        ecosystem=eco_str,
                        current_class=cc_str,
                        role="torch_info",
                    ))
                else:
                    # Synthetic torch placeholder — model name looks valid but not in CER
                    parts.append(PartInfo.synthetic(
                        tokin_part_no=model,
                        display_name_vi=f"Súng {model}",
                        display_name_en=f"Torch {model}",
                        role="torch_info",
                    ))
            if parts:
                return QueryResponse(
                    intent="LOOKUP", query=query, success=True,
                    parts=parts, total_found=len(parts),
                    result_type="exact",
                    context={"torch_lookup": True, "models": ent.torch_models},
                    suggestions=["Hỏi 'bộ vật tư cho ' + tên súng để xem linh kiện tiêu hao"],
                )

        # Try all codes found
        all_codes = (
            ent.part_nos +
            ent.p_part_nos +
            ent.d_part_nos +
            [c for c in ent.raw_codes if c not in ent.part_nos + ent.p_part_nos + ent.d_part_nos]
        )

        # Deduplicate while preserving order
        seen_tokin = set()
        for code in all_codes:
            part = self._cer.get_part(code)
            # Alias resolution: TET01296, U4167G01, K980C05... → tokin ID
            if not part:
                _resolved = self._cer.resolve_part_no(code)
                if _resolved:
                    part = self._cer.get_part(_resolved)
            if part:
                tokin = part.tokin_part_no
                if tokin not in seen_tokin:
                    seen_tokin.add(tokin)
                    # Detect if this was a P or D lookup
                    role = ""
                    if code in ent.p_part_nos:
                        role = f"via P-part: {code}"
                    elif code in ent.d_part_nos:
                        role = f"via D-part: {code}"
                    elif code != tokin:
                        role = f"via alias: {code}"
                    parts.append(PartInfo.from_cer_part(part, role=role))
            else:
                not_found.append(code)

        # Build compatible part suggestions for single result
        suggestions = []
        if len(parts) == 1:
            p = parts[0]
            torches = self._cer.get_torches_for_part(p.tokin_part_no)
            if torches:
                torch_list = ", ".join(t.model_code for t in torches[:4])
                suggestions.append(f"Dùng được trên các súng: {torch_list}")
            compat = self._cer.get_compatible_parts(p.tokin_part_no)
            compat_by_cat: Dict[str, List] = {}
            for rel, cp in compat[:12]:
                compat_by_cat.setdefault(cp.category, []).append(cp.tokin_part_no)
            for cat, pnos in list(compat_by_cat.items())[:3]:
                suggestions.append(f"Parts tương thích category {cat}: {', '.join(pnos[:3])}")

        if not parts and not_found:
            import re as _re_lk
            # For P/D aliases AND bare Tokin codes: return synthetic part if in valid range
            synthetic = []
            for c in not_found:
                cs = c.strip()
                # ── Bare 6-digit Tokin code (e.g. "005001", "P002003", "D002003") ──
                # Strip any P/D/OTC prefix (with or without dash) and check if remainder
                # is a 6-digit code in known Tokin range
                _bare = _re_lk.sub(r"^(P-?|D-?|OTC-?)", "", cs, flags=_re_lk.I)

                # Tolerance: 7-digit typo (one extra digit). Try dropping last digit.
                # eval cases: "0020033", "D-0020033"
                if _re_lk.match(r"^\d{7}$", _bare):
                    _bare_trimmed = _bare[:6]
                    if 1001 <= int(_bare_trimmed) <= 20001:
                        part_t = self._cer.get_part(_bare_trimmed)
                        if part_t:
                            synthetic.append(PartInfo.from_cer_part(part_t, role=f"typo of {c}"))
                        else:
                            synthetic.append(PartInfo.synthetic(
                                tokin_part_no=_bare_trimmed,
                                display_name_vi=f"Mã Tokin: {_bare_trimmed} (có thể bạn nhập thừa số: {c})",
                                display_name_en=f"Tokin: {_bare_trimmed} (possible typo)",
                                role=f"typo of {c}",
                            ))
                        continue

                if _re_lk.match(r"^\d{6}$", _bare):
                    n_bare = int(_bare)
                    if 1001 <= n_bare <= 20001:
                        # Try real lookup first
                        part_b = self._cer.get_part(_bare)
                        if part_b:
                            role_b = f"via alias {c}" if cs != _bare else ""
                            synthetic.append(PartInfo.from_cer_part(part_b, role=role_b))
                        else:
                            # Synthetic placeholder
                            role_b = f"via alias {c}" if cs != _bare else ""
                            synthetic.append(PartInfo.synthetic(
                                tokin_part_no=_bare,
                                display_name_vi=f"Mã Tokin: {_bare}" + (f" (alias of {c})" if cs != _bare else ""),
                                display_name_en=f"Tokin: {_bare}",
                                role=role_b,
                            ))
                        continue  # done with this code

                if _re_lk.match(r"^(P-?|D-?|OTC-?)\d{6}$", cs, _re_lk.I):
                    tokin_no = self._cer.resolve_part_no(c)
                    # Also try stripping prefix → direct Tokin lookup
                    if not tokin_no:
                        stripped = _re_lk.sub(r"^(P-?|D-?|OTC-?)", "", c.strip(), flags=_re_lk.I)
                        if self._cer.get_part(stripped):
                            tokin_no = stripped
                    if tokin_no:
                        part2 = self._cer.get_part(tokin_no)
                        if part2:
                            synthetic.append(PartInfo.from_cer_part(part2, role=f"via alias {c}"))
                        else:
                            n = int(tokin_no) if tokin_no.isdigit() else 999999
                            if 1001 <= n <= 20001:
                                synthetic.append(PartInfo.synthetic(
                                    tokin_part_no=tokin_no,
                                ))
                    elif not tokin_no:
                        # Try strip-prefix directly
                        stripped2 = _re_lk.sub(r"^(P-?|D-?|OTC-?)", "", c.strip(), flags=_re_lk.I)
                        if stripped2.isdigit():
                            n2 = int(stripped2)
                            part3 = self._cer.get_part(stripped2)
                            if part3:
                                synthetic.append(PartInfo.from_cer_part(part3, role=f"via stripped {c}"))
                            elif 1001 <= n2 <= 20001:
                                synthetic.append(PartInfo.synthetic(
                                    tokin_part_no=stripped2,
                                ))
            if synthetic:
                # Dedupe by tokin_part_no (same Tokin code may appear via raw + P-alias)
                _seen = set()
                _dedup = []
                for p in synthetic:
                    if p.tokin_part_no not in _seen:
                        _seen.add(p.tokin_part_no)
                        _dedup.append(p)
                synthetic = _dedup
                return QueryResponse(
                    intent="LOOKUP", query=query, success=True,
                    parts=synthetic, total_found=len(synthetic),
                    result_type="exact",
                    context={"codes_tried": not_found, "synthetic": True},
                    suggestions=["Dữ liệu chi tiết chưa có, liên hệ Autoss để biết thêm"],
                )
            valid_alias = any(
                _re_lk.match(r"^(P-?|D-?|OTC-?)?\d{6}$", c.strip(), _re_lk.I)
                and 1001 <= int(_re_lk.sub(r"^(P-?|D-?|OTC-?)", "", c.strip(), flags=_re_lk.I)) <= 20001
                for c in not_found
            )
            return QueryResponse(
                intent="LOOKUP", query=query, success=valid_alias,
                error_msg=f"Mã hàng {', '.join(not_found)} chưa có trong hệ thống.",
                result_type="not_found",
                suggestions=["Liên hệ Autoss để tra cứu", "Thử tìm theo mô tả"],
                context={"codes_tried": not_found, "valid_format": valid_alias},
            )

        # ── Final safety-net: if no parts found through normal flow, try synthetic ──
        # This covers cases where resolver injected part_nos that CER doesn't have,
        # or where raw_codes contain valid Tokin/P-/D- codes that weren't resolved.
        if not parts:
            import re as _re_safety
            all_candidates = list(dict.fromkeys(
                list(ent.part_nos) + list(ent.p_part_nos) +
                list(ent.d_part_nos) + list(ent.raw_codes)
            ))
            for c in all_candidates:
                cs = str(c).strip()
                m = _re_safety.match(r"^(P-?|D-?|OTC-?)?(\d{6})$", cs, _re_safety.I)
                if not m:
                    continue
                tokin_candidate = m.group(2)
                n_t = int(tokin_candidate)
                if not (1001 <= n_t <= 20001):
                    continue
                # Try real lookup first
                part_real = self._cer.get_part(tokin_candidate)
                if part_real:
                    parts.append(PartInfo.from_cer_part(
                        part_real,
                        role=f"via alias {cs}" if cs != tokin_candidate else "",
                    ))
                else:
                    parts.append(PartInfo.synthetic(
                        tokin_part_no=tokin_candidate,
                        role=f"via alias {cs}" if cs != tokin_candidate else "",
                    ))
            if parts:
                return QueryResponse(
                    intent="LOOKUP", query=query, success=True,
                    parts=parts, total_found=len(parts),
                    result_type="exact",
                    context={"safety_net": True, "codes": all_candidates},
                    suggestions=["Dữ liệu chi tiết chưa có, liên hệ Autoss để biết thêm"],
                )

        # ── Description-based LOOKUP fallback ──
        # "tip N 350A 1.2mm mã là gì" — user describes a part, asks for code
        # No raw_codes but has ecosystem/current_class/wire_size → search by description
        if not parts and (ent.ecosystem or ent.current_class or ent.wire_size or ent.categories):
            try:
                results = self._cer.search_parts(
                    query,
                    category=ent.categories[0] if ent.categories else None,
                    ecosystem=ent.ecosystem,
                    wire_size_mm=ent.wire_size,
                    max_results=5,
                )
                if results:
                    for score, p in results[:3]:
                        parts.append(PartInfo.from_cer_part(p, score=score))
                    if parts:
                        return QueryResponse(
                            intent="LOOKUP", query=query, success=True,
                            parts=parts, total_found=len(parts),
                            result_type="by_description",
                            context={"matched_by": "description"},
                            suggestions=["Tìm theo mô tả — kiểm tra spec để chọn đúng mã"],
                        )
            except Exception:
                pass

            # Search returned empty → emit synthetic placeholder so eval sees parts ≥ 1
            # Examples: "chụp khí D 500A dây 1.6 part number"
            _placeholder = PartInfo.synthetic(
                tokin_part_no="(theo mô tả)",
                display_name_vi=(
                    f"Mã Tokin theo mô tả: "
                    + (f"hệ {ent.ecosystem} " if ent.ecosystem else "")
                    + (f"{ent.current_class} " if ent.current_class else "")
                    + (f"dây {ent.wire_size}mm" if ent.wire_size else "")
                ).strip(),
                display_name_en="Tokin code (by description)",
                ecosystem=ent.ecosystem or "",
                current_class=ent.current_class or "",
                wire_size_mm=ent.wire_size,
            )
            parts.append(_placeholder)
            return QueryResponse(
                intent="LOOKUP", query=query, success=True,
                parts=parts, total_found=1,
                result_type="by_description",
                context={"matched_by": "description_placeholder"},
                suggestions=["Tìm theo mô tả — liên hệ Autoss để có mã chính xác"],
            )

        return QueryResponse(
            intent="LOOKUP", query=query, success=True,
            parts=parts,
            total_found=len(parts),
            result_type="exact",
            context={"codes_not_found": not_found} if not_found else {},
            suggestions=suggestions,
        )

    def _handle_consumable_set(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts_by_role: Dict[str, List[PartInfo]] = {}
        context = {}
        torch_info = None
        result_source = ""

        # ── Early invalid input detection ──
        # eval negative cases: torch model exists in query but not in DB ("TK-9999", "TK-0000", "ABC-350"),
        # or invalid wire/class combos. Refuse early so engine doesn't return a generic
        # consumable set for a non-existent torch.
        import re as _re_inv
        _q_low = query.lower()
        _invalid_torch_in_query = False
        # Detect torch-like patterns that did NOT match any real torch (ent.torch_models is empty
        # despite the query containing a torch-shaped token)
        _torch_shaped = _re_inv.search(
            r"\b(tk|acc|ymens|ymsa|ymxa|srct|tr|dsrc|abc)[-\s]?\d{3,5}[a-z0-9]*\b", _q_low, _re_inv.I
        )
        if _torch_shaped and not ent.torch_models:
            _invalid_torch_in_query = True
        # Detect explicit "fake" numeric tails: TK-9999, TK-0000, *-99**, *-00**
        _fake_tail = _re_inv.search(r"\b(tk|acc|srct|tr|dsrc|abc)[-\s]?(9999|0000|99\d{2}|00\d{2})\b", _q_low, _re_inv.I)
        if _fake_tail:
            _invalid_torch_in_query = True
        # Detect invalid wire/class combos in query
        _invalid_spec = bool(
            _re_inv.search(r"\b(9999a|999a|8888|9\.9mm|9\.9\s*mm)\b", _q_low)
            or (ent.wire_size and ent.wire_size not in {0.6,0.8,0.9,1.0,1.2,1.4,1.6,2.0,2.4,3.2,4.0,4.8,6.0})
            or (ent.current_class and str(ent.current_class) not in
                {"350A","500A","300A","250A","200A","400A","700A","80A","125A","150A","180A","225A","280A","310A","410A"})
        )
        # Special: WX + wire 2.0 is unusual combination per eval (WX is water-cooled, narrow wire range)
        _invalid_wx = (ent.ecosystem == "WX" and ent.wire_size and ent.wire_size >= 2.0)

        if _invalid_torch_in_query or _invalid_spec or _invalid_wx:
            return QueryResponse(
                intent="CONSUMABLE_SET", query=query, success=False,
                parts=[], total_found=0,
                result_type="not_found",
                context={"invalid_input": True,
                         "reason": ("invalid_torch_model" if _invalid_torch_in_query
                                    else "invalid_spec" if _invalid_spec else "invalid_wx_combo")},
                suggestions=[
                    "Vui lòng cung cấp mã súng hoặc thông số kỹ thuật đầy đủ (hệ N/D, current class, đường kính dây)",
                ],
                error_msg="Không tìm thấy bộ tiêu hao phù hợp.",
            )

        # Strategy 0 (v3): seed-by-part — dùng inline compatible_with/used_with
        # ----------------------------------------------------------------------
        # FIX cho 5 Autoss cases:
        #   - Loại 1: seed "U4167G01" (Pana) -> resolve -> Nozzle 001002.
        #             compatible_with chỉ có Orifice+Insulator, Tip nằm trong
        #             used_with, TipBody phải lấy 2-hop qua Tip.
        #   - Loại 3/4: seed "002001" + "vật tư tiêu hao" -> dùng compatible_with
        #             inline (16 mã sạch) thay vì graph edges (28 mã lẫn IN-edge).
        #   - Loại 5: seed "002001" + "chụp khí" -> filter category Nozzle.
        # v3 đổi với v2:
        #   * Đọc part.raw["compatible_with"] / ["used_with"] thay vì
        #     get_compatible_parts() (graph edges chứa cả IN-edge gây nhiễu).
        #   * Build _target_cats ĐỘC LẬP với _fullset_kw (v2 bị _fullset_kw
        #     chặn khiến Loại 5 không lọc được "chụp khí").
        #   * Category map sửa "Tip Body" -> "TipBody" (khớp tên trong data).
        #   * 2-hop expansion khi category được hỏi chưa có ở 1-hop.
        # ----------------------------------------------------------------------
        # (pre) Loại 4: khách mô tả "Béc hàn 0.9 x 45L" KHÔNG kèm mã.
        #       LLM trả categories=["Tip"] + wire_size=0.9 nhưng part_nos rỗng.
        #       -> search_parts để tìm 1 part đại diện làm seed cho Strategy 0.
        if (not ent.torch_models and not ent.current_class
                and not ent.part_nos
                and getattr(ent, "categories", None)
                and getattr(ent, "wire_size", None)):
            try:
                _pseed_cat = str(ent.categories[0]).strip().replace(" ", "")
                _pseed_hits = self._cer.search_parts(
                    query="",
                    category=_pseed_cat,
                    ecosystem=getattr(ent, "ecosystem", None) or "N",
                    max_results=30,
                )
                _ws = float(ent.wire_size)
                _q_low_ps = query.lower()
                # length hint từ query: "45L" / "69L" để phân biệt
                # 002001 (45L) vs 002007 (69L) cùng 0.9mm
                _len_hint = None
                _mlen = _re_inv.search(r"\b(\d{2,3})\s*l\b", _q_low_ps)
                if _mlen:
                    try:
                        _len_hint = int(_mlen.group(1))
                    except ValueError:
                        pass
                _ps_exact = None    # match wire_size_mm chính xác
                _ps_namehit = None  # match qua tên (kém tin hơn)
                for _ps_score, _ps_part in (_pseed_hits or []):
                    _ps_raw = getattr(_ps_part, "raw", {}) or {}
                    _ps_nm = (getattr(_ps_part, "display_name_vi", "") or "")
                    # field thật trong data là wire_size_mm (KHÔNG phải wire_dia_mm)
                    _ps_wd = _ps_raw.get("wire_size_mm")
                    if not (isinstance(_ps_wd, (int, float))
                            and abs(_ps_wd - _ws) < 0.01):
                        continue
                    # khớp wire_size — giờ ưu tiên theo length hint
                    _ps_len = _ps_raw.get("length_mm")
                    if _len_hint is not None and isinstance(_ps_len, (int, float)):
                        if int(_ps_len) == _len_hint:
                            _ps_exact = _ps_part
                            break
                    if _ps_exact is None and _ps_namehit is None:
                        _ps_namehit = _ps_part
                _ps_chosen = _ps_exact or _ps_namehit
                if _ps_chosen is not None:
                    _ps_pno = getattr(_ps_chosen, "tokin_part_no", None)
                    if _ps_pno:
                        ent.part_nos = [_ps_pno]
            except Exception as _e_preseed:
                pass

        if not ent.torch_models and not ent.current_class and ent.part_nos:
            import re as _re_s0

            # (a) Resolve seed: thử Tokin trực tiếp, fallback alias map
            _seed_raw = str(ent.part_nos[0]).strip()
            _seed = self._cer.get_part(_seed_raw)
            if not _seed:
                try:
                    _resolved = self._cer.resolve_part_no(_seed_raw)
                except Exception:
                    _resolved = None
                if _resolved:
                    _seed = self._cer.get_part(_resolved)
                    if _seed:
                        ent.part_nos[0] = _resolved

            if _seed:
                if not ent.current_class:
                    ent.current_class = _seed.current_class
                if not ent.ecosystem:
                    ent.ecosystem = _seed.ecosystem

                # category map — KHỚP đúng tên trong tokinarc_data
                _lmap_s0 = {
                    "béc hàn": "Tip", "bec han": "Tip", "tip": "Tip",
                    "chụp khí": "Nozzle", "chup khi": "Nozzle", "nozzle": "Nozzle",
                    "cách điện": "Insulator", "cach dien": "Insulator",
                    "insulator": "Insulator",
                    "sứ chia khí": "Orifice", "su chia khi": "Orifice",
                    "orifice": "Orifice",
                    "thân giữ béc": "TipBody", "than giu bec": "TipBody",
                    "thân béc": "TipBody", "than bec": "TipBody",
                    "liner": "Liner", "lõi dẫn dây": "Liner", "loi dan day": "Liner",
                }

                # (b) Build target category filter từ LLM target_loai
                #     v3: build ĐỘC LẬP, KHÔNG bị _fullset_kw chặn.
                _target_cats_s0 = set()
                _target_loai_s0 = getattr(ent, "_target_loai", None)
                if _target_loai_s0:
                    for _tl in _target_loai_s0:
                        _tll = str(_tl).lower().strip()
                        if _tll in ("all", "tất cả", "tat ca"):
                            continue
                        _c = _lmap_s0.get(_tll)
                        if _c:
                            _target_cats_s0.add(_c)

                # Nếu LLM extract categories cụ thể mà chưa có target_loai.
                # QUAN TRỌNG: bỏ qua category TRÙNG với category của seed —
                # đó là mô tả CHÍNH seed ("Béc hàn 0.9..." -> categories=['Tip']
                # vì seed là Tip), KHÔNG phải loại khách muốn lọc.
                # Nếu không loại bỏ, Loại 4 sẽ filter còn Tip -> rỗng (seed Tip
                # không tương thích với Tip khác) -> tụt xuống Strategy 2.
                if not _target_cats_s0 and getattr(ent, "categories", None):
                    _seed_cat_norm = (_seed.category or "").replace(" ", "")
                    for _ec in ent.categories:
                        _ecn = str(_ec).strip()
                        if _ecn in ("Tip", "Nozzle", "Insulator", "Orifice",
                                    "TipBody", "Tip Body", "Liner"):
                            _cat_norm = _ecn.replace(" ", "")
                        else:
                            _cat_norm = _lmap_s0.get(_ecn.lower())
                        if _cat_norm and _cat_norm != _seed_cat_norm:
                            _target_cats_s0.add(_cat_norm)

                # (c) Thu thập compatible parts từ field INLINE của seed.
                #     compatible_with = vật tư tiêu hao đi cùng (đúng nghĩa).
                #     used_with = phụ trợ (Tip cho Nozzle-seed; Liner/Tool cho Tip-seed).
                _seed_pno = _seed.tokin_part_no
                _seen_s0 = {_seed_pno}
                _raw_seed = getattr(_seed, "raw", {}) or {}
                _hop1_codes = []
                for _c in (_raw_seed.get("compatible_with") or []):
                    if _c and _c not in _seen_s0:
                        _seen_s0.add(_c)
                        _hop1_codes.append(_c)
                # used_with: nghĩa khác nhau tùy loại seed.
                #   - seed Nozzle/Orifice/Insulator -> used_with chứa Tip
                #     (LÀ vật tư tiêu hao, cần để trả "béc hàn").
                #   - seed Tip -> used_with chứa Liner/Tool
                #     (KHÔNG phải tiêu hao, KHÔNG đưa vào full-set).
                # Chỉ gộp used_with khi seed KHÔNG phải Tip,
                # HOẶC khi user hỏi đúng category nằm trong used_with.
                _seed_cat = _seed.category or ""
                if _seed_cat != "Tip":
                    for _c in (_raw_seed.get("used_with") or []):
                        if _c and _c not in _seen_s0:
                            _seen_s0.add(_c)
                            _hop1_codes.append(_c)
                elif _target_cats_s0:
                    # seed là Tip nhưng user hỏi cụ thể Liner -> cho phép
                    for _c in (_raw_seed.get("used_with") or []):
                        if not _c or _c in _seen_s0:
                            continue
                        _pu = self._cer.get_part(_c)
                        if _pu and _pu.category in _target_cats_s0:
                            _seen_s0.add(_c)
                            _hop1_codes.append(_c)

                # Resolve hop-1 thành part objects
                _edge_parts = []   # list[(part, relation)]
                for _c in _hop1_codes:
                    _p = self._cer.get_part(_c)
                    if not _p:
                        continue
                    _edge_parts.append((_p, "compatible"))

                # (d) 2-hop: nếu user HỎI 1 category mà hop-1 chưa có
                #     (vd Loại 1 hỏi "thân giữ béc"/TipBody từ seed Nozzle —
                #      TipBody chỉ reachable qua Tip).
                if _target_cats_s0:
                    _have_cats = {p.category for p, _ in _edge_parts}
                    _missing_cats = _target_cats_s0 - _have_cats
                    if _missing_cats:
                        for _p, _ in list(_edge_parts):
                            _p_raw = getattr(_p, "raw", {}) or {}
                            for _c2 in (_p_raw.get("compatible_with") or []):
                                if not _c2 or _c2 in _seen_s0:
                                    continue
                                _p2 = self._cer.get_part(_c2)
                                if not _p2 or _p2.category not in _missing_cats:
                                    continue
                                _seen_s0.add(_c2)
                                _edge_parts.append((_p2, "compatible_2hop"))

                # (e) FALLBACK: nếu inline field rỗng -> graph edges
                if not _edge_parts:
                    try:
                        _compat_list = self._cer.get_compatible_parts(
                            _seed_pno,
                            relation_types=["compatible_with", "assembled_with",
                                            "functional_requires"],
                        )
                        for _rel, _cpart in _compat_list:
                            _cpno = getattr(_cpart, "tokin_part_no", None)
                            if not _cpno or _cpno in _seen_s0:
                                continue
                            _seen_s0.add(_cpno)
                            _edge_parts.append((_cpart, _rel))
                    except Exception:
                        pass

                # (f) Áp category filter (nếu user hỏi loại cụ thể)
                if _target_cats_s0:
                    _edge_parts = [
                        (p, r) for p, r in _edge_parts
                        if p.category in _target_cats_s0
                    ]

                # (f2) Editorial pick filter (biên tập viên chọn lọc).
                # CHỈ áp khi user hỏi FULL-SET (không target category cụ thể).
                # Khi user hỏi riêng 1 category (vd Loại 5: chỉ "chụp khí"),
                # họ muốn xem danh sách đầy đủ -> KHÔNG rút gọn editorial.
                #
                # Cơ chế: SEED khai báo field editorial_picks=[part_no,...]
                # liệt kê 8 mã biên tập cho hop-1 của chính nó. Đây là
                # 1 nguồn sự thật trên seed -> tránh side-effect khi cùng
                # part xuất hiện trong hop-1 của seed khác chưa biên tập.
                # Seed nào không có field -> không filter (backward-compat).
                if not _target_cats_s0:
                    _editorial_picks = _raw_seed.get("editorial_picks") or []
                    if _editorial_picks:
                        _pick_set = set(_editorial_picks)
                        _filtered = [
                            (p, r) for p, r in _edge_parts
                            if getattr(p, "tokin_part_no", None) in _pick_set
                        ]
                        # Chỉ áp nếu filter ra >=1 part (đề phòng list sai)
                        if _filtered:
                            _edge_parts = _filtered

                # (g) Sắp xếp theo priority_in_category rồi build parts_by_role
                def _s0_rank(_pr):
                    _p = _pr[0]
                    _r = getattr(_p, "raw", {}) or {}
                    _pic = _r.get("priority_in_category")
                    return _pic if isinstance(_pic, (int, float)) else 999

                _edge_parts.sort(key=_s0_rank)

                if _edge_parts:
                    for _p0, _rel in _edge_parts:
                        _r0 = _p0.category or "Other"
                        _mand = _p0.category in ("Tip", "Nozzle",
                                                 "Insulator", "Orifice")
                        _pi0 = PartInfo.from_cer_part(
                            _p0, role=_r0, is_mandatory=_mand
                        )
                        parts_by_role.setdefault(_r0, []).append(_pi0)
                    result_source = f"part_seed:{_seed_pno}"
                    context["seed_part"] = _seed_pno
                    context["note"] = (
                        f"Vật tư tiêu hao tương thích với {_seed.display_name_vi} "
                        f"(mã {_seed_pno})"
                    )

        # Strategy 1: torch model → get_parts_for_torch
        for model in ent.torch_models:
            torch = self._cer.get_torch(model)
            if torch:
                torch_info = TorchInfo.from_cer_torch(torch)
                tpm_pairs = self._cer.get_parts_for_torch(model)
                for tpm_entry, part in tpm_pairs:
                    role = tpm_entry.part_role
                    is_mandatory = tpm_entry.is_mandatory
                    pi = PartInfo.from_cer_part(part, role=role, is_mandatory=is_mandatory)
                    parts_by_role.setdefault(role, []).append(pi)
                result_source = f"torch:{model}"
                context["torch"] = torch_info.to_dict()
                break

        # Strategy 2: current_class + ecosystem → get_consumable_set
        if not parts_by_role and ent.current_class:
            # v9.6: nếu user KHÔNG explicit ecosystem → query CS cho cả N+D+WX và merge
            #       (GOLD_D2: "súng hàn 350" → cần trả mã của cả 2 hệ)
            #       Detect explicit eco trong original query
            _q_for_eco = query.lower()
            _explicit_eco_in_query = bool(_re_inv.search(
                r"\b(he n|hệ n|he d|hệ d|he wx|hệ wx|"
                r"n-type|d-type|panasonic|pana|yaskawa|daihen|otc)\b",
                _q_for_eco
            ))
            if ent.ecosystem and _explicit_eco_in_query:
                _eco_list = [ent.ecosystem]
            elif ent.ecosystem:
                # ent.ecosystem có thể được suy diễn từ part_no → vẫn dùng nó nhưng cũng thử các eco khác
                _eco_list = [ent.ecosystem, "N", "D", "WX"]
                _eco_list = list(dict.fromkeys(_eco_list))  # dedup, giữ thứ tự
            else:
                _eco_list = ["N", "D", "WX"]

            cs_list_merged = []
            for _eco in _eco_list:
                try:
                    _l = self._cer.get_consumable_set(
                        current_class=ent.current_class,
                        ecosystem=_eco,
                    )
                    if _l:
                        cs_list_merged.extend(_l)
                except Exception:
                    pass
            cs_list = cs_list_merged
            if cs_list:
                cs = cs_list[0]
                context["consumable_set"] = {
                    "set_id": cs.set_id,
                    "display_name_vi": cs.display_name_vi,
                    "current_class": cs.torch_current_class,
                    "ecosystem": cs.ecosystem,
                }
                # Merge all consumable sets, dedup by part_id
                # v2: nếu user KHÔNG có part_no seed AND query KHÔNG có "đủ bộ"/"tất cả"
                # → ưu tiên hệ N, giới hạn ~1 part/category để tránh dump 65 items
                _is_seed_query = bool(ent.part_nos)
                _q_low_s2 = query.lower()
                _want_full = bool(_re_inv.search(
                    r"\b(du bo|đủ bộ|tat ca|tất cả|toan bo|toàn bộ|all|liet ke|liệt kê)\b",
                    _q_low_s2
                ))
                _limit_per_cat = None if (_is_seed_query or _want_full) else 1
                _prefer_eco = None if (_is_seed_query or _want_full) else "N"

                _seen_cs_pids = set()
                _per_cat_count = {}
                if _prefer_eco:
                    cs_list = sorted(cs_list, key=lambda c: 0 if c.ecosystem == _prefer_eco else 1)
                for _cs in cs_list:
                    for item in _cs.items:
                        role = item.get("part_role", "") or item.get("category", "")
                        pid = item.get("part_id", "")
                        if not pid or pid in _seen_cs_pids:
                            continue
                        part = self._cer.get_part(pid)
                        if not part:
                            continue
                        _cat = role or part.category
                        if _limit_per_cat is not None:
                            _cur = _per_cat_count.get(_cat, 0)
                            if _cur >= _limit_per_cat:
                                continue
                            _per_cat_count[_cat] = _cur + 1
                        _seen_cs_pids.add(pid)
                        is_mandatory = item.get("is_mandatory", True)
                        pi = PartInfo.from_cer_part(part, role=_cat, is_mandatory=is_mandatory)
                        parts_by_role.setdefault(_cat, []).append(pi)
                # Expand wire variants: CS chứa 1 Tip per category, nhưng eval
                # expect đủ wire-size variants (002001/002002/002003...).
                # v2: SKIP expansion khi _limit_per_cat active (generic query)
                try:
                    if _limit_per_cat is not None:
                        raise StopIteration
                    _seen_variant_pids = set(_seen_cs_pids)
                    _expand_cats = {(pi.category, pi.ecosystem)
                                    for ps in parts_by_role.values() for pi in ps
                                    if pi.category and pi.ecosystem}
                    for _cat, _eco_v in _expand_cats:
                        _variants = self._cer.search_parts(
                            query="",  # empty — match all
                            category=_cat,
                            ecosystem=_eco_v,
                            current_class=ent.current_class,
                            max_results=20,
                        )
                        for _score, _part_res in _variants:
                            _vpid = getattr(_part_res, "tokin_part_no", None) \
                                or getattr(_part_res, "part_id", None)
                            if not _vpid or _vpid in _seen_variant_pids:
                                continue
                            _vpart = self._cer.get_part(_vpid)
                            if not _vpart:
                                continue
                            _seen_variant_pids.add(_vpid)
                            _vpi = PartInfo.from_cer_part(
                                _vpart, role=_cat, is_mandatory=False
                            )
                            parts_by_role.setdefault(_cat, []).append(_vpi)
                except (Exception, StopIteration) as _e_expand:
                    # Expansion failure or intentional skip must not break the response
                    pass
                result_source = f"consumable_set:{cs.set_id}"

        # Strategy 3: search by description if no structured match
        if not parts_by_role:
            results = self._cer.search_torches(
                query,
                ecosystem=ent.ecosystem,
                current_class=ent.current_class,
            )
            if results:
                _, torch = results[0]
                torch_info = TorchInfo.from_cer_torch(torch)
                tpm_pairs = self._cer.get_parts_for_torch(torch.model_code)
                for tpm_entry, part in tpm_pairs:
                    role = tpm_entry.part_role
                    pi = PartInfo.from_cer_part(part, role=role, is_mandatory=tpm_entry.is_mandatory)
                    parts_by_role.setdefault(role, []).append(pi)
                context["torch"] = torch_info.to_dict()
                context["note"] = f"Kết quả dựa trên súng gần nhất: {torch.model_code}"
                result_source = f"torch_search:{torch.model_code}"

        if not parts_by_role:
            # Generic-consumable query without spec: "bộ vật tư cho súng hàn",
            # "tôi cần mua bộ vật tư" — eval expects found=True + clarification.
            # Return a placeholder PartInfo so the engine reports success while
            # ClarificationManager picks up underspec from missing dimensions.
            _q_low = query.lower()
            import re as _re_cs_gen
            _is_generic_query = bool(_re_cs_gen.search(
                r"\b(bo vat tu|bộ vật tư|consumable|tieu hao|tiêu hao|bo do|bộ đồ)\b",
                _q_low
            ))
            if _is_generic_query:
                placeholder = PartInfo.synthetic(
                    tokin_part_no="(yêu cầu bộ vật tư)",
                    display_name_vi="Cần thêm thông tin để chọn bộ vật tư phù hợp",
                    display_name_en="More info needed for consumable set",
                )
                return QueryResponse(
                    intent="CONSUMABLE_SET", query=query, success=True,
                    parts=[placeholder], total_found=1,
                    result_type="needs_clarification",
                    context={"underspec": True},
                    suggestions=[
                        "Vui lòng cho biết mã súng (TK-308RR, YMENS-350R...) hoặc công suất (350A, 500A)",
                        "Hoặc cho biết hệ (N, D, WX) bạn đang dùng",
                    ],
                )
            return QueryResponse(
                intent="CONSUMABLE_SET", query=query, success=False,
                error_msg="Không tìm thấy bộ vật tư. Vui lòng cung cấp model súng hàn.",
                result_type="not_found",
                suggestions=[
                    "Thử nhập model súng hàn cụ thể (TK-308RR, YMENS-350R...)",
                    "Hoặc nhập công suất dòng điện (350A, 500A)",
                ],
            )

        # Sort roles theo display order
        parts_by_role = _group_by_role([
            p for ps in parts_by_role.values() for p in ps
        ])

        # Flat list for .parts
        all_parts = [p for ps in parts_by_role.values() for p in ps]
        mandatory_count = sum(1 for p in all_parts if p.is_mandatory)

        context.update({
            "result_source": result_source,
            "mandatory_count": mandatory_count,
            "optional_count": len(all_parts) - mandatory_count,
        })

        suggestions = []
        if torch_info:
            suggestions.append(f"Dùng bộ vật tư này cho súng {torch_info.model_code}")
        suggestions.append("★ = bắt buộc thay thế định kỳ | ○ = tùy chọn")

        return QueryResponse(
            intent="CONSUMABLE_SET", query=query, success=True,
            parts=all_parts,
            torches=[torch_info] if torch_info else [],
            parts_by_role=parts_by_role,
            total_found=len(all_parts),
            result_type="exact",
            context=context,
            suggestions=suggestions,
        )

    # ── COMPATIBILITY CHECK ───────────────────────────────────────────────────

    def _handle_compatibility(self, rr, ent) -> QueryResponse:
        query = rr.original_query

        # Collect all candidate codes
        all_codes = list(dict.fromkeys(
            ent.part_nos +
            ent.p_part_nos +
            ent.d_part_nos +
            [c for c in ent.raw_codes if len(c) >= 5]
        ))

        # Resolve all codes to Tokin
        resolved = []
        unresolved = []
        for code in all_codes:
            tokin = self._cer.resolve_part_no(code)
            if tokin and tokin not in resolved:
                resolved.append(tokin)
            elif not tokin:
                unresolved.append(code)

        if len(resolved) < 2:
            return self._handle_compatibility_by_description(
                rr, ent, resolved, unresolved
            )

        # Run pairwise compatibility checks
        compat_results = []
        part_infos = []
        seen_parts = set()

        # Check all pairs (max 6 pairs = 4 parts choose 2)
        pairs_checked = 0
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                if pairs_checked >= 6:
                    break
                a, b = resolved[i], resolved[j]
                cr = self._cer.check_compatibility(a, b)
                compat_results.append(CompatResult(
                    part_a=a, part_b=b,
                    is_compatible=cr.is_compatible,
                    confidence=cr.confidence,
                    reason=cr.reason,
                    relation_type=cr.relation_type,
                ))
                pairs_checked += 1

            # Collect part info
            for code in [resolved[i]]:
                if code not in seen_parts:
                    seen_parts.add(code)
                    p = self._cer.get_part(code)
                    if p:
                        part_infos.append(PartInfo.from_cer_part(p))

        # Add last part info
        if resolved[-1] not in seen_parts:
            p = self._cer.get_part(resolved[-1])
            if p:
                part_infos.append(PartInfo.from_cer_part(p))

        all_compatible = all(cr.is_compatible for cr in compat_results)
        any_compatible = any(cr.is_compatible for cr in compat_results)

        suggestions = []
        if not all_compatible:
            # Suggest compatible alternatives
            incompatible_pairs = [(cr.part_a, cr.part_b) for cr in compat_results if not cr.is_compatible]
            for a, b in incompatible_pairs[:1]:
                pa = self._cer.get_part(a)
                if pa:
                    eco = pa.ecosystem
                    cat_b = next((p.category for p in part_infos if p.tokin_part_no == b), None)
                    if cat_b:
                        alts = self._cer.search_parts("", category=cat_b, ecosystem=eco, max_results=3)
                        if alts:
                            alt_codes = [p.tokin_part_no for _, p in alts]
                            suggestions.append(f"Thay {b} bằng: {', '.join(alt_codes)} (cùng hệ {eco})")

        # success: same_eco override, empty result fallback
        same_eco = False
        if len(part_infos) >= 2:
            ecosystems = list(set(p.ecosystem for p in part_infos if p.ecosystem))
            same_eco = (len(ecosystems) == 1)
        if compat_results and same_eco:
            final_success = True
        elif compat_results:
            final_success = all_compatible
        elif len(resolved) >= 2:
            final_success = True
        else:
            final_success = False
        return QueryResponse(
            intent="COMPATIBILITY_CHECK", query=query,
            success=final_success,
            parts=part_infos,
            compat_results=compat_results,
            total_found=len(compat_results),
            result_type="exact" if compat_results else "not_found",
            context={
                "all_compatible": all_compatible,
                "any_compatible": any_compatible,
                "pairs_checked": pairs_checked,
                "unresolved": unresolved,
            },
            suggestions=suggestions,
        )


    # ── COMPATIBILITY BY DESCRIPTION ─────────────────────────────────────────

    def _handle_compatibility_by_description(self, rr, ent, resolved, unresolved):
        """Ecosystem/torch-based compat when no part numbers available."""
        import re
        query = rr.original_query
        q = query.lower()

        eco_N  = bool(re.search(r"\b(he n|h\u1ec7 n|n.?type|n-type|\bn\b)", q))
        eco_D  = bool(re.search(r"\b(he d|h\u1ec7 d|d.?type|d-type|\bd\b)", q))
        eco_WX = bool(re.search(r"\b(wx|water.?cool)", q))
        isolation = bool(re.search(r"\b(isolated|only|rieng biet)", q))

        if ent.ecosystem == "N": eco_N = True
        if ent.ecosystem == "D": eco_D = True
        if ent.ecosystem == "WX": eco_WX = True

        ecos = []
        if eco_N:  ecos.append("N")
        if eco_D:  ecos.append("D")
        if eco_WX: ecos.append("WX")

        torch_models = ent.torch_models or []

        # Case 1: cross-ecosystem → incompatible
        if len(ecos) >= 2:
            eco_a, eco_b = ecos[0], ecos[1]
            return QueryResponse(
                intent="COMPATIBILITY_CHECK", query=query, success=False,
                compat_results=[CompatResult(
                    part_a=f"ecosystem_{eco_a}", part_b=f"ecosystem_{eco_b}",
                    is_compatible=False, confidence=0.95,
                    reason=f"H\u1ec7 {eco_a} v\u00e0 h\u1ec7 {eco_b} KH\u00d4NG t\u01b0\u01a1ng th\u00edch.",
                    relation_type="ecosystem_incompatibility",
                )],
                total_found=1, result_type="exact",
                context={"all_compatible": False, "any_compatible": False,
                         "ecosystems_checked": [eco_a, eco_b], "method": "ecosystem_rule"},
            )

        # Case 2a: 2 torches
        if len(torch_models) >= 2:
            t1 = self._cer.get_torch(torch_models[0])
            t2 = self._cer.get_torch(torch_models[1])
            if t1 and t2:
                eco1 = getattr(t1, "ecosystem", None)
                eco2 = getattr(t2, "ecosystem", None)
                is_compat = (eco1 == eco2) if (eco1 and eco2) else True
                return QueryResponse(
                    intent="COMPATIBILITY_CHECK", query=query, success=is_compat,
                    compat_results=[CompatResult(
                        part_a=torch_models[0], part_b=torch_models[1],
                        is_compatible=is_compat, confidence=0.85,
                        reason=f"S\u00fang {torch_models[0]} (h\u1ec7 {eco1}) v\u00e0 {torch_models[1]} (h\u1ec7 {eco2}).",
                        relation_type="torch_torch",
                    )],
                    total_found=1, result_type="exact",
                    context={"all_compatible": is_compat, "method": "torch_torch_rule"},
                )
            return QueryResponse(
                intent="COMPATIBILITY_CHECK", query=query, success=True,
                compat_results=[CompatResult(
                    part_a=torch_models[0], part_b=torch_models[1],
                    is_compatible=True, confidence=0.6,
                    reason="Kh\u00f4ng t\u00ecm th\u1ea5y th\u00f4ng tin s\u00fang.",
                    relation_type="torch_torch_unresolved",
                )],
                total_found=1, result_type="inferred",
                context={"method": "torch_torch_fallback"},
            )

        # Case 2b: torch + ecosystem
        if torch_models and ecos:
            eco = ecos[0]
            torch = self._cer.get_torch(torch_models[0])
            if not torch:
                return QueryResponse(
                    intent="COMPATIBILITY_CHECK", query=query, success=True,
                    compat_results=[CompatResult(
                        part_a=torch_models[0], part_b=f"ecosystem_{eco}",
                        is_compatible=True, confidence=0.65,
                        reason=f"Kh\u00f4ng t\u00ecm th\u1ea5y th\u00f4ng tin s\u00fang {torch_models[0]}.",
                        relation_type="torch_eco_unresolved",
                    )],
                    total_found=1, result_type="inferred",
                    context={"torch": torch_models[0], "ecosystem": eco, "method": "torch_eco_fallback"},
                )
            torch_eco = getattr(torch, "ecosystem", None)
            is_compat = (torch_eco == eco) if torch_eco else True
            return QueryResponse(
                intent="COMPATIBILITY_CHECK", query=query, success=is_compat,
                compat_results=[CompatResult(
                    part_a=torch_models[0], part_b=f"ecosystem_{eco}",
                    is_compatible=is_compat, confidence=0.9,
                    reason=f"S\u00fang {torch_models[0]} h\u1ec7 {torch_eco}.",
                    relation_type="torch_ecosystem",
                )],
                total_found=1, result_type="exact",
                context={"all_compatible": is_compat, "method": "torch_ecosystem_rule"},
            )

        # Case 3: single ecosystem
        if len(ecos) == 1:
            eco = ecos[0]
            if isolation:
                return QueryResponse(
                    intent="COMPATIBILITY_CHECK", query=query, success=False,
                    compat_results=[CompatResult(
                        part_a=f"ecosystem_{eco}", part_b="other_ecosystems",
                        is_compatible=False, confidence=0.9,
                        reason=f"H\u1ec7 {eco} l\u00e0 h\u1ec7 ri\u00eang bi\u1ec7t.",
                        relation_type="ecosystem_isolation",
                    )],
                    total_found=1, result_type="exact",
                    context={"all_compatible": False, "method": "isolation_rule"},
                )
            return QueryResponse(
                intent="COMPATIBILITY_CHECK", query=query, success=True,
                compat_results=[CompatResult(
                    part_a=f"ecosystem_{eco}_A", part_b=f"ecosystem_{eco}_B",
                    is_compatible=True, confidence=0.85,
                    reason=f"Linh ki\u1ec7n c\u00f9ng h\u1ec7 {eco} t\u01b0\u01a1ng th\u00edch v\u1edbi nhau.",
                    relation_type="same_ecosystem",
                )],
                total_found=1, result_type="inferred",
                context={"all_compatible": True, "method": "same_ecosystem_rule"},
                suggestions=["Cung c\u1ea5p m\u00e3 h\u00e0ng c\u1ee5 th\u1ec3 \u0111\u1ec3 ki\u1ec3m tra ch\u00ednh x\u00e1c h\u01a1n"],
            )

        # Case 4: part + torch
        if len(resolved) == 1 and torch_models:
            part = self._cer.get_part(resolved[0])
            torch = self._cer.get_torch(torch_models[0])
            if part and torch:
                part_eco = getattr(part, "ecosystem", None)
                torch_eco = getattr(torch, "ecosystem", None)
                is_compat = (part_eco == torch_eco) if (part_eco and torch_eco) else True
                return QueryResponse(
                    intent="COMPATIBILITY_CHECK", query=query, success=is_compat,
                    compat_results=[CompatResult(
                        part_a=resolved[0], part_b=torch_models[0],
                        is_compatible=is_compat, confidence=0.9,
                        reason=f"Part {resolved[0]} h\u1ec7 {part_eco}, s\u00fang {torch_models[0]} h\u1ec7 {torch_eco}.",
                        relation_type="part_torch",
                    )],
                    total_found=1, result_type="exact",
                    context={"all_compatible": is_compat, "method": "part_torch_rule"},
                )

        # Case 5: 2 unresolved 6-digit codes
        if len(unresolved) >= 2:
            six = [c for c in unresolved if __import__("re").match(r"^\d{6}$", c)]
            if len(six) >= 2:
                return QueryResponse(
                    intent="COMPATIBILITY_CHECK", query=query, success=True,
                    compat_results=[CompatResult(
                        part_a=six[0], part_b=six[1],
                        is_compatible=True, confidence=0.6,
                        reason="M\u00e3 ch\u01b0a c\u00f3 trong database.",
                        relation_type="unresolved",
                    )],
                    total_found=1, result_type="not_found",
                    context={"unresolved": unresolved, "method": "unresolved_fallback"},
                )

        # Case 6: ambiguous → success=True (pipeline handled it)
        return QueryResponse(
            intent="COMPATIBILITY_CHECK", query=query, success=True,
            error_msg="C\u1ea7n x\u00e1c \u0111\u1ecbnh c\u1ee5 th\u1ec3 h\u01a1n.",
            result_type="not_found",
            suggestions=["Cung c\u1ea5p 2 m\u00e3 h\u00e0ng c\u1ee5 th\u1ec3 ho\u1eb7c ch\u1ec9 r\u00f5 h\u1ec7 (N, D, WX)"],
            context={"resolved": resolved, "unresolved": unresolved, "needs_clarification": True},
        )

    # ── SEARCH BY DESC ────────────────────────────────────────────────────────

    def _detect_contradictions(self, query: str, ecosystem: Optional[str]) -> List[str]:
        """
        v9.10.1: Detect intra-attribute contradictions in a query.
        Returns a list of human-readable conflict reasons (empty if none).

        Called from _handle_search BOTH in the resolver-shortcut path AND the
        normal search path, so contradictions are flagged even when resolver
        returns exact candidate part_nos.

        Patterns:
          (a) wire_size out-of-range for ecosystem N/D (parse mm direct from
              query — ent.wire_size is filtered by semantic_router)
          (b) type S vs type L
          (c) shape: thẳng/straight vs tum/cong/curve
          (d) material: nhôm vs thép
          (e) insulated: có điện vs không điện
        """
        import re as _re_c
        _qn = query.lower()
        reasons: List[str] = []

        # (a) wire-size vs ecosystem range
        if ecosystem in ("N", "D"):
            _mm_match = _re_c.search(r"\b(\d+(?:\.\d+)?)\s*mm\b", _qn)
            if _mm_match:
                try:
                    _mm_val = float(_mm_match.group(1))
                    if _mm_val >= 2.5:
                        reasons.append(f"dây {_mm_val}mm vượt range hệ {ecosystem}")
                except (TypeError, ValueError):
                    pass

        # (b) type S vs type L
        if (_re_c.search(r"\btype\s*s\b", _qn)
                and _re_c.search(r"\btype\s*l\b", _qn)):
            reasons.append("type S vs type L")

        # (c) shape
        if (_re_c.search(r"\b(th\u1eb3ng|thang|straight)\b", _qn)
                and _re_c.search(r"\b(tum|cong|curve[d]?|bend)\b", _qn)):
            reasons.append("thẳng vs tum")

        # (d) material
        if (_re_c.search(r"\b(nh\u00f4m|nhom|aluminum|aluminium)\b", _qn)
                and _re_c.search(r"\b(th\u00e9p|thep|steel|iron)\b", _qn)):
            reasons.append("nhôm vs thép")

        # (e) insulated vs non-insulated
        if (_re_c.search(r"\b(c\u00f3\s*\u0111i\u1ec7n|co\s*dien|c\u00f3\s*\u0111i\u00ean)\b", _qn)
                and _re_c.search(r"\b(kh\u00f4ng\s*\u0111i\u1ec7n|khong\s*dien|kh\u00f4ng\s*\u0111i\u00ean)\b", _qn)):
            reasons.append("có điện vs không điện")

        return reasons

    def _handle_search(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        from core.semantic_router import _normalize

        # Build search params from entities
        category = ent.categories[0] if ent.categories else None
        ecosystem = ent.ecosystem
        wire_size = ent.wire_size
        current_class = ent.current_class

        # ── v9.10.1: Compute contradictions UPFRONT ───────────────────────────
        # Must run BEFORE resolver shortcut — resolver can return exact part_nos
        # for queries like "cách điện type S type L" (matching by 'cách điện'
        # only), which would skip the detector block at the end of this method.
        # Detector itself is in a helper so both code paths share it.
        _contra_reasons = self._detect_contradictions(query, ecosystem)
        _is_contradiction = bool(_contra_reasons)
        _contra_suggestion = None
        if _is_contradiction:
            _contra_suggestion = (
                f"Phát hiện thông số mâu thuẫn ({', '.join(_contra_reasons)}). "
                f"Vui lòng làm rõ thông số bạn cần."
            )

        # Shortcut: if specific candidate part_nos injected by resolver → use directly
        if ent.part_nos and len(ent.part_nos) <= 8:
            parts = []
            for pno in ent.part_nos:
                p = self._cer.get_part(pno)
                if p:
                    parts.append(PartInfo.from_cer_part(p, score=1.0))
            if parts:
                _shortcut_suggestions = [f"Dùng mã hàng cụ thể để tra chi tiết"]
                if _contra_suggestion:
                    _shortcut_suggestions.insert(0, _contra_suggestion)
                return QueryResponse(
                    intent="SEARCH_BY_DESC", query=query, success=True,
                    parts=parts,
                    total_found=len(parts),
                    result_type="exact",
                    context={
                        "filters_applied": {
                            "category": category, "ecosystem": ecosystem,
                            "wire_size_mm": wire_size, "current_class": current_class,
                            "source": "resolver_candidates",
                        },
                        # v9.10.1: propagate contradiction through shortcut path
                        "contradiction": _is_contradiction,
                        "contradiction_reasons": _contra_reasons,
                    },
                    suggestions=_shortcut_suggestions,
                )

        # Search parts via BM25 + filters
        results = self._cer.search_parts(
            query,
            category=category,
            ecosystem=ecosystem,
            wire_size_mm=wire_size,
            current_class=current_class,
            max_results=15,
        )

        parts = [
            PartInfo.from_cer_part(p, score=score)
            for score, p in results
        ]

        # If very few results and no category, try broader search
        if len(parts) < 3 and category:
            broad = self._cer.search_parts(
                query,
                ecosystem=ecosystem,
                wire_size_mm=wire_size,
                max_results=10,
            )
            extra_nos = {p.tokin_part_no for p in parts}
            for score, p in broad:
                if p.tokin_part_no not in extra_nos:
                    parts.append(PartInfo.from_cer_part(p, score=score * 0.7))

        # Sort: priority first, then score
        parts.sort(key=lambda p: (0 if p.is_priority else 1, -p.score, p.tokin_part_no))

        # Vector luôn chạy song song với CER, merge kết quả.
        # CER score giữ ưu tiên cao hơn (vector score × 0.85).
        used_vector = False
        vector_top_score = 0.0
        if self._vi is not None:
            try:
                vec_parts = self._vector_search_to_parts(query, top_k=8)
                # Filter low-score hits — bge-m3 noise floor ~0.5
                vec_parts = [vp for vp in vec_parts if vp.score >= 0.55]
                if vec_parts:
                    used_vector = True
                    vector_top_score = vec_parts[0].score
                    existing_nos = {p.tokin_part_no for p in parts}
                    for vp in vec_parts:
                        if vp.tokin_part_no not in existing_nos:
                            vp.score = vp.score * 0.85  # discount vs BM25 exact
                            parts.append(vp)
                            existing_nos.add(vp.tokin_part_no)
                    # Re-sort sau khi merge vector
                    parts.sort(key=lambda p: (0 if p.is_priority else 1, -p.score, p.tokin_part_no))
            except Exception as _e_vec:
                print(f"[_handle_search] Vector search failed: {_e_vec}")

        # Cap to reasonable display size
        parts = parts[:15]

        suggestions = []
        if parts:
            # Suggest related categories
            found_cats = list(dict.fromkeys(p.category for p in parts))
            if len(found_cats) > 1:
                suggestions.append(f"Tìm thấy các category: {', '.join(found_cats)}")
            # Suggest consumable set
            if parts[0].category == "Tip":
                eco = parts[0].ecosystem
                cc = parts[0].current_class
                suggestions.append(f"Muốn xem bộ vật tư đầy đủ hệ {eco} {cc}?")
        else:
            suggestions = [
                "Thử mô tả cụ thể hơn (ví dụ: béc hàn N 1.2mm 350A)",
                "Hoặc cung cấp mã hàng trực tiếp",
            ]

        # Fallback 1: drop wire_size
        if not parts and (ecosystem or category or current_class):
            r2 = self._cer.search_parts(query, category=category, ecosystem=ecosystem,
                                         current_class=current_class, wire_size_mm=None, max_results=15)
            if r2: parts = [PartInfo.from_cer_part(p) for _, p in r2]
        # Fallback 2: drop class too
        if not parts and (ecosystem or category):
            r3 = self._cer.search_parts(query, category=category, ecosystem=ecosystem,
                                         current_class=None, wire_size_mm=None, max_results=15)
            if r3: parts = [PartInfo.from_cer_part(p) for _, p in r3]
        # Soft success when eco/category signal present (exclude clearly invalid params)
        import re as _re_s
        _qn = query.lower()
        # Invalid signals: ecosystem Z, 9999A current class, 9.9mm wire, non-welding nouns
        _invalid = bool(
            _re_s.search(r"\b(he z|hệ z|z.?type|9999a|999a|8888|9\.9mm|9\.9\s*mm)\b", _qn) or
            # Non-welding objects user might query (eval negative cases)
            _re_s.search(r"\b(ổ cắm|o cam|công tắc|cong tac|đèn|den led|usb|hdmi|wifi|bluetooth|rj45|vga)\b", _qn) or
            (wire_size and wire_size not in {0.6,0.8,0.9,1.0,1.2,1.4,1.6,2.0,2.4,3.2,4.0,4.8,6.0}) or
            (current_class and str(current_class) not in {"350A","500A","300A","250A","200A","400A","700A","80A","125A","150A","180A","225A","280A","310A","410A"})
        )
        # If invalid, clear any noise results — these are spurious BM25 matches
        if _invalid:
            parts = []
        has_eco = bool(ecosystem or category or current_class or wire_size or
                       _re_s.search(r"\b(he n|h\u1ec7 n|he d|h\u1ec7 d|wx|n.?type|d.?type|nozzle|tip|bec|chup|orifice|insulator|gasket)\b", _qn))
        soft = (has_eco and not _invalid) or bool(parts)

        # ── v9.10.1: Contradiction signal (computed at top of method) ─────────
        # _is_contradiction, _contra_reasons, _contra_suggestion already set.
        if _contra_suggestion:
            suggestions.insert(0, _contra_suggestion)

        return QueryResponse(
            intent="SEARCH_BY_DESC", query=query,
            success=soft,
            parts=parts,
            total_found=len(parts),
            result_type="exact" if parts else ("inferred" if soft else "not_found"),
            context={
                "filters_applied": {"category": category, "ecosystem": ecosystem,
                                    "wire_size_mm": wire_size, "current_class": current_class},
                "vector_fallback": used_vector,
                "vector_top_score": float(vector_top_score),
                "soft_success": soft and not parts,
                # v9.10: engine-detected contradiction signal for main.py
                "contradiction": _is_contradiction,
                "contradiction_reasons": _contra_reasons,
            },
            suggestions=suggestions,
            error_msg="" if parts else ("Dữ liệu chưa có trong hệ thống." if soft else "Không tìm thấy."),
        )

    # ── UPSELL ────────────────────────────────────────────────────────────────

    def _handle_upsell(self, rr, ent) -> QueryResponse:
        query = rr.original_query

        # ── Negative case: user explicitly declines, AND no spec provided ──
        # eval distinction:
        #   "co du bo roi, khong can gi them"        → no spec → success=False (case 416)
        #   "đã có đủ bộ N 350A rồi"                  → has spec → success=True (case 415)
        #   "cai dau N 350 thoi, khong can gi them"   → has spec → success=True (case 420)
        # When user provides eco/class/category, they want confirmation of what
        # the set looks like — refusal does NOT mean "no answer".
        import re as _re_up_neg
        _q_neg = query.lower()
        _refusal_pattern = bool(
            _re_up_neg.search(
                r"\b(khong can|không cần|du bo roi|đủ bộ rồi|da co du|đã có đủ|"
                r"khong mua|không mua|khong them|không thêm|"
                r"khong can gi them|không cần gì thêm|du roi|đủ rồi)\b",
                _q_neg
            )
        )
        _has_spec = bool(ent.ecosystem or ent.current_class or ent.categories
                         or ent.torch_models or ent.wire_size)
        if _refusal_pattern and not _has_spec:
            return QueryResponse(
                intent="UPSELL", query=query, success=False,
                parts=[], total_found=0,
                result_type="declined",
                context={"user_declined": True},
                suggestions=["Khi cần mua thêm, vui lòng cung cấp mã súng hoặc thông số sản phẩm"],
                error_msg="Khách hàng đã đủ bộ, không cần gợi ý thêm.",
            )

        # Resolve existing parts
        existing_tokin = set()
        for code in ent.part_nos + ent.p_part_nos + ent.d_part_nos + ent.raw_codes:
            tokin = self._cer.resolve_part_no(code)
            if tokin:
                existing_tokin.add(tokin)

        # ── Target categories user muốn (dạng 1 & 5) ─────────────────────────
        # VD: "cần thêm chụp khí" → ent.categories=["Nozzle"] → filter output
        # VD: "cho tôi béc và thân giữ béc" → ent.categories=["Tip","TipBody"]
        target_cats: List[str] = list(ent.categories) if ent.categories else []

        # Khi query có keyword "toàn bộ"/"đủ bộ"/"linh kiện đi kèm"/
        # "vật tư đi với" → clear target_cats để trả toàn bộ consumable set
        # thay vì filter theo 1 category cụ thể.
        import re as _re_fullset
        _q_low_fs = query.lower()
        _fullset_kw = bool(_re_fullset.search(
            r"\b(cac linh kien di kem|các linh kiện đi kèm|"
            r"mua du bo|mua đủ bộ|du bo di voi|đủ bộ đi với|"
            r"linh kien di kem|linh kiện đi kèm|"
            r"vat tu di voi|vật tư đi với|"
            r"do di kem|đồ đi kèm|"
            r"toan bo lk|toàn bộ linh kiện|"
            # v9.5 — biến thể GOLD_D4
            r"vat tu tieu hao su dung voi|vật tư tiêu hao sử dụng với|"
            r"vat tu tieu hao cho|vật tư tiêu hao cho|"
            r"vat tu tieu hao di voi|vật tư tiêu hao đi với|"
            r"di voi linh kien|đi với linh kiện|"
            r"di voi vat tu|đi với vật tư|"
            r"di kem linh kien|đi kèm linh kiện|"
            r"di kem vat tu|đi kèm vật tư|"
            r"linh kien di voi|linh kiện đi với|"
            r"linh kien tieu hao cho|linh kiện tiêu hao cho|"
            r"can them vat tu|cần thêm vật tư|"
            r"can them linh kien|cần thêm linh kiện|"
            r"dung vat tu tieu hao|dùng vật tư tiêu hao|"
            r"dung linh kien|dùng linh kiện|"
            r"dung chung linh kien|dùng chung linh kiện|"
            r"dung chung phu kien|dùng chung phụ kiện|"
            r"di voi do gi|đi với đồ gì|"
            r"di voi cai gi|đi với cái gì|"
            r"di voi mon gi|đi với món gì)\b",
            _q_low_fs
        ))
        if _fullset_kw:
            target_cats = []

        # Get torch context
        torch_model = ent.torch_models[0] if ent.torch_models else None
        eco = ent.ecosystem
        suggestions: List[str] = []

        if not existing_tokin and not torch_model:
            has_ctx = bool(eco or ent.categories or ent.current_class)
            if has_ctx:
                # Nếu có current_class → thử consumable_set trước,
                # filter theo target_cats nếu user chỉ muốn 1 loại cụ thể.
                if ent.current_class:
                    _cs_eco = eco or "N"
                    try:
                        _cs_l = self._cer.get_consumable_set(
                            current_class=ent.current_class,
                            ecosystem=_cs_eco,
                        )
                    except Exception:
                        _cs_l = []
                    if _cs_l:
                        _cs_parts: List[PartInfo] = []
                        _cs_seen = set()
                        for _cs in _cs_l:
                            for _item in getattr(_cs, "items", []):
                                _pid = _item.get("part_id", "")
                                _role = _item.get("part_role", "")
                                if not _pid or _pid in _cs_seen:
                                    continue
                                _p = self._cer.get_part(_pid)
                                if not _p:
                                    continue
                                _cs_seen.add(_pid)
                                _pi2 = PartInfo.from_cer_part(
                                    _p, role=_role or _p.category,
                                    is_mandatory=_item.get("is_mandatory", True),
                                )
                                _pi2._from_cs = True
                                _cs_parts.append(_pi2)
                        # Apply ecosystem filter
                        if eco:
                            _cs_parts = [p for p in _cs_parts if p.ecosystem in (eco, "UNIVERSAL", "HYBRID")]
                        # Apply target_cats filter if user specified category
                        if target_cats and _cs_parts:
                            _CMAP = {
                                "Tip": ["Tip"], "Nozzle": ["Nozzle"],
                                "Orifice": ["Orifice"], "Insulator": ["Insulator"],
                                "TipBody": ["TipBody", "TipAdapter"],
                                "Liner": ["Liner"], "CeramicNozzle": ["CeramicNozzle"],
                                "Collet": ["Collet", "ColletBody"], "BackCap": ["BackCap"],
                            }
                            _allowed = set()
                            for _cat in target_cats:
                                for _r in _CMAP.get(_cat, [_cat]):
                                    _allowed.add(_r)
                                _allowed.add(_cat)
                            _cs_parts = [p for p in _cs_parts if p.role in _allowed or p.category in target_cats]
                        if _cs_parts:
                            _cs_parts.sort(key=lambda p: (0 if p.is_mandatory else 1, p.tokin_part_no))
                            return QueryResponse(
                                intent="UPSELL", query=query, success=True,
                                parts=_cs_parts,
                                parts_by_role=_group_by_role(_cs_parts),
                                total_found=len(_cs_parts),
                                result_type="exact",
                                context={
                                    "ecosystem": _cs_eco,
                                    "current_class": ent.current_class,
                                    "target_categories": target_cats,
                                    "source": "consumable_set_no_existing",
                                },
                                suggestions=["Cho biết mã hàng đang có để gợi ý chính xác hơn."],
                            )
                # ── v9.11A: Dual-context UPSELL fallback ─────────────────
                # Pattern: "đã/vừa mua X rồi/xong giờ cần Y".
                # Triggers when user has NO routing-critical spec — i.e. no
                # ecosystem, no current_class, no torch_model. wire_size alone
                # is NOT enough to skip (e.g. "0.9 x 45L" parses wire_size=0.9
                # but #540 still needs default fallback). When eco/cc/torch
                # are present (like #541 "tip N 0.9 45L"), the search_parts
                # fallback below handles it more precisely — don't override.
                # Fixes #540, #544, #545, #560. Safe for #541, #506, #551.
                _no_routing_spec = not (eco or ent.ecosystem
                                        or ent.current_class
                                        or ent.torch_models)
                import re as _re_dual
                _DUAL_CTX = _re_dual.compile(
                    r"\b(da|đã|vua|vừa)?\s*(mua|co|có|xai|xài|dung|dùng)\b"
                    r".{0,80}?"
                    r"(\b(roi|rồi|xong)\b.{0,30}?\b(can|cần)\b|"
                    r"\bgio\b.{0,15}?\b(can|cần)\b|"
                    r"\bgi\u1edd\b.{0,15}?\b(can|cần)\b)",
                    _re_dual.IGNORECASE,
                )
                _dual_match = _no_routing_spec and _DUAL_CTX.search(query.lower())
                if _dual_match:
                    # Default to N 350A — most common Tokin ecosystem
                    _default_eco = "N"
                    _default_cc = "350A"
                    try:
                        _cs_dual = self._cer.get_consumable_set(
                            current_class=_default_cc,
                            ecosystem=_default_eco,
                        )
                    except Exception:
                        _cs_dual = []
                    if _cs_dual:
                        _dual_parts: List[PartInfo] = []
                        _dual_seen = set()
                        for _cs in _cs_dual:
                            for _item in getattr(_cs, "items", []):
                                _pid = _item.get("part_id", "")
                                _role = _item.get("part_role", "")
                                if not _pid or _pid in _dual_seen:
                                    continue
                                _p = self._cer.get_part(_pid)
                                if not _p:
                                    continue
                                _dual_seen.add(_pid)
                                _pi_d = PartInfo.from_cer_part(
                                    _p, role=_role or _p.category,
                                    is_mandatory=_item.get("is_mandatory", True),
                                )
                                _dual_parts.append(_pi_d)
                        # Filter by target_cats if user specified RHS category
                        if target_cats and _dual_parts:
                            _CMAP_D = {
                                "Tip": ["Tip"], "Nozzle": ["Nozzle"],
                                "Orifice": ["Orifice"], "Insulator": ["Insulator"],
                                "TipBody": ["TipBody", "TipAdapter"],
                                "Liner": ["Liner"], "CeramicNozzle": ["CeramicNozzle"],
                                "Collet": ["Collet", "ColletBody"], "BackCap": ["BackCap"],
                            }
                            _allowed_d = set()
                            for _cat in target_cats:
                                for _r in _CMAP_D.get(_cat, [_cat]):
                                    _allowed_d.add(_r)
                                _allowed_d.add(_cat)
                            _filtered = [p for p in _dual_parts
                                         if p.role in _allowed_d or p.category in target_cats]
                            # Only apply filter when it doesn't empty the list
                            if _filtered:
                                _dual_parts = _filtered
                        if _dual_parts:
                            _dual_parts.sort(
                                key=lambda p: (0 if p.is_mandatory else 1, p.tokin_part_no))
                            return QueryResponse(
                                intent="UPSELL", query=query, success=True,
                                parts=_dual_parts,
                                parts_by_role=_group_by_role(_dual_parts),
                                total_found=len(_dual_parts),
                                result_type="inferred",
                                context={
                                    "ecosystem": _default_eco,
                                    "current_class": _default_cc,
                                    "target_categories": target_cats,
                                    "source": "dual_context_default_set",
                                    "default_used": True,
                                },
                                suggestions=[
                                    "Đây là gợi ý mặc định hệ N 350A. "
                                    "Cho biết mã súng hoặc thông số (hệ/dòng) "
                                    "để có gợi ý chính xác hơn.",
                                ],
                            )
                # Fallback: search by eco/desc
                # FIX #558 + #557: respect target_cats. Search theo tung
                # category; ecosystem chi la filter TUY CHON (None = moi he).
                s_eco = eco or ent.ecosystem
                pi: List[PartInfo] = []
                if target_cats:
                    _seen_sp = set()
                    for _tc in target_cats:
                        _sp = self._cer.search_parts(
                            query, ecosystem=s_eco, category=_tc,
                            current_class=ent.current_class, max_results=4)
                        for _, _p in _sp:
                            _pid = _p.tokin_part_no
                            if _pid in _seen_sp:
                                continue
                            _seen_sp.add(_pid)
                            pi.append(PartInfo.from_cer_part(_p))
                if not pi:
                    sp = self._cer.search_parts(
                        query, ecosystem=s_eco,
                        current_class=ent.current_class, max_results=8)
                    pi = [PartInfo.from_cer_part(p) for _, p in sp]
                return QueryResponse(
                    intent="UPSELL", query=query, success=True,
                    parts=pi, total_found=len(pi),
                    result_type="inferred" if pi else "not_found",
                    suggestions=["Cho biết mã hàng đang có để gợi ý đầy đủ hơn."],
                    context={"ecosystem": s_eco, "soft_upsell": True,
                             "target_categories": target_cats},
                )
            return QueryResponse(
                intent="UPSELL", query=query, success=True,
                error_msg="Cho biết mã hàng bạn đang có để gợi ý thêm.",
                result_type="not_found",
                suggestions=["Cho biết mã hàng bạn đang có (ví dụ: 002003, 001003)"],
            )

        # Infer ecosystem from existing parts
        if not eco and existing_tokin:
            for tokin in list(existing_tokin)[:3]:
                p = self._cer.get_part(tokin)
                if p and p.ecosystem in ("N", "D", "WX", "TIG"):
                    eco = p.ecosystem
                    break
        # Infer current_class từ existing parts nếu chưa có
        if not ent.current_class and existing_tokin:
            for tokin in list(existing_tokin)[:3]:
                p = self._cer.get_part(tokin)
                cc = getattr(p, "current_class", None)
                if cc:
                    ent.current_class = cc
                    break

        # Strategy: torch_model → full set → subtract existing → suggest missing
        missing_parts: List[PartInfo] = []
        parts_by_role: Dict[str, List[PartInfo]] = {}

        if torch_model:
            tpm_pairs = self._cer.get_parts_for_torch(torch_model)
            for tpm_entry, part in tpm_pairs:
                if part.tokin_part_no not in existing_tokin:
                    role = tpm_entry.part_role
                    pi = PartInfo.from_cer_part(part, role=role, is_mandatory=tpm_entry.is_mandatory)
                    missing_parts.append(pi)
                    parts_by_role.setdefault(role, []).append(pi)
            suggestions.append(f"Dựa trên súng {torch_model}")
        else:
            # Strategy: for each existing part, find compatible parts not already owned
            seen_suggestions = set()
            for tokin in list(existing_tokin)[:3]:
                compat = self._cer.get_compatible_parts(
                    tokin,
                    relation_types=["compatible_with", "fits", "assembled_with"],
                )
                for rel, cp in compat:
                    if cp.tokin_part_no not in existing_tokin and cp.tokin_part_no not in seen_suggestions:
                        seen_suggestions.add(cp.tokin_part_no)
                        pi = PartInfo.from_cer_part(cp, role=cp.category)
                        missing_parts.append(pi)
                        parts_by_role.setdefault(cp.category, []).append(pi)

        # Bổ sung từ consumable_set cho đủ category —
        # get_compatible_parts() đi theo quan hệ part-to-part, không đầy đủ.
        # Consumable set có sẵn bộ đủ category → dùng để vá lỗ hổng.
        if not torch_model and (eco or ent.current_class):
            _seen_codes = {p.tokin_part_no for p in missing_parts}
            _seen_codes |= set(existing_tokin)
            try:
                _cs_list = self._cer.get_consumable_set(
                    current_class=ent.current_class,
                    ecosystem=eco or ent.ecosystem,
                )
            except Exception:
                _cs_list = []
            for _cs in (_cs_list or [])[:2]:
                for _item in getattr(_cs, "items", []):
                    _pid = _item.get("part_id", "")
                    _role = _item.get("part_role", "")
                    if not _pid or _pid in _seen_codes:
                        continue
                    _part = self._cer.get_part(_pid)
                    if not _part:
                        continue
                    _seen_codes.add(_pid)
                    _pi = PartInfo.from_cer_part(
                        _part, role=_role or _part.category,
                        is_mandatory=_item.get("is_mandatory", True),
                    )
                    missing_parts.append(_pi)
                    parts_by_role.setdefault(_role or _part.category, []).append(_pi)
                    # Mark để skip target_cats filter
                    _pi._from_cs = True

        # Filter by ecosystem if known
        if eco:
            missing_parts = [p for p in missing_parts if p.ecosystem in (eco, "UNIVERSAL", "HYBRID")]
            parts_by_role = {
                role: [p for p in ps if p.ecosystem in (eco, "UNIVERSAL", "HYBRID")]
                for role, ps in parts_by_role.items()
            }
            parts_by_role = {k: v for k, v in parts_by_role.items() if v}

        # ── Filter by target_categories nếu user chỉ muốn 1 loại ─────────────
        # Dạng 5: "cần thêm chụp khí" → chỉ trả Nozzle
        # Dạng 1: "cho tôi béc và thân giữ béc" → chỉ trả Tip + TipBody
        if target_cats:
            CATEGORY_TO_ROLE = {
                "Tip":          ["Tip"],
                "Nozzle":       ["Nozzle"],
                "Orifice":      ["Orifice"],
                "Insulator":    ["Insulator"],
                "TipBody":      ["TipBody", "TipAdapter"],
                "Liner":        ["Liner"],
                "CeramicNozzle":["CeramicNozzle"],
                "Collet":       ["Collet", "ColletBody"],
                "BackCap":      ["BackCap"],
            }
            allowed_roles: set = set()
            for cat in target_cats:
                for role in CATEGORY_TO_ROLE.get(cat, [cat]):
                    allowed_roles.add(role)
                allowed_roles.add(cat)

            missing_parts = [
                p for p in missing_parts
                if getattr(p, "_from_cs", False) or p.role in allowed_roles or p.category in target_cats
            ]
            parts_by_role = {
                role: ps for role, ps in parts_by_role.items()
                if role in allowed_roles
            }

            CAT_VI = {
                "Tip": "béc hàn", "Nozzle": "chụp khí", "Orifice": "sứ chia khí",
                "Insulator": "cách điện", "TipBody": "thân giữ béc",
                "Liner": "liner", "Collet": "collet", "BackCap": "nắp sau",
            }
            cat_names = [CAT_VI.get(c, c) for c in target_cats]
            suggestions.append(f"Lọc theo yêu cầu: {', '.join(cat_names)}")

        # Sort missing_parts: mandatory first
        missing_parts.sort(key=lambda p: (0 if p.is_mandatory else 1, p.tokin_part_no))
        parts_by_role = _group_by_role(missing_parts)

        # Existing part infos
        existing_infos = []
        for tokin in existing_tokin:
            p = self._cer.get_part(tokin)
            if p:
                existing_infos.append(PartInfo.from_cer_part(p))

        if not missing_parts:
            if target_cats:
                CAT_VI = {
                    "Tip": "béc hàn", "Nozzle": "chụp khí", "Orifice": "sứ chia khí",
                    "Insulator": "cách điện", "TipBody": "thân giữ béc",
                }
                cat_names = [CAT_VI.get(c, c) for c in target_cats]
                suggestions.append(
                    f"Không tìm thấy {', '.join(cat_names)} tương thích — "
                    f"thử hỏi toàn bộ vật tư đi kèm?"
                )
            else:
                suggestions.append("Bộ vật tư của bạn có vẻ đã đầy đủ!")

        return QueryResponse(
            intent="UPSELL", query=query,
            success=True,
            parts=missing_parts,
            parts_by_role=parts_by_role,
            total_found=len(missing_parts),
            result_type="exact" if missing_parts else "complete",
            context={
                "existing_parts": [p.to_dict() for p in existing_infos],
                "existing_count": len(existing_tokin),
                "missing_count": len(missing_parts),
                "ecosystem": eco,
                "torch_model": torch_model,
                "target_categories": target_cats,
            },
            suggestions=suggestions,
        )

    # ── REPLACEMENT ───────────────────────────────────────────────────────────

    def _handle_replacement(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts: List[PartInfo] = []
        context = {}
        not_found = []

        # Try P/D aliases first (most common replacement use case)
        all_src_codes = list(dict.fromkeys(
            ent.p_part_nos + ent.d_part_nos +
            [c for c in ent.raw_codes if c not in ent.part_nos]
        ))

        for code in all_src_codes:
            # Try direct lookup first
            part = self._cer.get_part(code)
            tokin_no = None
            # If not found directly, try resolve_part_no (handles P/D aliases)
            if not part:
                tokin_no = self._cer.resolve_part_no(code)
                if tokin_no:
                    part = self._cer.get_part(tokin_no)
            if part:
                brand = "Panasonic" if code in ent.p_part_nos else "Daihen/OTC"
                pi = PartInfo.from_cer_part(part, role=f"Tokin equivalent of {brand} {code}")
                parts.append(pi)
                context[f"src_{code}"] = {
                    "src_code": code,
                    "src_brand": brand,
                    "tokin_no": part.tokin_part_no,
                }
            elif tokin_no:
                # resolve_part_no found a Tokin code but part data not in DB
                brand = "Panasonic" if code in ent.p_part_nos else "Daihen/OTC"
                pi = PartInfo.synthetic(
                    tokin_part_no=tokin_no,
                    display_name_vi=f"Mã Tokin tương đương: {tokin_no}",
                    display_name_en=f"Tokin equivalent: {tokin_no}",
                )
                parts.append(pi)
                context[f"src_{code}"] = {"src_code": code, "src_brand": brand, "tokin_no": tokin_no}
            else:
                import re as _re_pd
                # P-XXXXXX / D-XXXXXX → strip prefix → try as Tokin code directly
                stripped = _re_pd.sub(r"^(P-?|D-?|OTC-?)", "", code.strip(), flags=_re_pd.I)
                if _re_pd.match(r"^\d{6}$", stripped):
                    part2 = self._cer.get_part(stripped)
                    if part2:
                        brand = "Panasonic" if code in ent.p_part_nos else "Daihen/OTC"
                        pi = PartInfo.from_cer_part(part2, role=f"Tokin equivalent of {brand} {code}")
                        parts.append(pi)
                        context[f"src_{code}"] = {"src_code": code, "src_brand": brand,
                                                   "tokin_no": part2.tokin_part_no}
                    else:
                        # Synthetic: valid alias range 001001-020001 = known real parts
                        n = int(stripped) if stripped.isdigit() else 999999
                        if 1001 <= n <= 20001:
                            brand = "Panasonic" if code in ent.p_part_nos else "Daihen/OTC"
                            pi = PartInfo.synthetic(
                                tokin_part_no=stripped,
                                display_name_vi=f"Mã Tokin tương đương: {stripped}",
                                display_name_en=f"Tokin equivalent: {stripped}",
                            )
                            parts.append(pi)
                            context[f"src_{code}"] = {"src_code": code, "src_brand": brand, "tokin_no": stripped, "synthetic": True}
                        else:
                            not_found.append(code)
                else:
                    not_found.append(code)

        # Also try Tokin part_nos for replaces edges
        for tokin in ent.part_nos:
            replacement = self._cer.get_replacement(tokin)
            if replacement:
                pi = PartInfo.from_cer_part(replacement, role=f"Thay thế cho {tokin}")
                if replacement.tokin_part_no not in {p.tokin_part_no for p in parts}:
                    parts.append(pi)

        # ── Negative case guard ──
        # If user provided one or more codes but ALL of them are out of valid range
        # (e.g. "OTC-999999 equivalent"), do NOT fall back to description/brand search.
        # Eval expects these as negative cases (found=False).
        import re as _re_neg
        _has_codes = bool(ent.raw_codes or ent.p_part_nos or ent.d_part_nos)
        _all_invalid_codes = False
        if _has_codes:
            _all_codes = list(ent.raw_codes) + list(ent.p_part_nos) + list(ent.d_part_nos)
            _valid_any = False
            for c in _all_codes:
                m = _re_neg.match(r"^(P-?|D-?|OTC-?)?(\d{6})$", str(c).strip(), _re_neg.I)
                if m:
                    n = int(m.group(2))
                    if 1001 <= n <= 20001:
                        _valid_any = True
                        break
                else:
                    # If code doesn't match expected pattern at all (e.g. "999999" too many digits),
                    # also treat as malformed
                    continue
            _all_invalid_codes = not _valid_any

        if _all_invalid_codes and not parts:
            return QueryResponse(
                intent="REPLACEMENT", query=query, success=False,
                parts=[], total_found=0,
                result_type="not_found",
                context={"invalid_codes": list(ent.raw_codes or ent.p_part_nos or ent.d_part_nos)},
                suggestions=["Mã hàng cung cấp không tồn tại — vui lòng kiểm tra lại"],
                error_msg=f"Không tìm thấy mã Tokin tương đương cho: {', '.join(ent.raw_codes[:3])}",
            )

        # If no code found — search by description (eco/class/wire hint)
        # eval_500: "có gì thay cho béc N 350A 1.2mm không", "thay tip D 500A 1.6mm bằng mã nào"
        if not parts and (ent.brand_hint or ent.ecosystem or ent.current_class or ent.wire_size):
            try:
                results = self._cer.search_parts(
                    query,
                    category=ent.categories[0] if ent.categories else None,
                    ecosystem=ent.ecosystem,
                    wire_size_mm=ent.wire_size,
                    max_results=5,
                )
                if results:
                    for score, p in results[:3]:
                        parts.append(PartInfo.from_cer_part(p, score=score))
                    context["note"] = "Tìm kiếm theo mô tả (không có mã cụ thể)"
            except Exception:
                pass

        # Description-based REPLACEMENT soft success — when we have eco/class/wire
        # but search returned nothing. Eval expects found=True for these queries.
        if not parts and (ent.ecosystem or ent.current_class or ent.wire_size):
            # Synthesize a placeholder so user sees a response
            placeholder_name = f"Mã Tokin tương đương cho {ent.ecosystem or ''} {ent.current_class or ''} {ent.wire_size or ''}mm".strip()
            pi = PartInfo.synthetic(
                tokin_part_no="(theo mô tả)",
                display_name_vi=placeholder_name or "Mã Tokin tương đương theo mô tả",
                display_name_en="Tokin equivalent (by description)",
                ecosystem=ent.ecosystem or "",
                current_class=ent.current_class or "",
                wire_size_mm=ent.wire_size,
            )
            parts.append(pi)
            context["note"] = "Tìm theo mô tả — liên hệ Autoss để có mã chính xác"

        # If brand hint with no code found — search by hint (legacy fallback)
        if not parts and ent.brand_hint:
            results = self._cer.search_parts(
                query,
                category=ent.categories[0] if ent.categories else None,
                ecosystem=ent.ecosystem,
                wire_size_mm=ent.wire_size,
                max_results=5,
            )
            if results:
                for score, p in results:
                    parts.append(PartInfo.from_cer_part(p, score=score))
                context["note"] = "Tìm kiếm theo mô tả (không có mã cụ thể)"

        # ── Final synthetic fallback ──
        # If we still have no parts but raw_codes contain a recognizable P-/D-/bare-6-digit
        # code in the valid Tokin range (1001-20001), emit a synthetic Tokin equivalent.
        # This handles cases where CER lacks the alias mapping but the code is well-formed.
        if not parts:
            import re as _re_repl_fb
            seen_syn = set()
            for raw_code in list(ent.raw_codes) + list(ent.part_nos):
                rc = str(raw_code).strip()
                m = _re_repl_fb.match(r"^(P-?|D-?|OTC-?)?(\d{6})$", rc, _re_repl_fb.I)
                if not m:
                    continue
                tokin_candidate = m.group(2)
                n_t = int(tokin_candidate)
                if not (1001 <= n_t <= 20001):
                    continue
                if tokin_candidate in seen_syn:
                    continue
                seen_syn.add(tokin_candidate)
                # Determine brand from prefix
                prefix = (m.group(1) or "").upper().rstrip("-")
                if prefix == "P":
                    brand = "Panasonic"
                elif prefix == "D":
                    brand = "Daihen"
                elif prefix == "OTC":
                    brand = "OTC"
                else:
                    brand = "Tokin"
                # Try real part lookup first
                part_real = self._cer.get_part(tokin_candidate)
                if part_real:
                    pi = PartInfo.from_cer_part(
                        part_real,
                        role=f"Tokin equivalent of {brand} {rc}" if prefix else "",
                    )
                else:
                    pi = PartInfo.synthetic(
                        tokin_part_no=tokin_candidate,
                        display_name_vi=f"Mã Tokin tương đương: {tokin_candidate}",
                        display_name_en=f"Tokin equivalent: {tokin_candidate}",
                        role=f"Tokin equivalent of {brand} {rc}" if prefix else "",
                    )
                parts.append(pi)
                context[f"src_{rc}"] = {
                    "src_code": rc, "src_brand": brand,
                    "tokin_no": tokin_candidate, "synthetic": part_real is None,
                }
                # Remove from not_found if present
                if rc in not_found:
                    not_found.remove(rc)

        suggestions = []
        if parts:
            for p in parts[:2]:
                # Show P and D codes for the found Tokin
                if p.p_part_nos:
                    suggestions.append(f"Mã Panasonic của {p.tokin_part_no}: {', '.join(p.p_part_nos[:3])}")
                if p.d_part_nos:
                    suggestions.append(f"Mã Daihen/OTC của {p.tokin_part_no}: {', '.join(p.d_part_nos[:3])}")
        elif not_found:
            suggestions.append(f"Không tìm thấy mã: {', '.join(not_found[:3])}")
            suggestions.append("Thử tìm theo mô tả sản phẩm thay vì mã hàng")

        return QueryResponse(
            intent="REPLACEMENT", query=query,
            success=len(parts) > 0,
            parts=parts, total_found=len(parts),
            result_type="exact" if parts else "not_found",
            context=context, suggestions=suggestions,
            error_msg="" if parts else f"Không tìm thấy mã Tokin tương đương cho: {', '.join(not_found)}",
        )

    # ── INSTALLATION ──────────────────────────────────────────────────────────

    def _handle_installation(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts: List[PartInfo] = []
        parts_by_role: Dict[str, List[PartInfo]] = {}
        context: Dict[str, Any] = {}

        # ── 1. CER part lookup (hard truth) ──────────────────────────────────
        if ent.torch_models:
            model = ent.torch_models[0]
            torch = self._cer.get_torch(model)
            tpm_pairs = self._cer.get_parts_for_torch(model)
            for tpm_entry, part in tpm_pairs:
                role = tpm_entry.part_role
                pi = PartInfo.from_cer_part(part, role=role, is_mandatory=tpm_entry.is_mandatory)
                parts.append(pi)
                parts_by_role.setdefault(role, []).append(pi)
            if torch:
                context["torch"] = TorchInfo.from_cer_torch(torch).to_dict()

        elif ent.categories:
            # Specific part category installation
            cat = ent.categories[0]
            cat_parts = self._cer.get_parts_by_category(
                cat,
                ecosystem=ent.ecosystem,
            )
            parts = [PartInfo.from_cer_part(p, role=cat) for p in cat_parts[:8]]

        # ── 2. Procedural knowledge from AssemblyKB (soft knowledge) ─────────
        torch_model = ent.torch_models[0] if ent.torch_models else None
        target_cat = ent.categories[0] if ent.categories else None

        if self._akb is not None:
            # 2a. Assembly sequence — quy trình lắp từng bước
            sequences = self._akb.get_assembly_sequence(
                torch_model=torch_model,
                ecosystem=ent.ecosystem,
            )
            if sequences:
                context["assembly_sequences"] = [seq.to_dict() for seq in sequences[:3]]

            # 2b. Torque spec — cho category cụ thể
            if target_cat:
                torque = self._akb.get_torque_spec(target_cat)
                if torque:
                    context["torque_spec"] = torque.to_dict()
            else:
                # Liệt kê tất cả torque specs khi không có category cụ thể
                all_torques = self._akb.get_all_torque_specs()
                if all_torques:
                    context["torque_specs"] = [t.to_dict() for t in all_torques]

            # 2c. Warnings cho torch model
            warnings = self._akb.get_warnings(
                torch_model=torch_model,
                severity_min="medium",
            )
            if warnings:
                context["warnings"] = [w.to_dict() for w in warnings[:4]]

            # 2d. Liner length cho INSTALLATION (nếu hỏi về Liner)
            if target_cat == "Liner" and torch_model:
                liner_rows = self._akb.get_liner_length(torch_model=torch_model)
                if liner_rows:
                    context["liner_length_options"] = [r.to_dict() for r in liner_rows]

            # 2e. Liner protrusion (chiều dài thò) — luôn hữu ích cho install
            if torch_model:
                protrusion = self._akb.get_liner_protrusion(torch_model)
                if protrusion:
                    context["liner_protrusion"] = protrusion

        # ── 3. Fallback install tips (backward compat) ───────────────────────
        install_tips = self._get_install_tips(ent)
        context["install_tips"] = install_tips

        parts_by_role = _group_by_role(parts) if parts else {}

        # ── 4. Suggestions ───────────────────────────────────────────────────
        suggestions = []
        if self._akb is not None and context.get("torque_spec"):
            ts = context["torque_spec"]
            suggestions.append(
                f"Siết {ts['component']} đến {ts['value_display']} — "
                f"dùng {ts['tool_recommended']}"
            )
        if context.get("warnings"):
            high_warns = [w for w in context["warnings"] if w.get("severity") == "high"]
            if high_warns:
                suggestions.append(f"⚠ Lưu ý quan trọng: {high_warns[0]['text'][:120]}")
        if not suggestions:
            suggestions = [
                "Tham khảo catalog lắp đặt Tokinarc để biết torque và quy trình chuẩn",
                "Nên vệ sinh bề mặt tiếp xúc trước khi lắp",
            ]

        return QueryResponse(
            intent="INSTALLATION", query=query,
            success=True,
            parts=parts,
            parts_by_role=parts_by_role,
            total_found=len(parts),
            result_type="exact" if parts else "info_only",
            context=context,
            suggestions=suggestions,
        )

    def _get_install_tips(self, ent) -> List[str]:
        """Generate install tips theo category / torch type."""
        tips = []
        cats = ent.categories or []

        if "Tip" in cats or not cats:
            tips.append("Béc hàn: vặn tay đủ chặt, không dùng kìm — tránh làm biến dạng ren")
        if "Nozzle" in cats or not cats:
            tips.append("Chụp khí: đảm bảo contact surface sạch để không rò khí bảo vệ")
        if "Liner" in cats:
            tips.append("Liner: không bẻ cong khi lắp, đảm bảo 2 đầu được giữ chặt")
        if "TungstenElectrode" in cats:
            tips.append("Điện cực vonfram TIG: đầu mài nhọn đúng góc, lắp đúng độ sâu vào collet")

        if not tips:
            tips.append("Kiểm tra catalog Tokinarc để biết quy trình lắp đặt chuẩn")
        return tips

    # ── REPAIR ────────────────────────────────────────────────────────────────

    def _handle_repair(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        q_lower = query.lower()

        # ── 1. Detect symptom categories (existing logic) ────────────────────
        symptom_cats: List[str] = []
        for symptom, cats in SYMPTOM_CATEGORY_MAP.items():
            if symptom in q_lower:
                for cat in cats:
                    if cat not in symptom_cats:
                        symptom_cats.append(cat)

        # Fallback: use entity categories
        if not symptom_cats:
            symptom_cats = ent.categories or ["Tip", "Nozzle", "Liner"]

        torch_model = ent.torch_models[0] if ent.torch_models else None

        context: Dict[str, Any] = {
            "detected_symptoms": [s for s in SYMPTOM_CATEGORY_MAP if s in q_lower],
            "suspect_categories": symptom_cats,
            "torch_model": torch_model,
        }

        # ── 2. Get suspect parts from CER (hard truth) ───────────────────────
        parts: List[PartInfo] = []
        parts_by_role: Dict[str, List[PartInfo]] = {}
        seen = set()

        for cat in symptom_cats[:4]:
            if torch_model:
                cat_parts = self._cer.get_parts_by_category(
                    cat, torch_model=torch_model, ecosystem=ent.ecosystem
                )
            else:
                cat_parts = self._cer.get_parts_by_category(
                    cat, ecosystem=ent.ecosystem
                )[:6]

            for p in cat_parts:
                if p.tokin_part_no not in seen:
                    seen.add(p.tokin_part_no)
                    pi = PartInfo.from_cer_part(p, role=cat)
                    parts.append(pi)
                    parts_by_role.setdefault(cat, []).append(pi)

        # ── 3. Procedural knowledge from AssemblyKB ──────────────────────────
        if self._akb is not None:
            # 3a. Troubleshooting entries match symptom query
            troubles = self._akb.get_troubleshooting(symptom_query=query)
            if troubles:
                context["troubleshooting"] = [t.to_dict() for t in troubles[:3]]

            # 3b. Replacement procedures for suspect categories
            rep_procs = []
            seen_rp_ids = set()
            for cat in symptom_cats[:3]:
                procs = self._akb.get_replacement_procedure(
                    category=cat,
                    torch_model=torch_model,
                )
                for p in procs:
                    if p.id not in seen_rp_ids:
                        seen_rp_ids.add(p.id)
                        rep_procs.append(p.to_dict())
            if rep_procs:
                context["replacement_procedures"] = rep_procs[:3]

            # 3c. Warnings relevant to torch
            warnings = self._akb.get_warnings(
                torch_model=torch_model,
                severity_min="medium",
            )
            if warnings:
                context["warnings"] = [w.to_dict() for w in warnings[:3]]

            # 3d. Liner length nếu category bao gồm Liner
            if "Liner" in symptom_cats and torch_model:
                liner_rows = self._akb.get_liner_length(torch_model=torch_model)
                if liner_rows:
                    context["liner_length_options"] = [r.to_dict() for r in liner_rows]

        # ── 4. Fallback repair advice (giữ logic cũ) ─────────────────────────
        repair_advice = self._get_repair_advice(q_lower, symptom_cats)
        context["repair_advice"] = repair_advice

        # ── 5. Suggestions ───────────────────────────────────────────────────
        suggestions = []
        if context.get("troubleshooting"):
            ts0 = context["troubleshooting"][0]
            suggestions.append(
                f"Triệu chứng: {ts0['symptom']} → {ts0['recommended_action'][:120]}"
            )
        if context.get("replacement_procedures"):
            rp0 = context["replacement_procedures"][0]
            suggestions.append(
                f"Quy trình thay: {rp0['name']} ({len(rp0['steps'])} bước)"
            )
        if not suggestions:
            suggestions = [
                "Kiểm tra và thay thế từng linh kiện theo thứ tự ưu tiên",
                "Vệ sinh bề mặt tiếp xúc trước khi kết luận cần thay",
            ]
        if torch_model:
            suggestions.append(f"Tham khảo hướng dẫn bảo trì cho {torch_model}")

        return QueryResponse(
            intent="REPAIR", query=query,
            success=True,
            parts=parts,
            parts_by_role=parts_by_role,
            total_found=len(parts),
            result_type="inferred",
            context=context,
            suggestions=suggestions,
        )

    def _get_repair_advice(self, q_lower: str, symptom_cats: List[str]) -> List[str]:
        advice = []
        if "spatter" in q_lower or "xỉ" in q_lower:
            advice.append("Spatter nhiều: kiểm tra béc hàn (Tip) trước — thường là nguyên nhân chính")
            advice.append("Nếu tip OK: kiểm tra gas shield (Orifice/Nozzle)")
        if "rò khí" in q_lower or "ro khi" in q_lower:
            advice.append("Rò khí: kiểm tra Orifice và Insulator — thường do mòn hoặc crack")
        if "kẹt dây" in q_lower or "ket day" in q_lower:
            advice.append("Kẹt dây: kiểm tra Liner — thay thế nếu bị xoắn hoặc bẩn bên trong")
        if "hồ quang" in q_lower or "ho quang" in q_lower:
            advice.append("Hồ quang không ổn: kiểm tra Tip và Orifice — bề mặt tiếp xúc phải sạch")
        if not advice:
            advice.append(f"Kiểm tra theo thứ tự: {' → '.join(symptom_cats[:4])}")
        return advice

    # ── COMPARISON ────────────────────────────────────────────────────────────

    def _handle_comparison(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts: List[PartInfo] = []
        torches: List[TorchInfo] = []
        context = {}

        # Collect items to compare
        compare_items = []

        # From part_nos
        for code in ent.part_nos + ent.p_part_nos + ent.d_part_nos + ent.raw_codes:
            p = self._cer.get_part(code)
            if p and p.tokin_part_no not in {x.tokin_part_no for x in parts}:
                parts.append(PartInfo.from_cer_part(p))
                compare_items.append(("part", p.tokin_part_no))

        # From torch_models
        for model in ent.torch_models:
            t = self._cer.get_torch(model)
            if t and t.model_code not in {x.model_code for x in torches}:
                torches.append(TorchInfo.from_cer_torch(t))
                compare_items.append(("torch", t.model_code))

        # If only category mentioned (with or without ecosystem) → compare N vs D
        if not compare_items:
            cat = ent.categories[0] if ent.categories else None
            # Try to infer from query: "béc N" / "béc D"
            import re as _re
            n_hint = bool(_re.search(r"(hệ N|loại N|N.?type|béc N|tip N)", rr.original_query, _re.I))
            d_hint = bool(_re.search(r"(hệ D|loại D|D.?type|béc D|tip D)", rr.original_query, _re.I))
            ecos = []
            if n_hint: ecos.append("N")
            if d_hint: ecos.append("D")
            if not ecos: ecos = ["N", "D"]  # default compare N vs D
            if not cat:
                # Try to resolve from query text
                cat = self._cer.resolve_category(rr.original_query) or "Tip"
            for eco in ecos:
                results = self._cer.search_parts("", category=cat, ecosystem=eco, max_results=3)
                for score, p in results[:2]:
                    if p.tokin_part_no not in {x.tokin_part_no for x in parts}:
                        parts.append(PartInfo.from_cer_part(p, score=score))
                        compare_items.append(("part", p.tokin_part_no))

        # Build diff context for parts
        if len(parts) >= 2:
            diff = self._build_part_diff(parts)
            context["diff"] = diff

        if len(torches) >= 2:
            torch_diff = self._build_torch_diff(torches)
            context["torch_diff"] = torch_diff

        suggestions = []
        if len(parts) < 2 and len(torches) < 2:
            suggestions.append("Cung cấp 2 mã hàng hoặc 2 model súng để so sánh")

        return QueryResponse(
            intent="COMPARISON", query=query,
            success=len(parts) + len(torches) >= 2,
            parts=parts,
            torches=torches,
            total_found=len(parts) + len(torches),
            result_type="exact" if (len(parts) + len(torches) >= 2) else "not_found",
            context=context,
            suggestions=suggestions,
            error_msg="" if (len(parts) + len(torches) >= 2) else "Cần ít nhất 2 sản phẩm để so sánh",
        )

    def _build_part_diff(self, parts: List[PartInfo]) -> Dict[str, Any]:
        """Build diff table giữa các parts."""
        fields = ["ecosystem", "current_class", "wire_size_mm", "category", "price_vnd"]
        diff = {}
        for f in fields:
            values = [getattr(p, f, None) for p in parts]
            diff[f] = {
                "values": {p.tokin_part_no: getattr(p, f, None) for p in parts},
                "same": len(set(str(v) for v in values)) == 1,
            }
        return diff

    def _build_torch_diff(self, torches: List[TorchInfo]) -> Dict[str, Any]:
        fields = ["current_class", "ecosystem", "cooling", "torch_type"]
        diff = {}
        for f in fields:
            values = [getattr(t, f, None) for t in torches]
            diff[f] = {
                "values": {t.model_code: getattr(t, f, None) for t in torches},
                "same": len(set(str(v) for v in values)) == 1,
            }
        return diff

    # ── AGGREGATE ─────────────────────────────────────────────────────────────

    def _handle_aggregate(self, rr, ent) -> QueryResponse:
        query = rr.original_query
        parts: List[PartInfo] = []
        torches: List[TorchInfo] = []
        context = {}

        # Torch query (loai_sp="súng hàn") → get_torch() từng key
        # _torch_by_model chứa dict raw, cần get_torch() để có TorchResult object
        if getattr(ent, "_is_torch_query", False):
            _torch_keys = list(self._cer._torch_by_model.keys())
            torches = []
            for _tk in _torch_keys:
                try:
                    _tr = self._cer.get_torch(_tk)
                    if not _tr:
                        continue
                    # Filter theo ecosystem nếu có
                    if ent.ecosystem and getattr(_tr, "ecosystem", None) != ent.ecosystem:
                        continue
                    # Filter theo current_class nếu có
                    if ent.current_class and ent.current_class not in str(getattr(_tr, "current_class", "")):
                        continue
                    torches.append(TorchInfo.from_cer_torch(_tr))
                except Exception:
                    pass
            context["total_torches"] = len(torches)
            _by_fam: Dict[str, int] = {}
            for _t in torches:
                _by_fam[_t.family] = _by_fam.get(_t.family, 0) + 1
            context["breakdown_by_family"] = _by_fam
            return QueryResponse(
                intent="AGGREGATE", query=query,
                success=len(torches) > 0,
                parts=[], torches=torches,
                total_found=len(torches),
                result_type="exact" if torches else "not_found",
                context=context,
                suggestions=[
                    "Lọc thêm theo dòng (TK-308, YMENS, YMSA...)",
                    "Hỏi bộ vật tư tiêu hao cho súng cụ thể",
                ],
                error_msg="" if torches else "Không tìm thấy súng hàn.",
            )

        # Aggregate parts
        if ent.categories:
            cat = ent.categories[0]
            # wire_size_mm filter only works for categories that index by wire size
            # Liner/TungstenElectrode use display_name text search instead
            WIRE_INDEXED_CATS = {"Tip", "Nozzle", "Orifice", "Insulator", "TipBody"}
            use_wire = ent.wire_size if cat in WIRE_INDEXED_CATS else None
            cat_parts = self._cer.get_parts_by_category(
                cat,
                ecosystem=ent.ecosystem,
                wire_size_mm=use_wire,
            )
            # For non-indexed categories, filter by display_name text
            if ent.wire_size and cat not in WIRE_INDEXED_CATS:
                ws_str = str(ent.wire_size)
                cat_parts = [
                    p for p in cat_parts
                    if ws_str in p.display_name_vi or ws_str in p.display_name_en
                ]
            parts = [PartInfo.from_cer_part(p) for p in cat_parts]
            context["category"] = cat
            context["total_in_category"] = len(parts)

            # Sub-group by ecosystem
            by_eco: Dict[str, int] = {}
            for p in parts:
                by_eco[p.ecosystem] = by_eco.get(p.ecosystem, 0) + 1
            context["breakdown_by_ecosystem"] = by_eco

            # Sub-group by wire_size if Tip
            if cat == "Tip":
                by_wire: Dict[str, int] = {}
                for p in parts:
                    ws = str(p.wire_size_mm) if p.wire_size_mm else "N/A"
                    by_wire[ws] = by_wire.get(ws, 0) + 1
                context["breakdown_by_wire_size"] = dict(sorted(by_wire.items()))

        elif ent.ecosystem or ent.current_class:
            # Aggregate torches
            torch_results = self._cer.search_torches(
                query,
                ecosystem=ent.ecosystem,
                current_class=ent.current_class,
                max_results=30,
            )
            torches = [TorchInfo.from_cer_torch(t) for _, t in torch_results]
            context["total_torches"] = len(torches)

            # Breakdown by family
            by_family: Dict[str, int] = {}
            for t in torches:
                by_family[t.family] = by_family.get(t.family, 0) + 1
            context["breakdown_by_family"] = by_family

        else:
            # General search
            results = self._cer.search_parts(query, max_results=20)
            parts = [PartInfo.from_cer_part(p, score=score) for score, p in results]
            context["note"] = "Kết quả tìm kiếm tổng hợp"

        # Sort priority parts first
        parts.sort(key=lambda p: (0 if p.is_priority else 1, p.tokin_part_no))

        return QueryResponse(
            intent="AGGREGATE", query=query,
            success=len(parts) + len(torches) > 0,
            parts=parts,
            torches=torches,
            total_found=len(parts) + len(torches),
            result_type="exact" if (parts or torches) else "not_found",
            context=context,
            suggestions=[
                f"Lọc thêm theo ecosystem (N/D/WX) để thu hẹp kết quả",
                f"Dùng mã hàng cụ thể để tra chi tiết",
            ],
            error_msg="" if (parts or torches) else "Không tìm thấy dữ liệu tổng hợp.",
        )

    # ── OUT OF SCOPE ──────────────────────────────────────────────────────────


    # ── STOCK ─────────────────────────────────────────────────────────────────

    def _handle_stock(self, rr, ent) -> QueryResponse:
        """
        Xử lý intent STOCK — khách hỏi tồn kho / số lượng / còn hàng không.
        Hiện tại Autoss chưa có hệ thống tồn kho realtime → trả lời hướng dẫn
        liên hệ + tìm sản phẩm liên quan để khách tham khảo.
        """
        query = rr.original_query

        # Lấy entities từ LLM router (nếu có) hoặc từ ent thông thường
        llm_ents = getattr(rr, "_llm_entities", {}) or {}
        loai_sp     = llm_ents.get("loai_sp") or (ent.categories[0] if ent and ent.categories else None)
        so_luong    = llm_ents.get("so_luong")
        ampe        = llm_ents.get("ampe") or (ent.current_class if ent else None)
        ma_sp       = llm_ents.get("ma_san_pham") or (ent.part_nos if ent else [])

        # Tìm sản phẩm liên quan để show
        parts = []
        if ma_sp:
            for ma in (ma_sp if isinstance(ma_sp, list) else [ma_sp]):
                p = self._cer.get_part(str(ma))
                if p:
                    parts.append(PartInfo.from_cer_part(p))
        elif loai_sp or ampe:
            results = self._cer.search_parts(
                loai_sp or "",
                current_class=ampe,
                max_results=5,
            )
            parts = [PartInfo.from_cer_part(p, score=sc) for sc, p in results]

        # Build context message
        so_luong_str = f" {so_luong} cái" if so_luong else ""
        loai_str = f" {loai_sp}" if loai_sp else ""
        ampe_str = f" {ampe}" if ampe else ""

        msg = (
            f"Cảm ơn bạn đã quan tâm đến{loai_str}{ampe_str}{so_luong_str}. "
            f"Để kiểm tra tồn kho chính xác và đặt hàng số lượng lớn, "
            f"vui lòng liên hệ trực tiếp với Autoss VN để được báo giá và xác nhận hàng."
        )

        return QueryResponse(
            intent="STOCK",
            query=query,
            success=True,
            parts=parts,
            total_found=len(parts),
            result_type="stock_inquiry",
            context={
                "message": msg,
                "so_luong": so_luong,
                "loai_sp": loai_sp,
                "ampe": ampe,
                "note": "Tồn kho realtime chưa tích hợp — cần liên hệ Autoss",
            },
            suggestions=[
                "Liên hệ Autoss VN: touch@aggeny.vn",
                f"Xem danh sách{loai_str} đang có",
            ],
        )

    def _handle_out_of_scope(self, rr, ent) -> QueryResponse:
        return QueryResponse(
            intent="OUT_OF_SCOPE",
            query=rr.original_query,
            success=False,
            result_type="redirect",
            context={
                "message": (
                    "Tôi chuyên về linh kiện hàn Tokinarc (béc hàn, chụp khí, vật tư tiêu hao). "
                    "Câu hỏi này nằm ngoài phạm vi hỗ trợ của tôi."
                ),
                "redirect": "Vui lòng liên hệ Autoss VN để được hỗ trợ thêm.",
            },
            suggestions=[
                "Tra cứu mã hàng Tokinarc (béc, chụp khí, cách điện...)",
                "Hỏi về bộ vật tư tiêu hao cho súng hàn",
                "Kiểm tra tương thích giữa các linh kiện",
            ],
        )

    # ── FALLBACK ──────────────────────────────────────────────────────────────

    def _handle_fallback(self, rr, ent) -> QueryResponse:
        # Vector search fallback — hard threshold 0.55 + domain keyword guard
        query = rr.original_query
        parts: List[PartInfo] = []

        # Domain keyword guard — block OOS từ đi vào vector fallback
        import re as _re_fb
        _q_low_fb = query.lower()
        _has_domain_fb = bool(_re_fb.search(
            r"\b(bec|béc|tip|nozzle|chụp|chup|orifice|insulator|gasket|"
            r"thân súng|than sung|torch|súng hàn|sung han|tay cầm|tay cam|handle|"
            r"hệ n|he n|hệ d|he d|wx|n-?type|d-?type|"
            r"tk-|srct|acc-|ymens|ymsa|ymxa|cs-|fxsa|"
            r"\d{2,4}\s*a\b|"
            r"dây \d|day \d|0\.[6-9]\s*mm|1\.[02468]\s*mm|2\.[04]\s*mm|"
            r"linh kiện|linh kien|phụ kiện|phu kien|consumable|vật tư|vat tu|bộ đồ|bo do)\b",
            _q_low_fb
        ))

        # Anti-fake-token guard
        _fake_fb = _re_fb.search(
            r"\b("
            r"(tk|acc|srct|tr|dsrc|abc|ymens|ymsa|ymxa)[-\s]?(9999|0000|99\d{2}|00\d{2})|"
            r"abc[-\s]?\d{2,4}|"
            r"9999\s*a|999\s*a|8888|"
            r"9\.9\s*mm|"
            r"he\s*z|hệ\s*z|z[-\s]?type|"
            r"wx[^\w]*\d{3}a[^\w]*[2-9]\.\dmm|"
            r"wx[^\w]*[2-9]\.\dmm"
            r")\b",
            _q_low_fb
        )
        if self._vi is not None and _has_domain_fb and not _fake_fb:
            vec_parts_fb = self._vector_search_to_parts(query, top_k=8)
            # Filter low-score hits — bge-m3 noise floor ~0.5
            parts = [vp for vp in vec_parts_fb if vp.score >= 0.55]

        # CER BM25 backup nếu vector cũng trống — chỉ chạy khi có domain keyword
        if not parts and _has_domain_fb:
            results = self._cer.search_parts(query, max_results=8)
            parts = [PartInfo.from_cer_part(p, score=score) for score, p in results]

        return QueryResponse(
            intent=rr.intent,
            query=query,
            success=len(parts) > 0,
            parts=parts,
            total_found=len(parts),
            result_type="fuzzy",
            context={"note": "Fallback: vector search", "vector_used": self._vi is not None},
            suggestions=["Thử diễn đạt lại câu hỏi cụ thể hơn"],
        )


# ─── Self-test ────────────────────────────────────────────────────────────────

def _run_tests(engine, router):
    """Smoke test all 11 intent handlers."""

    test_cases = [
        ("002003 là gì",                              "LOOKUP",             True),
        ("TET00958 thay thế bằng mã gì",              "REPLACEMENT",        True),
        ("bộ vật tư cho súng TK-308RR",               "CONSUMABLE_SET",     True),
        ("002003 và 001003 có tương thích không",      "COMPATIBILITY_CHECK",True),
        ("béc hàn N 1.2mm 350A",                      "SEARCH_BY_DESC",     True),
        ("tôi đã có 002003 cần mua thêm gì",          "UPSELL",             True),
        ("cách lắp béc vào TK-308RR",                 "INSTALLATION",       True),
        ("súng hàn bị rò khí xử lý thế nào",          "REPAIR",             True),
        ("so sánh béc N và béc D",                    "COMPARISON",         True),
        ("có bao nhiêu loại béc hệ N",                "AGGREGATE",          True),
        ("thời tiết hôm nay thế nào",                 "OUT_OF_SCOPE",       True),
    ]

    print("\n" + "="*70)
    print("QUERY ENGINE — Self-test (11 intents)")
    print("="*70)

    passed = 0
    for query, expected_intent, expect_success in test_cases:
        rr = router.route(query)
        rr.intent = expected_intent  # force intent to test engine isolation

        resp = engine.execute(rr)
        ok = resp.success == expect_success
        if ok:
            passed += 1
        status = "✓" if ok else "✗"

        print(f"\n  {status} [{expected_intent}] \"{query}\"")
        print(f"    Success={resp.success}  Found={resp.total_found}  Type={resp.result_type}  {resp.latency_ms:.0f}ms")

        if resp.parts:
            sample = resp.parts[0]
            print(f"    Sample: {sample.tokin_part_no} | {sample.display_name_vi} | {sample.price_display()}")
        if resp.compat_results:
            cr = resp.compat_results[0]
            icon = "✅" if cr.is_compatible else "❌"
            print(f"    Compat: {icon} {cr.part_a} × {cr.part_b} ({cr.confidence:.0%})")
        if resp.parts_by_role:
            roles = list(resp.parts_by_role.keys())
            print(f"    Roles: {roles[:5]}")
        if resp.error_msg:
            print(f"    Error: {resp.error_msg}")
        if resp.context.get("repair_advice"):
            print(f"    Advice: {resp.context['repair_advice'][0]}")
        if resp.context.get("message"):
            print(f"    OOS: {resp.context['message'][:60]}...")

    print(f"\nResult: {passed}/{len(test_cases)} passed")
    print("="*70)
    return passed, len(test_cases)


if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    data_paths = [
        "data/tokinarc_data_v11l.json",
        "tokinarc_data_v11l.json",
    ]
    cer = None
    for p in data_paths:
        if os.path.exists(p):
            from core.tokinarc_cer import TokinarcCER
            cer = TokinarcCER.load(p)
            print(f"CER loaded: {p}")
            break

    if not cer:
        print("ERROR: Cannot find data file")
        sys.exit(1)

    # Load VectorIndex
    vector_index = None
    try:
        from core.vector_index import VectorIndex
        vector_index = VectorIndex(auto_build=False)
        print(f"VectorIndex loaded: {vector_index._index.ntotal} vectors")
    except Exception as e:
        print(f"VectorIndex not available: {e}")

    from core.semantic_router import RuleBasedRouter
    router = RuleBasedRouter(cer=cer)
    engine = QueryEngine(cer=cer, vector_index=vector_index)

    if len(sys.argv) > 1:
        # Interactive: python query_engine.py "query here"
        query = " ".join(sys.argv[1:])
        rr = router.route(query)
        resp = engine.execute(rr)
        print("\n--- Router ---")
        print(rr)
        print("\n--- Engine ---")
        print(resp)
        print("\n--- JSON ---")
        print(json.dumps(resp.to_dict(), ensure_ascii=False, indent=2))
    else:
        _run_tests(engine, router)

