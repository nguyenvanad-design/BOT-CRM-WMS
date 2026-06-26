# core/tool_wrappers.py
# TOKINARC Tool Wrappers — 9 functions cho tool-use architecture
# ==============================================================
# Mỗi function khớp với 1 tool trong TOOL_SCHEMA (system_prompts.py).
# LLM gọi tool → Gemini trả function call JSON → dispatcher gọi hàm tương ứng.
#
# Input:  **kwargs từ Gemini function call (validated theo TOOL_SCHEMA)
# Output: dict serializable — LLM đọc để tổng hợp câu trả lời
#
# Dependency chain:
#   tool_wrappers → TokinarcCER → TokinarcDataStore (singleton)
#                → GraphTraversal (dùng CER)
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("tokinarc.tools")

# ── Robot alias resolution ──────────────────────────────────────────────────────
# Map cách người dùng gõ tự nhiên ("1.4m", "1440", "yaskawa") → robot canonical.
# Nguồn: data.meta.robot_aliases (patch v11m). Có fallback hard-coded phòng khi
# data store cũ chưa có field này.
_ROBOT_ALIASES_FALLBACK = {
    "ma1440": "MA1440", "ar1440": "MA1440", "1.4m": "MA1440", "1,4m": "MA1440",
    "1.4 mét": "MA1440", "1.4 met": "MA1440", "1,4 mét": "MA1440", "1,4 met": "MA1440",
    "1440": "MA1440",
    "ma2010": "MA2010", "ar2010": "MA2010", "2.0m": "MA2010", "2,0m": "MA2010",
    "2.0 mét": "MA2010", "2,0 mét": "MA2010", "2010": "MA2010",
    "ar1730": "AR1730", "mh24": "AR1730", "1.7m": "AR1730", "1,7m": "AR1730",
    "1.7 mét": "AR1730", "1,7 mét": "AR1730", "1730": "AR1730",
    "ar700": "AR700", "700": "AR700",
    "ar900": "AR900", "900": "AR900",
    "ar1440e": "AR1440E", "1440e": "AR1440E",
    # Yaskawa + common typos (live log 2026-06-21: user gõ "yaskwa" thiếu 'a')
    "yaskawa": "Yaskawa AR Series", "yaskwa": "Yaskawa AR Series",
    "yaskaw": "Yaskawa AR Series", "yasakawa": "Yaskawa AR Series",
    "motoman": "Yaskawa AR Series", "motorman": "Yaskawa AR Series",
    "daihen": "Daihen", "otc": "Daihen",
    "panasonic": "Panasonic", "lincoln": "Lincoln", "miller": "Miller", "binzel": "Binzel",
}

# Các robot model CỤ THỂ đã biết — khi user hỏi đúng 1 trong số này thì KHÔNG
# tự gộp súng Universal/Various vào (chỉ trả súng chuyên dụng cho robot đó).
_KNOWN_ROBOT_MODELS = {
    "MA1440", "MA2010", "AR1730", "AR1440", "AR2010", "MH24",
    "AR700", "AR900", "AR1440E",
}


def _robot_aliases() -> dict:
    """Lấy alias map từ data store, fallback sang bản hard-coded."""
    try:
        ds = _get_ds()
        meta = getattr(ds, "meta", None) or {}
        amap = meta.get("robot_aliases") if isinstance(meta, dict) else None
        if amap:
            return amap
    except Exception:
        pass
    return _ROBOT_ALIASES_FALLBACK


def _resolve_robot(user_input: str) -> str:
    """Chuẩn hóa 1 chuỗi robot do user nhập → canonical model. Không match thì giữ nguyên."""
    if not user_input:
        return user_input
    key = user_input.lower().strip()
    return _robot_aliases().get(key, user_input)


def _robot_match(torch: dict, robot_query: str) -> bool:
    """
    Khớp robot với robot_compatibility của torch theo WORD-BOUNDARY (không substring).
    Lý do: substring khiến '1440' khớp nhầm 'AR1440E' (robot EA khác hẳn MA1440).
    Có resolve alias trước ('1.4m'/'1440' → 'MA1440').

    Quy tắc 'Universal'/'Various':
      - Khớp khi user hỏi CHUNG ('yaskawa', 'robot', 'fanuc'...) — vì súng universal
        gắn được mọi robot qua bracket riêng.
      - KHÔNG tự động gộp khi user hỏi 1 robot Motoman CỤ THỂ (MA1440/AR700...),
        để tránh trộn WX/TIG-robotic universal vào danh sách súng Motoman chuyên dụng.
    """
    canonical = _resolve_robot(robot_query)
    rc = torch.get("robot_compatibility") or []
    if isinstance(rc, str):
        rc = [rc]
    cl = canonical.lower().strip()
    if not cl:
        return False

    for r in rc:
        rl = str(r).lower()
        if rl == cl:
            return True
        # token riêng (vd 'ma1440' trong list) — \b chặn '1440' khớp 'ar1440e'
        if re.search(r"\b" + re.escape(cl) + r"\b", rl):
            return True

    # Universal/Various: chỉ khớp khi query KHÔNG phải 1 model robot cụ thể đã biết.
    is_specific_model = canonical in _KNOWN_ROBOT_MODELS
    if not is_specific_model and any(
        str(r).lower() in ("various", "universal") for r in rc
    ):
        return True

    # Query cấp hãng Yaskawa/Motoman: khớp luôn các súng list robot Motoman cụ thể
    # (MA1440/MA2010/AR1730...) — vì đó đều là robot Yaskawa.
    if cl in ("yaskawa ar series", "yaskawa", "motoman"):
        if any(str(r) in _KNOWN_ROBOT_MODELS or str(r).lower().startswith(("ma", "ar", "mh"))
               for r in rc):
            return True

    return False

# ── Lazy singletons ────────────────────────────────────────────────────────────

_cer  = None
_gt   = None
_ds   = None
_pqa  = None   # PQA Retriever
_kb   = None   # AssemblyKB — assembly_procedures_v1_3.json

def _get_cer():
    global _cer
    if _cer is None:
        from core.tokinarc_cer import get_cer
        _cer = get_cer()
    return _cer

def _get_gt():
    global _gt
    if _gt is None:
        from core.graph_traversal import get_graph_traversal
        _gt = get_graph_traversal(_get_cer())
    return _gt

def _get_ds():
    global _ds
    if _ds is None:
        from core.data_store import get_data_store
        _ds = get_data_store()
    return _ds


def set_data_store(ds) -> None:
    """Wire DataStore từ lifespan."""
    global _ds
    _ds = ds


def set_graph_traversal(gt) -> None:
    """Wire GraphTraversal từ lifespan."""
    global _gt
    _gt = gt


def set_cer(cer) -> None:
    """Wire CER từ lifespan."""
    global _cer
    _cer = cer


def set_pqa(pqa) -> None:
    """Wire PQA Retriever từ lifespan."""
    global _pqa
    _pqa = pqa


def set_assembly_kb(kb) -> None:
    """Wire AssemblyKB từ lifespan — dùng trong get_troubleshoot + get_liner_length + get_replacement_steps."""
    global _kb
    _kb = kb


def _get_pqa():
    return _pqa


def _get_kb():
    """Lazy getter — trả None nếu chưa wire (safe fallback)."""
    return _kb


# ── Helpers ────────────────────────────────────────────────────────────────────

def _part_to_response(part_dict: dict) -> dict:
    """Chuẩn hóa 1 part dict → response format cho LLM."""
    biz = part_dict.get("business") or {}
    # Enrich business từ DataStore nếu companion dict không có nested business
    if not biz.get("price_vnd") and not biz.get("is_contact_price"):
        pno = part_dict.get("tokin_part_no", "")
        if pno:
            try:
                raw = _get_ds().parts.get(pno, {})
                biz = raw.get("business") or biz
            except Exception:
                pass
    price_vnd = biz.get("price_vnd")
    is_contact = biz.get("is_contact_price", False)
    return {
        "tokin_part_no":   part_dict.get("tokin_part_no", ""),
        "display_name_vi": part_dict.get("display_name_vi", ""),
        "display_name_en": part_dict.get("display_name_en", ""),
        "category":        part_dict.get("category", ""),
        "ecosystem":       part_dict.get("ecosystem", ""),
        "current_class":   part_dict.get("current_class", ""),
        "wire_size_mm":    part_dict.get("wire_size_mm"),
        "p_part_nos":      part_dict.get("p_part_nos") or [],
        "d_part_nos":      part_dict.get("d_part_nos") or [],
        "o_part_nos":      part_dict.get("o_part_nos") or [],
        # Specs (category-dependent, các field None sẽ bị bỏ qua khi render)
        "total_length_mm":  part_dict.get("total_length_mm"),
        "thread_type":      part_dict.get("thread_type"),
        "material":         part_dict.get("material"),
        "inner_dia_mm":     part_dict.get("inner_dia_mm"),
        "outer_dia_mm":     part_dict.get("outer_dia_mm"),
        "length_mm":        part_dict.get("length_mm"),
        "insulator_class":  part_dict.get("insulator_class"),
        "tip_body_type":    part_dict.get("tip_body_type"),
        "orifice_class":    part_dict.get("orifice_class"),
        "supported_processes": part_dict.get("supported_processes") or [],
        "note":             part_dict.get("note", ""),
        # Business
        "price_vnd":        price_vnd,
        "price_unit":       biz.get("price_unit", "cái"),
        "is_contact_price": is_contact,
        "is_priority_sell": biz.get("is_priority_sell", False),
        "price_display":    f"{price_vnd:,}đ/{biz.get('price_unit','cái')}" if (price_vnd and not is_contact) else "Liên hệ báo giá",
    }


