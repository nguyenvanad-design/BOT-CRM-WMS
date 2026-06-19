"""
llm_explanation.py — TOKINARC LLM Explanation Layer
=====================================================
Autoss × Tokinarc — Industrial Compatibility Intelligence

Tầng cuối cùng: nhận QueryResponse (structured) → sinh ngôn ngữ tự nhiên
tiếng Việt cho khách hàng.

Kiến trúc:
    QueryResponse
      + ConstraintReport  (optional — violations/warnings)
      + ConfidenceDetail  (optional — band, score)
      + ClarificationDecision (optional — nếu cần hỏi thêm)
    → ExplanationRequest
    → ExplanationEngine.explain()
    → ExplanationResult (text + metadata)

Hai chế độ:
    MODE_TEMPLATE  — Pure template, không gọi LLM (fast, deterministic)
                     Dùng cho demo, test, khi không có API key
    MODE_LLM       — Gọi Claude API để sinh ngôn ngữ tự nhiên phong phú hơn
                     Template làm structured prompt, LLM polish output

Template coverage (11 intents):
    LOOKUP              → Thông tin chi tiết part
    CONSUMABLE_SET      → Bộ vật tư theo role, mandatory/optional
    COMPATIBILITY_CHECK → Kết quả tương thích + lý do
    SEARCH_BY_DESC      → Danh sách kết quả có filter
    UPSELL              → Linh kiện còn thiếu để hoàn chỉnh bộ
    REPLACEMENT         → Mã Tokin tương đương cho P/D alias
    INSTALLATION        → Hướng dẫn lắp đặt + linh kiện
    REPAIR              → Chẩn đoán triệu chứng + linh kiện suspect
    COMPARISON          → Bảng so sánh parallel
    AGGREGATE           → Tổng hợp thống kê
    OUT_OF_SCOPE        → Redirect lịch sự

Tone Autoss:
    - Chuyên nghiệp, ngắn gọn, không rườm rà
    - Dùng "ạ" cuối câu nơi phù hợp
    - Format: mã hàng in đậm, giá rõ ràng, nhóm by role
    - Ưu tiên mandatory parts trước optional
    - Luôn thêm 1 gợi ý follow-up

Usage:
    from llm_explanation import ExplanationEngine
    engine = ExplanationEngine()                        # template mode
    engine = ExplanationEngine(api_key="sk-ant-...")    # LLM mode

    result = engine.explain(response)
    print(result.text)

    # Với full context:
    result = engine.explain(
        response,
        constraint_report=cr,
        confidence_detail=cd,
        clarification=decision,
    )
"""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Constants ────────────────────────────────────────────────────────────────

MODE_TEMPLATE = "template"
MODE_LLM      = "llm"

# Số parts tối đa hiển thị per role trong consumable set
MAX_PARTS_PER_ROLE = 3
# Số parts tối đa trong flat list (SEARCH, AGGREGATE)
MAX_PARTS_FLAT = 8
# Số parts tối đa trong COMPARISON
MAX_COMPARE_PARTS = 6

# Vietnamese role names
ROLE_VI: Dict[str, str] = {
    "Tip":              "Béc hàn",
    "TipBody":          "Thân béc",
    "TipAdapter":       "Đầu nối béc",
    "Nozzle":           "Chụp khí",
    "Orifice":          "Orifice (lỗ khí)",
    "Insulator":        "Cách điện",
    "Liner":            "Liner (lõi dẫn dây)",
    "LinerORing":       "O-ring liner",
    "WaveWasher":       "Vòng đệm lò xo",
    "InnerTube":        "Ống nước bên trong",
    "TungstenElectrode":"Điện cực vonfram (TIG)",
    "Collet":           "Collet kẹp điện cực",
    "ColletBody":       "Thân collet",
    "CeramicNozzle":    "Chụp sứ (TIG)",
    "BackCap":          "Nắp sau",
    "GasHose":          "Ống dẫn khí",
    "CableAssembly":    "Dây cáp lắp ráp",
    "PowerCable":       "Cáp điện",
    "Handle":           "Tay cầm súng",
    "TorchBody":        "Thân súng hàn",
    "InsulationCollar": "Vòng cách điện",
    "WXNozzleSleeve":   "Ống bọc chụp WX",
    "WXCoverRubber":    "Cao su bọc WX",
}

# Category VI names (for search results)
CATEGORY_VI: Dict[str, str] = {
    "Tip":              "Béc hàn",
    "Nozzle":           "Chụp khí",
    "Orifice":          "Orifice",
    "Insulator":        "Cách điện",
    "Liner":            "Liner",
    "TungstenElectrode":"Điện cực TIG",
    "TipBody":          "Thân béc",
    "PowerCable":       "Cáp điện",
    "GasHose":          "Ống khí",
}


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class ExplanationResult:
    """Output của ExplanationEngine."""
    text: str                    # Natural language response (Markdown)
    intent: str
    mode: str                    # "template" / "llm"
    parts_shown: int = 0
    has_violations: bool = False
    has_clarification: bool = False
    latency_ms: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.text


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _price(part) -> str:
    """Format giá part."""
    if getattr(part, "is_contact_price", False):
        return "*(liên hệ báo giá)*"
    vnd = getattr(part, "price_vnd", None)
    if vnd:
        unit = getattr(part, "price_unit", "cái")
        return f"**{vnd:,}đ**/{unit}"
    return "*(chưa có giá)*"


