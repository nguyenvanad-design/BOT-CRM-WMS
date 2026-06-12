# core/pipeline_v7.py
# TOKINARC Pipeline V7 — Extractor → Planner → Executor
# ======================================================
# Kiến trúc 3 layer sạch, tất cả trong 1 file — không import từ v5/v6.
#
#   PipelinePlanner  — routing decision, confidence, early-exit
#   PipelineExecutor — DataStore/Graph call, format, session update
#   run_v7()         — entry point
#
# Thêm feature sau:
#   VectorIndex tier 3 → PipelineExecutor._execute_route()
#   alt_intent dual-run → PlanResult.alt_intent + Planner.plan()
#
# Backward compat: run_v6 = run_v5 = run_v7 — main.py không cần sửa.
# UTF-8 NO BOM

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("tokinarc.pipeline_v7")

# ─── Constants ────────────────────────────────────────────────────────────────

_TEMPLATE_ONLY_INTENTS = {
    "OUT_OF_SCOPE", "CLARIFY", "COMPATIBILITY_CHECK",
    "AGGREGATE", "COMPARISON",
}

_CLARIFY_REASON_MAP = {
    "NO_MATCH":                    "Bạn có thể cho biết mã hàng hoặc tên linh kiện cụ thể hơn không?",
    "NO_CONSUMABLE_SET_FOUND":     "Bạn cần bộ vật tư cho hệ nào và dòng điện bao nhiêu A? (Ví dụ: N 350A, D 350A)",
    "INSUFFICIENT_ENTITIES":       "Bạn có thể cho biết mã cụ thể hoặc mô tả chi tiết hơn không?",
    "CANNOT_DETERMINE_TARGET_SET": "Bạn đang dùng linh kiện hệ N hay hệ D? Và dòng điện 350A hay 500A?",
}

_CONTRA_CLARIFY_MAP = {
    "ecosystem_conflict": "Hệ N và hệ D không tương thích — ren khác nhau hoàn toàn. Bạn đang dùng hệ nào ạ?",
    "invalid_wire":       "Cỡ dây này không có trong danh mục Tokinarc. Bạn có thể xác nhận lại không ạ?",
    "amp_conflict":       "Bạn cần linh kiện 350A hay 500A? Hai dòng này không dùng chung được.",
}

_CONTRA_PATTERNS = [
    (r'(béc|tip|linh kiện)\s*(hệ\s*)?[DN].*(?:cho|của).*(?:panasonic|yaskawa|daihen|otc|hệ\s*[ND])', "ecosystem_conflict"),
    (r'(?:panasonic|yaskawa|hệ\s*N).*(?:daihen|otc|hệ\s*D)|(?:daihen|otc|hệ\s*D).*(?:panasonic|yaskawa|hệ\s*N)', "ecosystem_conflict"),
    (r'3\.0\s*mm|2\.5\s*mm|5\s*mm', "invalid_wire"),
    (r'350[Aa].*500[Aa]|500[Aa].*350[Aa]', "amp_conflict"),
]

_GIA_PAT = re.compile(
    r'gi[aá](\s+bao\s+nhi[eê]u|\s+bn?hi[eê]u|\b)|b[aá]o\s+gi[aá]|bao\s+nhi[eê]u',
    re.I | re.UNICODE,
)

_WX_KEYS     = ("/wx", "nước wx", "new β/wx", "newβ/wx", "water")
_WX_CAT_KEYS = ("carbon", "unionmelt", "newβ", "new β")
_SKIP_ROLES  = {"TipAdapter", "WXNozzleSleeve", "WXCoverRubber"}
_ROLE_VI = {
    "Tip": "Béc hàn", "Nozzle": "Chụp khí",
    "Insulator": "Cách điện", "TipBody": "Thân giữ béc",
    "Orifice": "Sứ chia khí", "Liner": "Liner",
    "Tool": "Dụng cụ", "WaveWasher": "Vòng đệm", "Other": "Linh kiện khác",
}
_ROLE_ORDER = ["TipBody", "Tip", "Nozzle", "Insulator", "Orifice",
               "Liner", "WaveWasher", "Tool", "Other"]
_ECO_VI = {
    "N": "hệ N (Panasonic/Yaskawa)", "D": "hệ D (Daihen/OTC)",
    "WX": "hệ WX", "TIG": "TIG",
}

# Built-in troubleshooting fallback khi assembly_procedures chưa load
_BUILTIN_TS = {
    "ts_excessive_spatter": {
        "symptom_vi": "Bắn tóe nhiều",
        "causes":  ["Chụp khí bị mòn hoặc biến dạng", "Béc hàn bị mòn lỗ quá lớn",
                    "Cài đặt dòng điện/điện áp không phù hợp", "Lưu lượng khí bảo vệ không đủ"],
        "actions": ["Kiểm tra và thay chụp khí mới",
                    "Kiểm tra béc hàn — thay nếu lỗ > 1.5× đường kính dây",
                    "Điều chỉnh thông số hàn (voltage/ampere)",
                    "Kiểm tra lưu lượng khí 15-20 L/min"],
    },
    "ts_wire_feeding_unstable": {
        "symptom_vi": "Dây hàn cấp không đều / kẹt dây",
        "causes":  ["Liner bị cong, bẩn hoặc mòn", "Béc hàn lỗ quá nhỏ hoặc dơ",
                    "Con lăn kéo dây mòn hoặc lực kẹp sai", "Dây hàn bị xoắn trong cuộn"],
        "actions": ["Kiểm tra và thay liner mới (flush bằng khí nén trước)",
                    "Vệ sinh hoặc thay béc hàn", "Kiểm tra lực kẹp con lăn",
                    "Kiểm tra cuộn dây — gỡ nếu bị xoắn"],
    },
    "ts_gas_leaking": {
        "symptom_vi": "Rò khí / khí bảo vệ không đều",
        "causes":  ["O-ring liner bị hỏng hoặc lệch vị trí", "Chụp khí lắp không chặt",
                    "Sứ chia khí bị nứt hoặc mẻ"],
        "actions": ["Kiểm tra O-ring liner — thay nếu biến dạng",
                    "Siết chặt chụp khí (lực siết 2–3 Nm)",
                    "Kiểm tra sứ chia khí — thay nếu nứt"],
    },
    "ts_arc_unstable": {
        "symptom_vi": "Hồ quang không ổn định",
        "causes":  ["Béc hàn bị mòn hoặc dính carbon", "Thân giữ béc lỏng — tiếp xúc điện kém",
                    "Cách điện bị hỏng gây rò điện", "Liner mòn làm dây lệch tâm"],
        "actions": ["Vệ sinh béc hàn hoặc thay mới", "Siết chặt thân giữ béc",
                    "Kiểm tra cách điện — thay nếu nứt/cháy", "Thay liner mới"],
    },
    "ts_ground_fault": {
        "symptom_vi": "Chạm mass / rò điện",
        "causes":  ["Cách điện bị nứt hoặc cháy", "Vỏ cách điện connector hỏng",
                    "Cáp súng bị trầy", "Orifice nứt gây dẫn điện ra nozzle"],
        "actions": ["Thay Insulator ngay", "Kiểm tra vỏ connector",
                    "Kiểm tra toàn bộ cáp súng", "Thay Orifice nếu nứt"],
    },
    "ts_torch_body_damaged_threads": {
        "symptom_vi": "Ren hỏng / thân súng mòn ren",
        "causes":  ["Siết béc quá chặt nhiều lần", "Dính bắn tóe làm ren bẩn"],
        "actions": ["Thay TipBody mới", "Siết đúng lực 2–3 Nm"],
    },
    "ts_center_ceramic_cracked": {
        "symptom_vi": "Sứ định tâm WX bị nứt / vỡ",
        "causes":  ["Va đập khi thay chụp khí", "Lắp sai thứ tự", "Nhiệt độ quá cao"],
        "actions": ["Thay sứ định tâm mới (mã 061445)",
                    "Lắp đúng thứ tự: TipAdapter→Orifice→CenterCeramic→Nozzle"],
    },
}

_REPAIR_KW_MAP = {
    "ban toe": "ts_excessive_spatter",     "bắn tóe": "ts_excessive_spatter",
    "spatter": "ts_excessive_spatter",     "bắn nhiều": "ts_excessive_spatter",
    "ket day": "ts_wire_feeding_unstable", "kẹt dây": "ts_wire_feeding_unstable",
    "cap khong deu": "ts_wire_feeding_unstable", "cấp không đều": "ts_wire_feeding_unstable",
    "wire feeding": "ts_wire_feeding_unstable", "day khong chay": "ts_wire_feeding_unstable",
    "ro khi": "ts_gas_leaking",            "rò khí": "ts_gas_leaking",
    "gas leak": "ts_gas_leaking",          "thoat khi": "ts_gas_leaking",
    "ho quang": "ts_arc_unstable",         "hồ quang": "ts_arc_unstable",
    "arc unstable": "ts_arc_unstable",     "chap dien": "ts_arc_unstable",
    "cham mass": "ts_ground_fault",        "chạm mass": "ts_ground_fault",
    "ro dien": "ts_ground_fault",          "rò điện": "ts_ground_fault",
    "giat dien": "ts_ground_fault",        "giật điện": "ts_ground_fault",
    "ren hong": "ts_torch_body_damaged_threads",
    "ren hỏng": "ts_torch_body_damaged_threads",
    "su vo": "ts_center_ceramic_cracked",
    "sứ vỡ": "ts_center_ceramic_cracked",
    "ceramic": "ts_center_ceramic_cracked",
}

