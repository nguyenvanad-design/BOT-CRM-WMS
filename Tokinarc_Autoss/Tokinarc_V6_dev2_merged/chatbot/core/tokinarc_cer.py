# core/tokinarc_cer.py
# TOKINARC CER — Compatibility & Entity Retrieval adapter
# =========================================================
# Wrap TokinarcDataStore để expose interface mà GraphTraversal cần.
#
# Vấn đề (C3): GraphTraversal gọi các method:
#   cer.get_part(part_no)           → PartResult object
#   cer.get_torch(model_code)       → TorchResult object
#   cer.get_compatible_parts(pno, relation_types=[...]) → List[(rel, PartResult)]
#   cer.get_consumable_set(current_class, ecosystem)    → List[ConsumableSetResult]
#   cer.get_parts_for_torch(torch_model)                → List[(TpmResult, PartResult)]
#   cer.resolve_part_no(code)       → canonical tokin_part_no or None
#   cer.search_parts(query, ...)    → List[(score, PartResult)]
#
# DataStore có data nhưng không expose các method này.
# CER là thin adapter: wrap DataStore, return lightweight result objects
# với attribute access mà GraphTraversal/graph_traversal._part_to_dict() đọc.
#
# Compatible với graph_traversal.py — _part_to_dict() đọc qua getattr():
#   part.tokin_part_no, part.display_name_vi, part.display_name_en,
#   part.category, part.ecosystem, part.current_class, part.wire_size_mm,
#   part.p_part_nos, part.d_part_nos, part.raw (business fields)
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tokinarc.cer")

# ── Lazy DataStore import (avoid circular at module level) ─────────────────────
_ds_instance = None

def _get_ds():
    global _ds_instance
    if _ds_instance is None:
        from data_store import get_data_store
        _ds_instance = get_data_store()
    return _ds_instance


# ══════════════════════════════════════════════════════════════════════════════
# Result dataclasses — lightweight wrappers around raw dicts
# GraphTraversal._part_to_dict() dùng getattr() nên cần attribute access
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PartResult:
    """
    Wrap 1 part dict thành object với attribute access.
    raw dict vẫn accessible qua .raw để backward compat.
    """
    tokin_part_no:   str
    display_name_vi: str
    display_name_en: str
    category:        str
    ecosystem:       str
    current_class:   str
    wire_size_mm:    Optional[float]
    p_part_nos:      List[str] = field(default_factory=list)
    d_part_nos:      List[str] = field(default_factory=list)
    o_part_nos:      List[str] = field(default_factory=list)
    compatible_with: List[str] = field(default_factory=list)
    editorial_picks: List[str] = field(default_factory=list)
    torch_models:    List[str] = field(default_factory=list)
    note:            str = ""
    raw:             Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "PartResult":
        biz = d.get("business") or {}
        return cls(
            tokin_part_no   = d.get("tokin_part_no", ""),
            display_name_vi = d.get("display_name_vi", ""),
            display_name_en = d.get("display_name_en", ""),
            category        = d.get("category", ""),
            ecosystem       = d.get("ecosystem", ""),
            current_class   = d.get("current_class", ""),
            wire_size_mm    = d.get("wire_size_mm"),
            p_part_nos      = list(d.get("p_part_nos") or []),
            d_part_nos      = list(d.get("d_part_nos") or []),
            o_part_nos      = list(d.get("o_part_nos") or []),
            compatible_with = list(d.get("compatible_with") or []),
            editorial_picks = list(d.get("editorial_picks") or []),
            torch_models    = list(d.get("torch_models") or []),
            note            = d.get("note", ""),
            raw             = d,
        )

    # GraphTraversal đọc business qua raw
    @property
    def price_vnd(self) -> Optional[int]:
        return (self.raw.get("business") or {}).get("price_vnd")

    @property
    def is_priority(self) -> bool:
        return bool((self.raw.get("business") or {}).get("is_priority_sell"))