def _torch_to_response(t: dict) -> dict:
    """Chuẩn hóa 1 torch dict → response format."""
    biz = t.get("business") or {}

    # Rated ampere — coalesce qua nhiều schema (MIG/MAG/MIG-nhôm/TIG).
    # Ưu tiên field thống nhất rated_a (patch v11n), fallback các field cũ.
    rated_a = (
        t.get("rated_a")
        or t.get("rated_co2_a") or t.get("rated_mag_a")
        or t.get("rated_mig_a") or t.get("rated_dc_a")
        or t.get("rated_current")
    )
    # Cỡ dây/tungsten hiển thị — coalesce wire_size/tungsten_mm.
    wire_display = (
        t.get("wire_display")
        or t.get("wire_size") or t.get("wire_size_mm") or t.get("tungsten_mm")
    )
    duty = (
        t.get("duty_display")
        or t.get("duty_co2_pct") or t.get("duty_cycle_pct") or t.get("duty_pct")
    )

    return {
        "model_code":          t.get("model_code", ""),
        "display_name_vi":     t.get("display_name_vi") or t.get("model_code", ""),
        "ecosystem":           t.get("ecosystem", ""),
        "current_class":       t.get("current_class", ""),
        "torch_type":          t.get("torch_type", ""),
        "cooling":             t.get("cooling", "air"),
        "rated_a":             rated_a,
        "rated_co2_a":         t.get("rated_co2_a"),
        "rated_mag_a":         t.get("rated_mag_a"),
        "wire_display":        wire_display,
        "wire_kind":           t.get("wire_kind", "wire"),
        "wire_size":           t.get("wire_size") or t.get("tungsten_mm"),
        "duty_co2_pct":        duty,
        "robot_compatibility": t.get("robot_compatibility"),
        "robot_series":        t.get("robot_series", ""),
        "shock_sensor_type":   t.get("shock_sensor_type", "NONE"),
        "functional_requires": t.get("functional_requires"),
        "coolant_unit_required": t.get("coolant_unit_required"),
        "note":                t.get("note", ""),
        "price_vnd":           biz.get("price_vnd"),
        "is_contact_price":    biz.get("is_contact_price", True),
    }


def _ok(data: Any, **extra) -> dict:
    return {"success": True, "data": data, **extra}

def _fail(reason: str, **extra) -> dict:
    return {"success": False, "reason": reason, **extra}


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — lookup_part
# ══════════════════════════════════════════════════════════════════════════════

def lookup_part(part_no: str = "", description: Optional[str] = None) -> dict:
    """
    Tra cứu thông tin đầy đủ 1 part.
    Nhận: Tokin 6 số, mã Panasonic (TET/TGN/TFZ/U...), mã Daihen/OTC (K/L/DAH/U4...).

    Returns:
        {
          success: bool,
          data: {
            ...full part fields...,
            resolved_from: str | None,  # nếu là alias
            brand: str | None           # "Panasonic" / "Daihen/OTC" nếu là alias
          }
        }
    """
    # Fix: nếu không có part_no nhưng có description → tự search_parts
    if not part_no and description:
        sr = search_parts(query=description)
        sr_parts = (sr.get("data") or {}).get("parts", [])
        if sr_parts:
            part_no = sr_parts[0].get("tokin_part_no", "")
            log.info(f"[lookup_part] description='{description}' → resolved part_no={part_no}")
    if not part_no:
        return _fail("MISSING_PART_NO")

    cer = _get_cer()
    ds  = _get_ds()

    # Direct Tokin lookup
    part_dict = ds.parts.get(part_no)
    resolved_from = None
    brand = None

    if not part_dict:
        # Try alias resolution
        tokin = (ds.p_alias.get(part_no.upper()) or
                 ds.d_alias.get(part_no.upper()) or
                 ds.p_model_alias.get(part_no.upper()) or
                 ds.d_model_alias.get(part_no.upper()) or
                 ds.o_model_alias.get(part_no.upper()) or
                 ds.o_part_alias.get(part_no.upper()) or
                 ds.model_alias.get(part_no.upper()))
        if tokin and tokin in ds.parts:
            part_dict = ds.parts[tokin]
            resolved_from = part_no
            # Detect brand
            p_upper = part_no.upper()
            if p_upper in ds.p_alias or p_upper in ds.p_model_alias:
                brand = "Panasonic"
            elif p_upper in ds.o_part_alias or p_upper in ds.o_model_alias:
                brand = "OTC"
            elif p_upper in ds.d_alias or p_upper in ds.d_model_alias:
                brand = "Daihen"

    # v19: fake_pno_aliases — reversed-prefix typo (e.g. 007001→001007)
    if not part_dict and hasattr(ds, 'fake_pno_aliases'):
        _fake = ds.fake_pno_aliases.get(part_no)
        if _fake:
            _primary = _fake.get("primary", "")
            if _primary and _primary in ds.parts:
                part_dict = ds.parts[_primary]
                resolved_from = part_no
                brand = "typo_alias"
                log.info(f"[lookup_part] fake_pno {part_no} → {_primary}")

    # Try torch lookup if part not found
    if not part_dict:
        torch_dict = ds.torches.get(part_no)
        if torch_dict:
            return _ok({
                "type": "torch",
                **_torch_to_response(torch_dict)
            })
        # Case-insensitive torch
        for k, v in ds.torches.items():
            if k.upper() == part_no.upper():
                return _ok({"type": "torch", **_torch_to_response(v)})
        return _fail(f"NOT_FOUND:{part_no}")

    resp = _part_to_response(part_dict)
    resp["type"] = "part"
    if resolved_from:
        resp["resolved_from"] = resolved_from
        resp["brand"] = brand

    log.info(f"[lookup_part] {part_no} → {resp['tokin_part_no']}")
    return _ok(resp)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — search_parts
# ══════════════════════════════════════════════════════════════════════════════