_BUILTIN_INSTALL = [
    "Dạ, hướng dẫn lắp đặt linh kiện súng hàn Tokinarc ạ:\n",
    "**Thứ tự lắp:**",
    "1. Lắp **liner** vào thân súng — đảm bảo thẳng, không cong",
    "2. Lắp **thân giữ béc (TipBody)** — siết chặt tay",
    "3. Lắp **cách điện (Insulator)** vào TipBody",
    "4. Lắp **sứ chia khí (Orifice)** — đẩy khít vào rãnh",
    "5. Vặn **béc hàn (Tip)** vào TipBody — siết **2–3 Nm**",
    "6. Lắp **chụp khí (Nozzle)** — vặn hoặc nhấn tùy loại",
    "",
    "**Lưu ý:**",
    "- Không siết quá tay béc hàn — sẽ khó tháo khi bị dính nhiệt",
    "- Kiểm tra chụp khí ngay thẳng để tránh rò khí",
    "- Thay béc hàn khi lỗ mòn > 1.5× đường kính dây",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def _band(confidence: float) -> str:
    if confidence >= 0.85:
        return "HIGH"
    if confidence >= 0.65:
        return "MEDIUM"
    return "LOW"


def _entity_match_score(e_dict: dict, intent: str) -> float:
    score = 0.5
    has_part_no = bool(
        e_dict.get("part_nos") or e_dict.get("part_no") or
        e_dict.get("owned_parts") or e_dict.get("d_part_nos") or
        e_dict.get("p_part_nos")
    )
    if has_part_no:
        score = min(score + 0.35, 1.0)
    if e_dict.get("ecosystem"):
        score = min(score + 0.10, 1.0)
    if e_dict.get("current_class"):
        score = min(score + 0.10, 1.0)
    if e_dict.get("category"):
        score = min(score + 0.05, 1.0)
    if intent == "UPSELL" and not e_dict.get("owned_parts") and not has_part_no:
        score = max(score - 0.20, 0.0)
    if intent == "CONSUMABLE_SET" and not e_dict.get("ecosystem") and not e_dict.get("current_class"):
        score = max(score - 0.15, 0.0)
    return round(score, 3)


def _data_found_score(ds_result: dict) -> float:
    if not ds_result.get("success"):
        reason = ds_result.get("reason", "")
        if reason in ("CLARIFY:", "INSUFFICIENT_ENTITIES"):
            return 0.30
        return 0.10
    data = ds_result.get("data")
    if data is None:
        return 0.40
    base = 0.85 if ds_result.get("source") == "graph" else 0.75
    if isinstance(data, list) and len(data) > 5:
        base = max(base - 0.05, 0.60)
    return round(base, 3)


def _compute_global_confidence(
    intent_score: float, e_dict: dict, ds_result: dict,
    intent: str, force_band: str = "",
) -> tuple:
    if force_band == "HIGH":
        return (max(intent_score, 0.85), "HIGH")
    s_intent = min(max(intent_score, 0.0), 1.0)
    s_entity = _entity_match_score(e_dict, intent)
    s_data   = _data_found_score(ds_result)
    s_band   = 0.90 if intent_score >= 0.85 else (0.70 if intent_score >= 0.65 else 0.40)
    gc = round(min(max(
        0.35 * s_intent + 0.30 * s_entity + 0.25 * s_data + 0.10 * s_band,
        0.0), 1.0), 3)
    b = _band(gc)
    log.debug(f"[P2] intent={s_intent:.2f} entity={s_entity:.2f} data={s_data:.2f} → {gc:.3f} [{b}]")
    return (gc, b)


def _make_response(
    intent: str, query: str, confidence: float, band: str,
    text: str, needs_clarify: bool, clarify_q: Optional[str],
    session_id: Optional[str], parts: list, latency_ms: float,
    success: bool = True, vision_used: bool = False,
    match_type: str = "exact", fallback_used: bool = False,
) -> dict:
    return {
        "intent":              intent,
        "query":               query,
        "text":                text,
        "confidence":          confidence,
        "confidence_band":     band,
        "needs_clarification": needs_clarify,
        "clarification_q":     clarify_q or "",
        "session_id":          session_id or "",
        "success":             success,
        "parts":               {p["tokin_part_no"]: p for p in parts},
        "parts_count":         len(parts),
        "latency_ms":          latency_ms,
        "mode":                "v7_3layer",
        "match_type":          match_type,
        "fallback_used":       fallback_used,
        "vision_used":         vision_used,
        "vision_part_type":    "",
        "vision_confidence":   "",
        "vision_condition":    "",
        "vision_confirm_msg":  "",
        "vision_confirm_needed": False,
    }


def _error_response(query: str, err: str, session_id, latency_ms: float) -> dict:
    return _make_response(
        intent="OUT_OF_SCOPE", query=query, confidence=0.0, band="LOW",
        text=f"Lỗi hệ thống: {err}",
        needs_clarify=False, clarify_q=None,
        session_id=session_id, parts=[], latency_ms=latency_ms,
        success=False, match_type="none",
    )


def _extract_parts(data) -> list:
    if isinstance(data, list):
        return [{"tokin_part_no": p.get("tokin_part_no", ""),
                 "display_name_vi": p.get("display_name_vi", "")}
                for p in data if isinstance(p, dict) and p.get("tokin_part_no")]
    if isinstance(data, dict):
        parts = []
        if "tokin_part_no" in data:
            parts.append({"tokin_part_no": data["tokin_part_no"],
                          "display_name_vi": data.get("display_name_vi", "")})
        for key in ("items", "missing", "related_parts"):
            for item in (data.get(key) or []):
                if isinstance(item, dict) and item.get("part_id"):
                    parts.append({"tokin_part_no": item["part_id"],
                                  "display_name_vi": item.get("display_name_vi", "")})
        return parts
    return []


# ─── Graph converters ─────────────────────────────────────────────────────────

def _upsell_to_ds_result(upsell_result) -> dict:
    if not upsell_result.found:
        return {"success": False, "data": None, "reason": "NO_MATCH", "source": "graph"}

    anchor_no  = upsell_result.anchor_part_no
    anchor_eco = upsell_result.anchor_ecosystem or ""
    anchor_cat = upsell_result.anchor_category  or ""

    _WX_CATS = {"WX", "WXNozzleSleeve", "WXCoverRubber", "WXCenterCeramic"}
    filtered = []
    for p in upsell_result.companions:
        p_eco  = (p.get("ecosystem") or "").upper()
        p_role = p.get("role") or p.get("category", "")
        if anchor_eco.upper() in ("N", "D"):
            if p_eco == "WX" or p_role in _WX_CATS:
                continue
            if any(k in (p.get("display_name_vi") or "").lower() for k in _WX_KEYS):
                continue
        filtered.append(p)

    missing = []
    for p in filtered:
        biz = p.get("business") or {}
        missing.append({
            "part_id":         p.get("tokin_part_no", ""),
            "display_name_vi": p.get("display_name_vi", ""),
            "part_role":       p.get("role") or p.get("category", ""),
            "is_mandatory":    p.get("is_mandatory", True),
            "ecosystem":       (p.get("ecosystem") or "").upper(),
            "category":        p.get("category", ""),
            "business": {
                "price_vnd":        biz.get("price_vnd") or p.get("price_vnd"),
                "price_unit":       biz.get("price_unit") or p.get("price_unit") or "cái",
                "is_contact_price": biz.get("is_contact_price") or p.get("is_contact_price") or False,
                "is_priority_sell": biz.get("is_priority_sell") or p.get("is_priority", False),
            },
        })

    log.info(f"[v7] upsell graph: anchor={anchor_no} eco={anchor_eco} "
             f"companions={len(upsell_result.companions)}→filtered={len(filtered)}")
    return {"success": True, "source": "graph", "reason": "OK", "data": {
        "owned":             [anchor_no],
        "missing":           missing,
        "ecosystem":         anchor_eco,
        "anchor_categories": [anchor_cat] if anchor_cat else [],
        "_graph_steps":      upsell_result.source_steps,
        "_anchor_eco":       anchor_eco,
        "_anchor_cc":        upsell_result.anchor_current_class,
    }}


def _consumable_set_to_ds_result(cs_results: list) -> dict:
    if not cs_results:
        return {"success": False, "data": None, "reason": "NO_CONSUMABLE_SET_FOUND", "source": "graph"}
    cs = cs_results[0]
    if not cs.found or not cs.parts:
        return {"success": False, "data": None, "reason": "NO_CONSUMABLE_SET_FOUND", "source": "graph"}
    items = [{"part_id": p.get("tokin_part_no", ""), "display_name_vi": p.get("display_name_vi", ""),
              "part_role": p.get("role") or p.get("category", ""), "is_mandatory": p.get("is_mandatory", True)}
             for p in cs.parts]
    log.info(f"[v7] consumable_set graph: set_id={cs.set_id} eco={cs.ecosystem} parts={len(cs.parts)}")
    return {"success": True, "source": "graph", "reason": "OK", "data": {
        "items": items, "ecosystem": cs.ecosystem,
        "torch_current_class": cs.torch_current_class,
        "_eco_inferred": False, "_graph_set_id": cs.set_id,
    }}


# ─── Router ───────────────────────────────────────────────────────────────────

def _route_query(
    intent: str, e_dict: dict, data_store,
    graph_traversal, vector_index=None,
) -> dict:
    """
    Routing table — 3 tiers:
      Tier 1: Graph      → UPSELL / CONSUMABLE_SET
      Tier 2: DataStore  → tất cả intent
      Tier 3: VectorIndex → SEARCH_BY_DESC miss (semantic fallback)
    """
    if intent == "UPSELL" and graph_traversal is not None:
        part_no = (
            (e_dict.get("owned_parts") or [None])[0]
            or (e_dict.get("part_nos") or [None])[0]
            or (e_dict.get("d_part_nos") or [None])[0]
            or (e_dict.get("p_part_nos") or [None])[0]
            or e_dict.get("part_no", "")
        )
        if part_no:
            log.info(f"[v7] UPSELL → Graph.resolve_upsell({part_no!r})")
            try:
                result = graph_traversal.resolve_upsell(part_no)
                if result.found:
                    return _upsell_to_ds_result(result)
                log.info(f"[v7] Graph UPSELL not found → fallback DS")
            except Exception as ex:
                log.error(f"[v7] Graph.resolve_upsell failed: {ex} → fallback DS")
        else:
            log.warning("[v7] UPSELL: no part_no → fallback DS")

    if intent == "CONSUMABLE_SET" and graph_traversal is not None:
        log.info(f"[v7] CONSUMABLE_SET → Graph torch={e_dict.get('torch_model')!r} "
                 f"cc={e_dict.get('current_class')!r} eco={e_dict.get('ecosystem')!r}")
        try:
            cs_results = graph_traversal.get_full_consumable_set(
                torch_model=e_dict.get("torch_model"),
                current_class=e_dict.get("current_class"),
                ecosystem=e_dict.get("ecosystem"),
            )
            ds = _consumable_set_to_ds_result(cs_results)
            if ds["success"]:
                return ds
            log.info("[v7] Graph CONSUMABLE_SET not found → fallback DS")
        except Exception as ex:
            log.error(f"[v7] Graph.get_full_consumable_set failed: {ex} → fallback DS")

    # ── Tier 1b: RetrievalOrchestrator — brand alias detection ──────────────────
    # Xử lý mã Panasonic (TET/TGN/TDT...) và Daihen (K.../L.../U...)
    # Mở rộng sang UPSELL, COMPATIBILITY_CHECK, COMPARISON để resolve alias trước DS
    if intent in ("LOOKUP", "REPLACEMENT", "UPSELL", "COMPATIBILITY_CHECK", "COMPARISON"):
        raw_q = e_dict.get("_raw_query", "")
        if raw_q:
            try:
                from core.retrieval_orchestrator import get_retrieval_orchestrator
                ret = get_retrieval_orchestrator(data_store)
                ret_result = ret.retrieve(raw_q, intent_hint=intent)
                if ret_result.success and ret_result.match_type in (
                    "exact_alias_p", "exact_alias_d",
                    "exact_tokin", "exact_model_alias", "exact_torch",
                ):
                    log.info(f"[v7] retrieval_orch hit: {ret_result.match_type} "
                             f"intent={intent}")
                    if ret_result.ds_result:
                        # For UPSELL/COMPAT/COMPARISON: inject resolved part_no into e_dict
                        # rồi để DataStore xử lý đúng intent (không return sớm)
                        if intent in ("UPSELL", "COMPATIBILITY_CHECK", "COMPARISON"):
                            resolved_part = ret_result.ds_result.get("data", {})
                            if isinstance(resolved_part, dict):
                                pno = resolved_part.get("tokin_part_no", "")
                                if pno:
                                    # Inject resolved tokin code vào e_dict
                                    if intent == "UPSELL":
                                        e_dict.setdefault("owned_parts", [])
                                        if pno not in e_dict["owned_parts"]:
                                            e_dict["owned_parts"].insert(0, pno)
                                        e_dict.setdefault("part_nos", [])
                                        if pno not in e_dict["part_nos"]:
                                            e_dict["part_nos"].insert(0, pno)
                                    else:
                                        e_dict.setdefault("part_nos", [])
                                        if pno not in e_dict["part_nos"]:
                                            e_dict["part_nos"].insert(0, pno)
                                    log.info(f"[v7] alias resolved {pno} → injected into e_dict")
                        else:
                            return ret_result.ds_result
            except Exception as ex:
                log.warning(f"[v7] retrieval_orch failed: {ex} → fallback DS")

    # ── Tier 2: DataStore ──────────────────────────────────────────────────────
    ds_result = data_store.query(intent, e_dict)

    # ── Tier 3: VectorIndex fallback — chỉ khi SEARCH_BY_DESC miss ────────────
    if (
        not ds_result["success"]
        and intent == "SEARCH_BY_DESC"
        and vector_index is not None
    ):
        raw_q = e_dict.get("_raw_query", "")
        if raw_q:
            try:
                log.info(f"[v7] VectorIndex tier 3 fallback q={raw_q[:50]!r}")
                hits = vector_index.search(raw_q, top_k=8, filter_type="part")
                parts = [h["data"] for h in hits if h.get("data")]
                if parts:
                    log.info(f"[v7] VectorIndex found {len(parts)} results")
                    return {
                        "success": True,
                        "data":    parts,
                        "reason":  "vector_fallback",
                        "source":  "vector",
                    }
            except Exception as ex:
                log.warning(f"[v7] VectorIndex fallback failed: {ex}")

    return ds_result


# ─── Template formatter ───────────────────────────────────────────────────────

# ─── Knowledge base — câu hỏi giải thích linh kiện ───────────────────────────
# Khi user hỏi câu kiến thức chung (không tra DB), trả lời ngay thay vì OUT_OF_SCOPE.

_EXPLAIN_KB = [
    # Béc hàn vs chụp khí
    {
        "keys": ["béc hàn", "chụp khí", "giống", "khác", "bec han", "chup khi", "tip", "nozzle",
                 "phân biệt", "phan biet", "so sánh", "so sanh", "là gì", "la gi", "khác nhau"],
        "require_all": False,
        "require_any": [["béc", "bec", "tip"], ["chụp", "chup", "nozzle"]],
        "answer": (
            "**Béc hàn (Contact Tip)** và **Chụp khí (Nozzle)** là 2 linh kiện khác nhau:\n\n"
            "**Béc hàn (Tip)** — mã dạng 002xxx\n"
            "- Hình trụ nhỏ, lỗ tâm dẫn dây hàn\n"
            "- Tiếp xúc trực tiếp với dây hàn → truyền điện\n"
            "- Bằng đồng/đồng hợp kim\n"
            "- Thay thường xuyên nhất (mòn theo dây hàn)\n\n"
            "**Chụp khí (Nozzle)** — mã dạng 001xxx\n"
            "- Hình ống lớn hơn, bao ngoài đầu súng\n"
            "- Định hướng khí bảo vệ xung quanh vùng hàn\n"
            "- Bằng đồng hoặc thép mạ\n"
            "- Thay khi bám xỉ nhiều hoặc biến dạng\n\n"
            "Anh/chị cần tư vấn loại nào cụ thể không ạ? 😊"
        ),
    },
    # Hệ N vs hệ D
    {
        "keys": ["hệ n", "he n", "hệ d", "he d", "panasonic", "yaskawa", "daihen", "otc",
                 "giống", "khác", "phân biệt", "phan biet", "tương thích", "tuong thich"],
        "require_any": [["hệ n", "he n", "panasonic", "yaskawa"], ["hệ d", "he d", "daihen", "otc"]],
        "answer": (
            "**Hệ N** và **Hệ D** là 2 chuẩn linh kiện KHÔNG tương thích nhau:\n\n"
            "**Hệ N** (Panasonic/Yaskawa/Motoman)\n"
            "- Ren kiểu N-type\n"
            "- Súng: TK-308RR, YMSA, CSH, A-350R...\n"
            "- Mã linh kiện Tokinarc bắt đầu: 001-004xxx\n\n"
            "**Hệ D** (Daihen/OTC)\n"
            "- Ren kiểu D-type (khác hoàn toàn với hệ N)\n"
            "- Súng: D-350R, D-500R...\n"
            "- Mã linh kiện Tokinarc bắt đầu: 023xxx\n\n"
            "⚠️ Linh kiện hệ N **không lắp được** vào súng hệ D và ngược lại.\n\n"
            "Anh/chị đang dùng hệ nào để em tư vấn đúng ạ?"
        ),
    },
    # Scenario E: Hàn nhôm — cần béc đặc biệt
    {
        "keys": ["nhôm", "nhom", "aluminum", "aluminium", "al", "hàn nhôm", "han nhom"],
        "require_any": [["nhôm", "nhom", "aluminum", "aluminium", "al"]],
        "answer": (
            "**Hàn nhôm** cần béc hàn khác so với hàn thép:\n\n"
            "✅ **002019** — Béc hàn N nhôm 1.2mm — **31,000đ**\n"
            "✅ **002023** — Béc hàn N nhôm 0.8mm — **28,000đ**\n"
            "✅ **002024** — Béc hàn N nhôm 1.0mm — **28,000đ**\n\n"
            "**Lý do khác:**\n"
            "- Lỗ béc lớn hơn: nhôm mềm, dây dễ mòn và kẹt nếu lỗ nhỏ\n"
            "- Vật liệu Cu tinh khiết (không CuCrZr) — bám xỉ nhôm ít hơn\n"
            "- Quy trình: MIG nhôm dùng khí Ar hoặc Ar/He\n\n"
            "⚠️ KHÔNG dùng béc thép thường cho nhôm — kẹt dây, hỏng béc nhanh\n\n"
            "Anh/chị hàn dây nhôm cỡ mấy mm để em tư vấn đúng ạ?"
        ),
    },
    # Scenario E: Bảng chọn béc theo cỡ dây
    {
        "keys": ["cỡ dây", "co day", "dây mấy", "day may", "bảng chọn", "bang chon",
                 "wire size", "chọn béc", "chon bec", "béc mấy", "bec may"],
        "require_any": [["cỡ dây", "co day", "dây mấy", "day may", "bảng", "bang chon",
                         "chọn béc", "chon bec", "wire size"]],
        "answer": (
            "**Bảng chọn béc hàn theo cỡ dây (hệ N):**\n\n"
            "| Cỡ dây | Mã Tokinarc | Giá |\n"
            "|--------|-------------|-----|\n"
            "| 0.6mm  | **002016**  | 18,000đ |\n"
            "| 0.8mm  | **002005**  | 18,000đ |\n"
            "| 0.9mm  | **002001** ✅ phổ biến | 18,000đ |\n"
            "| 1.0mm  | **002002**  | 18,000đ |\n"
            "| 1.2mm  | **002003** ✅ phổ biến nhất | 20,000đ |\n"
            "| 1.4mm  | **002017**  | 22,000đ |\n"
            "| 1.6mm  | **002004**  | 24,000đ |\n\n"
            "Hệ D → mã 023xxx (023001 = 0.9mm, 023010 = 1.2mm, 023011 = 1.6mm)\n\n"
            "Anh/chị đang dùng hệ nào và dây cỡ mấy mm ạ?"
        ),
    },
    # Scenario G: Duty cycle — khi nào cần WX water-cooled
    {
        "keys": ["duty cycle", "hàn liên tục", "han lien tuc", "water cool", "làm mát",
                 "lam mat nuoc", "wx", "8h", "ca ngày", "ca ngay", "nước", "nuoc"],
        "require_any": [["duty cycle", "hàn liên tục", "han lien tuc", "water cool",
                         "làm mát nước", "lam mat nuoc", "8h", "ca ngày", "ca ngay"]],
        "answer": (
            "**Duty cycle và khi nào cần súng water-cooled:**\n\n"
            "**Súng air-cooled (thông thường):**\n"
            "- ACC-308RR: 350A / **60% duty** — hàn ≤6 phút/10 phút OK\n"
            "- TK-308RR: 350A / **60% duty**\n"
            "- Phù hợp: hàn gián đoạn, robot standard, xưởng thông thường\n\n"
            "**Súng water-cooled (WX) — cần khi:**\n"
            "- Duty cycle >80% (hàn liên tục >8 phút/10 phút)\n"
            "- Robot hàn liên tục 8h/ca\n"
            "- Dòng điện >400A liên tục\n"
            "- WX500R: 500A / **100% duty** — phù hợp ca liên tục\n\n"
            "Anh/chị đang hàn robot hay cầm tay? Hàn bao lâu liên tục ạ?"
        ),
    },
    # Scenario G: Chọn nozzle diameter
    {
        "keys": ["13mm", "16mm", "19mm", "đường kính chụp", "duong kinh chup",
                 "nozzle diameter", "chụp mấy mm", "chup may mm", "nozzle nào", "nozzle nao"],
        "require_any": [["13mm", "16mm", "19mm", "đường kính", "duong kinh",
                         "chụp mấy", "chup may", "nozzle nào"]],
        "answer": (
            "**Chọn đường kính chụp khí theo ứng dụng:**\n\n"
            "**∅13mm** — 001005 (85,000đ)\n"
            "- Coverage hẹp, tập trung\n"
            "- Tốt cho: hàn góc kín, robot, vị trí khó tiếp cận\n\n"
            "**∅16mm** — 001002 (65,000đ) ✅ phổ biến nhất\n"
            "- Cân bằng coverage và tiếp cận\n"
            "- Phù hợp: hầu hết ứng dụng robot và cầm tay\n\n"
            "**∅19mm** — 001001 (95,000đ)\n"
            "- Coverage rộng nhất, bảo vệ khí tốt nhất\n"
            "- Tốt cho: hàn mối dài, vật liệu dày, CO2 lưu lượng cao\n\n"
            "Lưu lượng khí khuyến nghị: **15–20 L/min** (CO2) / **12–18 L/min** (MAG)\n\n"
            "Anh/chị hàn robot hay cầm tay? Góc hàn hay phẳng ạ?"
        ),
    },
    # Liner là gì
    {
        "keys": ["liner", "lót dây", "lot day", "lõi", "loi", "ống dẫn", "ong dan"],
        "require_any": [["liner", "lót dây", "lot day", "lõi", "ong lot", "loi day"]],
        "answer": (
            "**Liner** (lõi dẫn dây hàn) là ống lò xo bên trong cáp súng hàn:\n\n"
            "- Dẫn dây hàn từ hộp cấp dây đến béc hàn\n"
            "- Thay khi dây hàn bị kẹt, cấp không đều, hoặc liner bị cong/mòn\n"
            "- Chọn đúng cỡ liner theo cỡ dây: 0.8-1.0mm / 1.2-1.6mm\n"
            "- Chọn đúng chiều dài theo cáp súng\n\n"
            "Anh/chị cần liner cho súng nào và dây cỡ bao nhiêu mm ạ?"
        ),
    },
    # Vật tư tiêu hao là gì
    {
        "keys": ["vật tư tiêu hao", "vat tu tieu hao", "consumable", "tiêu hao", "tieu hao",
                 "bộ vật tư", "bo vat tu", "bộ linh kiện", "bo linh kien"],
        "require_any": [["tiêu hao", "tieu hao", "consumable", "vật tư", "vat tu"]],
        "answer": (
            "**Vật tư tiêu hao** (consumables) là các linh kiện mòn theo thời gian hàn, cần thay định kỳ:\n\n"
            "✅ **Béc hàn (Tip)** — thay thường xuyên nhất, mòn theo dây\n"
            "✅ **Chụp khí (Nozzle)** — thay khi bám xỉ hoặc biến dạng\n"
            "✅ **Cách điện (Insulator)** — thay khi nứt hoặc bị cháy\n"
            "✅ **Sứ chia khí (Orifice)** — thay khi tắc hoặc nứt\n"
            "✅ **Thân giữ béc (TipBody)** — thay khi ren mòn\n"
            "🔵 **Liner** — thay khi dây kẹt\n\n"
            "Anh/chị cần bộ vật tư cho súng nào (hệ N/D, dòng điện 350A/500A) ạ?"
        ),
    },
    # TipBody là gì
    {
        "keys": ["thân giữ béc", "than giu bec", "tipbody", "tip body", "cổ béc", "co bec"],
        "require_any": [["thân giữ", "than giu", "tipbody", "tip body", "cổ béc"]],
        "answer": (
            "**Thân giữ béc (TipBody / Tip Adapter)** là bộ phận nối giữa súng hàn và béc hàn:\n\n"
            "- Giữ béc hàn và cách điện đúng vị trí\n"
            "- Truyền điện từ súng đến béc hàn\n"
            "- Thay khi ren mòn hoặc tiếp xúc điện kém (hồ quang không ổn)\n"
            "- Lực siết: **8 N·m** (không siết quá tay)\n\n"
            "Anh/chị cần thân giữ béc cho súng nào ạ?"
        ),
    },
    # Nozzle Cleaners / Peripheral (TKS, TKN, TKC, TKP)
    {
        "keys": ["tks", "tkn", "tkc", "tkp", "nozzle cleaner", "vệ sinh chụp",
                 "ve sinh chup", "anti spatter", "chống bắn tóe", "chong ban toe",
                 "wire cutter", "cắt dây", "cat day"],
        "require_any": [["tks", "tkn", "tkc", "tkp", "nozzle cleaner",
                         "vệ sinh chụp", "anti spatter", "wire cutter",
                         "cắt dây", "chống bắn"]],
        "allow_with_numbers": True,
        "answer": (
            "Dạ, đây là dòng **thiết bị ngoại vi robot hàn** của Tokinarc ạ:\n\n"
            "**Nozzle Cleaner Station:**\n"
            "- **046301** TKS-RC: Direct Command Type\n"
            "- **046302** TKS-RS: Proximity Sensor Type\n"
            "- **046311/312/313** TKS-Z1/Z2/Z3: Standard Station (nozzle cleaner + wire cutter + sprayer)\n\n"
            "**Linh kiện rời:**\n"
            "- **046200** TKN-A1: Nozzle Cleaner (khí nén)\n"
            "- **046250/046256** TKC-A2/B1: Wire Cutter\n"
            "- **046260** TKP-A1: Anti-Spatter Sprayer\n"
            "- **046113/046114** Nozzle Coat 18L/2L\n"
            "- **046703** Handy Tip Changer\n\n"
            "Anh/chị cần mã nào để em tra giá cụ thể ạ? 😊"
        ),
    },
    # Fume Extractors (WF series)
    {
        "keys": ["wf-", "fume", "hút khói", "hut khoi", "lọc khói", "loc khoi",
                 "máy hút khói", "may hut khoi", "fume extractor"],
        "require_any": [["wf-", "fume", "hút khói", "hut khoi",
                         "lọc khói", "loc khoi", "fume extractor"]],
        "allow_with_numbers": True,
        "answer": (
            "Dạ, **WF Series** là dòng **máy hút khói hàn** của Tokinarc ạ:\n\n"
            "- **046401** WF-120: 1000W, 200V, 30kg — compact\n"
            "- **046402** WF-130: 1000W, 3 phase, 80kg\n"
            "- **046403** WF-180: 1000W, 3 phase, brushless ~8000h, 80kg\n"
            "- **046404** WF-300: 0.75kW, 3 phase — high flow 8m³/min\n\n"
            "**Torch hút khói tích hợp:**\n"
            "- F-308RR: Robotic | WXF-500R: Water-cooled | CFL-20/35: Semi-auto\n\n"
            "Anh/chị cần mã nào để em tra báo giá ạ? 😊"
        ),
    },
    # Conduit / Flexible conduit
    {
        "keys": ["conduit", "ống dẫn dây", "ong dan day", "smart-glide", "smartglide",
                 "hpr conduit", "n-24", "d-24", "n-35", "d-35", "n-55",
                 "flexible conduit", "cáp dẫn", "cap dan"],
        "require_any": [["conduit", "ống dẫn", "ong dan", "smart-glide",
                         "n-24", "d-24", "n-35", "flexible conduit", "cap dan"]],
        "allow_with_numbers": True,
        "answer": (
            "Dạ, Tokinarc có các dòng **conduit dẫn dây hàn** ạ:\n\n"
            "**Roller-type (ma sát thấp nhất):**\n"
            "- **047001** Smart-Glide: hệ số ma sát 0.0495, dây 0.9–1.6mm, tối đa 20m\n\n"
            "**Standard flexible conduit:**\n"
            "- N-24 / D-24: đến 5m | N-35 / D-35: đến 15m | N-55: đến 20m\n\n"
            "**HPR Flexible Conduit:** đến 100m, dùng được dây nhôm\n\n"
            "**Internal Replacement Type:** thay liner bên trong, tiết kiệm chi phí\n\n"
            "Anh/chị cần conduit cho hệ N hay D, chiều dài bao nhiêu m ạ?"
        ),
    },
    # Coolant Circulation (WR-100, WR-200TC)
    {
        "keys": ["wr-100", "wr-200", "coolant", "làm mát nước", "lam mat nuoc",
                 "chiller", "tuần hoàn nước", "tuan hoan nuoc", "bơm làm mát"],
        "require_any": [["wr-100", "wr-200", "coolant", "chiller",
                         "tuần hoàn nước", "tuan hoan nuoc", "bơm làm mát"]],
        "allow_with_numbers": True,
        "answer": (
            "Dạ, **WR Series** là **hệ thống tuần hoàn nước làm mát** cho súng WX ạ:\n\n"
            "**046500 — WR-100**\n"
            "- 200V single phase | 0.3MPa | 2.1–2.2 L/min | Tank 10L | 22kg\n\n"
            "**046501 — WR-200TC** (Thermo-chiller)\n"
            "- 200V single phase | 0.4MPa | Làm lạnh 1700/1900W\n"
            "- Tank ~5L | 45kg | Cài nhiệt độ 5–40°C (±0.1°C)\n\n"
            "Dùng kèm với súng WX500R, WX451, WX452, TK-308RW.\n"
            "Anh/chị cần mã nào để em tra báo giá ạ? 😊"
        ),
    },
    # YMHS Collision Sensor
    {
        "keys": ["ymhs", "collision sensor", "cảm biến va chạm", "cam bien va cham",
                 "shock sensor", "ymhs-308"],
        "require_any": [["ymhs", "collision sensor", "cảm biến va chạm",
                         "cam bien va cham", "shock sensor"]],
        "allow_with_numbers": True,
        "answer": (
            "Dạ, **YMHS** là **Collision Sensor cao cấp** của Tokinarc ạ:\n\n"
            "- Phát hiện va chạm từ mọi hướng → bảo vệ robot\n"
            "- Độ cứng cao + độ chính xác lặp lại cao → thay súng nhanh\n"
            "- Tương thích: ACC-308RR, TK-308RR, TK-508RR, SRCT-308R...\n\n"
            "**YMHS-308 Unit Assembly:**\n"
            "- **YMHS00001** (900g) — HP/MH robot Yaskawa | **YMHS00005** (620g) — MH6·∅30\n\n"
            "Anh/chị đang dùng robot model gì để em tư vấn đúng ạ?"
        ),
    },
    # TIG dòng sản phẩm overview
    {
        "keys": ["mã ta", "dòng ta", "dong ta", "ta series", "tig series",
                 "súng tig", "sung tig", "tig torch", "hàn tig", "han tig",
                 "tungsten", "vonfram", "tig là", "tig la"],
        "require_any": [["mã ta", "dòng ta", "dong ta", "ta series",
                         "súng tig", "sung tig", "hàn tig", "han tig",
                         "tungsten", "vonfram", "tig là", "tig la"]],
        "answer": (
            "Dạ, Tokinarc có dòng **súng hàn TIG** series TA/FX/FXS ạ:\n\n"
            "**Air-Cooled:** TA-9 (125A), TA-17 (150A), TA-24 (80A), TA-26 (200A), "
            "FXSA-150, FXSA-200\n"
            "**Water-Cooled:** TA-18 (350A), TA-24W (180A), TA-280 (280A), FX-25 (200A)\n"
            "**Robotic TIG:** TA-203CDA (200A), TA-303CDW (300A), TA-500CDW (500A)\n\n"
            "Anh/chị muốn xem thông số model nào cụ thể ạ? "
            "(Vi du: TA-24 thong so, TA-18 gia bao nhieu)"
        ),
    },
    # TA vs Tokin (TK/ACC) — TIG vs MIG/MAG
    {
        "keys": ["ta", "tokin", "tk", "acc", "khác", "khac", "giống", "giong",
                 "so sánh", "so sanh", "dòng ta", "dong ta", "mig", "mag", "tig",
                 "khác nhau", "khac nhau", "phân biệt", "phan biet",
                 "2 dòng", "hai dong", "2 loai", "hai loai"],
        "require_any": [["dòng ta", "dong ta", "sung ta", "súng ta",
                         "series ta", "ta series", "ta khac", "ta vs",
                         "ta voi tokin", "ta và tokin", "ta va tokin",
                         "2 dong", "2 dòng", "hai dong", "hai dòng",
                         "khac nhau the nao", "khác nhau thế nào",
                         "khac gi", "khác gì", "phan biet", "phân biệt",
                         "so sanh", "so sánh", "tig mig", "mig tig",
                         "tig va mig", "tig và mig"]],
        "answer": (
            "Dạ, **dòng TA** và **dòng TK/ACC** là 2 dòng súng hàn **hoàn toàn khác nhau** ạ:\n\n"
            "**Dòng TA — Súng hàn TIG:**\n"
            "- Quy trình: TIG (Tungsten Inert Gas) — hàn chính xác cao\n"
            "- Điện cực Tungsten không nóng chảy, que hàn phụ nếu cần\n"
            "- Khí bảo vệ: Argon 100% hoặc Ar/He\n"
            "- Linh kiện tiêu hao: Collet, Collet Body, Ceramic Nozzle, Back Cap, Tungsten Electrode\n"
            "- Model: TA-9 (125A), TA-17 (150A), TA-26 (200A), TA-18W (350A water-cooled)\n"
            "- Ứng dụng: hàn inox, nhôm, titan, mối hàn mỏng cần thẩm mỹ cao\n\n"
            "**Dòng TK/ACC — Súng hàn MIG/MAG:**\n"
            "- Quy trình: MIG/MAG — hàn năng suất cao, tự động hoá\n"
            "- Dây hàn kim loại nóng chảy liên tục qua béc\n"
            "- Khí bảo vệ: CO2 hoặc hỗn hợp Ar/CO2\n"
            "- Linh kiện tiêu hao: Tip (béc), Nozzle (chụp khí), Insulator, TipBody, Orifice, Liner\n"
            "- Model: TK-308RR (350A), ACC-308RR (350A), TK-508RR (500A)\n"
            "- Ứng dụng: hàn thép carbon, robot hàn công nghiệp, năng suất cao\n\n"
            "⚠️ Linh kiện 2 dòng **không hoán đổi được** — khác hoàn toàn về cơ học và điện.\n\n"
            "Anh/chị đang cần tư vấn dòng nào ạ?"
        ),
    },
]


def _try_explain(query: str, last_text: str = "") -> str:
    """Kiểm tra query có phải câu hỏi kiến thức chung không.
    Trả về str nếu match, None nếu không match.
    last_text: response text của turn trước (session context).
    """
    import re as _r
    q = (query or "").lower()

    # Follow-up pronoun + comparison → enrich query với context từ turn trước
    _FOLLOWUP_COMPARE = _r.compile(
        r"(2|hai|2 cái|hai cái)\s*(dòng|loại|cái|thứ|loai|dong)"
        r"|(khác nhau|phan biet|so sanh|phân biệt|so sánh|khac gi|khác gì)"
        r"|(này|nay|đó|do|chúng|chung)\s*(khác|giống|so sánh|thế nào|the nao)",
        _r.I | _r.UNICODE,
    )
    if _FOLLOWUP_COMPARE.search(q) and last_text:
        lt = last_text.lower()
        # Nếu turn trước nhắc đến TA/TIG/MIG → inject context
        if any(k in lt for k in ["dòng ta", "dong ta", "tig", "ta-9", "ta-17", "ta-18",
                                   "fxsa", "fx-25", "ta-26", "ta-24"]):
            if any(k in lt for k in ["mig", "mag", "tk-308", "acc-308", "csh-", "csl-",
                                      "dòng tk", "dong tk"]):
                # Cả TA lẫn TK/ACC được nhắc → rõ ràng là so sánh 2 dòng
                q = q + " dòng ta so sánh mig mag"
            else:
                q = q + " dòng ta"
    # Guard: 6-digit part code / wire mm / amperage → đi DB
    _is_spec = (
        bool(_r.search(r"[0-9]{6}", q)) or
        bool(_r.search(r"[0-9]+[.][0-9]+ *mm", q)) or
        bool(_r.search(r"[0-9]{3,4}[aA]", q))
    )
    for entry in _EXPLAIN_KB:
        # Skip nếu có spec số VÀ entry không allow
        if _is_spec and not entry.get("allow_with_numbers", False):
            continue
        matched_any = False
        for group in entry.get("require_any", [[]]):
            if any(kw in q for kw in group):
                matched_any = True
                break
        if not matched_any:
            continue
        matched_keys = sum(1 for kw in entry["keys"] if kw in q)
        if matched_keys >= 1:
            return entry["answer"]
    return None


def _template_format(intent: str, query: str, ds_result: dict) -> str:  # noqa: C901
    data   = ds_result.get("data")
    reason = ds_result.get("reason", "")

    if not ds_result["success"]:
        clarify_map = {
            "NO_MATCH":                    "Không tìm thấy linh kiện phù hợp. Bạn có thể cho biết mã hàng hoặc mô tả chi tiết hơn không ạ?",
            "NO_CONSUMABLE_SET_FOUND":     "Bạn cần bộ vật tư cho hệ nào và dòng điện bao nhiêu A? (Ví dụ: N 350A, D 500A)",
            "INSUFFICIENT_ENTITIES":       "Bạn có thể cho biết mã cụ thể hoặc mô tả chi tiết hơn không ạ?",
            "CANNOT_DETERMINE_TARGET_SET": "Bạn đang dùng linh kiện hệ N hay hệ D? Và dòng điện 350A hay 500A?",
            "NO_RESULTS":                  "Không tìm thấy kết quả phù hợp. Thử mô tả khác xem sao ạ?",
            "OUT_OF_SCOPE":                "Xin chào! Bạn cần tư vấn linh kiện hàn Tokinarc gì ạ?",
        }
        for k, msg in clarify_map.items():
            if k in reason:
                return msg
        return "Không tìm được thông tin. Bạn có thể cung cấp thêm chi tiết không ạ?"

    # ── LOOKUP ────────────────────────────────────────────────────────────────
    if intent == "LOOKUP":
        if isinstance(data, dict):
            biz      = data.get("business", {}) or {}
            brand    = data.get("_brand", "")
            resolved = data.get("_resolved_from", "")
            category = data.get("category", "")
            lines = []

            # FIX 1: Detect khi user dùng sai tên linh kiện
            _CAT_VI = {
                "Tip": ["béc", "bec", "tip"],
                "Nozzle": ["chụp", "chup", "nozzle"],
                "Insulator": ["cách điện", "cach dien", "insulator"],
                "TipBody": ["thân", "than", "tipbody"],
                "Liner": ["liner"],
                "Orifice": ["sứ", "su", "orifice"],
            }
            _CAT_VI_NAME = {
                "Tip": "Béc hàn (Contact tip)",
                "Nozzle": "Chụp khí (Nozzle)",
                "Insulator": "Cách điện (Insulator)",
                "TipBody": "Thân giữ béc (Tip body)",
                "Liner": "Liner",
                "Orifice": "Sứ chia khí (Orifice)",
            }
            _q_lower = (query or "").lower()
            _user_cat = None
            for cat, kws in _CAT_VI.items():
                if any(kw in _q_lower for kw in kws):
                    _user_cat = cat
                    break
            if _user_cat and category and _user_cat != category:
                lines.append(
                    f"⚠️ Lưu ý: mã **{data.get('tokin_part_no','')}** là "
                    f"**{_CAT_VI_NAME.get(category, category)}** "
                    f"(không phải {_CAT_VI_NAME.get(_user_cat, _user_cat)}) ạ.\n"
                )

            if brand and resolved:
                lines.append(f"Dạ, mã **{resolved}** là sản phẩm của **{brand}** — "
                             f"bên em có sản phẩm Tokin tương đương chất lượng Nhật Bản ạ:\n")
            pno  = data.get("tokin_part_no", "")
            name = data.get("display_name_vi") or data.get("display_name_en", "")
            cat  = data.get("category", "")
            lines.append(f"**{pno}** — {name}")

            # Cross-brand note
            if brand and resolved:
                lines.append(f"- Tương đương {brand}: {resolved}")

            # ── Core specs — luôn show ──────────────────────────────────────
            _ECO_FULL = {"N": "N — Panasonic/Yaskawa", "D": "D — Daihen/OTC",
                         "WX": "WX — Water-cooled", "TIG": "TIG", "UNIVERSAL": "Universal"}
            eco_str = _ECO_FULL.get((data.get("ecosystem") or "").upper(), data.get("ecosystem", ""))
            if eco_str:             lines.append(f"- Hệ: {eco_str}")
            if data.get("current_class"): lines.append(f"- Dòng điện: {data['current_class']}")

            # ── Category-specific technical specs ───────────────────────────
            if cat == "Tip":
                if data.get("wire_size_mm"):   lines.append(f"- Cỡ lỗ dây: ∅{data['wire_size_mm']}mm")
                if data.get("total_length_mm"):lines.append(f"- Chiều dài: {data['total_length_mm']}mm tổng" +
                    (f" / {data['body_length_mm']}mm thân" if data.get("body_length_mm") else ""))
                if data.get("thread_type"):    lines.append(f"- Ren: {data['thread_type']}")
                if data.get("material"):       lines.append(f"- Vật liệu: {data['material']}")
                if data.get("supported_processes"):
                    lines.append(f"- Quy trình: {', '.join(data['supported_processes'])}")

            elif cat == "Nozzle":
                if data.get("inner_dia_mm"):   lines.append(f"- Đường kính trong: ∅{data['inner_dia_mm']}mm")
                if data.get("outer_dia_mm"):   lines.append(f"- Đường kính ngoài: ∅{data['outer_dia_mm']}mm")
                if data.get("length_mm"):      lines.append(f"- Chiều dài: {data['length_mm']}mm")
                if data.get("thread_spec"):    lines.append(f"- Lắp ráp: {data['thread_spec']}")
                if data.get("nozzle_type"):    lines.append(f"- Loại: {data['nozzle_type']}")

            elif cat == "Insulator":
                if data.get("length_mm"):      lines.append(f"- Chiều dài: {data['length_mm']}mm")
                if data.get("inner_dia_mm"):   lines.append(f"- ∅ trong: {data['inner_dia_mm']}mm")
                if data.get("outer_dia_mm"):   lines.append(f"- ∅ ngoài: {data['outer_dia_mm']}mm")
                if data.get("insulator_class"):lines.append(f"- Class: {data['insulator_class']}")

            elif cat == "TipBody":
                if data.get("length_mm"):      lines.append(f"- Chiều dài: {data['length_mm']}mm")
                if data.get("tip_body_type"):  lines.append(f"- Type: {data['tip_body_type']}")
                if data.get("note"):           lines.append(f"- Ghi chú: {(data['note'])[:120]}")

            elif cat in ("Liner", "InnerTube"):
                wr = data.get("wire_size_range", {})
                if wr: lines.append(f"- Cỡ dây: {wr.get('min','?')}–{wr.get('max','?')}mm")
                elif data.get("wire_size_mm"): lines.append(f"- Cỡ dây: ∅{data['wire_size_mm']}mm")
                if data.get("liner_length_mm"): lines.append(f"- Chiều dài liner: {data['liner_length_mm']}mm")
                elif data.get("total_length_mm"): lines.append(f"- Chiều dài: {data['total_length_mm']}mm")
                if data.get("robot_model"):    lines.append(f"- Robot: {data['robot_model']}")
                if data.get("cable_length_m"): lines.append(f"- Cáp súng: {data['cable_length_m']}m")
                if data.get("liner_material"): lines.append(f"- Vật liệu: {data['liner_material']}")
                if data.get("note"):           lines.append(f"- Ghi chú: {(data['note'])[:120]}")

            elif cat == "Orifice":
                if data.get("length_mm"):      lines.append(f"- Chiều dài: {data['length_mm']}mm")
                if data.get("note"):           lines.append(f"- Ghi chú: {(data['note'])[:80]}")

            else:
                # Generic: wire_size + length nếu có
                if data.get("wire_size_mm"):   lines.append(f"- Cỡ dây: {data['wire_size_mm']}mm")
                if data.get("total_length_mm"):lines.append(f"- Chiều dài: {data['total_length_mm']}mm")
                if data.get("note"):           lines.append(f"- Ghi chú: {(data['note'])[:120]}")

            # ── Giá ────────────────────────────────────────────────────────
            if biz.get("is_contact_price"):
                lines.append("- Giá: Vui lòng liên hệ để báo giá")
            elif biz.get("price_vnd"):
                price_note = f" _{biz['price_note']}_" if biz.get("price_note") else ""
                lines.append(f"- Giá: **{biz['price_vnd']:,}đ**/{biz.get('price_unit','cái')}{price_note}")

            # ── Cross-brand codes ──────────────────────────────────────────
            if data.get("p_part_nos") and not (brand and resolved):
                lines.append(f"- Mã Panasonic: {', '.join(data['p_part_nos'][:3])}")
            if data.get("d_part_nos") and not (brand and resolved):
                lines.append(f"- Mã Daihen/OTC: {', '.join(data['d_part_nos'][:3])}")

            # ── Compatible torches (nếu hỏi về part) ──────────────────────
            torch_models = data.get("torch_models", [])
            if torch_models and len(torch_models) <= 6:
                lines.append(f"- Dùng với súng: {', '.join(torch_models)}")
            elif torch_models:
                lines.append(f"- Dùng với súng: {', '.join(torch_models[:5])} ... (+{len(torch_models)-5})")

            # ── CTA ────────────────────────────────────────────────────────
            if brand and resolved:
                lines.append("\nAnh/chị cần báo giá hoặc đặt hàng số lượng bao nhiêu ạ? 😊")
            else:
                lines.append("\nAnh/chị cần báo giá SL bao nhiêu, hoặc tư vấn linh kiện đi kèm ạ? 😊")
            return "\n".join(lines)

        # Torch lookup — torch dict không có tokin_part_no, detect bằng model_code
        if isinstance(data, dict) and (data.get("_type") == "torch" or
           (data.get("model_code") and not data.get("tokin_part_no"))):
            t = data
            biz = t.get("business", {}) or {}
            _ECO_TORCH = {"N": "hệ N (Panasonic/Yaskawa)", "D": "hệ D (Daihen/OTC)",
                          "WX": "hệ WX (water-cooled)", "TIG": "TIG"}
            eco_str = _ECO_TORCH.get((t.get("ecosystem") or "").upper(), t.get("ecosystem",""))
            is_robot = bool(t.get("robot_compatibility") or t.get("has_shock_sensor"))

            lines = [f"**{t.get('model_code','')}** — {t.get('display_name_vi') or t.get('display_name_en','')}"]
            if is_robot:
                lines.append("🤖 _Súng hàn dành cho robot_")

            # ── Electrical specs ───────────────────────────────────────────
            if eco_str:                lines.append(f"- Hệ: {eco_str}")
            if t.get("current_class"): lines.append(f"- Dòng điện max: {t['current_class']}")
            if t.get("rated_co2_a"):   lines.append(f"- Định mức CO₂: {t['rated_co2_a']}A")
            if t.get("rated_mag_a"):   lines.append(f"- Định mức MAG: {t['rated_mag_a']}A")
            if t.get("duty_cycle_pct"):lines.append(f"- Duty cycle: {t['duty_cycle_pct']}%")
            if t.get("wire_size"):     lines.append(f"- Cỡ dây: {t['wire_size']}")

            # ── Mechanical specs ───────────────────────────────────────────
            if t.get("cooling"):       lines.append(f"- Làm mát: {t['cooling']}")
            if t.get("body_type"):     lines.append(f"- Thân súng: {t['body_type']}")
            if t.get("angle_deg"):     lines.append(f"- Góc đầu súng: {t['angle_deg']}°")

            # Dimensions nếu có
            dim_parts = []
            if t.get("dim_x_mm"):
                tol_x = f"±{t['dim_x_tol']}" if t.get("dim_x_tol") else ""
                dim_parts.append(f"X={t['dim_x_mm']}{tol_x}mm")
            if t.get("dim_y_mm"):
                tol_y = f"±{t['dim_y_tol']}" if t.get("dim_y_tol") else ""
                dim_parts.append(f"Y={t['dim_y_mm']}{tol_y}mm")
            if dim_parts:
                lines.append(f"- Kích thước: {' · '.join(dim_parts)}")

            # ── Robot specs ────────────────────────────────────────────────
            if t.get("mounting"):      lines.append(f"- Mounting: {t['mounting']}")
            robot_compat = t.get("robot_compatibility") or []
            if robot_compat:
                lines.append(f"- Robot tương thích: {', '.join(robot_compat)}")
            robot_series = t.get("robot_series") or []
            if robot_series:
                lines.append(f"- Robot series: {', '.join(robot_series)}")
            shock = t.get("shock_sensor_type", "NONE")
            if shock and shock != "NONE":
                lines.append(f"- Shock sensor: {shock} ✅")
            elif is_robot:
                lines.append("- Shock sensor: Không có")

            # ── Connection types ───────────────────────────────────────────
            conn = ", ".join(t.get("connection_types") or [])
            if conn: lines.append(f"- Kết nối: {conn}")

            # ── Note ───────────────────────────────────────────────────────
            if t.get("note"):          lines.append(f"- Ghi chú: {t['note']}")

            # ── Giá ────────────────────────────────────────────────────────
            if biz.get("is_contact_price"):
                lines.append("- Giá: Vui lòng liên hệ để báo giá")
            elif biz.get("price_vnd"):
                lines.append(f"- Giá: **{biz['price_vnd']:,}đ**/{biz.get('price_unit','cái')}")

            # ── Vật tư tiêu hao ────────────────────────────────────────────
            cp = t.get("compatible_parts", [])
            if cp:
                lines.append(f"- Linh kiện tiêu hao: {', '.join(cp[:6])}" +
                             (f" ... (+{len(cp)-6})" if len(cp) > 6 else ""))

            cta = "Anh/chị cần báo giá hoặc tư vấn vật tư tiêu hao đi kèm không ạ? 😊"
            if is_robot:
                cta = "Anh/chị cần tư vấn vật tư tiêu hao hoặc thông tin lắp ráp robot không ạ? 😊"
            lines.append(f"\n{cta}")
            return "\n".join(lines)

        if isinstance(data, list):
            lines = ["Các sản phẩm phù hợp:"]
            for p in data[:8]:
                biz = p.get("business", {}) or {}
                price_str = f" — **{biz['price_vnd']:,}đ**" if biz.get("price_vnd") else ""
                ws_str = f" {p.get('wire_size_mm','')}mm" if p.get("wire_size_mm") else ""
                lines.append(f"- **{p.get('tokin_part_no','')}** {p.get('display_name_vi','')}{ws_str}{price_str}")
            return "\n".join(lines)

    # ── CONSUMABLE_SET ────────────────────────────────────────────────────────
    if intent == "CONSUMABLE_SET":
        if isinstance(data, dict):
            eco = data.get("ecosystem", data.get("eco", ""))
            cc  = data.get("torch_current_class", data.get("cc", ""))
            torch_model = data.get("torch_model", "")

            header = f"Bộ vật tư tiêu hao"
            if torch_model:
                header += f" **{torch_model}**"
            elif eco or cc:
                header += f" {eco} {cc}".strip()
            header += ":"
            if data.get("_eco_inferred"):
                header += " (tự động nhận diện hệ)"
            lines = [header, ""]

            # Group theo role, mandatory trước, cap optional mỗi role
            # Dùng module-level _ROLE_VI và _ROLE_ORDER
            _WX_SKIP = {"WXNozzleSleeve", "WXCoverRubber", "WXCenterCeramic", "TipAdapter"}

            # Group
            by_role: dict = {}
            for item in (data.get("items") or []):
                role = item.get("part_role") or item.get("category") or "Other"
                if role in _WX_SKIP:
                    continue
                # Bỏ WX parts khi eco là N hoặc D
                item_eco = (item.get("ecosystem") or "").upper()
                if item_eco == "WX" and (eco or "").upper() in ("N", "D"):
                    continue
                by_role.setdefault(role, []).append(item)

            # Render mỗi role: mandatory trước, max 2 optional
            _MAX_OPTIONAL = 2
            has_content = False
            for role in _ROLE_ORDER + [r for r in by_role if r not in _ROLE_ORDER]:
                items = by_role.get(role)
                if not items:
                    continue
                has_content = True
                mandatory = [i for i in items if i.get("is_mandatory")]
                optional  = [i for i in items if not i.get("is_mandatory")]

                lines.append(f"**{_ROLE_VI.get(role, role)}**")
                for i in mandatory:
                    lines.append(f"  ✅ **{i.get('part_id','')}** — {i.get('display_name_vi','')}")
                shown_opt = 0
                for i in optional:
                    if shown_opt >= _MAX_OPTIONAL:
                        remaining = len(optional) - shown_opt
                        lines.append(f"  _(+{remaining} loại khác — hỏi để xem thêm)_")
                        break
                    lines.append(f"  🔵 **{i.get('part_id','')}** — {i.get('display_name_vi','')}")
                    shown_opt += 1
                lines.append("")

            if not has_content:
                lines.append("Không có thông tin vật tư. Bạn cho biết model súng cụ thể không ạ?")

            lines.append("Anh/chị cần báo giá hoặc thêm thông tin gì không ạ? 😊")
            return "\n".join(lines)

    # ── REPLACEMENT ── Scenario F: cross-brand expert ──────────────────────────
    if intent == "REPLACEMENT":
        if isinstance(data, dict):
            p     = data.get("part_info", {})
            brand = data.get("source_brand", "")
            src   = data.get("source_code", "")
            tokin = data.get("tokin_part_no", "")
            biz   = p.get("business", {}) or {}
            cat   = p.get("category", "")

            brand_vi = {"Panasonic": "Panasonic", "Daihen/OTC": "Daihen/OTC",
                        "OTC": "Daihen/OTC"}.get(brand, brand)
            lines = [
                f"Dạ, mã **{src}** là sản phẩm của **{brand_vi}** — "
                f"bên em có Tokin tương đương chất lượng Nhật Bản ạ:\n",
                f"**{tokin}** — {p.get('display_name_vi','')}",
            ]
            if p.get("ecosystem"):    lines.append(f"- Hệ: {p['ecosystem']}")
            if p.get("current_class"):lines.append(f"- Dòng điện: {p['current_class']}")

            # Spec theo category — Scenario F
            if cat == "Tip":
                if p.get("material"):        lines.append(f"- Vật liệu: **{p['material']}**")
                if p.get("total_length_mm"): lines.append(f"- Chiều dài: {p['total_length_mm']}mm")
                if p.get("thread_type"):     lines.append(f"- Ren: {p['thread_type']}")
                if p.get("wire_size_mm"):    lines.append(f"- Cỡ dây: {p['wire_size_mm']}mm")
            elif cat == "Nozzle":
                if p.get("inner_dia_mm"):    lines.append(f"- ID: ∅{p['inner_dia_mm']}mm")
                if p.get("length_mm"):       lines.append(f"- Dài: {p['length_mm']}mm")

            # Cross-brand equivalents khác (Daihen nếu đang tra Pana, và ngược lại)
            other_brand_nos = []
            if brand in ("Panasonic",) and p.get("d_part_nos"):
                other_brand_nos = [(f"Daihen/OTC", p["d_part_nos"][:2])]
            elif brand in ("Daihen/OTC", "OTC") and p.get("p_part_nos"):
                other_brand_nos = [(f"Panasonic", p["p_part_nos"][:2])]
            for ob, nos in other_brand_nos:
                lines.append(f"- Tương đương {ob}: {', '.join(nos)}")

            if biz.get("is_contact_price"):
                lines.append("- Giá: Vui lòng liên hệ để báo giá")
            elif biz.get("price_vnd"):
                lines.append(f"- Giá: **{biz['price_vnd']:,}đ**/{biz.get('price_unit','cái')}")

            lines.append("\nCần báo giá số lượng bao nhiêu ạ? 😊")
            return "\n".join(lines)

    # ── UPSELL ────────────────────────────────────────────────────────────────
    if intent == "UPSELL":
        if isinstance(data, dict):
            owned   = data.get("owned", [])
            missing = data.get("missing", [])
            eco     = (data.get("ecosystem") or data.get("_anchor_eco") or "")
            anchor  = owned[0] if owned else ""

            intro = "Dạ, bên em là Nhà phân phối độc quyền vật tư Tokin Nhật Bản"
            intro += (f", cung cấp đầy đủ vật tư tiêu hao đi kèm với **{anchor}** như sau ạ:"
                      if anchor else ", cung cấp đầy đủ vật tư tiêu hao như sau ạ:")
            lines = [intro, ""]

            if not missing:
                lines.append("✅ Bộ vật tư đã đầy đủ rồi ạ!")
            else:
                by_role: dict = {}
                for m in missing:
                    role      = m.get("part_role", "") or m.get("category", "Other")
                    m_eco     = m.get("ecosystem", "")
                    name_low  = (m.get("display_name_vi") or "").lower()
                    if role in _SKIP_ROLES:
                        continue
                    is_wx = (m_eco == "WX" or any(k in name_low for k in _WX_KEYS)
                             or any(k in name_low for k in _WX_CAT_KEYS))
                    if is_wx and eco.upper() in ("N", "D"):
                        continue
                    if is_wx and not eco:
                        continue
                    by_role.setdefault(role or m.get("category", "Other"), []).append(m)

                for role, items in sorted(by_role.items(),
                    key=lambda x: _ROLE_ORDER.index(x[0]) if x[0] in _ROLE_ORDER else 99):
                    lines.append(f"**{_ROLE_VI.get(role, role)}**")
                    for m in items[:5]:
                        biz = m.get("business", {}) or {}
                        if biz.get("is_contact_price"):
                            price_str = " — Liên hệ báo giá"
                        elif biz.get("price_vnd"):
                            price_str = f" — **{biz['price_vnd']:,}đ**"
                        else:
                            price_str = ""
                        lines.append(f"- **{m.get('part_id','')}** — {m.get('display_name_vi','')}{price_str}")
                    lines.append("")

            # Vision condition advice
            _cond = data.get("_vision_condition","") or (
                plan.session_ctx.vision_condition
                if hasattr(plan, "session_ctx") and plan.session_ctx else ""
            ) if "plan" in dir() else ""
            if not _cond and "_vision_condition" in data:
                _cond = data["_vision_condition"]
            if _cond == "worn":
                lines.append("\n⚠️ Linh kiện trong ảnh có vẻ đã mòn — em khuyên thay cả bộ cùng lúc để tiết kiệm công ạ.")
            elif _cond == "damaged":
                lines.append("\n🔴 Linh kiện bị hỏng — nên kiểm tra thêm TipBody và cách điện cùng lúc ạ.")

            lines.append("Anh/chị cần báo giá hoặc thêm thông tin gì không ạ? 😊")
            return "\n".join(lines)

    # ── SEARCH_BY_DESC ────────────────────────────────────────────────────────
    if intent == "SEARCH_BY_DESC":
        if isinstance(data, list) and data:
            lines = ["Bên em có các sản phẩm phù hợp ạ:"]

            # Detect dominant category để qualify đúng
            _cats = [p.get("category","") for p in data[:8]]
            _cat_main = max(set(_cats), key=_cats.count) if _cats else ""
            _eco_set = set((p.get("ecosystem","") or "").upper() for p in data[:8] if p.get("ecosystem"))

            for p in data[:8]:
                biz = p.get("business", {}) or {}
                if biz.get("is_contact_price"):
                    price_str = " — Liên hệ báo giá"
                elif biz.get("price_vnd"):
                    price_str = f" — **{biz['price_vnd']:,}đ**"
                else:
                    price_str = ""
                # Thêm wire_size nếu là Tip
                ws_str = f" ∅{p['wire_size_mm']}mm" if p.get("wire_size_mm") and _cat_main == "Tip" else ""
                # Đánh dấu priority
                is_priority = (p.get("business", {}) or {}).get("is_priority_sell", False)
                star = " ✅" if is_priority and p == data[0] else ""
                lines.append(f"- **{p.get('tokin_part_no','')}** {p.get('display_name_vi','')}{ws_str}{price_str}{star}")

            # Proactive qualify — chỉ hỏi thông tin CHƯA biết
            _q_sd = (query or "").lower()
            _know_eco  = any(k in _q_sd for k in ["he n","hệ n","he d","hệ d","pana","daihen"])
            _know_wire = any(str(w).replace(".",",") in _q_sd or str(w) in _q_sd
                             for w in [0.9,1.0,1.2,1.4,1.6,2.0])
            _know_cc   = any(k in _q_sd for k in ["350","500","250","400"])
            if _cat_main == "Tip":
                if not _know_eco and not _know_wire:
                    qualify = "Anh/chị đang dùng súng hệ nào (N/D)? Dây hàn cỡ mấy mm? 😊"
                elif not _know_eco:
                    qualify = "Súng hệ N (Panasonic/Yaskawa) hay hệ D (Daihen/OTC) ạ? 😊"
                elif not _know_wire:
                    qualify = "Dây hàn cỡ mấy mm (0.9/1.0/1.2/1.4/1.6mm)? 😊"
                elif not _know_cc:
                    qualify = "Súng 350A hay 500A? Robot hay cầm tay ạ? 😊"
                else:
                    qualify = "Anh/chị cần loại nào để em báo giá chi tiết ạ? 😊"
            elif _cat_main == "Nozzle":
                qualify = ("Cần đường kính trong 13mm, 16mm hay 19mm ạ? 😊" if _know_eco
                           else "Súng hệ N hay D? Cần đường kính 13/16/19mm? 😊")
            elif _cat_main == "Insulator":
                qualify = ("Súng 350A (Type S) hay 500A (Type L) ạ? 😊" if _know_eco
                           else "Hệ N hay D? Súng 350A hay 500A? 😊")
            elif _cat_main == "TipBody":
                qualify = "Model súng của anh/chị là gì? Em chọn đúng TipBody ạ 😊"
            elif _cat_main == "Liner":
                qualify = "Cỡ dây hàn mấy mm? Cáp súng dài bao nhiêu mét? 😊"
            else:
                qualify = "Anh/chị cần loại nào để em báo giá chi tiết ạ? 😊"
            lines.append(f"\n{qualify}")
            return "\n".join(lines)

    # ── COMPATIBILITY_CHECK ───────────────────────────────────────────────────
    if intent == "COMPATIBILITY_CHECK":
        # Detect cross-ecosystem từ query trước khi cần data
        import re as _re_cc
        _q_cc = (query or "").lower()
        _eco_kw = {
            "N": ["he n", "hệ n", "pana", "yaskawa", "panasonic"],
            "D": ["he d", "hệ d", "daihen", "otc"],
            "WX": ["wx", "water", "lam mat nuoc", "làm mát nước"],
        }
        _found_ecos = []
        for _eco, _kws in _eco_kw.items():
            if any(k in _q_cc for k in _kws):
                _found_ecos.append(_eco)
        if len(_found_ecos) >= 2:
            # Cross-ecosystem query → không tương thích luôn
            _ECO_FULL2 = {"N": "hệ N (Panasonic/Yaskawa)", "D": "hệ D (Daihen/OTC)",
                          "WX": "hệ WX (water-cooled)"}
            _ea, _eb = _found_ecos[0], _found_ecos[1]
            _lines_cc = [
                "\u274c **Kh\u00f4ng t\u01b0\u01a1ng th\u00edch** \u2014 " + _ECO_FULL2.get(_ea,_ea) + " v\u00e0 " + _ECO_FULL2.get(_eb,_eb) + " kh\u00e1c nhau ho\u00e0n to\u00e0n.",
                "L\u00fd do k\u1ef9 thu\u1eadt: thread geometry, ren v\u00e0 k\u00edch th\u01b0\u1edbc l\u1eafp r\u00e1p kh\u00e1c nhau gi\u1eefa 2 h\u1ec7.",
                "\u2192 L\u1eafp ch\u00e9o h\u1ec7 g\u00e2y: r\u00f2 kh\u00ed b\u1ea3o v\u1ec7, h\u1ed3 quang kh\u00f4ng \u1ed5n \u0111\u1ecbnh.",
                "",
                "Anh/ch\u1ecb c\u1ea7n linh ki\u1ec7n h\u1ec7 " + _ea + " hay h\u1ec7 " + _eb + "? Em t\u01b0 v\u1ea5n \u0111\u00fang lo\u1ea1i ngay \u1ea1 \U0001f60a",
            ]
            return "\n".join(_lines_cc)

        if isinstance(data, dict):
            compat     = data.get("compatible")
            reason_txt = data.get("reason", "")
            rule_id    = data.get("rule_id", "")
            eco_a      = data.get("eco_a", "")
            eco_b      = data.get("eco_b", "")
            parts_a    = data.get("parts_a", [])
            parts_b    = data.get("parts_b", [])

            if compat is False:
                lines = [f"❌ **Không tương thích**"]
                if reason_txt:
                    lines.append(f"Lý do kỹ thuật: {reason_txt}")
                # Ecosystem mismatch hint
                if eco_a and eco_b and eco_a != eco_b:
                    _ECO_VI2 = {"N": "hệ N (Panasonic/Yaskawa)", "D": "hệ D (Daihen/OTC)",
                                "WX": "hệ WX (water-cooled)"}
                    lines.append(f"→ {_ECO_VI2.get(eco_a, eco_a)} và {_ECO_VI2.get(eco_b, eco_b)} không tương thích chéo.")
                    lines.append("→ Linh kiện khác hệ sẽ gây: rò khí, arc không ổn định, có thể hỏng súng.")
                    # Suggest đúng hệ
                    suggest_eco = eco_a or eco_b
                    if suggest_eco:
                        lines.append(f"\nAnh/chị cần linh kiện hệ {suggest_eco} — em tư vấn đúng loại ngay ạ 😊")
                else:
                    lines.append("\nAnh/chị cần thêm thông tin gì không ạ? 😊")
                return "\n".join(lines)

            if compat is True:
                lines = [f"✅ **Tương thích**"]
                if reason_txt:
                    lines.append(reason_txt)
                lines.append("\nAnh/chị cần báo giá hoặc tư vấn linh kiện bổ sung không ạ? 😊")
                return "\n".join(lines)

    # ── AGGREGATE — Scenario C: robot compat ─────────────────────────────────
    if intent == "AGGREGATE":
        if isinstance(data, dict):
            # Robot compatibility result
            if data.get("type") == "robot_compat":
                robot = data.get("robot_model", "")
                torches = data.get("torches", [])
                lines = [f"Súng hàn Tokinarc tương thích với **{robot}**:\n"]
                for t in torches:
                    eco_str = _ECO_VI.get((t.get("ecosystem") or "").upper(), "")
                    cc_str  = t.get("current_class", "")
                    sensor  = t.get("shock_sensor_type", "NONE")
                    mount   = t.get("mounting", "")
                    spec_parts = [eco_str, cc_str]
                    if sensor and sensor != "NONE": spec_parts.append(f"sensor: {sensor}")
                    if mount: spec_parts.append(f"mount: {mount}")
                    spec = " | ".join(filter(None, spec_parts))
                    biz = (t.get("business") or {})
                    price = f" — **{biz['price_vnd']:,}đ**" if biz.get("price_vnd") else ""
                    lines.append(f"✅ **{t.get('model_code','')}** — {t.get('display_name_vi') or t.get('model_code','')}{price}")
                    if spec: lines.append(f"   _{spec}_")
                lines.append("\nAnh/chị cần tư vấn vật tư tiêu hao đi kèm không ạ? 😊")
                return "\n".join(lines)

            if data.get("type") == "torch_list":
                torches = data.get("torches", [])
                cnt = data.get("count", len(torches))
                lines = [f"Bên em đang phân phối **{cnt} model súng hàn Tokinarc** ạ:", ""]
                for t in torches[:30]:
                    eco_t = _ECO_VI.get((t.get("ecosystem") or "").upper(), "")
                    cc_t  = t.get("current_class", "")
                    spec  = " | ".join(filter(None, [eco_t, cc_t]))
                    lines.append(f"- **{t.get('model_code','')}** — {t.get('display_name_vi') or t.get('model_code','')}" +
                                 (f" ({spec})" if spec else ""))
                lines.append("\nAnh/chị cần tư vấn súng hàn loại nào ạ? 😊")
                return "\n".join(lines)
            if "count" in data:
                cat = data.get("category") or data.get("ecosystem", "")
                cnt = data["count"]
                lines = [f"Tìm thấy **{cnt}** linh kiện loại {cat}:"]
                for p in (data.get("parts") or [])[:10]:
                    lines.append(f"- **{p.get('tokin_part_no','')}** {p.get('display_name_vi','')}")
                if cnt > 10:
                    lines.append(f"... và {cnt-10} mã khác")
                return "\n".join(lines)
            if "total_parts" in data:
                return (f"Database TOKINARC: **{data['total_parts']}** parts | "
                        f"**{data['total_torches']}** torches | "
                        f"**{data['total_consumable_sets']}** bộ vật tư")

    # ── COMPARISON ────────────────────────────────────────────────────────────
    if intent == "COMPARISON":
        if isinstance(data, dict) and "part" in data.get("type", ""):
            a = data.get("item_a", {})
            b = data.get("item_b", {})
            return (f"So sánh:\n"
                    f"- **{a.get('tokin_part_no','')}**: {a.get('display_name_vi','')} | Hệ {a.get('ecosystem','')}\n"
                    f"- **{b.get('tokin_part_no','')}**: {b.get('display_name_vi','')} | Hệ {b.get('ecosystem','')}")

    # ── INSTALLATION — Scenario B: ASCII diagram ─────────────────────────────
    if intent == "INSTALLATION":
        _ROLE_VI_INSTALL = {"Tip": "Béc hàn", "TipBody": "Thân giữ béc",
                            "Nozzle": "Chụp khí", "Insulator": "Cách điện",
                            "Orifice": "Sứ chia khí", "Liner": "Liner"}

        # ASCII assembly diagram — luôn show khi INSTALLATION
        _q_low = (query or "").lower()
        _DIAGRAM_N = """
Thứ tự lắp đầu súng hệ N (từ trong ra ngoài):

  [ THÂN SÚNG ]
       │
  [ LINER ]          ← 016076 (N 350A) / 016077 (N 500A)
       │
  [ TipBody ]        ← 036001 (350A) / 036003 (500A)
    ├── [ Insulator ] ← 004002 (350A) / 004001 (500A)
    ├── [ Orifice ]   ← 003002 (350A) / 003001 (500A)
    ├── [ Tip ]       ← 002003 (1.2mm) — siết 2–3 Nm
    └── [ Nozzle ]    ← 033203 (350A) — nhấn khớp"""

        _DIAGRAM_D = """
Thứ tự lắp đầu súng hệ D (từ trong ra ngoài):

  [ THÂN SÚNG ]
       │
  [ LINER ]          ← liner hệ D
       │
  [ TipBody D ]      ← 023461 / 023462
    ├── [ Insulator D ]
    ├── [ Orifice D ]
    ├── [ Tip D ]     ← 023010 (1.2mm) — siết 2–3 Nm
    └── [ Nozzle D ]  ← 033203 hoặc tương đương"""

        _TORQUE_STD = """
Lực siết chuẩn Tokinarc:
  Béc hàn (Tip)     : 2.0–3.0 Nm
  Thân giữ béc      : 8.0–12.0 Nm
  Liner fitting     : 1.5–2.0 Nm
  Nozzle (press-fit): nhấn tới khớp, không siết
⚠️  Siết quá → kẹt khi béc nóng | Quá lỏng → arc lệch"""

        if isinstance(data, dict):
            has_content = False
            lines = ["Dạ, hướng dẫn lắp đặt như sau ạ:\n"]

            # Show diagram nếu user hỏi sơ đồ / thứ tự / cách lắp
            _ASK_DIAGRAM = ["sơ đồ", "so do", "thu tu", "thứ tự", "lắp", "lap",
                            "assembly", "bản vẽ", "ban ve", "trình tự", "cach lap"]
            if any(k in _q_low for k in _ASK_DIAGRAM):
                eco = (data.get("_anchor_eco") or data.get("ecosystem") or "").upper()
                if eco == "D":
                    lines.append(_DIAGRAM_D)
                else:
                    lines.append(_DIAGRAM_N)
                lines.append(_TORQUE_STD)
                lines.append("\nAnh/chị cần linh kiện cụ thể nào để em báo giá ạ? 😊")
                return "\n".join(lines)
            inner = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
            real_steps = [s for s in (inner.get("steps") or [])
                          if s.get("description_vi") or s.get("description")]
            if real_steps:
                has_content = True
                lines.append("**Các bước lắp đặt:**")
                for i, s in enumerate(real_steps[:8], 1):
                    lines.append(f"{i}. {s.get('description_vi') or s.get('description','')}")
                lines.append("")
            torque = data.get("torque_specs") or inner.get("torque_specs")
            real_torque = {k: v for k, v in (torque or {}).items() if v} if isinstance(torque, dict) else {}
            if real_torque:
                has_content = True
                lines.append("**Lực siết:**")
                for part_type, spec in real_torque.items():
                    lines.append(f"- {_ROLE_VI_INSTALL.get(part_type, part_type)}: {spec}")
                lines.append("")
            real_items = [p for p in (inner.get("items") or inner.get("parts") or [])
                          if p.get("part_id") or p.get("tokin_part_no")]
            if real_items:
                has_content = True
                lines.append("**Linh kiện liên quan:**")
                for p in real_items[:6]:
                    pid = p.get("part_id") or p.get("tokin_part_no", "")
                    biz = p.get("business", {}) or {}
                    price_str = f" — **{biz['price_vnd']:,}đ**" if biz.get("price_vnd") else ""
                    lines.append(f"- **{pid}** — {p.get('display_name_vi','')}{price_str}")
            if not has_content:
                lines = list(_BUILTIN_INSTALL)
            lines.append("\nAnh/chị cần thêm thông tin gì không ạ? 😊")
            return "\n".join(lines)

    # ── REPAIR ────────────────────────────────────────────────────────────────
    if intent == "REPAIR":
        if isinstance(data, dict):
            raw_q = (query or "").lower()
            lines = ["Dạ, em phân tích triệu chứng như sau ạ:\n"]
            ts = data.get("troubleshooting")
            matched_sid = next((sid for kw, sid in _REPAIR_KW_MAP.items() if kw in raw_q), None)
            ts_info = (ts if ts and isinstance(ts, dict) and ts.get("symptom_vi")
                       else _BUILTIN_TS.get(matched_sid))
            if ts_info:
                lines.append(f"**Triệu chứng:** {ts_info.get('symptom_vi','')}\n")
                causes = ts_info.get("causes") or ts_info.get("possible_causes", [])
                if causes:
                    lines.append("**Nguyên nhân có thể:**")
                    for c in causes[:4]:
                        lines.append(f"- {c.get('description_vi', c) if isinstance(c, dict) else c}")
                    lines.append("")
                actions = ts_info.get("actions") or ts_info.get("corrective_actions", [])
                if actions:
                    lines.append("**Hướng xử lý:**")
                    for i, a in enumerate(actions[:5], 1):
                        lines.append(f"{i}. {a.get('action_vi', a) if isinstance(a, dict) else a}")
                    lines.append("")
            else:
                lines.append("Anh/chị có thể mô tả triệu chứng cụ thể hơn không ạ?\n")
                lines.append("Ví dụ: bắn tóe nhiều, dây hàn kẹt, rò khí, hồ quang không ổn định...")
            rp = data.get("related_parts", [])
            if rp:
                lines.append("\n**Linh kiện cần kiểm tra:**")
                for p in rp[:6]:
                    biz = p.get("business", {}) or {}
                    price_str = f" — **{biz['price_vnd']:,}đ**" if biz.get("price_vnd") else ""
                    lines.append(f"- **{p.get('tokin_part_no','')}** — "
                                 f"{p.get('display_name_vi','')} ({p.get('category','')}){price_str}")
            # Proactive ask để narrow diagnosis
            _q_lower = (query or "").lower()
            if not any(k in _q_lower for k in ["he n", "he d", "N 350", "D 350", "ymsa", "acc-308", "tk-308"]):
                lines.append("\nAnh/chị đang dùng súng model gì? Hệ N hay D? Dây mấy mm?")
                lines.append("Cho em biết để chẩn đoán chính xác hơn ạ 😊")
            else:
                lines.append("\nAnh/chị cần hỗ trợ thêm không ạ? 😊")
            return "\n".join(lines)

    return "Đã xử lý xong. Bạn cần thêm thông tin gì không ạ?"


def _gemini_format(gemini_model, intent: str, query: str, ds_result: dict) -> str:
    try:
        from core.llm_explanation import ExplanationEngine
        engine = ExplanationEngine(gemini_model)
        return engine.format(intent=intent, query=query, ds_result=ds_result)
    except Exception as ex:
        log.warning(f"[v7] gemini_format failed ({ex}), fallback template")
        return _template_format(intent, query, ds_result)


# ─── PlanResult ───────────────────────────────────────────────────────────────

@dataclass
class PlanResult:
    intent:      str
    confidence:  float
    band:        str
    e_dict:      dict
    force_band:  Optional[str]
    early_exit:  bool = False
    early_response: Optional[dict] = None
    use_graph:   bool = False
    use_gemini:  bool = False
    vision_used: bool = False
    session_ctx: object = None
    plan_reason: str = ""


# ─── LAYER 1: Planner ─────────────────────────────────────────────────────────

class PipelinePlanner:
    """
    Quyết định routing và early-exit.
    KHÔNG gọi DataStore, Graph, hay Gemini.
    """

    def plan(self, extraction, query: str, session_ctx=None, session_store=None,
             vision_context=None, graph_traversal=None, gemini_model=None,
             session_id=None, t0: float = 0.0) -> PlanResult:

        intent     = extraction.intent
        confidence = extraction.confidence
        e_dict     = extraction.entities.to_dict()
        e_dict["_raw_query"] = query
        force_band = extraction.force_band

        log.info(f"[v7.Planner] intent={intent} conf={confidence:.2f} "
                 f"reason={extraction.reason!r} q={query[:60]!r}")

        # 1. Session inject + intent override
        if session_ctx is not None and session_store is not None:
            e_dict = session_store.inject_context(session_ctx, query, e_dict)
            if e_dict.get("_session_injected_parts") and intent in ("SEARCH_BY_DESC", "OUT_OF_SCOPE"):
                if _GIA_PAT.search(query):
                    intent, confidence = "LOOKUP", 0.80
                    log.info("[v7.Planner] session override → LOOKUP/price")
                else:
                    intent, confidence = "UPSELL", 0.80
                    log.info("[v7.Planner] session override → UPSELL")

        # 1b. Hard OOS override
        _q_lower = query.lower().strip()
        import re as _re2
        _HARD_OOS_PATTERNS = [
            r'^(alo|a lo|hello|hi|hey|xin ch\u00e0o|chao|ch\u00e0o)\s*[!?]*$',
            r'(zalo|so may|s\u1ed1 m\u00e1y|sdt|s\u1ed1 \u0111i\u1ec7n tho\u1ea1i|lien he)',
            r'(kim\s*h[\u00e0a]n\s*tig|tungsten|vonfram|wolfram)',
            r'(m\u00e1y\s*h[\u00e0a]n|may\s*han).*(gi[\u00e1a]|bao\s*nhi[\u00eau])',
        ]
        for _pat in _HARD_OOS_PATTERNS:
            if _re2.search(_pat, _q_lower, _re2.UNICODE | _re2.IGNORECASE):
                return PlanResult(
                    intent="OUT_OF_SCOPE", confidence=0.95, band="HIGH",
                    e_dict=e_dict, force_band="HIGH", early_exit=True,
                    early_response=_make_response(
                        intent="OUT_OF_SCOPE", query=query,
                        confidence=0.95, band="HIGH",
                        text="Xin chào! Bạn cần tư vấn linh kiện hàn Tokinarc gì ạ? 😊",
                        needs_clarify=False, clarify_q=None,
                        session_id=session_id, parts=[],
                        latency_ms=_ms(t0), success=False,
                    ),
                    session_ctx=session_ctx,
                    plan_reason="hard_oos_pattern",
                )

        # 2. Vision confirm check — TRƯỚC khi merge context mới
        # Nếu turn trước bot suggest mã từ ảnh và user vừa confirm/deny
        vision_used = False
        if session_ctx is not None and session_ctx.pending_vision_candidates:
            from core.session_store import is_vision_confirm, is_vision_deny, extract_vision_choice
            if is_vision_confirm(query):
                # User xác nhận → lấy mã đúng
                choice     = extract_vision_choice(query)
                candidates = session_ctx.pending_vision_candidates
                confirmed  = (candidates[choice - 1] if choice and choice <= len(candidates)
                              else candidates[0])
                session_ctx.confirm_vision_part(confirmed)
                # Override e_dict → UPSELL với confirmed part + condition advice
                e_dict["part_nos"] = [confirmed]
                e_dict["_vision_confirmed"]  = True
                e_dict["_vision_condition"]  = session_ctx.vision_condition
                e_dict["_session_injected_parts"] = True
                intent     = "UPSELL"
                confidence = 0.92
                force_band = "HIGH"
                vision_used = True
                log.info(f"[v7.Planner] Vision confirm: {confirmed} → UPSELL")
            elif is_vision_deny(query):
                # User từ chối → clear, hỏi lại
                session_ctx.clear_vision_state()
                log.info(f"[v7.Planner] Vision denied → clear state")

        # 2b. Vision context từ ảnh mới gửi lên
        if vision_context and isinstance(vision_context, dict):
            candidates  = vision_context.get("_vision_candidates") or []
            conf_vis    = float(vision_context.get("_vision_confidence") or 0.0)
            condition   = vision_context.get("_vision_condition") or ""
            part_type   = (vision_context.get("categories") or [""])[0]
            eco_vis     = vision_context.get("ecosystem")
            confirm_msg = vision_context.get("_vision_confirm_msg", "")

            # Inject part_nos từ vision
            for pno in (vision_context.get("part_nos") or []):
                if pno and pno not in e_dict.get("part_nos", []):
                    e_dict.setdefault("part_nos", []).append(pno)
                    vision_used = True

            # Inject ecosystem nếu chưa có
            if eco_vis and not e_dict.get("ecosystem"):
                e_dict["ecosystem"] = eco_vis

            # Lưu pending vào session để handle confirm turn tiếp theo
            if session_ctx is not None and candidates:
                session_ctx.set_vision_pending(
                    candidates=candidates,
                    part_type=part_type,
                    ecosystem=eco_vis,
                    condition=condition,
                )

            # Nếu cần confirm → trả confirm_msg ngay, không route DataStore
            if vision_context.get("_vision_confirm_needed") and confirm_msg and candidates:
                return PlanResult(
                    intent=intent, confidence=confidence, band="MEDIUM",
                    e_dict=e_dict, force_band=None,
                    early_exit=True,
                    early_response=_make_response(
                        intent="LOOKUP", query=query, confidence=0.75, band="MEDIUM",
                        text=confirm_msg,
                        needs_clarify=True,
                        clarify_q=confirm_msg,
                        session_id=session_id,
                        parts=[],
                        latency_ms=_ms(t0),
                        success=True,
                        vision_used=True,
                    ),
                    vision_used=True,
                    session_ctx=session_ctx,
                )

            vision_used = True

        # 3. Band
        band = force_band if force_band else _band(confidence)

        # 4. Contradiction detection
        if intent == "COMPATIBILITY_CHECK" and force_band != "HIGH":
            contra = self._detect_contradiction(query)
            if contra:
                msg = _CONTRA_CLARIFY_MAP.get(contra, "Thông tin có vẻ mâu thuẫn — bạn có thể mô tả rõ hơn không ạ?")
                return PlanResult(
                    intent=intent, confidence=0.55, band="LOW",
                    e_dict=e_dict, force_band=force_band, early_exit=True,
                    early_response=_make_response(
                        intent=intent, query=query, confidence=0.55, band="LOW",
                        text=msg, needs_clarify=True, clarify_q=msg,
                        session_id=session_id, parts=[], latency_ms=_ms(t0), success=False,
                    ),
                    vision_used=vision_used, session_ctx=session_ctx,
                    plan_reason=f"contradiction:{contra}",
                )

        # 5. OUT_OF_SCOPE — thử knowledge base câu hỏi giải thích trước
        if intent == "OUT_OF_SCOPE":
            _last_text = (session_ctx.last_text if session_ctx else "") or ""
            _explain = _try_explain(query, last_text=_last_text)

            # Follow-up ngắn về thông số kỹ thuật → override thành LOOKUP
            # Ví dụ: "thông số kỹ thuật chi tiết" sau khi đã lookup torch
            _SPEC_PAT = re.compile(
                r"(th[oô]ng\s*s[oố]|spec|k[ỹy]\s*thu[ậa]t|chi\s*ti[eế]t|"
                r"thong\s*so|ky\s*thuat|chi\s*tiet)",
                re.I | re.UNICODE,
            )
            if (not _explain and _SPEC_PAT.search(query)
                    and session_ctx is not None and session_ctx.turn_count > 0):
                # Inject part/torch từ session rồi chuyển sang LOOKUP
                _inj = session_store.inject_context(session_ctx, query, e_dict) if session_store else e_dict
                _inj_parts = (_inj.get("part_nos") or _inj.get("last_part_nos") or
                              session_ctx.last_part_nos or session_ctx.last_returned_parts)
                if _inj_parts:
                    # Override: chạy LOOKUP với part từ session
                    return PlanResult(
                        intent="LOOKUP", confidence=0.80, band="MEDIUM",
                        e_dict={**e_dict, "part_nos": list(_inj_parts[:1])},
                        force_band=None, early_exit=False,
                        use_graph=False,
                        use_gemini=False,
                        vision_used=vision_used, session_ctx=session_ctx,
                        plan_reason="spec_followup_override",
                    )

            return PlanResult(
                intent=intent, confidence=confidence, band=band,
                e_dict=e_dict, force_band=force_band, early_exit=True,
                early_response=_make_response(
                    intent=intent, query=query, confidence=confidence, band=band,
                    text=_explain or "Xin chào! Bạn cần tư vấn linh kiện hàn Tokinarc gì ạ?",
                    needs_clarify=not bool(_explain), clarify_q=None,
                    session_id=session_id, parts=[], latency_ms=_ms(t0),
                    success=bool(_explain),
                ),
                vision_used=vision_used, session_ctx=session_ctx,
                plan_reason="out_of_scope_explained" if _explain else "out_of_scope",
            )

        # 6. SEARCH_BY_DESC + LOW → clarify
        if intent == "SEARCH_BY_DESC" and band == "LOW" and not extraction.reason.endswith("prefilter"):
            msg = "Bạn có thể mô tả rõ hơn không ạ? Ví dụ: hệ N hay D, dòng điện 350A hay 500A, cỡ dây bao nhiêu mm?"
            return PlanResult(
                intent=intent, confidence=confidence, band=band,
                e_dict=e_dict, force_band=force_band, early_exit=True,
                early_response=_make_response(
                    intent=intent, query=query, confidence=confidence, band=band,
                    text=msg, needs_clarify=True, clarify_q=msg,
                    session_id=session_id, parts=[], latency_ms=_ms(t0), success=False,
                ),
                vision_used=vision_used, session_ctx=session_ctx, plan_reason="search_low_clarify",
            )

        # 7. Terse → clarify
        if band == "LOW" and intent == "SEARCH_BY_DESC" and extraction.reason == "terse_prefilter":
            msg = "Bạn cần tìm linh kiện gì ạ? Ví dụ: béc hàn N 350A 1.2mm, chụp khí 500A, bộ vật tư TK-308RR..."
            return PlanResult(
                intent=intent, confidence=confidence, band=band,
                e_dict=e_dict, force_band=force_band, early_exit=True,
                early_response=_make_response(
                    intent=intent, query=query, confidence=confidence, band=band,
                    text=msg, needs_clarify=True, clarify_q="Bạn cần tìm linh kiện gì?",
                    session_id=session_id, parts=[], latency_ms=_ms(t0),
                ),
                vision_used=vision_used, session_ctx=session_ctx, plan_reason="terse_clarify",
            )

        # 8. Routing decisions
        return PlanResult(
            intent=intent, confidence=confidence, band=band,
            e_dict=e_dict, force_band=force_band, early_exit=False,
            use_graph=graph_traversal is not None and intent in ("UPSELL", "CONSUMABLE_SET"),
            use_gemini=gemini_model is not None and intent not in _TEMPLATE_ONLY_INTENTS,
            vision_used=vision_used, session_ctx=session_ctx, plan_reason="proceed",
        )

    @staticmethod
    def _detect_contradiction(query: str) -> Optional[str]:
        for pat, reason in _CONTRA_PATTERNS:
            if re.search(pat, query, re.I | re.UNICODE):
                return reason
        return None


# ─── LAYER 2: Executor ────────────────────────────────────────────────────────

class PipelineExecutor:
    """
    Thực thi PlanResult: gọi DataStore/Graph, format, update session.
    """

    def execute(self, plan: PlanResult, query: str, data_store,
                graph_traversal=None, gemini_model=None,
                session_store=None, session_id=None, t0: float = 0.0,
                vector_index=None) -> dict:

        if plan.early_exit:
            return plan.early_response

        intent = plan.intent
        e_dict = plan.e_dict

        # Route
        try:
            ds_result = _route_query(intent, e_dict, data_store,
                                     graph_traversal if plan.use_graph else None,
                                     vector_index=vector_index)
        except Exception as ex:
            log.error(f"[v7.Executor] route failed: {ex}")
            return _error_response(query, str(ex), session_id, _ms(t0))

        log.debug(f"[v7.Executor] ds success={ds_result['success']} reason={ds_result['reason']}")

        # Recompute confidence P2
        confidence, band = _compute_global_confidence(
            intent_score=plan.confidence, e_dict=e_dict, ds_result=ds_result,
            intent=intent, force_band=plan.force_band or "",
        )
        log.info(f"[v7.Executor][P2] global_conf={confidence:.3f} band={band}")

        # Parts
        parts = _extract_parts(ds_result["data"])

        # Format
        if plan.use_gemini and ds_result["success"]:
            text = _gemini_format(gemini_model, intent, query, ds_result)
        else:
            text = _template_format(intent, query, ds_result)

        # Clarify
        needs_clarify = not ds_result["success"]
        clarify_q = None
        if needs_clarify:
            reason = ds_result.get("reason", "")
            clarify_q = (reason[8:] if reason.startswith("CLARIFY:")
                         else _CLARIFY_REASON_MAP.get(reason))

        # Session update
        if plan.session_ctx is not None and session_store is not None and ds_result["success"]:
            session_store.update(plan.session_ctx, intent, e_dict, parts)

        match_type = "none"
        if ds_result["success"]:
            src = ds_result.get("source", "")
            if src == "vector":
                match_type = "vector"
            elif src == "text_fallback":
                match_type = "fuzzy"
            else:
                match_type = "exact"

        return _make_response(
            intent=intent, query=query, confidence=confidence, band=band,
            text=text, needs_clarify=needs_clarify, clarify_q=clarify_q,
            session_id=session_id, parts=parts, latency_ms=_ms(t0),
            success=ds_result["success"], vision_used=plan.vision_used,
            match_type=match_type,
            fallback_used=ds_result.get("source") in ("text_fallback", "vector"),
        )


# ─── Singletons ───────────────────────────────────────────────────────────────

_planner  = PipelinePlanner()
_executor = PipelineExecutor()


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_v7(
    query: str,
    extractor,
    data_store,
    gemini_model=None,
    session_id: Optional[str] = None,
    vision_context: Optional[dict] = None,
    graph_traversal=None,
    vector_index=None,      # reserved — VectorIndex tier 3
    session_store=None,
) -> dict:
    t0 = time.perf_counter()
    q  = query.strip()

    # Session
    session_ctx = None
    if session_store is not None:
        session_ctx = session_store.get_or_create(session_id)

    # Extractor
    try:
        extraction = extractor.extract(q)
    except Exception as ex:
        from core.gemini_resilience import (
            fallback_error_response,
            GeminiRateLimitError, GeminiTimeoutError, GeminiUnavailableError,
        )
        if isinstance(ex, (GeminiRateLimitError, GeminiTimeoutError, GeminiUnavailableError)):
            log.error(f"[v7] extractor resilience fail: {ex}")
            return fallback_error_response(q, ex, session_id, _ms(t0))
        log.error(f"[v7] extractor failed: {ex}")
        return _error_response(q, str(ex), session_id, _ms(t0))

    # Planner
    plan = _planner.plan(
        extraction=extraction, query=q,
        session_ctx=session_ctx, session_store=session_store,
        vision_context=vision_context, graph_traversal=graph_traversal,
        gemini_model=gemini_model, session_id=session_id, t0=t0,
    )

    # Executor
    return _executor.execute(
        plan=plan, query=q, data_store=data_store,
        graph_traversal=graph_traversal, gemini_model=gemini_model,
        session_store=session_store, session_id=session_id, t0=t0,
        vector_index=vector_index,
    )


# ─── Backward-compat shims ────────────────────────────────────────────────────
# main.py gọi run_v6 / run_v5 → không cần sửa gì.

run_v6 = run_v7
run_v5 = run_v7