@dataclass
class TorchResult:
    """Wrap 1 torch dict."""
    model_code:        str
    display_name_vi:   Optional[str]
    ecosystem:         str
    current_class:     str
    torch_type:        str
    cooling:           str
    rated_co2_a:       Optional[int]
    rated_mag_a:       Optional[int]
    duty_co2_pct:      Optional[int]
    wire_size:         Optional[str]
    robot_compatibility: Optional[Any]
    shock_sensor_type: str
    functional_requires: Optional[List[str]]
    coolant_unit_required: Optional[str]
    raw:               Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "TorchResult":
        return cls(
            model_code           = d.get("model_code", ""),
            display_name_vi      = d.get("display_name_vi"),
            ecosystem            = d.get("ecosystem", ""),
            current_class        = d.get("current_class", ""),
            torch_type           = d.get("torch_type", ""),
            cooling              = d.get("cooling", "air"),
            rated_co2_a          = d.get("rated_co2_a"),
            rated_mag_a          = d.get("rated_mag_a"),
            duty_co2_pct         = d.get("duty_co2_pct") or d.get("duty_cycle_pct"),
            wire_size            = d.get("wire_size"),
            robot_compatibility  = d.get("robot_compatibility"),
            shock_sensor_type    = d.get("shock_sensor_type", "NONE"),
            functional_requires  = d.get("functional_requires"),
            coolant_unit_required = d.get("coolant_unit_required"),
            raw                  = d,
        )


@dataclass
class ConsumableSetResult:
    """Wrap 1 consumable_set dict."""
    set_id:              str
    display_name_vi:     str
    torch_current_class: str
    ecosystem:           str
    cooling_method:      str
    default_wire_size_mm: float
    items:               List[dict] = field(default_factory=list)
    notes:               str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ConsumableSetResult":
        return cls(
            set_id               = d.get("set_id", ""),
            display_name_vi      = d.get("display_name_vi", ""),
            torch_current_class  = d.get("torch_current_class", ""),
            ecosystem            = d.get("ecosystem", ""),
            cooling_method       = d.get("cooling_method", "air"),
            default_wire_size_mm = d.get("default_wire_size_mm", 1.2),
            items                = list(d.get("items") or []),
            notes                = d.get("notes", ""),
        )


@dataclass
class TpmResult:
    """Wrap 1 torch_part_mapping row — dùng trong get_parts_for_torch."""
    torch_model:  str
    part_nos:     List[str]
    part_role:    str
    is_mandatory: bool
    ref_no:       Optional[str] = None

    @property
    def role(self) -> str:
        return self.part_role


# ══════════════════════════════════════════════════════════════════════════════
# CER — main adapter class
# ══════════════════════════════════════════════════════════════════════════════