def _role_vi(role: str) -> str:
    return ROLE_VI.get(role, role)


def _cat_vi(cat: str) -> str:
    return CATEGORY_VI.get(cat, cat)


def _eco_vi(eco: str) -> str:
    mapping = {
        "N": "hệ N (Panasonic/Yaskawa)",
        "D": "hệ D (Daihen/OTC)",
        "WX": "hệ WX (robot đặc biệt)",
        "TIG": "TIG",
        "UNIVERSAL": "universal",
        "TCC": "TCC",
    }
    return mapping.get(eco, eco)


def _mandatory_icon(is_mandatory: bool) -> str:
    return "★" if is_mandatory else "○"


def _part_line(part, show_role: bool = False) -> str:
    """Single line for a part."""
    role_str = f" *({_role_vi(part.role)})*" if show_role and part.role else ""
    wire_str = f" — dây {part.wire_size_mm}mm" if part.wire_size_mm else ""
    note_str = f" _{part.note}_" if getattr(part, "note", "") else ""
    return (
        f"`{part.tokin_part_no}` — {part.display_name_vi}"
        f"{wire_str}{role_str} — {_price(part)}{note_str}"
    )


def _violation_block(constraint_report: dict) -> str:
    """Format constraint violations thành warning block."""
    violations = constraint_report.get("violations", [])
    warnings_list = constraint_report.get("warnings", [])
    if not violations and not warnings_list:
        return ""

    lines = []
    blockers = [v for v in violations if v.get("severity") == "BLOCK"]
    warns    = [v for v in violations if v.get("severity") == "WARN"]

    if blockers:
        lines.append("\n> ⚠️ **Cảnh báo không tương thích:**")
        for v in blockers[:2]:
            lines.append(f"> - {v.get('reason_vi', '')}")
            if v.get("suggestion_vi"):
                lines.append(f">   _{v['suggestion_vi']}_")

    if warns:
        lines.append("\n> ℹ️ **Lưu ý:**")
        for v in warns[:2]:
            lines.append(f"> - {v.get('reason_vi', '')}")

    for w in warnings_list[:1]:
        lines.append(f"\n> ℹ️ {w.get('message_vi', '')}")

    return "\n".join(lines)


def _confidence_note(confidence_band: str) -> str:
    """Note nhỏ nếu confidence thấp."""
    if confidence_band in ("LOW", "VERY_LOW"):
        return "\n\n*Kết quả có thể chưa chính xác hoàn toàn — bạn có thể cung cấp thêm thông tin (model súng, hệ N/D, kích cỡ dây) để tôi lọc chính xác hơn ạ.*"
    return ""


# ─── Template renderers (11 intents) ──────────────────────────────────────────

def _render_lookup(resp, ctx: dict) -> str:
    if not resp.parts:
        code = resp.query
        return (
            f"Xin lỗi, em không tìm thấy mã hàng **{code}** trong hệ thống ạ.\n\n"
            f"Anh/chị có thể kiểm tra lại mã hàng, hoặc mô tả sản phẩm để em tìm giúp ạ."
        )

    lines = []
    for part in resp.parts[:4]:
        eco  = _eco_vi(part.ecosystem)
        cc   = f" — {part.current_class}" if part.current_class else ""
        wire = f" — dây {part.wire_size_mm}mm" if part.wire_size_mm else ""

        # FIX câu 6: detect alias từ hãng khác → tư vấn nhiệt tình
        resolved_from = getattr(part, "_resolved_from", "") or ""
        brand         = getattr(part, "_brand", "") or ""
        if resolved_from and brand:
            lines.append(
                f"Dạ, mã **{resolved_from}** là sản phẩm của **{brand}** — "
                f"bên em có sản phẩm Tokin tương đương chất lượng Nhật Bản ạ:\n"
            )

        lines.append(f"**{part.tokin_part_no}** — {part.display_name_vi}")
        lines.append(f"- Loại: {_cat_vi(part.category)} | Hệ: {eco}{cc}{wire}")
        lines.append(f"- Giá: {_price(part)}")

        if part.p_part_nos:
            lines.append(f"- Mã Panasonic tương đương: {', '.join(part.p_part_nos[:4])}")
        if part.d_part_nos:
            lines.append(f"- Mã Daihen/OTC tương đương: {', '.join(part.d_part_nos[:4])}")
        if getattr(part, "note", ""):
            lines.append(f"- Ghi chú: {part.note}")

        if resolved_from and brand:
            lines.append(
                f"\nAnh/chị cần báo giá chi tiết hoặc đặt hàng số lượng bao nhiêu ạ? 😊"
            )

        lines.append("")

    return "\n".join(lines).strip()


