# core/memory_manager.py
# TOKINARC MemoryManager — tách khỏi OrchestratorV2
# ===================================================
# Quản lý session context, inject hints, extract entities.
# Tách ra để OrchestratorV2 không phình thành God Object.
#
# OrchestratorV2 chỉ cần gọi:
#   mm = MemoryManager(session_store)
#   hint = mm.build_hint(session_id, query)
#   mm.update(session_id, tools_called, tool_results, query, response_text)
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tokinarc.memory_manager")


class MemoryManager:
    """
    Tách session logic ra khỏi OrchestratorV2.

    Responsibilities:
      - build_hint()  → inject [SESSION] context vào query
      - extract()     → parse intent/entities từ tool calls
      - update()      → persist về SessionStore
    """

    def __init__(self, session_store=None):
        if session_store is None:
            from core.session_store import get_session_store
            session_store = get_session_store()
        self._ss = session_store

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_create(self, session_id: Optional[str]):
        return self._ss.get_or_create(session_id)

    def build_hint(self, ctx, query: str) -> str:
        """
        Build [SESSION] hint string để inject vào user message.
        Chỉ inject khi query ngắn / pronoun / follow-up.
        """
        if ctx is None or ctx.turn_count == 0:
            return ""

        from core.session_store import is_pronoun_query, is_followup_query
        has_code  = bool(re.search(r'\b\d{6}\b|TET|TGN|TFZ|K\d{3}|U4', query, re.I))
        is_short  = len(query.strip()) <= 60
        should    = (is_pronoun_query(query)
                     or is_followup_query(query)
                     or (is_short and not has_code))

        if not should:
            return ""

        lines = []

        # Parts anchor
        anchor = (ctx.last_part_nos[:2] if ctx.last_part_nos
                  else ctx.last_returned_parts[:2])
        if anchor:
            lines.append(f"[SESSION] Turn trước: parts {anchor}.")
            lines.append(
                f"[SESSION] Nếu user hỏi đi kèm/thêm/cần gì "
                f"→ gọi find_upsell_companions(part_no=\"{anchor[0]}\")."
            )

        # Ecosystem / class
        eco_cc = []
        if ctx.last_ecosystem:     eco_cc.append(f"hệ {ctx.last_ecosystem}")
        if ctx.last_current_class: eco_cc.append(ctx.last_current_class)
        if eco_cc:
            lines.append(f"[SESSION] Ngữ cảnh: {', '.join(eco_cc)}.")

        # Torch
        if ctx.last_torch_models:
            lines.append(f"[SESSION] Súng: {ctx.last_torch_models[0]}.")

        hint = " ".join(lines)
        if hint:
            log.debug(f"[MemoryManager] hint injected for session {ctx.session_id}: {hint[:80]}")
        return hint

    def extract(
        self,
        tools_called: List[str],
        tool_results: List[dict],
        query: str,
    ) -> Tuple[str, dict, list]:
        """
        Extract (intent, entities, returned_parts) từ tool call results.
        Dùng để update SessionContext.
        """
        TOOL_INTENT_MAP = {
            "lookup_part":            "LOOKUP",
            "search_parts":           "SEARCH_BY_DESC",
            "get_consumable_set":     "CONSUMABLE_SET",
            "find_upsell_companions": "UPSELL",
            "find_replacement":       "REPLACEMENT",
            "check_compatibility":    "COMPATIBILITY_CHECK",
            "compare_parts":          "COMPARISON",
            "get_torches":            "AGGREGATE",
            "get_troubleshoot":       "REPAIR",
        }
        intent = next(
            (TOOL_INTENT_MAP[t] for t in tools_called if t in TOOL_INTENT_MAP),
            "OUT_OF_SCOPE",
        )

        entities: dict = {}
        returned: list = []

        for tr in tool_results:
            args   = tr.get("args", {})
            result = tr.get("result", {})

            if args.get("part_no"):
                entities.setdefault("part_nos", [])
                if args["part_no"] not in entities["part_nos"]:
                    entities["part_nos"].append(args["part_no"])

            if args.get("ecosystem"):     entities["ecosystem"]     = args["ecosystem"]
            if args.get("current_class"): entities["current_class"] = args["current_class"]
            if args.get("torch_model"):
                entities.setdefault("torch_models", [])
                if args["torch_model"] not in entities["torch_models"]:
                    entities["torch_models"].append(args["torch_model"])

            # Extract returned parts
            data = result.get("data") if result.get("success") else None
            if isinstance(data, dict):
                if data.get("tokin_part_no"):
                    returned.append({"tokin_part_no": data["tokin_part_no"]})
                for p in (data.get("companions") or [])[:5]:
                    if p.get("tokin_part_no"):
                        returned.append({"tokin_part_no": p["tokin_part_no"]})
                for p in (data.get("parts") or [])[:5]:
                    if p.get("tokin_part_no"):
                        returned.append({"tokin_part_no": p["tokin_part_no"]})
                for cs in (data.get("sets") or []):
                    for p in (cs.get("parts") or [])[:3]:
                        if p.get("tokin_part_no"):
                            returned.append({"tokin_part_no": p["tokin_part_no"]})

        # Deduplicate
        seen: set = set()
        deduped = []
        for p in returned:
            pno = p.get("tokin_part_no", "")
            if pno and pno not in seen:
                seen.add(pno)
                deduped.append(p)

        return intent, entities, deduped[:10]

    def update(
        self,
        ctx,
        tools_called: List[str],
        tool_results: List[dict],
        query: str,
        response_text: str,
    ):
        """Persist extracted data về SessionStore."""
        if ctx is None:
            return
        intent, entities, returned = self.extract(tools_called, tool_results, query)
        self._ss.update(
            ctx, intent, entities, returned,
            query=query, response_text=response_text[:200],
        )
        log.debug(f"[MemoryManager] session {ctx.session_id} updated: intent={intent}")


# ── Singleton ──────────────────────────────────────────────────────────────────

_mm_instance: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    global _mm_instance
    if _mm_instance is None:
        _mm_instance = MemoryManager()
        log.info("[MemoryManager] initialized")
    return _mm_instance