class TokinarcCER:
    """
    Compatibility & Entity Retrieval — adapter layer trên TokinarcDataStore.

    GraphTraversal nhận instance này và gọi:
      get_part(), get_torch(), resolve_part_no(),
      get_compatible_parts(), get_consumable_set(),
      get_parts_for_torch(), search_parts()

    Tất cả methods đều delegate về DataStore._-indexes đã được build sẵn.
    Không query lại file JSON — chỉ đọc từ in-memory dicts.
    """

    def __init__(self, ds=None):
        """
        Args:
            ds: TokinarcDataStore instance. None = lazy load singleton.
        """
        self._ds = ds  # lazy: set khi cần
        # Cache raw data từ DataStore để tránh double dict lookup
        self._raw: Dict[str, Any] = {}

    @property
    def ds(self):
        if self._ds is None:
            self._ds = _get_ds()
        return self._ds

    # ── Raw data access (dùng bởi compatibility_matrix.py deprecated stub) ─────

    def _ensure_raw(self):
        if not self._raw:
            import json
            data_path = os.environ.get(
                "TOKINARC_DATA",
                getattr(self.ds, '_data_path', None) or
                os.path.join(os.path.dirname(__file__), "data", "tokinarc_data_v14.json")
            )
            try:
                with open(data_path, encoding="utf-8") as f:
                    self._raw = json.load(f)
            except FileNotFoundError:
                # Fallback: reconstruct từ DataStore indexes
                self._raw = {
                    "parts": list(self.ds.parts.values()),
                    "torches": list(self.ds.torches.values()),
                    "compatibility_edges": self.ds._compat_edges,
                    "torch_part_mappings": self.ds._tpms,
                    "negative_rules": self.ds._negative_rules,
                    "consumable_sets": self.ds._consumable_sets,
                    "process_edges": self.ds._process_edges,
                    "gas_flow_edges": getattr(self.ds, '_gas_flow_edges', []),
                    "category_vocabulary": self.ds._category_vocab,
                }

    # ── Part retrieval ──────────────────────────────────────────────────────────

    def get_part(self, part_no: str) -> Optional[PartResult]:
        """
        Lấy part theo mã — tự resolve Panasonic/Daihen/OTC alias.

        Returns:
            PartResult | None
        """
        if not part_no:
            return None
        ds = self.ds

        # 1. Direct Tokin lookup
        d = ds.parts.get(part_no)
        if d:
            return PartResult.from_dict(d)

        # 2. P-alias (TET..., TGN..., TFZ..., U...)
        tokin = ds.p_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 3. D-alias (K..., L..., DAH..., U4...)
        tokin = ds.d_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 4. P model code (YT-35CE, YT-50CS...)
        tokin = ds.p_model_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 5. D model code (WT3500, WTCX-3504...)
        tokin = ds.d_model_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 6. OTC model code (OMT-3, OMT-5...)
        tokin = ds.o_model_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 7. OTC part no (060-430, 050-035...)
        tokin = ds.o_part_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        # 8. Static model alias (TKS-RC, WF-120...)
        tokin = ds.model_alias.get(part_no.upper())
        if tokin and tokin in ds.parts:
            return PartResult.from_dict(ds.parts[tokin])

        return None

    def get_torch(self, model_code: str) -> Optional[TorchResult]:
        """
        Lấy torch theo model_code.

        Returns:
            TorchResult | None
        """
        if not model_code:
            return None
        d = self.ds.torches.get(model_code)
        if d:
            return TorchResult.from_dict(d)
        # Case-insensitive fallback
        mc_upper = model_code.upper()
        for k, v in self.ds.torches.items():
            if k.upper() == mc_upper:
                return TorchResult.from_dict(v)
        return None

    def resolve_part_no(self, code: str) -> Optional[str]:
        """
        Resolve bất kỳ code nào → canonical Tokin Part No.

        Dùng bởi GraphTraversal._resolve().

        Returns:
            6-digit Tokin string | None
        """
        if not code:
            return None
        ds = self.ds
        code_upper = code.upper()

        # Direct
        if code in ds.parts:
            return code

        # All alias maps
        for alias_map in (
            ds.p_alias, ds.d_alias,
            ds.p_model_alias, ds.d_model_alias,
            ds.o_model_alias, ds.o_part_alias,
            ds.model_alias,
        ):
            tokin = alias_map.get(code_upper)
            if tokin and tokin in ds.parts:
                return tokin

        return None

    # ── Compatibility graph ─────────────────────────────────────────────────────

    def get_compatible_parts(
        self,
        part_no: str,
        relation_types: Optional[List[str]] = None,
    ) -> List[Tuple[str, PartResult]]:
        """
        1-hop traverse qua compatibility_edges từ part_no.

        Args:
            part_no:        Tokin Part No. (canonical)
            relation_types: filter relation types — None = tất cả upsell types

        Returns:
            List of (relation_type: str, PartResult)
            Đây là format GraphTraversal.get_compat_edges() mong đợi.

        Implementation:
            Đọc từ ds._compat_edges (list[dict]) — đây là index nhanh nhất
            vì đã load sẵn vào memory. Không cần parse lại JSON.
        """
        ds = self.ds
        rel_filter = set(relation_types) if relation_types else None
        results: List[Tuple[str, PartResult]] = []
        seen: set = set()

        # Traverse từ compat_edges
        for edge in ds._compat_edges:
            rel = edge.get("relation_type", "compatible_with")

            # Filter relation type
            if rel_filter and rel not in rel_filter:
                continue

            from_p = edge.get("from_part", "")
            to_p   = edge.get("to_part", "")

            # Bidirectional cho compatible_with, assembled_with, functional_requires
            # Unidirectional cho replaces, belongs_to
            _BIDIRECTIONAL = {"compatible_with", "assembled_with", "functional_requires"}

            if from_p == part_no and to_p not in seen:
                part = self.get_part(to_p)
                if part:
                    seen.add(to_p)
                    results.append((rel, part))

            elif (rel in _BIDIRECTIONAL and
                  to_p == part_no and from_p not in seen):
                part = self.get_part(from_p)
                if part:
                    seen.add(from_p)
                    results.append((rel, part))

        # Fallback: compatible_with field trên part dict (denormalized)
        if not rel_filter or "compatible_with" in rel_filter:
            part_dict = ds.parts.get(part_no, {})
            for cid in (part_dict.get("compatible_with") or []):
                if cid not in seen and cid in ds.parts:
                    seen.add(cid)
                    p = self.get_part(cid)
                    if p:
                        results.append(("compatible_with", p))

        log.debug(f"[CER] get_compatible_parts({part_no}, rel={rel_filter}): {len(results)} results")
        return results

    # ── Consumable set ──────────────────────────────────────────────────────────

    def get_consumable_set(
        self,
        current_class: Optional[str] = None,
        ecosystem: Optional[str] = None,
    ) -> List[ConsumableSetResult]:
        """
        Lấy consumable set(s) theo ecosystem + current_class.

        Args:
            current_class: "350A", "500A"... (case-insensitive)
            ecosystem:     "N", "D", "WX"... (case-insensitive)

        Returns:
            List[ConsumableSetResult] — có thể nhiều set nếu match (N350A_standard + N350A_09wire)

        Implementation:
            Delegate về DataStore._lookup_consumable_set() rồi enrich,
            hoặc scan _consumable_sets trực tiếp nếu muốn trả nhiều sets.
        """
        ds = self.ds
        eco_upper = (ecosystem or "").upper()
        cc_upper  = (current_class or "").upper()

        # CC banding: 250A/300A → accept 350A; 450A → accept 500A
        _CC_BAND = {
            "200A": {"200A", "350A"},
            "250A": {"250A", "350A"},
            "300A": {"300A", "350A"},
            "400A": {"400A", "350A", "500A"},
            "450A": {"450A", "500A"},
        }
        cc_accept = _CC_BAND.get(cc_upper, {cc_upper}) if cc_upper else set()

        matched = []
        for cs_dict in ds._consumable_sets:
            cs_eco = (cs_dict.get("ecosystem") or "").upper()
            cs_cc  = (cs_dict.get("torch_current_class") or "").upper()

            eco_match = (not eco_upper) or (cs_eco == eco_upper)
            cc_match  = (not cc_upper) or (cs_cc in cc_accept)

            if eco_match and cc_match:
                # Enrich items với display_name_vi từ parts
                enriched_items = []
                for item in (cs_dict.get("items") or []):
                    pid  = item.get("part_id", "")
                    info = ds.parts.get(pid, {})
                    enriched_items.append({
                        **item,
                        "display_name_vi": info.get("display_name_vi", ""),
                        "category":        info.get("category", item.get("part_role", "")),
                        "ecosystem":       info.get("ecosystem", ""),
                        "business":        info.get("business") or {},
                    })
                cs_enriched = {**cs_dict, "items": enriched_items}
                matched.append(ConsumableSetResult.from_dict(cs_enriched))

        # Sort: N trước D trước WX (theo _ECO_PRIORITY)
        _ECO_ORDER = {"N": 0, "D": 1, "WX": 2, "HYBRID": 3, "TIG": 4, "TCC": 5}
        matched.sort(key=lambda s: _ECO_ORDER.get(s.ecosystem.upper(), 9))

        log.debug(f"[CER] get_consumable_set(eco={eco_upper}, cc={cc_upper}): {len(matched)} sets")
        return matched

    # ── Torch → Parts (TPM) ─────────────────────────────────────────────────────

    def get_parts_for_torch(
        self,
        torch_model: str,
    ) -> List[Tuple[TpmResult, PartResult]]:
        """
        Lấy tất cả parts được map với torch_model qua TPM.

        Args:
            torch_model: model code e.g. "TK-308RR"

        Returns:
            List of (TpmResult, PartResult)
            GraphTraversal.get_full_consumable_set() đọc:
              tpm = item[0] → role = getattr(tpm, "role") = tpm.part_role
              part = item[1]

        Implementation:
            Đọc từ ds.torch_parts (index: model → [part_nos]) đã build sẵn
            + ds._tpms để lấy role/is_mandatory per part.
        """
        ds = self.ds
        results: List[Tuple[TpmResult, PartResult]] = []
        seen: set = set()

        # Build role lookup từ TPM list
        role_map: Dict[str, Dict] = {}  # part_no → {role, is_mandatory, ref_no}
        for tpm_row in ds._tpms:
            if tpm_row.get("torch_model") != torch_model:
                continue
            role    = tpm_row.get("part_role", "")
            mandatory = tpm_row.get("is_mandatory", True)
            ref_no  = tpm_row.get("ref_no")
            for pno in (tpm_row.get("part_nos") or []):
                if pno not in role_map:
                    role_map[pno] = {"role": role, "is_mandatory": mandatory, "ref_no": ref_no}

        # Build results từ ds.torch_parts index
        for pno in ds.torch_parts.get(torch_model, []):
            if pno in seen or pno not in ds.parts:
                continue
            seen.add(pno)

            rm   = role_map.get(pno, {})
            tpm  = TpmResult(
                torch_model  = torch_model,
                part_nos     = [pno],
                part_role    = rm.get("role", ""),
                is_mandatory = rm.get("is_mandatory", True),
                ref_no       = rm.get("ref_no"),
            )
            part = PartResult.from_dict(ds.parts[pno])
            results.append((tpm, part))

        # Fallback: torch.compatible_parts nếu TPM rỗng
        if not results:
            torch_dict = ds.torches.get(torch_model, {})
            for pno in (torch_dict.get("compatible_parts") or []):
                if pno in seen or pno not in ds.parts:
                    continue
                seen.add(pno)
                tpm  = TpmResult(
                    torch_model  = torch_model,
                    part_nos     = [pno],
                    part_role    = ds.parts[pno].get("category", ""),
                    is_mandatory = True,
                )
                part = PartResult.from_dict(ds.parts[pno])
                results.append((tpm, part))

        log.debug(f"[CER] get_parts_for_torch({torch_model}): {len(results)} parts")
        return results

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_parts(
        self,
        query: str,
        category: Optional[str] = None,
        ecosystem: Optional[str] = None,
        current_class: Optional[str] = None,
        wire_size_mm: Optional[float] = None,
        max_results: int = 20,
    ) -> List[Tuple[float, PartResult]]:
        """
        Search parts theo mô tả tự nhiên.
        Delegate về DataStore._search_by_desc() + _text_search_fallback().

        Args:
            query:         Mô tả tự nhiên — có thể rỗng nếu đã có filters
            category:      Category name (Tip/Nozzle/...)
            ecosystem:     N/D/WX/TIG/TCC
            current_class: 350A/500A/...
            wire_size_mm:  float mm
            max_results:   tối đa

        Returns:
            List of (score: float, PartResult) — sorted by score desc
        """
        ds = self.ds
        eco_upper = (ecosystem or "").upper()
        cc_upper  = (current_class or "").upper()

        # Normalize category qua cat_vocab
        cat = ""
        if category:
            cat = ds.cat_vocab.get(category.lower(), category)

        # Build entity dict compatible với _search_by_desc()
        e = {
            "ecosystem":    eco_upper,
            "current_class": cc_upper,
            "wire_size":    wire_size_mm,
            "categories":   [cat] if cat else [],
            "_raw_query":   query,
        }

        result = ds._search_by_desc(e)

        if result.get("success") and result.get("data"):
            raw_list = result["data"]
            if isinstance(raw_list, list):
                pairs = []
                for item in raw_list[:max_results]:
                    if isinstance(item, dict) and item.get("tokin_part_no"):
                        score = 1.0 if (item.get("business") or {}).get("is_priority_sell") else 0.8
                        pairs.append((score, PartResult.from_dict(item)))
                return pairs

        return []

    # ── Helpers dùng bởi compatibility_matrix stub ─────────────────────────────

    def get_all_parts(self) -> List[PartResult]:
        return [PartResult.from_dict(d) for d in self.ds.parts.values()]

    def get_all_torches(self) -> List[TorchResult]:
        return [TorchResult.from_dict(d) for d in self.ds.torches.values()]

    def stats(self) -> Dict[str, int]:
        ds = self.ds
        return {
            "parts":            len(ds.parts),
            "torches":          len(ds.torches),
            "compat_edges":     len(ds._compat_edges),
            "tpms":             len(ds._tpms),
            "negative_rules":   len(ds._negative_rules),
            "consumable_sets":  len(ds._consumable_sets),
            "process_edges":    len(ds._process_edges),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Singleton factory
# ══════════════════════════════════════════════════════════════════════════════

_cer_instance: Optional[TokinarcCER] = None

def get_cer(ds=None) -> TokinarcCER:
    """
    Lazy singleton.
    Dùng trong GraphTraversal:
        from tokinarc_cer import get_cer
        gt = GraphTraversal(get_cer())

    Args:
        ds: TokinarcDataStore — nếu None, lazy load singleton DataStore
    """
    global _cer_instance
    if _cer_instance is None:
        _cer_instance = TokinarcCER(ds=ds)
        log.info("[CER] initialized")
    return _cer_instance


def reset_cer():
    """Reset singleton — dùng trong tests."""
    global _cer_instance
    _cer_instance = None