def _render_consumable_set(resp, ctx: dict) -> str:
    torch_info = ctx.get("context", {}).get("torch")
    torch_name = torch_info["model_code"] if torch_info else "súng hàn"
    mandatory  = ctx.get("context", {}).get("mandatory_count", 0)
    optional   = ctx.get("context", {}).get("optional_count", 0)

    lines = [
        f"## Bộ vật tư tiêu hao — {torch_name}\n",
        f"Tổng cộng **{resp.total_found} linh kiện** "
        f"(★ {mandatory} bắt buộc · ○ {optional} tùy chọn)\n",
    ]

    if resp.parts_by_role:
        for role, parts in resp.parts_by_role.items():
            role_label = _role_vi(role)
            lines.append(f"**{role_label}**")
            for p in parts[:MAX_PARTS_PER_ROLE]:
                icon = _mandatory_icon(p.is_mandatory)
                wire = f" {p.wire_size_mm}mm" if p.wire_size_mm else ""
                lines.append(
                    f"  {icon} `{p.tokin_part_no}` {p.display_name_vi}{wire} — {_price(p)}"
                )
            lines.append("")

    lines.append("*★ = thay thế định kỳ · ○ = tùy chọn theo nhu cầu*")
    return "\n".join(lines)


def _render_compatibility(resp, ctx: dict) -> str:
    if not resp.compat_results:
        return "Không thể kiểm tra tương thích — vui lòng cung cấp ít nhất 2 mã hàng ạ."

    lines = []
    for cr in resp.compat_results:
        if cr.is_compatible:
            lines.append(f"✅ **{cr.part_a}** và **{cr.part_b}** **tương thích** với nhau ạ.")
        else:
            lines.append(f"❌ **{cr.part_a}** và **{cr.part_b}** **không tương thích**.")

        lines.append(f"> {cr.reason}")
        if cr.relation_type and cr.relation_type not in ("unknown", "incompatible"):
            lines.append(f"> *Quan hệ: {cr.relation_type}*")
        lines.append(f"> *Độ tin cậy: {cr.confidence:.0%}*\n")

    return "\n".join(lines).strip()


def _render_search(resp, ctx: dict) -> str:
    if not resp.parts:
        return (
            "Không tìm thấy linh kiện phù hợp với mô tả của bạn ạ.\n\n"
            "Bạn có thể thử:\n"
            "- Cung cấp thêm thông tin (hệ N/D, kích cỡ dây, công suất)\n"
            "- Tìm theo mã hàng cụ thể\n"
            "- Mô tả triệu chứng/vấn đề để tôi gợi ý linh kiện"
        )

    filters = ctx.get("context", {}).get("filters_applied", {})
    filter_str = ""
    if filters:
        parts_f = []
        if filters.get("ecosystem"):
            parts_f.append(f"hệ {filters['ecosystem']}")
        if filters.get("wire_size_mm"):
            parts_f.append(f"dây {filters['wire_size_mm']}mm")
        if filters.get("current_class"):
            parts_f.append(filters["current_class"])
        if parts_f:
            filter_str = f" *(lọc: {', '.join(parts_f)})*"

    total = resp.total_found
    shown = min(total, MAX_PARTS_FLAT)

    lines = [f"Tìm thấy **{total} linh kiện**{filter_str}:\n"]

    for part in resp.parts[:MAX_PARTS_FLAT]:
        eco = f" [{part.ecosystem}]" if part.ecosystem else ""
        wire = f" — {part.wire_size_mm}mm" if part.wire_size_mm else ""
        cc = f" — {part.current_class}" if part.current_class else ""
        score_str = f" *(phù hợp: {part.score:.0%})*" if part.score < 0.99 else ""
        lines.append(
            f"- `{part.tokin_part_no}` — {part.display_name_vi}"
            f"{eco}{wire}{cc} — {_price(part)}{score_str}"
        )

    if total > shown:
        lines.append(f"\n*...và {total - shown} kết quả khác. Lọc thêm để thu hẹp ạ.*")

    return "\n".join(lines)


