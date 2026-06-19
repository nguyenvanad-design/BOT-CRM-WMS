# core/confidence_layer.py
# TOKINARC Confidence Layer
# =========================
# Unified confidence scoring cho mọi kết quả retrieval.
# Mỗi tool result được wrap thêm confidence + warnings
# để Gemini synthesis có thể:
#   - Hiển thị cảnh báo nếu confidence thấp
#   - Hỏi clarification thay vì tự đoán
#   - Không fabricate data khi uncertain
#
# UTF-8 NO BOM

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ConfidenceResult:
    """
    Wrap tool result với confidence metadata.
    LLM đọc fields này để quyết định có cần hỏi thêm không.
    """
    success:    bool
    data:       Any
    confidence: float          # 0.0 – 1.0
    tier:       str            # "exact" | "fuzzy" | "inferred" | "fallback"
    warnings:   List[str]      = field(default_factory=list)
    ask_clarify: bool          = False
    clarify_hint: str          = ""
    source:     str            = ""     # tool name

    def to_dict(self) -> dict:
        d = {
            "success":     self.success,
            "data":        self.data,
            "confidence":  round(self.confidence, 3),
            "tier":        self.tier,
        }
        if self.warnings:
            d["warnings"] = self.warnings
        if self.ask_clarify:
            d["ask_clarify"]   = True
            d["clarify_hint"]  = self.clarify_hint
        return d


# ── Confidence thresholds ──────────────────────────────────────────────────────

THRESHOLDS = {
    "clarify_below":  0.55,   # dưới mức này → ask clarification
    "warn_below":     0.75,   # dưới mức này → thêm warning vào response
    "exact_min":      0.95,   # exact match
    "fuzzy_min":      0.70,   # fuzzy / alias match
    "inferred_min":   0.55,   # inferred từ context
}


# ── Scorers cho từng tool ──────────────────────────────────────────────────────

def score_lookup(result: dict, part_no: str) -> ConfidenceResult:
    """
    lookup_part: exact = 1.0, alias = 0.9, not found = 0.0
    """
    if not result.get("success"):
        return ConfidenceResult(
            success=False, data=None, confidence=0.0, tier="fallback",
            warnings=[f"Không tìm thấy mã {part_no}"],
            ask_clarify=True,
            clarify_hint="Anh/chị có thể kiểm tra lại mã hàng không ạ?",
        )
    data = result.get("data", {})
    resolved = data.get("resolved_from")
    conf = 0.92 if resolved else 1.0
    tier = "fuzzy" if resolved else "exact"
    warnings = []
    if resolved:
        brand = data.get("brand", "hãng khác")
        warnings.append(f"Mã {part_no} ({brand}) → Tokin {data.get('tokin_part_no')}")
    return ConfidenceResult(
        success=True, data=data, confidence=conf, tier=tier,
        warnings=warnings, source="lookup_part",
    )


def score_search(result: dict, query: str, filters: dict) -> ConfidenceResult:
    """
    search_parts: confidence dựa trên số kết quả + filter coverage + BM25 score top result.
    """
    if not result.get("success"):
        return ConfidenceResult(
            success=False, data=None, confidence=0.0, tier="fallback",
            warnings=["Không tìm thấy linh kiện phù hợp"],
            ask_clarify=True,
            clarify_hint="Anh/chị có thể mô tả rõ hơn hoặc cho biết mã hàng không ạ?",
        )

    data = result.get("data", {})
    parts = data.get("parts", [])
    total = data.get("total", 0)
    applied = data.get("filters_applied", {})

    if total == 0:
        return ConfidenceResult(
            success=False, data=data, confidence=0.0, tier="fallback",
            warnings=["Không có kết quả nào khớp"],
            ask_clarify=True,
            clarify_hint="Thử mô tả khác hoặc cho biết hệ N/D và cỡ dây ạ?",
        )

    # Score = coverage filter + top result priority
    filter_score   = len(applied) / 4.0   # max 4 filters
    top_priority   = 0.1 if (parts and parts[0].get("is_priority_sell")) else 0.0
    result_penalty = 0.0 if total >= 3 else 0.1   # ít kết quả → uncertain
    conf = min(0.95, 0.65 + filter_score * 0.2 + top_priority - result_penalty)

    tier     = "exact" if applied.get("ecosystem") and applied.get("wire_size_mm") else "fuzzy"
    warnings = []
    if not applied.get("ecosystem"):
        warnings.append("Chưa xác định hệ (N/D/WX) — kết quả có thể chưa chính xác")
    if total > 10:
        warnings.append(f"Có {total} kết quả — nên thu hẹp bộ lọc")

    return ConfidenceResult(
        success=True, data=data, confidence=round(conf, 3),
        tier=tier, warnings=warnings, source="search_parts",
    )