def search_parts(
    query: str = "",
    category: Optional[str] = None,
    ecosystem: Optional[str] = None,
    current_class: Optional[str] = None,
    wire_size_mm: Optional[float] = None,
    max_results: int = 10,
) -> dict:
    """
    Tìm parts theo mô tả tự nhiên + optional filters.

    Returns:
        {
          success: bool,
          data: {
            parts: List[part_response],
            total: int,
            filters_applied: dict
          }
        }
    """
    max_results = min(max(1, max_results), 20)

    # ── Category normalization ────────────────────────────────────────────────
    # CeramicNozzle trong MIG context → Nozzle (CeramicNozzle chỉ là TIG)
    _q_lower = (query or "").lower()
    _is_tig_context = any(k in _q_lower for k in ("tig", "tungsten", "collet", "back cap", "backcap"))
    if category == "CeramicNozzle" and not _is_tig_context and ecosystem not in ("TIG",):
        category = "Nozzle"

    # FIX: "thân béc/thân giữ béc" + wire_size → user muốn Tip (béc hàn), không phải TipBody (thân giữ)
    # Trong tiếng Việt "thân béc X ly" thường ý là béc (Tip) cỡ X mm
    _than_bec_with_wire = (
        category == "TipBody" and wire_size_mm is not None and
        any(k in _q_lower for k in ("thân béc", "than bec", "thân giữ béc", "linh kiện thân"))
    )
    if _than_bec_with_wire:
        log.info(f"[search_parts] 'thân béc' + wire_size={wire_size_mm} → remap TipBody→Tip")
        category = "Tip"

    # FIX: "linh kiện thân béc/thân giữ béc" không có wire_size → search Tip với eco filter
    _linh_kien_than_bec = (
        category == "TipBody" and wire_size_mm is None and
        any(k in _q_lower for k in ("linh kiện thân", "linh kien than", "thân béc", "than bec"))
    )
    if _linh_kien_than_bec:
        log.info(f"[search_parts] 'linh kiện thân béc' → remap TipBody→Tip")
        category = "Tip"

    # InnerTube không phân biệt hệ N/D — flag để dùng sau
    _innertube_fallback = False

    # TipBody + "thân giữ béc" VN context thực ra muốn Tip assembly
    # → giữ TipBody nhưng nếu trả rỗng sẽ fallback sang Tip bên dưới
    _original_category = category

    # ── FIX: category normalization ──────────────────────────────────────────
    # CeramicNozzle trong context MIG → Nozzle
    if category == "CeramicNozzle":
        _tig_kw = any(k in (query or "").lower() for k in ("tig", "collet", "tungsten", "bạch kim"))
        if not _tig_kw and (ecosystem or "").upper() in ("", "N", "D"):
            log.info("[search_parts] CeramicNozzle → Nozzle (MIG context)")
            category = "Nozzle"

    # ── FIX: InnerTube eco=D → also search eco=N (InnerTube only exists in N/WX) ──
    _search_eco = ecosystem
    if category == "InnerTube" and (ecosystem or "").upper() == "D":
        log.info("[search_parts] InnerTube eco=D → fallback eco=N")
        _search_eco = "N"
        _innertube_fallback = True

    def _do_search(eco, ws):
        try:
            from core.retrieval_orchestrator import get_retrieval_orchestrator
            orch = get_retrieval_orchestrator()
            result = orch.retrieve(
                query         = query or "",
                ecosystem     = _search_eco if _search_eco != ecosystem else eco,
                current_class = current_class,
                wire_size_mm  = ws,
                category      = category,
                top_k         = max_results,
            )
            return result.parts[:max_results], result.filters_applied
        except Exception as _orch_err:
            log.warning(f"[search_parts] orchestrator failed, fallback CER: {_orch_err}")
            cer = _get_cer()
            scored = cer.search_parts(
                query         = query or "",
                category      = category,
                ecosystem     = eco,
                current_class = current_class,
                wire_size_mm  = ws,
                max_results   = max_results,
            )
            parts = [pr.raw.copy() for _, pr in scored] if scored else []
            filters = {k: v for k, v in {"category": category, "ecosystem": eco,
                       "current_class": current_class, "wire_size_mm": ws}.items() if v is not None}
            return parts, filters

    # FIX: TIG parts dung tungsten_dia_mm thay vi wire_size_mm
    # Neu category TIG (Collet/CeramicNozzle/ColletBody/BackCap) -> filter sau khi search
    _tig_cats = {"Collet", "CeramicNozzle", "ColletBody", "BackCap", "GasLens", "TungstenElectrode"}
    _is_tig_search = (ecosystem or "").upper() == "TIG" or category in _tig_cats
    _tungsten_filter = wire_size_mm if _is_tig_search else None
    _wire_filter = None if _is_tig_search else wire_size_mm

    # ── Wire retrieval_orchestrator ──────────────────────────────────────────
    raw_parts, filters_used = _do_search(_search_eco, _wire_filter)

    # FIX: post-filter theo tungsten_dia_mm cho TIG parts
    if _tungsten_filter and _is_tig_search and raw_parts:
        raw_parts = [p for p in raw_parts
                     if abs(float(p.get("tungsten_dia_mm") or p.get("wire_size_mm") or 0) - _tungsten_filter) < 0.05]
        log.info(f"[search_parts] TIG tungsten filter {_tungsten_filter}mm -> {len(raw_parts)} parts")

    # FIX: retry không wire_size nếu không tìm được (wire filter quá strict)
    if not raw_parts and wire_size_mm is not None:
        log.info(f"[search_parts] retry without wire_size_mm={wire_size_mm}")
        raw_parts, filters_used = _do_search(_search_eco, None)

    # FIX: retry với eco=None nếu vẫn không có (ecosystem filter quá strict)
    if not raw_parts and _search_eco:
        log.info(f"[search_parts] retry without ecosystem={_search_eco}")
        raw_parts, filters_used = _do_search(None, wire_size_mm)

    # ── Fallback: TipBody → Tip nếu không có kết quả ─────────────────────────
    if not raw_parts and _original_category == "TipBody":
        try:
            from core.retrieval_orchestrator import get_retrieval_orchestrator
            orch2 = get_retrieval_orchestrator()
            result2 = orch2.retrieve(
                query         = query or "",
                ecosystem     = _search_eco,
                current_class = current_class,
                wire_size_mm  = wire_size_mm,
                category      = "Tip",
                top_k         = max_results,
            )
            raw_parts = result2.parts[:max_results]
            if raw_parts:
                log.info("[search_parts] TipBody→Tip fallback: found %d", len(raw_parts))
        except Exception as _e:
            log.debug("[search_parts] TipBody fallback error: %s", _e)

    # ── Fallback: InnerTube eco=D → eco=N ────────────────────────────────────
    if not raw_parts and _innertube_fallback:
        try:
            from core.retrieval_orchestrator import get_retrieval_orchestrator
            orch3 = get_retrieval_orchestrator()
            result3 = orch3.retrieve(
                query         = query or "",
                ecosystem     = "N",
                current_class = current_class,
                wire_size_mm  = wire_size_mm,
                category      = "InnerTube",
                top_k         = max_results,
            )
            raw_parts = result3.parts[:max_results]
            if raw_parts:
                log.info("[search_parts] InnerTube D→N fallback: found %d", len(raw_parts))
        except Exception as _e:
            log.debug("[search_parts] InnerTube fallback error: %s", _e)

    if not raw_parts:
        return _fail("NO_RESULTS", filters={
            "category": category, "ecosystem": ecosystem,
            "current_class": current_class, "wire_size_mm": wire_size_mm,
        })

    parts = []
    for d in raw_parts:
        resp = _part_to_response(d)
        resp["confidence"] = 0.9 if d.get("is_priority_sell") else 0.75
        parts.append(resp)

    return _ok({
        "parts": parts,
        "total": len(parts),
        "filters_applied": filters_used,
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — get_consumable_set
# ══════════════════════════════════════════════════════════════════════════════

def get_consumable_set(
    torch_model: Optional[str] = None,
    ecosystem: Optional[str] = None,
    current_class: Optional[str] = None,
    part_no: Optional[str] = None,
) -> dict:
    """
    Lấy bộ vật tư tiêu hao đầy đủ.

    Returns:
        {
          success: bool,
          data: {
            sets: List[{set_id, display_name_vi, ecosystem, current_class,
                         parts: List[{...part + is_mandatory + part_role}]}],
            torch_info: dict | None
          }
        }
    """
    gt  = _get_gt()
    ds  = _get_ds()

    torch_info = None

    # Fix: resolve eco/cc từ part_no nếu có
    if part_no and not ecosystem and not torch_model:
        pno_dict = ds.parts.get(part_no, {})
        if not pno_dict:
            cer = _get_cer()
            resolved = cer.resolve_part_no(part_no)
            if resolved:
                pno_dict = ds.parts.get(resolved, {})
        if pno_dict:
            ecosystem     = ecosystem     or pno_dict.get("ecosystem", "")
            current_class = current_class or pno_dict.get("current_class", "")
            log.info(f"[get_consumable_set] part_no={part_no} -> eco={ecosystem} cc={current_class}")

    # Resolve eco/cc từ torch model nếu có
    if torch_model:
        torch_dict = ds.torches.get(torch_model)
        if not torch_dict:
            # Case insensitive
            for k, v in ds.torches.items():
                if k.upper() == torch_model.upper():
                    torch_dict = v
                    torch_model = k
                    break
        if torch_dict:
            torch_info = _torch_to_response(torch_dict)
            ecosystem    = ecosystem    or torch_dict.get("ecosystem", "")
            current_class = current_class or torch_dict.get("current_class", "")
    cs_results = gt.get_full_consumable_set(
        torch_model   = torch_model,
        ecosystem     = ecosystem,
        current_class = current_class,
        expand_variants = False,
    )

    if not cs_results:
        return _fail("NO_CONSUMABLE_SET_FOUND", torch_model=torch_model,
                     ecosystem=ecosystem, current_class=current_class)

    sets_out = []
    for cs in cs_results:
        parts_out = []
        # Group by category, ưu tiên is_mandatory=True, lấy tối đa 3 Tip + 1 mỗi cat khác
        from collections import defaultdict

        by_cat = defaultdict(list)
        for p in cs.parts:
            cat = p.get("part_role") or p.get("category", "OTHER")
            by_cat[cat].append(p)
        CAT_ORDER = ["TipBody","Tip","Nozzle","Insulator","Orifice","Liner","InnerTube","LinerORing","InsulationCollar","PowerCable","TorchBody"]
        seen_cats = set()
        for cat in CAT_ORDER:
            if cat not in by_cat:
                continue
            items = sorted(by_cat[cat], key=lambda x: (not x.get("is_mandatory", True)))
            limit = 3 if cat in ("Tip", "TipBody", "Nozzle") else 1
            for p in items[:limit]:
                resp = _part_to_response(p)
                resp["is_mandatory"] = p.get("is_mandatory", True)
                resp["part_role"] = cat
                parts_out.append(resp)
        # Thêm các cat còn lại không trong CAT_ORDER
        for cat, items in by_cat.items():
            if cat not in CAT_ORDER:
                p = items[0]
                resp = _part_to_response(p)
                resp["is_mandatory"] = p.get("is_mandatory", True)
                resp["part_role"] = cat
                parts_out.append(resp)
        # Merge CS items cho các cat còn thiếu
        existing_cats = {p.get("part_role") for p in parts_out}
        for p in cs.parts:
            cat = p.get("part_role") or p.get("category", "OTHER")
            if cat not in existing_cats:
                resp = _part_to_response(p)
                resp["is_mandatory"] = p.get("is_mandatory", True)
                resp["part_role"] = cat
                parts_out.append(resp)
                existing_cats.add(cat)

        sets_out.append({
            "set_id":          cs.set_id,
            "display_name_vi": cs.set_name,
            "ecosystem":       cs.ecosystem,
            "current_class":   cs.torch_current_class,
            "parts":           parts_out,
            "found":           cs.found,
        })

    return _ok({
        "sets":       sets_out,
        "torch_info": torch_info,
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — find_upsell_companions
# ══════════════════════════════════════════════════════════════════════════════

def find_upsell_companions(
    part_no: str = "",
    exclude_categories: Optional[List[str]] = None,
    include_categories: Optional[List[str]] = None,
    description: Optional[str] = None,
    torch_model: Optional[str] = None,
    page: int = 1,
) -> dict:
    """
    Tìm linh kiện đi kèm với part đã có.
    Graph RAG: hỗ trợ torch_model trực tiếp + 2-hop traversal.

    Returns:
        {
          success: bool,
          data: {
            anchor: {tokin_part_no, display_name_vi, category, ecosystem, current_class},
            companions: List[{...part + is_mandatory + part_role}],
            companions_by_role: {role: [parts]},
            source_steps: List[str],
            found: bool
          }
        }
    """
    # Normalize exclude_categories: LLM đôi khi truyền string thay vì list
    if isinstance(exclude_categories, str):
        import ast as _ast_local
        try:
            _v = _ast_local.literal_eval(exclude_categories)
            exclude_categories = _v if isinstance(_v, list) else [str(_v)]
        except Exception:
            _cleaned = exclude_categories.strip().strip("[]")
            exclude_categories = [s.strip().strip(chr(39)).strip(chr(34))
                                  for s in _cleaned.split(",") if s.strip()]

    gt = _get_gt()

    # ── Graph RAG: torch_model path ──────────────────────────────────────────
    # Khi user hỏi "súng TK-308RR cần thêm gì" — không cần part_no
    if torch_model and not part_no:
        result = gt.resolve_upsell_torch(
            torch_model  = torch_model,
            exclude_cats = exclude_categories or [],
        )
        if result.found:
            companions_out = []
            by_role: dict  = {}
            for p in result.companions:
                resp = _part_to_response(p)
                resp["is_mandatory"]  = p.get("is_mandatory", True)
                resp["part_role"]     = p.get("role") or p.get("category", "")
                resp["relation_type"] = p.get("relation_type", "compatible_with")
                companions_out.append(resp)
                role = resp["part_role"] or "other"
                by_role.setdefault(role, []).append(resp)
            return _ok({
                "anchor":             {"torch_model": torch_model,
                                       "ecosystem":   result.anchor_ecosystem,
                                       "current_class": result.anchor_current_class},
                "companions":         companions_out,
                "companions_by_role": by_role,
                "source_steps":       result.source_steps,
                "found":              True,
                "total":              len(companions_out),
                "_graph_rag":         "torch_level",
            })
        # Fallback: dùng get_consumable_set nếu torch traverse không có kết quả
        log.info(f"[find_upsell_companions] torch_model={torch_model} no TPM → fallback consumable_set")
        return get_consumable_set(torch_model=torch_model)

    # Fix: nếu không có part_no nhưng có description → tự search_parts
    if not part_no and description:
        sr = search_parts(query=description)
        sr_parts = (sr.get("data") or {}).get("parts", [])
        if sr_parts:
            part_no = sr_parts[0].get("tokin_part_no", "")
            log.info(f"[find_upsell_companions] description='{description}' → resolved part_no={part_no}")
    if not part_no:
        return _fail("MISSING_PART_NO")

    cer = _get_cer()
    gt  = _get_gt()

    # FIX: nếu part_no không resolve được → thử lookup để detect external alias
    # Ví dụ: "U4167G01 cần béc gì" → part_no="U4167G01" → resolve → "001002"
    canonical = cer.resolve_part_no(part_no)
    if not canonical:
        # Try DS alias maps directly
        ds = _get_ds()
        canonical = (ds.p_alias.get(part_no.upper()) or
                     ds.d_alias.get(part_no.upper()) or
                     ds.p_model_alias.get(part_no.upper()) or
                     ds.d_model_alias.get(part_no.upper()))
    # v19: fake_pno_aliases fallback
    if not canonical:
        _ds2 = _get_ds()
        if hasattr(_ds2, 'fake_pno_aliases'):
            _fk = _ds2.fake_pno_aliases.get(part_no)
            if _fk and _fk.get("primary"):
                canonical = _fk["primary"]
                log.info(f"[find_upsell] fake_pno {part_no} → {canonical}")
    if not canonical:
        return _fail(f"NOT_FOUND:{part_no}")

    # Get anchor info
    anchor_part = cer.get_part(canonical)
    anchor_info = {
        "tokin_part_no":   canonical,
        "display_name_vi": anchor_part.display_name_vi if anchor_part else canonical,
        "category":        anchor_part.category if anchor_part else "",
        "ecosystem":       anchor_part.ecosystem if anchor_part else "",
        "current_class":   anchor_part.current_class if anchor_part else "",
    }
    if part_no != canonical:
        anchor_info["resolved_from"] = part_no

    # ── Graph RAG: 2-hop traversal ────────────────────────────────────────────
    result = gt.resolve_upsell_2hop(
        part_no      = canonical,
        exclude_cats = exclude_categories or [],
        max_anchors  = 5,
    )

    if not result.found:
        # ── PRIORITY FALLBACK 1: editorial_picks ─────────────────────────────
        ds = _get_ds()
        anchor_raw = ds.parts.get(canonical) if hasattr(ds, 'parts') else None

        if isinstance(anchor_raw, dict) and anchor_raw.get('editorial_picks'):
            picks = anchor_raw['editorial_picks']
            log.info(f"[find_upsell] {canonical} → editorial_picks fallback: {picks}")
            pick_companions = []
            by_role: dict = {}
            for pno in picks:
                ep_raw = ds.parts.get(pno) if hasattr(ds, 'parts') else None
                if not ep_raw:
                    continue
                resp = _part_to_response(ep_raw)
                resp['is_mandatory'] = True
                resp['part_role']    = ep_raw.get('category', '')
                resp['relation_type'] = 'editorial_pick'
                pick_companions.append(resp)
                role = resp['part_role'] or 'other'
                by_role.setdefault(role, []).append(resp)
            if pick_companions:
                return _ok({
                    'anchor':             anchor_info,
                    'companions':         pick_companions,
                    'companions_by_role': by_role,
                    'source_steps':       [f'editorial_picks:{canonical}'],
                    'found':              True,
                    'total':              len(pick_companions),
                    '_editorial_picks':   True,
                })

        # ── PRIORITY FALLBACK 2: consumable_set ──────────────────────────────
        # BUG-2 FIX: fallback sang consumable_set khi part không có compat edges
        # Thứ tự thử: (1) exact eco+cc, (2) cùng eco cc gần nhất, (3) eco N 350A default
        anchor_eco = anchor_info.get("ecosystem", "")
        anchor_cc  = anchor_info.get("current_class", "")
        anchor_cat = anchor_info.get("category", "")

        # Danh sách fallback eco+cc theo thứ tự ưu tiên
        _CC_FALLBACK = {"200A": "350A", "250A": "350A", "300A": "350A",
                        "400A": "500A", "450A": "500A", "700A": "500A"}
        fallback_targets = []
        if anchor_eco and anchor_cc:
            fallback_targets.append((anchor_eco, anchor_cc))
            # Nếu cc không có set → thử cc gần nhất
            fallback_cc = _CC_FALLBACK.get(anchor_cc.upper())
            if fallback_cc:
                fallback_targets.append((anchor_eco, fallback_cc))
        # Cuối cùng: N 350A (phổ biến nhất, luôn có set)
        if ("N", "350A") not in fallback_targets:
            fallback_targets.append(("N", "350A"))

        for fb_eco, fb_cc in fallback_targets:
            cs_result = get_consumable_set(ecosystem=fb_eco, current_class=fb_cc)
            if not cs_result.get("success"):
                continue
            fallback_companions = []
            for s in (cs_result.get("data", {}).get("sets") or []):
                for p in (s.get("parts") or []):
                    if p.get("part_role", "") != anchor_cat:
                        p["_fallback_source"] = "consumable_set"
                        fallback_companions.append(p)
            if fallback_companions:
                by_role: dict = {}
                for p in fallback_companions:
                    role = p.get("part_role") or p.get("category", "other")
                    by_role.setdefault(role, []).append(p)
                return _ok({
                    "anchor":             anchor_info,
                    "companions":         fallback_companions,
                    "companions_by_role": by_role,
                    "source_steps":       [f"consumable_set_fallback:{fb_eco}_{fb_cc}"],
                    "found":              True,
                    "total":              len(fallback_companions),
                    "_fallback":          True,
                    "_fallback_eco":      fb_eco,
                    "_fallback_cc":       fb_cc,
                })

        return _fail("NO_COMPANIONS_FOUND",
                     anchor=anchor_info,
                     hint="Thêm compat edges cho part này vào data để cải thiện")

    _anchor_eco = (anchor_info.get("ecosystem") or "").upper()
    _CROSS_ECO_SKIP = {
        ("WX","N"),("WX","D"),("N","D"),("D","N"),
        ("TIG","N"),("TIG","D"),("TIG","WX"),
        ("N","TIG"),("D","TIG"),("WX","TIG"),
    }
    companions_out = []
    # EDITORIAL_PICKS FILTER: nếu anchor có editorial_picks → lấy thẳng từ ds.parts
    # Không phụ thuộc vào graph traversal result
    ds = _get_ds()
    anchor_raw = ds.parts.get(canonical) if hasattr(ds, 'parts') else None
    ep_order = anchor_raw.get('editorial_picks', []) if isinstance(anchor_raw, dict) else []
    compat_all = anchor_raw.get('compatible_with', []) if isinstance(anchor_raw, dict) else []
    PAGE_SIZE = 8

    # page=1 → editorial_picks; page=2+ → compatible_with (trừ editorial_picks)
    if page >= 2 and compat_all:
        remaining = [pno for pno in compat_all if pno not in ep_order]
        start    = (page - 2) * PAGE_SIZE
        end      = start + PAGE_SIZE
        page_items = remaining[start:end]
        has_more   = end < len(remaining)

        page_companions = []
        by_role: dict = {}
        for pno in page_items:
            ep_raw = ds.parts.get(pno) if hasattr(ds, 'parts') else None
            if ep_raw and isinstance(ep_raw, dict):
                # Apply include_categories filter
                if include_categories:
                    if ep_raw.get('category', '') not in include_categories:
                        continue
                resp = _part_to_response(ep_raw)   # ← dùng _part_to_response để có giá
                resp['is_mandatory']  = False
                resp['part_role']     = ep_raw.get('category', '')
                resp['relation_type'] = 'compatible_with'
                page_companions.append(resp)
                role = ep_raw.get('category', 'other')
                by_role.setdefault(role, []).append(resp)

        total_remaining = len(remaining)
        shown_p2_so_far = min(end, total_remaining)
        log.info(f"[find_upsell] {canonical} page={page}: {len(page_companions)} parts, has_more={has_more} ({shown_p2_so_far}/{total_remaining})")
        return _ok({
            'anchor':             anchor_info,
            'companions':         page_companions,
            'companions_by_role': by_role,
            'source_steps':       [f'compatible_with_page{page}:{canonical}'],
            'found':              True,
            'total':              total_remaining,
            'page':               page,
            'has_more':           has_more,
            'shown_so_far':       len(ep_order) + shown_p2_so_far,
            'total_all':          len(ep_order) + total_remaining,
        })

    if ep_order:
        filtered_companions = []
        for pno in ep_order:
            ep_raw = ds.parts.get(pno) if hasattr(ds, 'parts') else None
            if ep_raw and isinstance(ep_raw, dict):
                if include_categories and ep_raw.get('category', '') not in include_categories:
                    continue
                ep_dict = dict(ep_raw)
                ep_dict['is_mandatory'] = True
                ep_dict['role'] = ep_dict.get('category', '')
                ep_dict['relation_type'] = 'editorial_pick'
                filtered_companions.append(ep_dict)

        # include_categories: nếu picks cho ít hơn PAGE_SIZE → bổ sung từ compatible_with
        if include_categories and len(filtered_companions) < PAGE_SIZE and compat_all:
            already = {p.get('tokin_part_no', '') for p in filtered_companions}
            for pno in compat_all:
                if pno in already:
                    continue
                ep_raw = ds.parts.get(pno) if hasattr(ds, 'parts') else None
                if not ep_raw or not isinstance(ep_raw, dict):
                    continue
                if ep_raw.get('category', '') not in include_categories:
                    continue
                ep_dict = dict(ep_raw)
                ep_dict['is_mandatory'] = False
                ep_dict['role'] = ep_dict.get('category', '')
                ep_dict['relation_type'] = 'compatible_with'
                filtered_companions.append(ep_dict)
                already.add(pno)
                if len(filtered_companions) >= PAGE_SIZE:
                    break
            log.info(f"[find_upsell] {canonical} include={include_categories} expanded: {len(filtered_companions)}")

        log.info(f"[find_upsell] {canonical} editorial_picks: {len(ep_order)} picks → {len(filtered_companions)} found: {ep_order}")
        result_companions = filtered_companions
    else:
        result_companions = result.companions

    for p in result_companions:
        _comp_eco = (p.get("ecosystem") or "").upper()
        if _anchor_eco and _comp_eco and _comp_eco not in ("UNIVERSAL","HYBRID"):
            if (_comp_eco, _anchor_eco) in _CROSS_ECO_SKIP:
                continue
        resp = _part_to_response(p)
        resp["is_mandatory"] = p.get("is_mandatory", True)
        resp["part_role"]    = p.get("role") or p.get("category", "")
        resp["relation_type"] = p.get("relation_type", "compatible_with")
        companions_out.append(resp)

    # Rebuild companions_by_role với response format
    by_role: dict = {}
    for p in companions_out:
        role = p.get("part_role") or p.get("category", "other")
        by_role.setdefault(role, []).append(p)

    return _ok({
        "anchor":             anchor_info,
        "companions":         companions_out,
        "companions_by_role": by_role,
        "source_steps":       result.source_steps,
        "found":              True,
        "total":              len(companions_out),
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — find_replacement
# ══════════════════════════════════════════════════════════════════════════════

def find_replacement(part_no: str = "", description: Optional[str] = None) -> dict:
    """
    Tìm mã Tokin thay thế cho mã hãng khác (Panasonic/Daihen/OTC)
    hoặc tìm alternate part khi discontinued.

    Returns:
        {
          success: bool,
          data: {
            source_code: str,
            source_brand: str | None,
            tokin_part: {...full part},
            spec_note: str,        # "tương đương kỹ thuật"
            alternatives: List[...] # replaces edges nếu có
          }
        }
    """
    # Fix: nếu không có part_no nhưng có description → tự search_parts
    if not part_no and description:
        sr = search_parts(query=description)
        sr_parts = (sr.get("data") or {}).get("parts", [])
        if sr_parts:
            part_no = sr_parts[0].get("tokin_part_no", "")
            log.info(f"[find_replacement] description='{description}' → resolved part_no={part_no}")
    if not part_no:
        return _fail("MISSING_PART_NO")

    cer = _get_cer()
    ds  = _get_ds()

    # Detect brand từ prefix
    pn_upper = part_no.upper()
    brand = None
    if any(pn_upper.startswith(p) for p in ("TET", "TGN", "TFZ", "TCU", "TCN")):
        brand = "Panasonic"
    elif any(pn_upper.startswith(p) for p in ("K", "L", "DAH", "U5", "U6", "U2")):
        brand = "Daihen"
    elif pn_upper.startswith("U4"):
        brand = "Daihen/OTC"
    elif any(pn_upper.startswith(p) for p in ("060-", "050-", "060", "050")):
        brand = "OTC"

    # Try alias resolution
    tokin = cer.resolve_part_no(part_no)

    if tokin and tokin in ds.parts:
        part_dict = ds.parts[tokin]
        resp = _part_to_response(part_dict)

        # Build spec note
        cat  = part_dict.get("category", "")
        eco  = part_dict.get("ecosystem", "")
        spec_parts = []
        if part_dict.get("wire_size_mm"):
            spec_parts.append(f"dây {part_dict['wire_size_mm']}mm")
        if part_dict.get("thread_type"):
            spec_parts.append(f"ren {part_dict['thread_type']}")
        if part_dict.get("material"):
            spec_parts.append(part_dict["material"])
        spec_note = f"{cat} hệ {eco}" + (f" — {', '.join(spec_parts)}" if spec_parts else "")

        # Find alternatives via replaces edges
        alternatives = []
        for edge in ds._compat_edges:
            if edge.get("relation_type") == "replaces":
                if edge.get("from_part") == tokin or edge.get("to_part") == tokin:
                    alt_pno = edge.get("to_part") if edge.get("from_part") == tokin else edge.get("from_part")
                    if alt_pno and alt_pno != tokin and alt_pno in ds.parts:
                        alternatives.append(_part_to_response(ds.parts[alt_pno]))

        return _ok({
            "source_code":  part_no,
            "source_brand": brand,
            "tokin_part":   resp,
            "spec_note":    spec_note,
            "alternatives": alternatives[:3],
        })

    # Part không phải alias — kiểm tra nếu là Tokin part đang tìm alternate
    if part_no in ds.parts:
        part_dict = ds.parts[part_no]
        # Tìm replaces edges
        alternatives = []
        for edge in ds._compat_edges:
            if edge.get("relation_type") == "replaces":
                if edge.get("from_part") == part_no:
                    alt_pno = edge.get("to_part")
                    if alt_pno and alt_pno in ds.parts:
                        alternatives.append(_part_to_response(ds.parts[alt_pno]))
        if alternatives:
            return _ok({
                "source_code":  part_no,
                "source_brand": "Tokin",
                "tokin_part":   _part_to_response(part_dict),
                "spec_note":    "Tìm thấy hàng thay thế",
                "alternatives": alternatives[:3],
            })
        return _ok({
            "source_code":  part_no,
            "source_brand": "Tokin",
            "tokin_part":   _part_to_response(part_dict),
            "spec_note":    "Mã Tokin chuẩn — không cần thay thế",
            "alternatives": [],
        })

    return _fail(f"NO_REPLACEMENT_FOUND:{part_no}",
                 hint="Mã không tìm thấy trong database. Kiểm tra lại mã hoặc liên hệ Autoss.")


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 6 — check_compatibility
# ══════════════════════════════════════════════════════════════════════════════

def check_compatibility(part_no_a: str, part_no_b: str,
                        description_a: Optional[str] = None,
                        description_b: Optional[str] = None) -> dict:
    """
    Kiểm tra 2 parts có tương thích không.

    Returns:
        {
          success: bool,
          data: {
            part_a: {tokin_part_no, display_name_vi, category, ecosystem},
            part_b: {...},
            compatible: bool,
            reason: str,          # lý do kỹ thuật cụ thể
            rule_id: str | None,  # negative rule áp dụng
            direct_compat: bool,  # có trong compatible_with list không
          }
        }
    """
    # Fix: resolve từ description nếu không có part_no
    if not part_no_a and description_a:
        sr = search_parts(query=description_a)
        parts_a = (sr.get("data") or {}).get("parts", [])
        if parts_a:
            part_no_a = parts_a[0].get("tokin_part_no", "")
    if not part_no_b and description_b:
        sr = search_parts(query=description_b)
        parts_b = (sr.get("data") or {}).get("parts", [])
        if parts_b:
            part_no_b = parts_b[0].get("tokin_part_no", "")
    if not part_no_a or not part_no_b:
        return _fail("MISSING_PART_NOS")

    cer = _get_cer()
    ds  = _get_ds()

    # Resolve cả 2
    pno_a = cer.resolve_part_no(part_no_a) or part_no_a
    pno_b = cer.resolve_part_no(part_no_b) or part_no_b

    # Delegate về DataStore._check_two_parts() — logic đầy đủ nhất
    result = ds._check_two_parts(pno_a, pno_b)

    if not result["success"]:
        return _fail(result.get("reason", "CHECK_FAILED"),
                     part_no_a=pno_a, part_no_b=pno_b)

    data = result["data"]

    # Enrich với resolved_from nếu dùng alias
    if part_no_a != pno_a:
        if "part_a" in data:
            data["part_a"]["resolved_from"] = part_no_a
    if part_no_b != pno_b:
        if "part_b" in data:
            data["part_b"]["resolved_from"] = part_no_b

    return _ok(data)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 7 — compare_parts
# ══════════════════════════════════════════════════════════════════════════════

def compare_parts(
    part_no_a: str = "",
    part_no_b: str = "",
    description_a: Optional[str] = None,
    description_b: Optional[str] = None,
) -> dict:
    """
    So sánh chi tiết 2 parts.

    Returns:
        {
          success: bool,
          data: {
            part_a: {...full part},
            part_b: {...full part},
            differences: List[{field, value_a, value_b}],
            recommendation: str   # gợi ý dùng cái nào trong hoàn cảnh nào
          }
        }
    """
    # Fix: resolve từ description nếu không có part_no
    if not part_no_a and description_a:
        sr = search_parts(query=description_a)
        parts_a = (sr.get("data") or {}).get("parts", [])
        if parts_a:
            part_no_a = parts_a[0].get("tokin_part_no", "")
    if not part_no_b and description_b:
        sr = search_parts(query=description_b)
        parts_b = (sr.get("data") or {}).get("parts", [])
        if parts_b:
            part_no_b = parts_b[0].get("tokin_part_no", "")
    if not part_no_a or not part_no_b:
        return _fail("MISSING_PART_NOS")

    cer = _get_cer()
    ds  = _get_ds()

    pno_a = cer.resolve_part_no(part_no_a) or part_no_a
    pno_b = cer.resolve_part_no(part_no_b) or part_no_b

    da = ds.parts.get(pno_a)
    db = ds.parts.get(pno_b)

    # Try torch comparison
    if not da:
        da = ds.torches.get(pno_a)
    if not db:
        db = ds.torches.get(pno_b)

    if not da:
        return _fail(f"NOT_FOUND:{pno_a}")
    if not db:
        return _fail(f"NOT_FOUND:{pno_b}")

    ra = _part_to_response(da) if da.get("tokin_part_no") else _torch_to_response(da)
    rb = _part_to_response(db) if db.get("tokin_part_no") else _torch_to_response(db)

    # Build differences list
    COMPARE_FIELDS = [
        "category", "ecosystem", "current_class", "wire_size_mm",
        "total_length_mm", "thread_type", "material",
        "inner_dia_mm", "outer_dia_mm", "length_mm",
        "insulator_class", "supported_processes",
        "price_vnd", "price_display",
    ]
    diffs = []
    for f in COMPARE_FIELDS:
        va = ra.get(f)
        vb = rb.get(f)
        if va != vb and (va is not None or vb is not None):
            diffs.append({"field": f, "value_a": va, "value_b": vb})

    # Simple recommendation
    rec = ""
    eco_a = da.get("ecosystem", "")
    eco_b = db.get("ecosystem", "")
    if eco_a != eco_b:
        rec = f"Khác hệ ({eco_a} vs {eco_b}) — không thay thế lẫn nhau được."
    elif da.get("wire_size_mm") and db.get("wire_size_mm"):
        wa, wb = da["wire_size_mm"], db["wire_size_mm"]
        if wa != wb:
            rec = f"{pno_a} dùng cho dây {wa}mm, {pno_b} dùng cho dây {wb}mm."
    elif da.get("category") == db.get("category") == "Nozzle":
        ia = da.get("inner_dia_mm", 0)
        ib = db.get("inner_dia_mm", 0)
        if ia != ib:
            rec = (f"{pno_a} (∅{ia}mm) dùng cho coverage {'rộng' if ia >= 16 else 'hẹp'}, "
                   f"{pno_b} (∅{ib}mm) dùng cho coverage {'rộng' if ib >= 16 else 'hẹp'}.")

    return _ok({
        "part_a":         ra,
        "part_b":         rb,
        "differences":    diffs,
        "recommendation": rec or "Xem spec chi tiết để quyết định.",
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 8 — get_torches
# ══════════════════════════════════════════════════════════════════════════════

def get_torches(
    ecosystem: Optional[str] = None,
    current_class: Optional[str] = None,
    torch_type: Optional[str] = None,
    robot_model: Optional[str] = None,
) -> dict:
    """
    Liệt kê model súng hàn theo bộ lọc.

    Returns:
        {
          success: bool,
          data: {
            torches: List[torch_response],
            total: int,
            filters_applied: dict
          }
        }
    """
    ds = _get_ds()
    results = list(ds.torches.values())

    eco_upper = (ecosystem or "").upper()
    cc_upper  = (current_class or "").upper()
    type_lower = (torch_type or "").lower()

    if eco_upper:
        results = [t for t in results
                   if (t.get("ecosystem") or "").upper() == eco_upper]

    if cc_upper:
        results = [t for t in results
                   if (t.get("current_class") or "").upper() == cc_upper]

    if type_lower:
        results = [t for t in results
                   if (t.get("torch_type") or "").lower() == type_lower]

    if robot_model:
        # Word-boundary match + alias resolve ('1.4m'/'1440' -> MA1440).
        # Tránh substring khiến '1440' khớp nhầm 'AR1440E'.
        results = [t for t in results if _robot_match(t, robot_model)]

    results.sort(key=lambda t: (
        t.get("ecosystem", ""),
        t.get("current_class", ""),
        t.get("model_code", ""),
    ))

    if not results:
        # Soft-fail retry: nếu strict filter ra empty và torch_type là 1 trong các filter,
        # thử lại bỏ torch_type. Lý do: 28% torches trong data có torch_type=None
        # (vd toàn bộ Yaskawa-compatible YMENS + TR series). Planner LLM hay đoán
        # torch_type khi user không nói → over-specify → reject hợp lệ records.
        # Chỉ retry khi còn ít nhất 1 filter khác để tránh trả full list 121 torches.
        if torch_type and (ecosystem or current_class or robot_model):
            log.info(
                f"[get_torches] strict filter empty (torch_type={torch_type!r}); "
                f"retrying without torch_type"
            )
            retry = get_torches(
                ecosystem=ecosystem,
                current_class=current_class,
                torch_type=None,
                robot_model=robot_model,
            )
            if retry.get("success") and isinstance(retry.get("data"), dict):
                retry["data"]["retry_dropped"] = ["torch_type"]
            return retry

        # Soft-fail retry 2: drop ecosystem khi robot_model đã đủ xác định.
        # Lý do: Planner đôi khi tự thêm ecosystem="N" không cần thiết, làm miss
        # súng HYBRID (TK-308RW, TK-309R1 eco=HYBRID) dù match đúng robot MA1440.
        if ecosystem and robot_model and not torch_type:
            log.info(
                f"[get_torches] ecosystem+robot_model empty (eco={ecosystem!r}); "
                f"retrying without ecosystem"
            )
            retry2 = get_torches(
                ecosystem=None,
                current_class=current_class,
                torch_type=None,
                robot_model=robot_model,
            )
            if retry2.get("success") and isinstance(retry2.get("data"), dict):
                retry2["data"]["retry_dropped"] = ["ecosystem"]
            return retry2

        return _fail("NO_TORCHES_FOUND", filters={
            "ecosystem": ecosystem, "current_class": current_class,
            "torch_type": torch_type, "robot_model": robot_model,
        })

    return _ok({
        "torches": [_torch_to_response(t) for t in results[:50]],
        "total":   len(results),
        "filters_applied": {
            k: v for k, v in {
                "ecosystem": ecosystem, "current_class": current_class,
                "torch_type": torch_type, "robot_model": robot_model,
            }.items() if v
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 9 — get_troubleshoot
# ══════════════════════════════════════════════════════════════════════════════

def get_troubleshoot(
    symptom: str = "",
    ecosystem: Optional[str] = None,
    torch_model: Optional[str] = None,
) -> dict:
    """
    Tra cứu hướng dẫn troubleshoot theo triệu chứng.
    AssemblyKB (structured) → ds._repair() (text-match) fallback.
    """
    if not symptom:
        return _fail("MISSING_SYMPTOM")

    ds = _get_ds()
    kb = _get_kb()

    # ── Path A: AssemblyKB — structured causes + actions ─────────────────────
    if kb is not None:
        try:
            ts_list = kb.get_troubleshooting(symptom_query=symptom)
            if ts_list:
                # Lấy best match (first) + warning nếu có
                best = ts_list[0]
                warnings_out = []
                if torch_model:
                    for w in kb.get_warnings(torch_model=torch_model, severity_min="medium"):
                        warnings_out.append(w.message if hasattr(w, "message") else str(w))

                # Enrich related_parts từ DataStore
                related_parts_out = []
                for p_ref in (getattr(best, "related_parts", None) or []):
                    pno = p_ref if isinstance(p_ref, str) else p_ref.get("tokin_part_no", "")
                    if pno and pno in ds.parts:
                        related_parts_out.append(_part_to_response(ds.parts[pno]))

                result = {
                    "symptom_vi":    getattr(best, "symptom", symptom),
                    "causes":        getattr(best, "likely_causes", []) or getattr(best, "causes", []),
                    "actions":       getattr(best, "recommended_actions", []) or getattr(best, "actions", []),
                    "related_parts": related_parts_out,
                    "source":        "assembly_kb",
                }
                if warnings_out:
                    result["warnings"] = warnings_out
                # Thêm các entries khác (nếu có nhiều match)
                if len(ts_list) > 1:
                    result["other_matches"] = [
                        {
                            "symptom": getattr(t, "symptom", ""),
                            "causes":  (getattr(t, "likely_causes", None) or [])[:2],
                        }
                        for t in ts_list[1:4]
                    ]
                return _ok(result)
        except Exception as _kb_err:
            log.debug(f"[get_troubleshoot] AssemblyKB failed: {_kb_err} — fallback ds._repair()")

    # ── Path B: DataStore text-match fallback ─────────────────────────────────
    e: dict = {
        "_raw_query":   symptom,
        "ecosystem":    ecosystem or "",
        "torch_models": [torch_model] if torch_model else [],
        "categories":   [],
        "_symptom_raw": symptom,  # FIX: pass raw symptom for keyword matching
    }
    result = ds._repair(e)

    if not result["success"]:
        return _fail("TROUBLESHOOT_FAILED")

    data = result["data"]
    related_parts_out = []
    for p in (data.get("related_parts") or []):
        if isinstance(p, dict) and p.get("tokin_part_no"):
            related_parts_out.append(_part_to_response(p))

    ts = data.get("troubleshooting")
    if ts:
        return _ok({
            "symptom_vi":    ts.get("symptom_vi", symptom),
            "causes":        ts.get("causes", []),
            "actions":       ts.get("actions", []),
            "related_parts": related_parts_out,
            "source":        "data_store",
        })

    all_ts = data.get("all_troubleshooting") or []
    return _ok({
        "symptom_vi":       symptom,
        "causes":           [],
        "actions":          ["Vui lòng mô tả triệu chứng cụ thể hơn để em chẩn đoán chính xác ạ"],
        "related_parts":    related_parts_out,
        "source":           "data_store",
        "all_troubleshooting": [
            {
                "id":      t.get("id", ""),
                "symptom": t.get("symptom", ""),
                "causes":  t.get("likely_causes", [])[:2],
            }
            for t in all_ts[:8]
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 10 — get_liner_length
# ══════════════════════════════════════════════════════════════════════════════

def get_liner_length(
    torch_model: Optional[str] = None,
    wire_size:   Optional[str] = None,
) -> dict:
    """
    Tra cứu chiều dài liner (ống dẫn dây) theo model súng và cỡ dây.
    Dùng khi user hỏi: 'liner TK-308RR dài bao nhiêu', 'ống lót dây 1.2mm cần cắt mấy cm'.

    Returns:
        {
          success: bool,
          data: {
            entries: List[{torch_model, wire_size, length_mm, protrusion_mm, note}],
            protrusion: dict | None,   # liner protrusion spec nếu có
            inner_tube:  List[dict],   # inner tube length nếu có
          }
        }
    """
    kb = _get_kb()
    if kb is None:
        return _fail("ASSEMBLY_KB_NOT_AVAILABLE",
                     hint="AssemblyKB chưa được khởi tạo — kiểm tra assembly_procedures.json")

    try:
        entries = kb.get_liner_length(torch_model=torch_model, wire_size=wire_size)
        entries_out = []
        for e in entries:
            if hasattr(e, "to_dict"):
                entries_out.append(e.to_dict())
            elif isinstance(e, dict):
                entries_out.append(e)

        protrusion = None
        if torch_model:
            raw_prot = kb.get_liner_protrusion(torch_model)
            if raw_prot:
                protrusion = raw_prot if isinstance(raw_prot, dict) else vars(raw_prot)

        inner_tube = []
        if torch_model:
            raw_it = kb.get_inner_tube_length(torch_model)
            if raw_it:
                inner_tube = [
                    (t.to_dict() if hasattr(t, "to_dict") else t)
                    for t in raw_it
                ]

        if not entries_out and not protrusion and not inner_tube:
            return _fail("NO_LINER_DATA",
                         torch_model=torch_model, wire_size=wire_size,
                         hint="Thử bỏ bộ lọc wire_size hoặc kiểm tra tên model súng")

        return _ok({
            "entries":    entries_out,
            "protrusion": protrusion,
            "inner_tube": inner_tube,
        })
    except Exception as e:
        log.exception(f"[get_liner_length] error: {e}")
        return _fail(f"LINER_ERROR:{e}")


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 11 — get_replacement_steps
# ══════════════════════════════════════════════════════════════════════════════

def get_replacement_steps(
    category:    str,
    torch_model: Optional[str] = None,
) -> dict:
    """
    Hướng dẫn từng bước thay thế linh kiện (tip, liner, nozzle, inner tube...).
    Dùng khi user hỏi: 'cách thay béc', 'quy trình thay liner TK-308RR',
    'thay insulator như thế nào', 'torque vặn béc bao nhiêu'.

    Returns:
        {
          success: bool,
          data: {
            procedures: List[{name, steps:[{order, description, part_role, torque}], warnings}],
            torque_spec: {value_display, tool_recommended, warning} | None,
          }
        }
    """
    kb = _get_kb()
    if kb is None:
        return _fail("ASSEMBLY_KB_NOT_AVAILABLE",
                     hint="AssemblyKB chưa được khởi tạo")

    if not category:
        return _fail("MISSING_CATEGORY",
                     hint="Cần biết loại linh kiện: Tip/Liner/Nozzle/InnerTube/Insulator")
    try:
        procedures = kb.get_replacement_procedure(
            category    = category,
            torch_model = torch_model,
        )

        procs_out = []
        for rp in procedures[:3]:  # cap 3 procedures
            proc_dict = rp.to_dict() if hasattr(rp, "to_dict") else (rp if isinstance(rp, dict) else vars(rp))
            # Format steps gọn
            steps_raw = proc_dict.get("steps") or []
            steps_out = []
            for s in steps_raw:
                if hasattr(s, "to_dict"):
                    s = s.to_dict()
                elif not isinstance(s, dict):
                    s = vars(s)
                steps_out.append({
                    "order":       s.get("order", 0),
                    "description": s.get("description", ""),
                    "part_role":   s.get("part_role", ""),
                    "torque":      s.get("torque_spec", ""),
                    "warning":     s.get("warning", ""),
                })
            proc_dict["steps"] = steps_out
            procs_out.append(proc_dict)

        # Torque spec cho category
        torque = kb.get_torque_spec(category=category)
        torque_out = None
        if torque:
            torque_out = {
                "value_display":    torque.value_display if hasattr(torque, "value_display") else "",
                "tool_recommended": torque.tool_recommended if hasattr(torque, "tool_recommended") else "",
                "warning":          torque.warning if hasattr(torque, "warning") else "",
            }

        if not procs_out and not torque_out:
            return _fail("NO_PROCEDURE_FOUND",
                         category=category, torch_model=torch_model,
                         hint="Thử dùng tên category tiếng Anh: Tip/Liner/Nozzle/InnerTube")

        # Inject related_parts theo category để Gemini có mã để mention.
        # FILTERED by torch_model.ecosystem + current_class để tránh mix 350A/500A
        # hoặc cross-ecosystem (bug fix: 2026-06 — YMSA-508R không được kèm 308RR).
        _CATEGORY_PARTS = {
            "Tip":       ["002001","002002","002003","002005","002017","002004"],
            "Nozzle":    ["001002","033203","001001","001010","001005","001008","001013"],
            "Liner":     ["016051","016076","016126","037002","037003","036001","036003"],
            "InnerTube": ["016053","016054","016505"],
            "Insulator": ["004002","004001","023015"],
            "TipBody":   ["036001","016403","016051","016503"],
            "Orifice":   ["003002","003001","023014"],
        }

        ds = _get_ds()

        # Resolve torch_model -> (ecosystem, current_class)
        torch_eco, torch_cc = "", ""
        if torch_model:
            try:
                cer = _get_cer()
                t_obj = cer.resolve_torch(torch_model) if hasattr(cer, "resolve_torch") else None
                if t_obj is None and hasattr(ds, "torches") and isinstance(ds.torches, dict):
                    t_obj = ds.torches.get(torch_model)
                if t_obj is not None:
                    _get = (t_obj.get if isinstance(t_obj, dict)
                            else (lambda k, d=None: getattr(t_obj, k, d)))
                    torch_eco = (_get("ecosystem", "") or "").upper()
                    torch_cc  = (_get("current_class", "") or "").upper()
            except Exception as _e:
                log.debug(f"[get_replacement_steps] torch resolution failed: {_e}")

        # Current-class banding — torch 300A có thể nhận parts 350A, v.v.
        _CC_BAND = {
            "200A": {"200A","350A"}, "250A": {"250A","350A"},
            "300A": {"300A","350A"}, "400A": {"400A","350A","500A"},
            "450A": {"450A","500A"},
        }
        cc_accept = _CC_BAND.get(torch_cc, {torch_cc}) if torch_cc else set()

        def _part_compatible(p: dict) -> bool:
            """Giữ part nếu khớp eco + cc của torch (hoặc UNIVERSAL/HYBRID)."""
            if not torch_eco and not torch_cc:
                return True  # No context → keep all (backward compat)
            p_eco = (p.get("ecosystem") or "").upper()
            p_cc  = (p.get("current_class") or "").upper()
            if torch_eco and p_eco and p_eco not in ("UNIVERSAL","HYBRID"):
                if p_eco != torch_eco:
                    return False
            if cc_accept and p_cc and p_cc != "UNIVERSAL":
                if p_cc not in cc_accept:
                    return False
            return True

        related_parts_out = []
        skipped = []
        for pno in _CATEGORY_PARTS.get(category, _CATEGORY_PARTS.get(category.lower(), [])):
            p = ds.parts.get(pno)
            if not p:
                continue
            if _part_compatible(p):
                related_parts_out.append(_part_to_response(p))
            else:
                skipped.append(pno)

        if skipped:
            log.info(
                f"[get_replacement_steps] torch={torch_model} eco={torch_eco} "
                f"cc={torch_cc} category={category} skipped_incompatible={skipped}"
            )

        # Safety net: nếu filter quá khắt → fallback về unfiltered (better than empty)
        if not related_parts_out:
            log.warning(
                f"[get_replacement_steps] no compatible parts for torch={torch_model} "
                f"category={category} — falling back to unfiltered list"
            )
            for pno in _CATEGORY_PARTS.get(category, _CATEGORY_PARTS.get(category.lower(), [])):
                if pno in ds.parts:
                    related_parts_out.append(_part_to_response(ds.parts[pno]))

        return _ok({
            "procedures":    procs_out,
            "torque_spec":   torque_out,
            "related_parts": related_parts_out,
            "category":      category,
            "torch_model":   torch_model,
        })
    except Exception as e:
        log.exception(f"[get_replacement_steps] error: {e}")
        return _fail(f"PROCEDURE_ERROR:{e}")


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 12 — capture_lead (ghi lead về CRM, một chiều)
# ══════════════════════════════════════════════════════════════════════════════

def check_stock(part_no: str = "", part_nos: str = "") -> dict:
    """Tool 13 — Hỏi TÌNH TRẠNG còn hàng (thô) của 1 hay nhiều mã part.

    Trả: Còn hàng / Sắp hết hàng / Hết hàng / Liên hệ. KHÔNG có số lượng chính xác.
    Dùng khi khách hỏi 'còn hàng không', 'có sẵn không'.
    """
    from core.stock_query import fetch_stock
    codes = [c.strip() for c in (part_nos or part_no).replace(";", ",").split(",") if c.strip()]
    if not codes:
        return _fail("Cần mã part để kiểm tra tồn.")
    data = fetch_stock(codes)
    if not data:
        return _fail("Chưa kết nối được kho. Vui lòng liên hệ nhân viên.")
    items = [{"part_no": c, "status": data.get(c, {}).get("label", "Liên hệ để biết"),
              "name": data.get(c, {}).get("name", "")} for c in codes]
    return _ok({"items": items})


def capture_lead(name: str = "", phone: str = "", company: str = "",
                 email: str = "", note: str = "", address: str = "",
                 tax_code: str = "", force: bool = False) -> dict:
    """Ghi LEAD về CRM khi khách CHỦ ĐỘNG để lại liên hệ (ghi-1-chiều, an toàn).

    KHÔNG đọc dữ liệu nội bộ. Chỉ gọi khi khách cung cấp tên/SĐT và muốn được
    tư vấn / báo giá / liên hệ lại. Thu thập đủ: tên, SĐT, công ty, địa chỉ, MST.
    force=True: đã năn nỉ 1 lần mà khách vẫn chỉ cho SĐT → VẪN lưu (chỉ với SĐT).
    """
    # NĂN NỈ XIN ĐỦ (1 LẦN): chưa lưu nếu mới có SĐT mà thiếu Tên công ty VÀ Địa chỉ.
    # Nhưng nếu force=True (đã năn nỉ rồi mà khách không cho thêm) → vẫn lưu.
    if (not force) and (phone or "").strip() and not ((company or "").strip() or (address or "").strip()):
        return _ok(
            {"saved": False, "need_more_info": True},
            message=("CHƯA lưu lead — khách mới cho SĐT, còn THIẾU Tên công ty + Địa chỉ. "
                     "Hãy NĂN NỈ MỘT LẦN, giọng dễ thương, hơi tội nghiệp: 'Anh/chị cho em xin "
                     "thêm họ tên, tên công ty và địa chỉ với ạ, không sếp lại nhắc em huhu 🙏'. "
                     "Nếu sau câu này khách vẫn không cho thêm / từ chối → gọi lại capture_lead "
                     "với force=true để vẫn lưu SĐT. TUYỆT ĐỐI chưa nói 'đã ghi nhận' lúc này."))

    from core.lead_capture import push_lead
    r = push_lead(name=name, phone=phone, company=company, email=email,
                  note=note, address=address, tax_code=tax_code)
    if r.get("success") is False or r.get("ok") is False:
        return _fail(f"LEAD_CAPTURE_FAILED:{r.get('error')}")
    return _ok({"saved": True, "lead_id": r.get("id")},
               message="Đã ghi nhận thông tin, bộ phận kinh doanh sẽ gọi ngay cho anh/chị.")


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER — map tool name → function
# ══════════════════════════════════════════════════════════════════════════════

TOOL_HANDLERS: Dict[str, callable] = {
    "lookup_part":           lookup_part,
    "search_parts":          search_parts,
    "get_consumable_set":    get_consumable_set,
    "find_upsell_companions": find_upsell_companions,
    "find_replacement":      find_replacement,
    "check_compatibility":   check_compatibility,
    "compare_parts":         compare_parts,
    "get_torches":           get_torches,
    "get_troubleshoot":      get_troubleshoot,
    "get_liner_length":      get_liner_length,       # Tool 10 — mới
    "get_replacement_steps": get_replacement_steps,  # Tool 11 — mới
    "capture_lead":          capture_lead,           # Tool 12 — đẩy lead về CRM
    "check_stock":           check_stock,            # Tool 13 — tình trạng còn hàng (thô)
}


def dispatch(tool_name: str, tool_args: dict) -> dict:
    """
    Dispatcher — gọi từ LLM orchestrator khi nhận function call.

    Args:
        tool_name: tên tool từ Gemini function call
        tool_args: arguments dict từ Gemini

    Returns:
        dict — serializable result cho LLM

    Usage:
        # Trong Gemini response handler:
        for part in response.parts:
            if part.function_call:
                result = dispatch(part.function_call.name,
                                  dict(part.function_call.args))
                # Gửi result về Gemini qua function_response
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return _fail(f"UNKNOWN_TOOL:{tool_name}",
                     available=list(TOOL_HANDLERS.keys()))
    try:
        result = handler(**tool_args)
        log.info(f"[dispatch] {tool_name}({list(tool_args.keys())}) → success={result.get('success')}")
        try:
            from core.confidence_layer import score_tool_result
            result = score_tool_result(tool_name, tool_args, result)
        except Exception as _ce:
            log.debug(f"[dispatch] confidence skip: {_ce}")
        return result
    except TypeError as e:
        log.error(f"[dispatch] {tool_name} arg error: {e}")
        return _fail(f"INVALID_ARGS:{e}", tool=tool_name, received=list(tool_args.keys()))
    except Exception as e:
        log.exception(f"[dispatch] {tool_name} error: {e}")
        return _fail(f"TOOL_ERROR:{type(e).__name__}:{e}", tool=tool_name)