def _render_upsell(resp, ctx: dict) -> str:
    """
    5 loại UPSELL theo spec Autoss:
    Loại 1: alias hãng khác (U4167G01) → linh kiện đi kèm
    Loại 2: mô tả súng/amperage → bộ vật tư
    Loại 3/4: mã Tokin hoặc mô tả + hỏi đi kèm → compatible_with list + giá
    Loại 5: đã mua X, cần thêm Y cụ thể (filter_category)
    """
    c = ctx.get("context", {})
    eco     = c.get("ecosystem", "")
    torch_m = c.get("torch_model", "")

    eco_str   = f" hệ {eco}" if eco else ""
    torch_str = f" súng {torch_m}" if torch_m else ""
    anchor    = c.get("anchor_part", "")
    anchor_name = c.get("anchor_name", "")
    filter_cat  = c.get("filter_category", "")

    # Header tư vấn Autoss
    intro = "Dạ, bên em là Nhà phân phối độc quyền vật tư Tokin Nhật Bản"
    if anchor:
        intro += f", cung cấp đầy đủ vật tư tiêu hao đi kèm với **{anchor}**"
        if anchor_name:
            intro += f" ({anchor_name})"
    elif eco_str or torch_str:
        intro += f", cung cấp đầy đủ vật tư tiêu hao cho{torch_str}{eco_str}"
    intro += " như sau ạ:\n"

    lines = [intro]

    # Nếu có filter_category (Loại 5) — chỉ show parts thuộc category đó
    if filter_cat and resp.parts_by_role:
        filter_roles = {
            "Nozzle":    ["Nozzle"],
            "Insulator": ["Insulator"],
            "TipBody":   ["TipBody"],
            "Tip":       ["Tip"],
            "Liner":     ["Liner"],
            "Orifice":   ["Orifice"],
        }
        target_roles = filter_roles.get(filter_cat, [filter_cat])
        for role in target_roles:
            if role in resp.parts_by_role:
                lines.append(f"**{_role_vi(role)}**")
                for p in resp.parts_by_role[role][:5]:
                    lines.append(f"- **{p.tokin_part_no}** — {p.display_name_vi} — {_price(p)}")
                lines.append("")
        if len(lines) <= 2:
            # filter_category không khớp → show tất cả
            filter_cat = ""

    if not filter_cat:
        # Show theo role groups — chỉ hệ N/D, bỏ WX/carbon/Unionmelt
        _SKIP_ROLES = {"TipAdapter", "WXNozzleSleeve", "WXCoverRubber", "WXCenterCeramic"}
        if resp.parts_by_role:
            for role, parts in resp.parts_by_role.items():
                if role in _SKIP_ROLES:
                    continue
                # Lọc parts không phải WX khi eco là N hoặc D
                filtered = []
                for p in parts:
                    p_eco = getattr(p, "ecosystem", "") or ""
                    if eco and p_eco not in (eco, "UNIVERSAL", "HYBRID", ""):
                        continue
                    if not eco and p_eco == "WX":
                        continue
                    filtered.append(p)
                if not filtered:
                    continue
                lines.append(f"**{_role_vi(role)}**")
                for p in filtered[:3]:
                    lines.append(f"- **{p.tokin_part_no}** — {p.display_name_vi} — {_price(p)}")
                lines.append("")
        elif resp.parts:
            for part in resp.parts[:10]:
                p_eco = getattr(part, "ecosystem", "") or ""
                if not eco and p_eco == "WX":
                    continue
                lines.append(
                    f"- **{part.tokin_part_no}** — {part.display_name_vi} "
                    f"({_cat_vi(getattr(part, 'category', ''))}) — {_price(part)}"
                )

    lines.append("\nAnh/chị cần báo giá hoặc thêm thông tin gì không ạ? 😊")
    return "\n".join(lines).strip()


def _render_replacement(resp, ctx: dict) -> str:
    if not resp.parts:
        return (
            f"{resp.error_msg}\n\n"
            "Bạn có thể thử:\n"
            "- Kiểm tra lại mã hàng (mã Panasonic dạng **TET#####**, mã Daihen/OTC dạng **K###X##** hoặc **L####X##**)\n"
            "- Cung cấp thêm mô tả sản phẩm để tôi tìm tương đương"
        )

    lines = ["Mã Tokin tương đương:\n"]
    for part in resp.parts[:4]:
        role_note = f" *({part.role})*" if part.role else ""
        lines.append(f"### `{part.tokin_part_no}` — {part.display_name_vi}{role_note}")
        lines.append(f"- **Giá:** {_price(part)}")
        lines.append(f"- **Hệ:** {_eco_vi(part.ecosystem)}")
        if part.p_part_nos:
            lines.append(f"- **Mã Panasonic tương đương:** {', '.join(part.p_part_nos[:4])}")
        if part.d_part_nos:
            lines.append(f"- **Mã Daihen/OTC tương đương:** {', '.join(part.d_part_nos[:4])}")
        lines.append("")

    return "\n".join(lines).strip()


def _render_installation(resp, ctx: dict) -> str:
    c = ctx.get("context", {})
    tips = c.get("install_tips", [])
    torch_info = c.get("torch")
    torch_str = f" cho **{torch_info['model_code']}**" if torch_info else ""

    lines = [f"## Hướng dẫn lắp đặt{torch_str}\n"]

    if tips:
        lines.append("**Lưu ý kỹ thuật:**")
        for tip in tips:
            lines.append(f"- {tip}")
        lines.append("")

    if resp.parts_by_role:
        lines.append("**Các linh kiện cần thiết:**\n")
        for role, parts in resp.parts_by_role.items():
            lines.append(f"**{_role_vi(role)}**")
            for p in parts[:2]:
                icon = _mandatory_icon(p.is_mandatory)
                lines.append(f"  {icon} `{p.tokin_part_no}` — {p.display_name_vi} — {_price(p)}")
            lines.append("")
    elif resp.parts:
        lines.append("**Linh kiện liên quan:**")
        for p in resp.parts[:5]:
            lines.append(f"- `{p.tokin_part_no}` — {p.display_name_vi} — {_price(p)}")

    return "\n".join(lines).strip()