def score_upsell(result: dict) -> ConfidenceResult:
    """
    find_upsell_companions: confidence dựa trên source_steps (compat_edges vs fallback).
    """
    if not result.get("success"):
        return ConfidenceResult(
            success=False, data=None, confidence=0.0, tier="fallback",
            warnings=["Không tìm thấy linh kiện đi kèm"],
            ask_clarify=True,
            clarify_hint="Part này chưa có dữ liệu tương thích đầy đủ",
        )

    data         = result.get("data", {})
    steps        = data.get("source_steps", [])
    total        = data.get("total", 0)

    # Nếu đến từ compat_edges → high confidence; consumable_set → medium; wire_expand → lower
    has_compat   = any("compat_edges" in s for s in steps)
    has_cs       = any("consumable_set" in s for s in steps)

    if has_compat and total >= 3:
        conf, tier = 0.92, "exact"
    elif has_cs:
        conf, tier = 0.78, "fuzzy"
    else:
        conf, tier = 0.60, "inferred"

    warnings = []
    if total > 15:
        warnings.append("Nhiều linh kiện đi kèm — nên lọc theo cỡ dây hoặc hệ cụ thể")

    return ConfidenceResult(
        success=True, data=data, confidence=conf,
        tier=tier, warnings=warnings, source="find_upsell_companions",
    )


def score_compatibility(result: dict) -> ConfidenceResult:
    """
    check_compatibility: exact rule match = 1.0, same-eco inference = 0.75
    """
    if not result.get("success"):
        return ConfidenceResult(
            success=False, data=None, confidence=0.0, tier="fallback",
            warnings=["Không thể kiểm tra tương thích"],
        )
    data     = result.get("data", {})
    rule_id  = data.get("rule_id")
    direct   = data.get("direct_compat", False)

    if rule_id:
        conf, tier = 1.0, "exact"       # negative rule khớp
    elif direct:
        conf, tier = 0.97, "exact"      # trong compat_edges
    else:
        conf, tier = 0.72, "inferred"   # inferred từ same ecosystem

    warnings = []
    if not rule_id and not direct and data.get("compatible"):
        warnings.append("Tương thích suy luận từ hệ — chưa có edge trực tiếp trong data")

    return ConfidenceResult(
        success=True, data=data, confidence=conf,
        tier=tier, warnings=warnings, source="check_compatibility",
    )


def score_generic(result: dict, source: str) -> ConfidenceResult:
    """Fallback scorer cho các tool còn lại."""
    if not result.get("success"):
        return ConfidenceResult(
            success=False, data=None, confidence=0.0, tier="fallback",
            warnings=[result.get("reason", "Tool failed")],
        )
    return ConfidenceResult(
        success=True, data=result.get("data"),
        confidence=0.90, tier="exact", source=source,
    )


# ── Main entry ─────────────────────────────────────────────────────────────────

def score_tool_result(
    tool_name: str,
    tool_args: dict,
    raw_result: dict,
) -> dict:
    """
    Wrap raw tool result với confidence metadata.
    Gọi từ dispatch() trước khi return cho orchestrator.

    Returns: dict với keys success, data, confidence, tier, warnings, ask_clarify
    """
    if tool_name == "lookup_part":
        cr = score_lookup(raw_result, tool_args.get("part_no", ""))
    elif tool_name == "search_parts":
        cr = score_search(
            raw_result,
            tool_args.get("query", ""),
            {k: v for k, v in tool_args.items() if k != "query" and v},
        )
    elif tool_name == "find_upsell_companions":
        cr = score_upsell(raw_result)
    elif tool_name == "check_compatibility":
        cr = score_compatibility(raw_result)
    else:
        cr = score_generic(raw_result, tool_name)

    return cr.to_dict()