def _render_repair(resp, ctx: dict) -> str:
    c = ctx.get("context", {})
    symptoms    = c.get("detected_symptoms", [])
    suspect_cats = c.get("suspect_categories", [])
    advice      = c.get("repair_advice", [])
    torch_m     = c.get("torch_model")

    torch_str = f" trên súng **{torch_m}**" if torch_m else ""

    lines = []
    if symptoms:
        sym_str = ", ".join(symptoms[:3])
        lines.append(f"Phân tích triệu chứng **{sym_str}**{torch_str}:\n")
    else:
        lines.append(f"Chẩn đoán vấn đề{torch_str}:\n")

    if suspect_cats:
        cat_str = ", ".join(_cat_vi(c) for c in suspect_cats[:4])
        lines.append(f"**Nguyên nhân có thể:** liên quan đến {cat_str}.\n")

    if advice:
        lines.append("**Hướng xử lý:**")
        for a in advice[:3]:
            lines.append(f"- {a}")
        lines.append("")

    if resp.parts_by_role:
        lines.append("**Linh kiện cần kiểm tra/thay thế:**\n")
        for role, parts in resp.parts_by_role.items():
            lines.append(f"**{_role_vi(role)}**")
            for p in parts[:2]:
                lines.append(f"  - `{p.tokin_part_no}` — {p.display_name_vi} — {_price(p)}")
            lines.append("")
    elif resp.parts:
        lines.append("**Linh kiện liên quan:**")
        for p in resp.parts[:6]:
            lines.append(f"- `{p.tokin_part_no}` — {_cat_vi(p.category)} — {_price(p)}")

    return "\n".join(lines).strip()


def _render_comparison(resp, ctx: dict) -> str:
    c = ctx.get("context", {})
    groups = c.get("groups", {})

    if not resp.parts and not groups:
        return "Không đủ dữ liệu để so sánh. Vui lòng cung cấp ít nhất 2 mã hàng hoặc 2 loại linh kiện ạ."

    lines = ["## So sánh linh kiện\n"]

    if resp.parts:
        # Flat comparison: group by ecosystem
        by_eco: Dict[str, list] = {}
        for p in resp.parts[:MAX_COMPARE_PARTS]:
            by_eco.setdefault(p.ecosystem, []).append(p)

        for eco, parts in by_eco.items():
            lines.append(f"### {_eco_vi(eco)}")
            for p in parts:
                wire = f" — {p.wire_size_mm}mm" if p.wire_size_mm else ""
                cc   = f" — {p.current_class}" if p.current_class else ""
                lines.append(
                    f"- `{p.tokin_part_no}` — {p.display_name_vi}{wire}{cc} — {_price(p)}"
                )
            lines.append("")

    # Diff table from engine context
    diff = c.get("diff", {})
    if diff:
        diff_points = []
        for field_name, info in diff.items():
            if not info.get("same"):
                vals = info.get("values", {})
                val_str = " vs ".join(f"{k}: {v}" for k, v in list(vals.items())[:2])
                diff_points.append(f"**{field_name}**: {val_str}")
        if diff_points:
            lines.append("\n**Điểm khác biệt:**")
            for d in diff_points[:4]:
                lines.append(f"- {d}")
    # Torch diff
    torch_diff = c.get("torch_diff", {})
    if torch_diff:
        diff_points = []
        for field_name, info in torch_diff.items():
            if not info.get("same"):
                vals = info.get("values", {})
                val_str = " vs ".join(f"{k}: {v}" for k, v in list(vals.items())[:2])
                diff_points.append(f"**{field_name}**: {val_str}")
        if diff_points:
            lines.append("\n**Điểm khác biệt:**")
            for d in diff_points[:4]:
                lines.append(f"- {d}")

    return "\n".join(lines).strip()


def _render_aggregate(resp, ctx: dict) -> str:
    c = ctx.get("context", {})
    cat = c.get("category", "")
    total = c.get("total_in_category", resp.total_found)
    by_eco  = c.get("breakdown_by_ecosystem", {})
    by_wire = c.get("breakdown_by_wire_size", {})
    total_torches = c.get("total_torches", 0)
    by_family = c.get("breakdown_by_family", {})

    lines = []

    if cat:
        lines.append(f"## Tổng hợp: {_cat_vi(cat)}\n")
        lines.append(f"Tổng cộng **{total} linh kiện** trong danh mục {_cat_vi(cat)}.\n")

        if by_eco:
            lines.append("**Phân theo hệ:**")
            for eco, cnt in sorted(by_eco.items(), key=lambda x: -x[1]):
                bar = "█" * min(cnt, 20)
                lines.append(f"  {eco:10} {bar} {cnt}")
            lines.append("")

        if by_wire:
            lines.append("**Phân theo kích cỡ dây:**")
            for wire, cnt in sorted(by_wire.items()):
                lines.append(f"  {wire}mm — {cnt} linh kiện")
            lines.append("")

    elif total_torches:
        lines.append(f"## Tổng hợp: Súng hàn\n")
        lines.append(f"Tổng cộng **{total_torches} súng hàn** trong danh mục.\n")

        if by_family:
            lines.append("**Phân theo dòng:**")
            for fam, cnt in sorted(by_family.items(), key=lambda x: -x[1]):
                lines.append(f"  {fam:15} — {cnt} model")

    elif c.get("type") == "torch_list" or (not cat and not total_torches and not by_family):
        # FIX câu 4: torch list từ _aggregate
        torches = c.get("torches", [])
        if torches:
            count = c.get("count", len(torches))
            lines.append(f"Danh mục súng hàn Tokinarc ({count} model):\n")
            for t in torches[:30]:
                eco_t = _eco_vi((t.get("ecosystem") or ""))
                cc_t  = t.get("current_class", "")
                name  = t.get("display_name_vi") or t.get("model_code", "")
                lines.append(
                    f"- **{t.get('model_code','')}** — {name} | {eco_t}"
                    + (f" | {cc_t}" if cc_t else "")
                )
        else:
            lines.append(f"Tìm thấy **{resp.total_found} kết quả** tổng hợp.\n")
            for part in resp.parts[:5]:
                lines.append(f"- `{part.tokin_part_no}` — {part.display_name_vi} — {_price(part)}")
    else:
        lines.append(f"Tìm thấy **{resp.total_found} kết quả** tổng hợp.\n")
        for part in resp.parts[:5]:
            lines.append(f"- `{part.tokin_part_no}` — {part.display_name_vi} — {_price(part)}")

    return "\n".join(lines).strip()


def _render_out_of_scope(resp, ctx: dict) -> str:
    c = ctx.get("context", {})
    msg      = c.get("message", "Câu hỏi này nằm ngoài phạm vi hỗ trợ của tôi.")
    redirect = c.get("redirect", "")

    lines = [
        f"{msg}\n",
        "Tôi chuyên hỗ trợ về **linh kiện hàn Tokinarc** — béc hàn, chụp khí, vật tư tiêu hao, súng hàn.",
    ]
    if redirect:
        lines.append(f"\n{redirect}")

    if resp.suggestions:
        lines.append("\n**Tôi có thể giúp bạn:**")
        for s in resp.suggestions[:3]:
            lines.append(f"- {s}")

    return "\n".join(lines)


def _render_not_found(resp) -> str:
    return (
        f"Xin lỗi, không tìm thấy kết quả cho yêu cầu của bạn ạ.\n\n"
        f"*{resp.error_msg}*\n\n"
        "**Gợi ý:**\n"
        "- Kiểm tra lại mã hàng hoặc cách viết\n"
        "- Thử mô tả theo loại linh kiện (béc hàn, chụp khí...)\n"
        "- Cung cấp thêm thông tin: hệ N/D, kích cỡ dây, công suất súng"
    )


# ─── ExplanationEngine ────────────────────────────────────────────────────────

INTENT_RENDERERS = {
    "LOOKUP":             _render_lookup,
    "CONSUMABLE_SET":     _render_consumable_set,
    "COMPATIBILITY_CHECK":_render_compatibility,
    "SEARCH_BY_DESC":     _render_search,
    "UPSELL":             _render_upsell,
    "REPLACEMENT":        _render_replacement,
    "INSTALLATION":       _render_installation,
    "REPAIR":             _render_repair,
    "COMPARISON":         _render_comparison,
    "AGGREGATE":          _render_aggregate,
    "OUT_OF_SCOPE":       _render_out_of_scope,
}


class ExplanationEngine:
    """
    Converts QueryResponse → Vietnamese natural language.

    Template mode (default): deterministic, no API calls.
    LLM mode: gọi Claude API để polish output.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,          # deprecated: ignored (Anthropic key không còn dùng)
        model: str = "gemini-2.5-flash-lite",         # Gemini model cho polish
        max_tokens: int = 800,
        mode: Optional[str] = None,
        pqa_retriever=None,
    ):
        # api_key (Anthropic) kept for backward compat nhưng không dùng
        # Polish luôn dùng Gemini REST (GEMINI_API_KEY từ env)
        self._model      = model
        self._max_tokens = max_tokens
        _has_key = bool(os.environ.get("GEMINI_API_KEY", ""))
        self._mode = mode or (MODE_LLM if _has_key else MODE_TEMPLATE)
        self._pqa  = pqa_retriever

    @property
    def mode(self) -> str:
        return self._mode

    def explain(
        self,
        response,
        constraint_report: Optional[dict] = None,
        confidence_detail: Optional[dict] = None,
        clarification=None,
    ) -> ExplanationResult:
        """
        Main entry point.

        Args:
            response:           QueryResponse từ QueryEngine
            constraint_report:  dict từ ConstraintReport.to_dict() (optional)
            confidence_detail:  dict từ ConfidenceDetail.to_dict() (optional)
            clarification:      ClarificationDecision (optional)

        Returns:
            ExplanationResult với .text là Markdown tiếng Việt
        """
        import time
        t0 = time.time()

        intent = response.intent
        ctx    = {"context": response.context, "suggestions": response.suggestions}

        # 1. Clarification takes priority nếu cần hỏi lại
        # Chỉ clarify nếu: cần hỏi VÀ engine không tìm được gì cụ thể
        # (nếu engine đã có kết quả tốt → hiện kết quả + hint nhẹ, không block)
        hard_clarify = (
            clarification
            and getattr(clarification, "should_clarify", False)
            and not response.success
        )
        soft_clarify = (
            clarification
            and getattr(clarification, "should_clarify", False)
            and response.success
            and response.total_found == 0
        )
        if hard_clarify or soft_clarify:
            text = self._render_clarification(clarification, response)
            return ExplanationResult(
                text=text,
                intent=intent,
                mode=self._mode,
                has_clarification=True,
                latency_ms=(time.time() - t0) * 1000,
            )

        # 2. Not found fallback
        if not response.success and intent not in ("OUT_OF_SCOPE",):
            text = _render_not_found(response)
            # Append constraint violations if any
            if constraint_report:
                text += _violation_block(constraint_report)
            return ExplanationResult(
                text=text,
                intent=intent,
                mode=self._mode,
                latency_ms=(time.time() - t0) * 1000,
            )

        # 3. Render via intent-specific template
        renderer = INTENT_RENDERERS.get(intent, _render_search)
        body = renderer(response, ctx)

        # 4. Append constraint violations
        if constraint_report:
            body += _violation_block(constraint_report)

        # 5. Append confidence note
        band = (confidence_detail or {}).get("band", "")
        body += _confidence_note(band)

        # 6. Append follow-up suggestions (max 1)
        suggestions = response.suggestions or []
        non_violation_suggestions = [
            s for s in suggestions
            if not s.startswith("⚠️")
        ]
        if non_violation_suggestions:
            follow = non_violation_suggestions[0]
            body += f"\n\n---\n*Gợi ý: {follow}*"

        # 7. LLM polish nếu mode=llm
        _POLISH_INTENTS = {"INSTALLATION", "REPAIR"}
        if self._mode == MODE_LLM and intent in _POLISH_INTENTS:
            body = self._llm_polish(body, response, ctx)

        # parts_shown: đếm số part user nhìn thấy.
        # response.parts là flat list; response.parts_by_role là CÙNG parts đó
        # nhóm theo role. Trước đây cộng cả 2 -> đếm gấp đôi (8 -> 16).
        # Ưu tiên parts_by_role nếu có nội dung; fallback len(parts).
        _pbr_total = sum(len(ps) for ps in response.parts_by_role.values())
        parts_shown = _pbr_total if _pbr_total > 0 else len(response.parts)

        return ExplanationResult(
            text=body,
            intent=intent,
            mode=self._mode,
            parts_shown=parts_shown,
            has_violations=bool(constraint_report and not constraint_report.get("is_clean")),
            has_clarification=False,
            latency_ms=(time.time() - t0) * 1000,
        )

    # ── Concurrent polish support ─────────────────────────────────────────────
    _POLISH_INTENTS = {"INSTALLATION", "REPAIR"}

    def needs_polish(self, intent: str) -> bool:
        """True nếu intent này cần LLM polish và mode=llm."""
        return self._mode == MODE_LLM and intent in self._POLISH_INTENTS

    def explain_template_only(
        self,
        response,
        constraint_report=None,
        confidence_detail=None,
        clarification=None,
    ) -> tuple:
        """
        Chạy tất cả các bước trong explain() NGOẠI TRỪ LLM polish.
        Trả (template_body: str, ctx: dict, intent: str).
        Dùng để fire polish concurrently với steps 3-5 trong pipeline.
        """
        import time
        t0 = time.time()
        intent = getattr(response, "intent", "OUT_OF_SCOPE") or "OUT_OF_SCOPE"
        ctx = {
            "constraint_report":  constraint_report or {},
            "confidence_detail":  confidence_detail or {},
            "context":            (response.context or {}) if hasattr(response, "context") else {},
        }

        # Clarification short-circuit
        hard_clarify = clarification and getattr(clarification, "should_clarify", False) and getattr(clarification, "dimension", "")
        soft_clarify = clarification and getattr(clarification, "should_clarify", False) and not getattr(clarification, "dimension", "")
        if hard_clarify or soft_clarify:
            body = self._render_clarification(clarification, response)
            return body, ctx, intent

        # Failure path
        if not response.success and intent not in ("OUT_OF_SCOPE",):
            fail_lines = ["❌ Không tìm thấy kết quả phù hợp."]
            if constraint_report:
                fail_lines.append(self._violation_block_text(constraint_report))
            body = "\n".join(l for l in fail_lines if l)
            return body, ctx, intent

        # Route to template renderer
        render_fn = {
            "LOOKUP":             _render_lookup,
            "CONSUMABLE_SET":     _render_consumable_set,
            "COMPATIBILITY_CHECK":_render_compatibility,
            "SEARCH_BY_DESC":     _render_search,
            "UPSELL":             _render_upsell,
            "REPLACEMENT":        _render_replacement,
            "INSTALLATION":       _render_installation,
            "REPAIR":             _render_repair,
            "COMPARISON":         _render_comparison,
            "AGGREGATE":          _render_aggregate,
        }.get(intent)

        if render_fn:
            body = render_fn(response, ctx)
        else:
            body = response.answer_text or "Không có thông tin."

        # Constraint violations
        if constraint_report:
            viol = _violation_block(constraint_report)
            if viol:
                body += "\n\n" + viol

        # Confidence note
        if confidence_detail:
            band = (confidence_detail or {}).get("band", "HIGH")
            note = _confidence_note(band)
            if note:
                body += "\n\n" + note

        # Suggestions
        non_violation_suggestions = []
        if constraint_report:
            for s in constraint_report.get("suggestions", []):
                if not s.startswith("⚠️"):
                    non_violation_suggestions.append(s)
        if non_violation_suggestions:
            body += f"\n\n---\n*Gợi ý: {non_violation_suggestions[0]}*"

        return body, ctx, intent

    def polish_body(self, template_body: str, response, ctx: dict) -> str:
        """Chạy LLM polish trên template_body đã có. Gọi trong thread riêng."""
        return self._llm_polish(template_body, response, ctx)

    def finalize(
        self,
        template_body: str,
        polished_body: Optional[str],
        response,
        ctx: dict,
        intent: str,
        constraint_report=None,
        confidence_detail=None,
    ) -> "ExplanationResult":
        """Kết hợp template + polish thành ExplanationResult cuối."""
        body = polished_body if polished_body else template_body
        _pbr_total = sum(len(ps) for ps in response.parts_by_role.values())
        parts_shown = _pbr_total if _pbr_total > 0 else len(response.parts)
        return ExplanationResult(
            text=body,
            intent=intent,
            mode=self._mode,
            parts_shown=parts_shown,
            has_violations=bool(constraint_report and not constraint_report.get("is_clean")),
            has_clarification=False,
            latency_ms=0,
        )

    def _violation_block_text(self, constraint_report: dict) -> str:
        """Helper để extract violation text."""
        return _violation_block(constraint_report)

    def _render_clarification(self, decision, response) -> str:
        """Render clarification question với options."""
        lines = []

        # Nếu có kết quả partial — hiện trước, rồi hỏi
        if response.success and response.parts:
            partial_text = f"Tôi tìm thấy **{response.total_found} kết quả**"
            if response.parts:
                top = response.parts[0]
                partial_text += f" — ví dụ: `{top.tokin_part_no}` {top.display_name_vi}"
            lines.append(partial_text + ".\n")

        lines.append(decision.question)

        if decision.options:
            lines.append("")
            for opt in decision.options[:5]:
                lines.append(f"- {opt}")

        if hasattr(decision, "reason") and "confidence" in (decision.reason or ""):
            pass  # don't expose internal confidence reason to user

        return "\n".join(lines)

    def _llm_polish(self, template_output: str, response, ctx: dict) -> str:
        """Goi Gemini API de polish template output + inject PQA phrasing examples."""
        import logging as _log
        _log.getLogger(__name__).info(f"[LLM_POLISH] called intent={getattr(response, 'intent', '?')}")
        try:
            import urllib.request, os, json as _json

            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            if not gemini_key:
                return template_output

            pqa_section = ""
            if hasattr(self, "_pqa") and self._pqa is not None:
                try:
                    intent = getattr(response, "intent", None)
                    query  = ctx.get("context", {}).get("original_query", template_output[:80])
                    hits   = self._pqa.retrieve(query, intent=intent, top_k=2)
                    if hits:
                        snippets = ["Q: " + h["question"] + "\nA: " + h["answer"] for h in hits]
                        pqa_section = "\n\n## Vi du phrasing chuan Autoss:\n" + "\n\n".join(snippets)
                except Exception:
                    pass

            system_prompt = (
                "Ban la tro ly tu van linh kien han Tokinarc cua Autoss VN. "
                "Nhiem vu: viet lai response bang tieng Viet tu nhien, chuyen nghiep. "
                "Quy tac: giu nguyen ma hang, gia, so lieu, Markdown formatting. "
                "Tone chuyen nghiep, ngan gon, dung 'a' cuoi cau khi phu hop. "
                "KHONG them thong tin moi. Output chi la response da polish."
            )

            user_msg = "Polish response sau:\n\n" + template_output + pqa_section
            full_msg = system_prompt + "\n\n" + user_msg

            # Log token count
            import logging as _lg
            _lg.getLogger(__name__).info(f"[LLM_POLISH] prompt_chars={len(full_msg)} approx_tokens={len(full_msg)//4}")

            payload = _json.dumps({
                "contents": [{"role": "user", "parts": [{"text": full_msg}]}],
                "generationConfig": {
                    "maxOutputTokens": 1024,
                    "temperature": 0.3,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }).encode()

            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=" + gemini_key
            from core.gemini_resilience import (
                with_retry, GeminiRateLimitError,
                GeminiTimeoutError, URLLIB_TIMEOUT,
            )

            def _do_request():
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=URLLIB_TIMEOUT) as r:
                    data = _json.loads(r.read())
                    return data["candidates"][0]["content"]["parts"][0]["text"]

            try:
                text = with_retry(_do_request, label="llm_polish")
                if text:
                    return text.strip()
            except (GeminiRateLimitError, GeminiTimeoutError) as ex:
                _log.getLogger(__name__).warning(f"[LLM_POLISH] resilience fallback: {ex}")
            except Exception:
                pass
        except Exception:
            pass
        return template_output


# ─── Convenience function ─────────────────────────────────────────────────────

def explain(
    response,
    constraint_report=None,
    confidence_detail=None,
    clarification=None,
    api_key: Optional[str] = None,
) -> ExplanationResult:
    """
    One-shot convenience wrapper.

    Usage:
        from llm_explanation import explain
        result = explain(query_response)
        print(result.text)
    """
    engine = ExplanationEngine(api_key=api_key)
    return engine.explain(
        response,
        constraint_report=constraint_report,
        confidence_detail=confidence_detail,
        clarification=clarification,
    )


