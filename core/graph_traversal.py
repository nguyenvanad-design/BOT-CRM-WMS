"""
graph_traversal.py — Knowledge Graph Traversal Layer
=====================================================
Autoss × Tokinarc — Single source of truth cho tất cả graph operations.

Cả v1 QueryEngine và v2 LLMOrchestrator đều dùng module này.
Không còn duplicate logic giữa _handle_upsell (v1) và _handler_find_upsell (v2).

P4 — Graph Relation Typing (session V6+):
  Các loại quan hệ được định nghĩa rõ ràng trong RelationType enum.
  Mỗi use-case (upsell, contradict check, variant expand) dùng đúng
  tập relation riêng thay vì hard-code string list.

  RELATION_UPSELL:        compatible_with, assembled_with, functional_requires
  RELATION_REQUIRES:      functional_requires (bắt buộc — dùng cho CONTRADICT check)
  RELATION_VARIANT:       replaces (A thay thế B — cùng function)
  RELATION_STRUCTURAL:    belongs_to, belongs_to_alternate

  Fix: loại bỏ 'fits' (không tồn tại trong data), thêm 'functional_requires'
  → fix GOLD_D5 #541 (004002 cần lấy thêm sau mua tip N 0.9 45L)
  → fix WX CONTRADICT false negative khi dùng functional_requires

Root cause fix (phiên trước):
  v2 thiếu 2 bước mà v1 làm đúng:
    1. get_compatible_parts() đi theo compatibility_edges (graph traversal thật)
    2. expand_wire_variants() trả đủ 001001/001002/001003... thay vì 1 item/category

Public API:
    gt = GraphTraversal(cer)

    # Upsell — dùng cho cả v1 và v2
    result = gt.resolve_upsell(part_no="U4167G01", exclude_cats=["Nozzle"])

    # Consumable set đầy đủ với wire expansion
    result = gt.get_full_consumable_set(torch_model="TK-308RR")
    result = gt.get_full_consumable_set(current_class="350A", ecosystem="N")

    # Graph edges trực tiếp — chỉ định relation group
    parts = gt.get_compat_edges(part_no="002001", relation_group="upsell")
    parts = gt.get_compat_edges(part_no="034115", relation_group="requires")

    # Wire variants cho 1 category
    parts = gt.expand_wire_variants(category="Tip", ecosystem="N", current_class="350A")

Output format:
    Tất cả trả List[PartDict] — dict có tokin_part_no, display_name_vi, category,
    ecosystem, current_class, wire_size_mm, role, is_mandatory, price_vnd...
    Compatible với _collect_parts_data() trong llm_orchestrator.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set

log = logging.getLogger("tokinarc.graph_traversal")

# ── PartDict type alias ────────────────────────────────────────────────────────
PartDict = Dict[str, Any]

VALID_ECOSYSTEMS = {"N", "D", "WX", "TIG", "UNIVERSAL", "HYBRID"}

# ── P4: Relation Type Definitions ─────────────────────────────────────────────

class RelationType(str, Enum):
    """
    Các loại quan hệ tồn tại trong compatibility_edges của tokinarc_data.
    Giá trị khớp với relation_type field trong JSON.
    """
    COMPATIBLE_WITH    = "compatible_with"      # A lắp được với B — quan hệ phổ biến nhất (980 edges)
    ASSEMBLED_WITH     = "assembled_with"        # A + B lắp thành cụm (2 edges)
    FUNCTIONAL_REQUIRES = "functional_requires" # A BẮT BUỘC cần B (5 edges — WX nozzle cần WX orifice)
    REPLACES           = "replaces"             # A thay thế B (discontinued / alternate) (13 edges)
    BELONGS_TO         = "belongs_to"           # A thuộc set/family B (14 edges)
    BELONGS_TO_ALTERNATE = "belongs_to_alternate" # A thuộc alternate set B (2 edges)


# ── Relation Groups — dùng cho từng use-case ──────────────────────────────────

# Upsell: mua A → gợi ý mua thêm B
# Bao gồm functional_requires để fix GOLD_D5 #541
# (mua tip N 0.9 → cần cách điện N S — có functional edge)
RELATION_GROUP_UPSELL: FrozenSet[str] = frozenset({
    RelationType.COMPATIBLE_WITH,
    RelationType.ASSEMBLED_WITH,
    RelationType.FUNCTIONAL_REQUIRES,
})

# Requires: A không hoạt động nếu không có B — dùng cho CONTRADICT detection
# VD: WX Water-Cooled Nozzle REQUIRES WX Orifice (không dùng được N Orifice)
RELATION_GROUP_REQUIRES: FrozenSet[str] = frozenset({
    RelationType.FUNCTIONAL_REQUIRES,
})

# Variant: A thay thế B cùng function — dùng để suggest alternative khi OOS
RELATION_GROUP_VARIANT: FrozenSet[str] = frozenset({
    RelationType.REPLACES,
})

# Structural: A thuộc family/set B — dùng để nhóm parts liên quan
RELATION_GROUP_STRUCTURAL: FrozenSet[str] = frozenset({
    RelationType.BELONGS_TO,
    RelationType.BELONGS_TO_ALTERNATE,
})

# Legacy alias — backward compat cho code cũ dùng list string
# Không dùng 'fits' vì không tồn tại trong data
UPSELL_RELATION_TYPES: List[str] = list(RELATION_GROUP_UPSELL)

# ── Categories có wire-size variants (cần expand) ─────────────────────────────
VARIANT_EXPAND_CATS = {"Tip", "TipBody", "TipAdapter", "Insulator", "Orifice", "Nozzle"}

# Display order cho sort output
ROLE_ORDER = [
    "Tip", "TipBody", "TipAdapter",
    "Nozzle", "Orifice", "Insulator",
    "Liner", "LinerORing",
    "WaveWasher", "InnerTube",
    "TungstenElectrode", "Collet", "ColletBody",
    "CeramicNozzle", "BackCap",
    "GasHose", "CableAssembly", "PowerCable",
    "Handle", "TorchBody",
    "InsulationCollar", "WXNozzleSleeve", "WXCoverRubber",
]
_ROLE_IDX = {r: i for i, r in enumerate(ROLE_ORDER)}


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class UpsellResult:
    """Kết quả resolve_upsell() — đủ để cả v1 và v2 dùng."""
    anchor_part_no: str
    anchor_category: str
    anchor_ecosystem: str
    anchor_current_class: str
    companions: List[PartDict] = field(default_factory=list)
    companions_by_role: Dict[str, List[PartDict]] = field(default_factory=dict)
    source_steps: List[str] = field(default_factory=list)
    found: bool = False

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "anchor_part_no": self.anchor_part_no,
            "anchor_category": self.anchor_category,
            "anchor_ecosystem": self.anchor_ecosystem,
            "anchor_current_class": self.anchor_current_class,
            "companions": self.companions,
            "parts": self.companions,          # alias cho _collect_parts_data
            "companions_by_role": self.companions_by_role,
            "source_steps": self.source_steps,
        }


@dataclass
class ConsumableSetResult:
    """Kết quả get_full_consumable_set()."""
    set_id: str
    set_name: str
    torch_current_class: str
    ecosystem: str
    parts: List[PartDict] = field(default_factory=list)
    parts_by_role: Dict[str, List[PartDict]] = field(default_factory=dict)
    found: bool = False

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "set_id": self.set_id,
            "set_name": self.set_name,
            "torch_current_class": self.torch_current_class,
            "ecosystem": self.ecosystem,
            "parts": self.parts,
            "parts_by_role": self.parts_by_role,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _part_to_dict(part, role: str = "", is_mandatory: bool = True,
                  score: float = 1.0) -> PartDict:
    """Convert CER PartResult → PartDict chuẩn."""
    if part is None:
        return {}
    if isinstance(part, dict):
        d = dict(part)
        if "tokin_part_no" not in d and "part_id" in d:
            d["tokin_part_no"] = d["part_id"]
        if role and not d.get("role"):
            d["role"] = role
        return d

    raw = getattr(part, "raw", {}) or {}
    biz = raw.get("business") or {}
    return {
        "tokin_part_no":    part.tokin_part_no,
        "display_name_vi":  getattr(part, "display_name_vi", part.tokin_part_no),
        "display_name_en":  getattr(part, "display_name_en", part.tokin_part_no),
        "category":         getattr(part, "category", ""),
        "ecosystem":        getattr(part, "ecosystem", ""),
        "current_class":    getattr(part, "current_class", ""),
        "wire_size_mm":     getattr(part, "wire_size_mm", None),
        "p_part_nos":       getattr(part, "p_part_nos", []),
        "d_part_nos":       getattr(part, "d_part_nos", []),
        "price_vnd":        biz.get("price_vnd") or raw.get("price_vnd"),
        "price_unit":       biz.get("price_unit", "cái"),
        "is_contact_price": biz.get("is_contact_price", False),
        "is_priority":      biz.get("is_priority_sell", False),
        "note":             raw.get("note", ""),
        "role":             role or getattr(part, "category", ""),
        "is_mandatory":     is_mandatory,
        "score":            round(score, 3),
    }


def _sort_by_role(parts: List[PartDict]) -> List[PartDict]:
    return sorted(parts, key=lambda p: (
        _ROLE_IDX.get(p.get("role") or p.get("category", ""), 99),
        p.get("tokin_part_no", ""),
    ))


def _group_by_role(parts: List[PartDict]) -> Dict[str, List[PartDict]]:
    groups: Dict[str, List[PartDict]] = {}
    for p in parts:
        key = p.get("role") or p.get("category", "unknown")
        groups.setdefault(key, []).append(p)
    return dict(sorted(groups.items(), key=lambda x: _ROLE_IDX.get(x[0], 99)))


def _eco_ok(eco: str, filter_eco: Optional[str]) -> bool:
    """True nếu part eco compatible với filter."""
    if not filter_eco:
        return True
    return eco in (filter_eco, "UNIVERSAL", "HYBRID", "")


# ── Main class ─────────────────────────────────────────────────────────────────

class GraphTraversal:
    """
    Knowledge Graph Traversal — single source of truth.

    Wrap CER API để thực hiện multi-hop graph traversal đúng cách.
    Cả v1 QueryEngine và v2 LLMOrchestrator import class này.

    P4 addition: get_compat_edges() nhận relation_group parameter
    để filter đúng loại quan hệ theo use-case.

    Usage:
        gt = GraphTraversal(cer)
        result = gt.resolve_upsell("U4167G01")
        result = gt.get_full_consumable_set(torch_model="TK-308RR")

        # P4: explicit relation group
        parts = gt.get_compat_edges("034115", relation_group="requires")
        parts = gt.get_compat_edges("002001", relation_group="upsell")
    """

    # Map group name string → frozenset (dùng trong get_compat_edges)
    _RELATION_GROUPS: Dict[str, FrozenSet[str]] = {
        "upsell":     RELATION_GROUP_UPSELL,
        "requires":   RELATION_GROUP_REQUIRES,
        "variant":    RELATION_GROUP_VARIANT,
        "structural": RELATION_GROUP_STRUCTURAL,
    }

    def __init__(self, cer):
        self._cer = cer

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════════════

    def resolve_upsell(
        self,
        part_no: str,
        exclude_cats: Optional[List[str]] = None,
        expand_variants: bool = True,
    ) -> UpsellResult:
        """
        COMPOSITE: Tìm tất cả parts đi kèm với part_no đã có.

        3 bước theo thứ tự ưu tiên:
          Step 1: get_compat_edges(group="upsell") — graph traversal thật
                  Dùng RELATION_GROUP_UPSELL: compatible_with + assembled_with
                  + functional_requires (P4 fix: thêm functional_requires)
          Step 2: consumable_set vá lỗ hổng từ step 1
          Step 3: expand_wire_variants() cho đủ wire-size variants

        Args:
            part_no:         Tokin 6-digit hoặc alias (U4167G01, TET01296...)
            exclude_cats:    Categories loại khỏi kết quả
            expand_variants: True = expand đủ wire-size variants

        Returns:
            UpsellResult với companions[] đầy đủ
        """
        canonical = self._resolve(part_no)
        if not canonical:
            log.warning(f"[GT] resolve_upsell: cannot resolve '{part_no}'")
            return UpsellResult(
                anchor_part_no=part_no, anchor_category="",
                anchor_ecosystem="", anchor_current_class="",
                found=False,
            )

        anchor = self._cer.get_part(canonical)
        if not anchor:
            log.warning(f"[GT] resolve_upsell: part '{canonical}' not in CER")
            return UpsellResult(
                anchor_part_no=canonical, anchor_category="",
                anchor_ecosystem="", anchor_current_class="",
                found=False,
            )

        anchor_cat = getattr(anchor, "category", "")
        anchor_eco = getattr(anchor, "ecosystem", "")
        anchor_cc  = getattr(anchor, "current_class", "")

        excl: Set[str] = set(c.lower() for c in (exclude_cats or []))
        excl.add(anchor_cat.lower())

        seen: Set[str] = {canonical}
        companions: List[PartDict] = []
        steps: List[str] = []

        # ── Step 1: graph traversal với UPSELL relation group ─────────────────
        # P4 fix: dùng group="upsell" thay vì hard-code list (bao gồm functional_requires)
        step1 = self.get_compat_edges(canonical, excl_cats=excl, relation_group="upsell")
        if step1:
            for p in step1:
                pid = p.get("tokin_part_no", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    companions.append(p)
            steps.append(f"compat_edges:{len(step1)}")
            log.info(f"[GT] step1 compat_edges(upsell): {len(step1)} parts from '{canonical}'")

        # ── Step 2: consumable_set — vá lỗ hổng step 1 ───────────────────────
        step2 = self._consumable_set_companions(
            current_class=anchor_cc,
            ecosystem=anchor_eco,
            exclude_pids=seen,
            excl_cats=excl,
        )
        if step2:
            for p in step2:
                pid = p.get("tokin_part_no", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    companions.append(p)
            steps.append(f"consumable_set:{len(step2)}")
            log.info(f"[GT] step2 consumable_set: {len(step2)} additional parts")

        # ── Step 3: wire variant expansion ───────────────────────────────────
        if expand_variants:
            step3 = self._expand_companions_variants(
                companions=companions,
                ecosystem=anchor_eco,
                current_class=anchor_cc,
                exclude_pids=seen,
                excl_cats=excl,
            )
            if step3:
                for p in step3:
                    pid = p.get("tokin_part_no", "")
                    if pid and pid not in seen:
                        seen.add(pid)
                        companions.append(p)
                steps.append(f"wire_expand:{len(step3)}")
                log.info(f"[GT] step3 wire_expand: {len(step3)} variant parts")

        # ── Cap per-category ───────────────────────────────────────────────────
        MAX_PER_CAT = {"Tip": 4, "Nozzle": 4, "Insulator": 2,
                       "TipBody": 2, "TipAdapter": 2, "Orifice": 2}
        DEFAULT_MAX = 2
        _cat_count: dict = {}
        _capped: List[PartDict] = []
        for p in companions:
            cat = p.get("role") or p.get("category", "")
            limit = MAX_PER_CAT.get(cat, DEFAULT_MAX)
            if _cat_count.get(cat, 0) < limit:
                _capped.append(p)
                _cat_count[cat] = _cat_count.get(cat, 0) + 1
        companions = _capped[:30]  # hard cap tổng 30 parts

        companions = _sort_by_role(companions)
        by_role = _group_by_role(companions)

        return UpsellResult(
            anchor_part_no=canonical,
            anchor_category=anchor_cat,
            anchor_ecosystem=anchor_eco,
            anchor_current_class=anchor_cc,
            companions=companions,
            companions_by_role=by_role,
            source_steps=steps,
            found=len(companions) > 0,
        )

    def resolve_upsell_torch(
        self,
        torch_model: str,
        exclude_cats: Optional[List[str]] = None,
    ) -> UpsellResult:
        """
        Graph RAG: Traverse torch → TPM edges → full ecosystem parts.
        Dùng khi user hỏi "súng TK-308RR cần thêm gì" mà không có part_no cụ thể.

        Flow:
          1. get_parts_for_torch(torch_model) → anchor parts từ TPM
          2. Với mỗi anchor part → get_compat_edges(upsell) → companions
          3. Dedup + sort

        Returns UpsellResult với companions đầy đủ cho torch.
        """
        excl: Set[str] = set(c.lower() for c in (exclude_cats or []))
        seen: Set[str] = set()
        companions: List[PartDict] = []
        steps: List[str] = []

        # Step 1: lấy parts của torch từ TPM
        tpm_parts: List[PartDict] = []
        if hasattr(self._cer, "get_parts_for_torch"):
            try:
                raw = self._cer.get_parts_for_torch(torch_model) or []
                for item in raw:
                    tpm  = item[0] if isinstance(item, tuple) else None
                    part = item[1] if isinstance(item, tuple) else item
                    if part is None:
                        continue
                    role      = getattr(tpm, "role", None) or getattr(tpm, "part_role", "") if tpm else ""
                    mandatory = getattr(tpm, "is_mandatory", True) if tpm else True
                    d = _part_to_dict(part, role=role or getattr(part, "category", ""), is_mandatory=mandatory)
                    pid = d.get("tokin_part_no", "")
                    if pid and pid not in seen:
                        seen.add(pid)
                        tpm_parts.append(d)
                        companions.append(d)
                steps.append(f"torch_tpm:{len(tpm_parts)}")
                # Cap TPM: priority roles only, max 12
                PRIORITY_ROLES = {"Tip","TipBody","Nozzle","Orifice","Insulator","Liner"}
                tpm_parts = [p for p in tpm_parts if p.get("part_role","") in PRIORITY_ROLES][:12]
                companions = list(tpm_parts)
                seen = {p.get("tokin_part_no","") for p in companions}
                log.info(f"[GT] resolve_upsell_torch '{torch_model}': {len(tpm_parts)} TPM parts")
            except Exception as e:
                log.warning(f"[GT] resolve_upsell_torch get_parts_for_torch error: {e}")

        # Lấy torch eco/cc để dùng consumable_set fallback
        torch_eco = ""
        torch_cc  = ""
        if hasattr(self._cer, "get_torch"):
            try:
                torch_obj = self._cer.get_torch(torch_model)
                if torch_obj:
                    torch_eco = getattr(torch_obj, "ecosystem", "")
                    torch_cc  = getattr(torch_obj, "current_class", "")
            except Exception:
                pass

        # Step 2: 2-hop — với mỗi TPM part → traverse compat edges
        hop2_count = 0
        for anchor_part in list(tpm_parts)[:2]:  # cap 2 anchors  # giới hạn 6 anchors
            pid = anchor_part.get("tokin_part_no", "")
            if not pid:
                continue
            hop2 = self.get_compat_edges(pid, excl_cats=excl, relation_group="upsell")
            for p in hop2:
                p2_pid = p.get("tokin_part_no", "")
                if p2_pid and p2_pid not in seen:
                    seen.add(p2_pid)
                    companions.append(p)
                    hop2_count += 1
        if hop2_count:
            steps.append(f"2hop_compat:{hop2_count}")
            log.info(f"[GT] resolve_upsell_torch 2-hop: {hop2_count} additional parts")
        # Hard cap tổng companions
        companions = companions[:32]
        seen = {p.get("tokin_part_no","") for p in companions}

        # Step 3: consumable_set để vá lỗ hổng
        if torch_eco and torch_cc:
            cs_parts = self._get_cs_items(
                current_class=torch_cc,
                ecosystem=torch_eco,
                exclude_pids=seen,
            )
            for p in cs_parts:
                pid = p.get("tokin_part_no", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    companions.append(p)
            if cs_parts:
                steps.append(f"cs_fill:{len(cs_parts)}")

        # Filter excl_cats
        companions = [p for p in companions
                      if (p.get("role") or p.get("category", "")).lower() not in excl]

        # Sort + group
        companions = _sort_by_role(companions)
        by_role = _group_by_role(companions)

        return UpsellResult(
            anchor_part_no=torch_model,
            anchor_category="Torch",
            anchor_ecosystem=torch_eco,
            anchor_current_class=torch_cc,
            companions=companions,
            companions_by_role=by_role,
            source_steps=steps,
            found=len(companions) > 0,
        )

    def resolve_upsell_2hop(
        self,
        part_no: str,
        exclude_cats: Optional[List[str]] = None,
        max_anchors: int = 2,
    ) -> UpsellResult:
        """
        Graph RAG 2-hop: A → B (1-hop) → C (2-hop).
        max_anchors=2 để tránh explosion — chỉ traverse TipBody + Insulator.
        """
        # Bước 1: 1-hop standard
        hop1 = self.resolve_upsell(part_no, exclude_cats=exclude_cats, expand_variants=True)
        if not hop1.found:
            return hop1

        seen: Set[str] = {part_no}
        seen.update(p.get("tokin_part_no", "") for p in hop1.companions)

        excl: Set[str] = set(c.lower() for c in (exclude_cats or []))
        excl.add(hop1.anchor_category.lower())

        # Bước 2: 2-hop từ companions quan trọng nhất (TipBody ưu tiên)
        _PRIORITY_CATS = {"tipbody", "insulator"}
        anchors = sorted(
            hop1.companions,
            key=lambda p: (0 if (p.get("role") or p.get("category", "")).lower() in _PRIORITY_CATS else 1)
        )[:max_anchors]

        hop2_parts: List[PartDict] = []
        MAX_HOP2 = 10  # hard cap hop2
        for anchor in anchors:
            if len(hop2_parts) >= MAX_HOP2:
                break
            a_pid = anchor.get("tokin_part_no", "")
            if not a_pid:
                continue
            hop2 = self.get_compat_edges(a_pid, excl_cats=excl, relation_group="upsell")
            for p in hop2:
                if len(hop2_parts) >= MAX_HOP2:
                    break
                pid = p.get("tokin_part_no", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    p["_hop"] = 2
                    hop2_parts.append(p)

        all_companions = hop1.companions + hop2_parts
        all_companions = _sort_by_role(all_companions)
        by_role = _group_by_role(all_companions)

        steps = hop1.source_steps + ([f"2hop:{len(hop2_parts)}"] if hop2_parts else [])
        log.info(f"[GT] resolve_upsell_2hop '{part_no}': hop1={len(hop1.companions)} hop2={len(hop2_parts)}")

        return UpsellResult(
            anchor_part_no=hop1.anchor_part_no,
            anchor_category=hop1.anchor_category,
            anchor_ecosystem=hop1.anchor_ecosystem,
            anchor_current_class=hop1.anchor_current_class,
            companions=all_companions,
            companions_by_role=by_role,
            source_steps=steps,
            found=len(all_companions) > 0,
        )

    def get_full_consumable_set(
        self,
        torch_model: Optional[str] = None,
        current_class: Optional[str] = None,
        ecosystem: Optional[str] = None,
        expand_variants: bool = True,
    ) -> List[ConsumableSetResult]:
        """
        Lấy consumable set đầy đủ với wire expansion.

        Tier A: torch_model có → get_parts_for_torch() + consumable_set
        Tier B: thiếu torch, có class/eco → consumable_set trực tiếp
        Cả 2 tier đều expand wire variants nếu expand_variants=True.

        Returns:
            List[ConsumableSetResult] — có thể nhiều set nếu nhiều eco
        """
        results: List[ConsumableSetResult] = []

        # Tier A: torch_model path
        if torch_model:
            torch_obj = None
            if hasattr(self._cer, "get_torch"):
                torch_obj = self._cer.get_torch(torch_model)

            if torch_obj:
                t_cc  = getattr(torch_obj, "current_class", current_class)
                t_eco = getattr(torch_obj, "ecosystem", ecosystem)

                tpm_parts: List[PartDict] = []
                seen_tpm: Set[str] = set()
                if hasattr(self._cer, "get_parts_for_torch"):
                    raw = self._cer.get_parts_for_torch(torch_model) or []
                    for item in raw:
                        tpm  = item[0] if isinstance(item, tuple) else None
                        part = item[1] if isinstance(item, tuple) else item
                        if part is None:
                            continue
                        role = getattr(tpm, "role", None) or getattr(tpm, "part_role", "") if tpm else ""
                        mandatory = getattr(tpm, "is_mandatory", True) if tpm else True
                        d = _part_to_dict(part, role=role, is_mandatory=mandatory)
                        pid = d.get("tokin_part_no", "")
                        if pid and pid not in seen_tpm:
                            seen_tpm.add(pid)
                            tpm_parts.append(d)

                # Chỉ exclude Tip variants — cho phép CS bổ sung Nozzle/Insulator/Orifice/Liner
                tip_pids = {p.get("tokin_part_no","") for p in tpm_parts if p.get("category","") == "Tip" or p.get("part_role","") == "Tip"}
                cs_items = self._get_cs_items(current_class=t_cc, ecosystem=t_eco,
                                               exclude_pids=tip_pids)
                all_parts = tpm_parts + cs_items

                if expand_variants:
                    variants = self._expand_companions_variants(
                        companions=all_parts,
                        ecosystem=t_eco,
                        current_class=t_cc,
                        exclude_pids={p.get("tokin_part_no", "") for p in all_parts},
                        excl_cats=set(),
                    )
                    all_parts = all_parts + variants

                all_parts = _sort_by_role(all_parts)
                results.append(ConsumableSetResult(
                    set_id=f"torch:{torch_model}",
                    set_name=f"Bộ tiêu hao {torch_model}",
                    torch_current_class=t_cc or "",
                    ecosystem=t_eco or "",
                    parts=all_parts,
                    parts_by_role=_group_by_role(all_parts),
                    found=len(all_parts) > 0,
                ))
                return results

        # Tier B: class/eco path
        if not current_class and not ecosystem:
            current_class = "350A"
            ecosystem = "N"
            log.info("[GT] get_full_consumable_set: no params → default 350A N")

        # CC banding: thử cc tương đương khi không tìm thấy exact match
        _CC_FALLBACK = {
            "200A": ["200A", "350A"],
            "250A": ["250A", "350A"],
            "300A": ["300A", "350A"],
            "400A": ["400A", "350A", "500A"],
            "450A": ["450A", "500A"],
        }
        cc_variants = [current_class] + [
            c for c in _CC_FALLBACK.get(current_class or "", [])
            if c != current_class
        ] if current_class else [current_class]

        raw_sets = []
        if hasattr(self._cer, "get_consumable_set"):
            for try_cc in cc_variants:
                try:
                    raw_sets = self._cer.get_consumable_set(
                        current_class=try_cc,
                        ecosystem=ecosystem,
                    ) or []
                    if raw_sets:
                        if try_cc != current_class:
                            log.info(f"[GT] CC banding: {current_class} → {try_cc}")
                        break
                except Exception as e:
                    log.warning(f"[GT] get_consumable_set error: {e}")

        if not raw_sets:
            return results

        if len(raw_sets) > 1:
            raw_sets = sorted(raw_sets, key=lambda s: 0 if getattr(s, "ecosystem", "") == "N" else 1)

        for cs in raw_sets[:3]:
            seen_cs: Set[str] = set()
            parts: List[PartDict] = []

            for item in getattr(cs, "items", []):
                pid  = item.get("part_id", "")
                role = item.get("part_role", "") or item.get("category", "")
                if not pid or pid in seen_cs:
                    continue
                part = self._cer.get_part(pid)
                if not part:
                    continue
                seen_cs.add(pid)
                d = _part_to_dict(
                    part,
                    role=role or getattr(part, "category", ""),
                    is_mandatory=item.get("is_mandatory", True),
                )
                parts.append(d)

            if expand_variants:
                variants = self._expand_companions_variants(
                    companions=parts,
                    ecosystem=getattr(cs, "ecosystem", ecosystem),
                    current_class=getattr(cs, "torch_current_class", current_class),
                    exclude_pids=seen_cs,
                    excl_cats=set(),
                )
                parts = parts + variants

            parts = _sort_by_role(parts)
            results.append(ConsumableSetResult(
                set_id=getattr(cs, "set_id", ""),
                set_name=getattr(cs, "display_name_vi", ""),
                torch_current_class=getattr(cs, "torch_current_class", current_class or ""),
                ecosystem=getattr(cs, "ecosystem", ecosystem or ""),
                parts=parts,
                parts_by_role=_group_by_role(parts),
                found=len(parts) > 0,
            ))

        return results

    def get_compat_edges(
        self,
        part_no: str,
        excl_cats: Optional[Set[str]] = None,
        relation_types: Optional[List[str]] = None,
        relation_group: Optional[str] = None,
    ) -> List[PartDict]:
        """
        1-hop graph traversal qua compatibility_edges.

        P4: Nhận relation_group (string) hoặc relation_types (list) để filter.
        relation_group ưu tiên hơn relation_types nếu cả 2 được truyền.

        Args:
            part_no:        Tokin part number (canonical)
            excl_cats:      lowercase category set cần loại
            relation_types: list string các relation type cần filter (legacy)
            relation_group: tên group — "upsell", "requires", "variant", "structural"
                            Nếu None và relation_types None → dùng UPSELL group

        Returns:
            List[PartDict] — parts linked trực tiếp qua edges
        """
        # Resolve relation filter: group > explicit list > default upsell
        if relation_group is not None:
            rels: FrozenSet[str] = self._RELATION_GROUPS.get(
                relation_group, RELATION_GROUP_UPSELL
            )
        elif relation_types is not None:
            rels = frozenset(relation_types)
        else:
            rels = RELATION_GROUP_UPSELL

        excl = excl_cats or set()
        results: List[PartDict] = []

        if not hasattr(self._cer, "get_compatible_parts"):
            return results

        try:
            compat = self._cer.get_compatible_parts(part_no, relation_types=list(rels)) or []
        except Exception as e:
            log.warning(f"[GT] get_compat_edges error for '{part_no}': {e}")
            return results

        seen: Set[str] = set()
        for item in compat:
            rel  = item[0] if isinstance(item, tuple) else ""
            part = item[1] if isinstance(item, tuple) else item
            if part is None:
                continue
            pid = getattr(part, "tokin_part_no", None)
            if not pid or pid in seen:
                continue
            cat = getattr(part, "category", "")
            if cat.lower() in excl:
                continue
            seen.add(pid)
            # Đánh dấu relation_type vào PartDict để upstream code biết loại quan hệ
            d = _part_to_dict(part, role=cat, is_mandatory=True)
            d["relation_type"] = rel if rel else RelationType.COMPATIBLE_WITH.value
            results.append(d)

        return results

    def get_required_parts(self, part_no: str) -> List[PartDict]:
        """
        Lấy các parts BẮT BUỘC theo functional_requires edges.
        Dùng cho CONTRADICT detection (WX nozzle → phải dùng WX orifice).

        Khác get_compat_edges(group="upsell"): chỉ trả parts có quan hệ
        functional_requires, không bao gồm compatible_with.

        Returns:
            List[PartDict] — parts có relation_type="functional_requires"
        """
        return self.get_compat_edges(part_no, relation_group="requires")

    def get_replacement_parts(self, part_no: str) -> List[PartDict]:
        """
        Lấy các parts thay thế (discontinued / alternate) theo replaces edges.
        Dùng khi user hỏi part OOS hoặc không còn sản xuất.

        Returns:
            List[PartDict] — parts có relation_type="replaces"
        """
        return self.get_compat_edges(part_no, relation_group="variant")

    def expand_wire_variants(
        self,
        category: str,
        ecosystem: str,
        current_class: str,
        exclude_pids: Optional[Set[str]] = None,
    ) -> List[PartDict]:
        """
        Expand tất cả wire-size variants cho 1 (category, ecosystem, class).

        Ví dụ: category=Tip, eco=N, class=350A
        → 002001 (0.9mm), 002002 (0.9mm 60L), 002003 (1.0mm), 002004 (1.2mm)...

        Args:
            category:      "Tip", "Insulator", "Nozzle"...
            ecosystem:     "N", "D", "WX"...
            current_class: "350A", "500A"...
            exclude_pids:  part numbers đã có, skip

        Returns:
            List[PartDict] — tất cả variants chưa có trong exclude_pids
        """
        excl = exclude_pids or set()
        results: List[PartDict] = []

        if not hasattr(self._cer, "search_parts"):
            return results

        try:
            raw = self._cer.search_parts(
                query="",
                category=category,
                ecosystem=ecosystem,
                current_class=current_class,
                max_results=20,
            ) or []
        except Exception as e:
            log.warning(f"[GT] expand_wire_variants error cat={category} eco={ecosystem}: {e}")
            return results

        for item in raw:
            part  = item[1] if isinstance(item, tuple) else item
            score = item[0] if isinstance(item, tuple) else 1.0
            if part is None:
                continue
            pid = getattr(part, "tokin_part_no", None) or getattr(part, "part_id", None)
            if not pid or pid in excl:
                continue
            excl.add(pid)
            results.append(_part_to_dict(part, role=category, is_mandatory=False, score=float(score)))

        return results

    # ══════════════════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _resolve(self, part_no: str) -> Optional[str]:
        """Resolve alias/P-part/D-part → canonical Tokin part number."""
        if not part_no:
            return None
        if hasattr(self._cer, "get_part") and self._cer.get_part(part_no):
            return part_no
        if hasattr(self._cer, "resolve_part_no"):
            resolved = self._cer.resolve_part_no(part_no)
            if resolved:
                return resolved
        return None

    def _consumable_set_companions(
        self,
        current_class: str,
        ecosystem: str,
        exclude_pids: Set[str],
        excl_cats: Set[str],
    ) -> List[PartDict]:
        """
        Lấy items từ consumable_set, loại các pid/category đã có.
        Dùng để vá lỗ hổng sau step 1 (compat_edges không trả đủ).
        """
        results: List[PartDict] = []
        if not current_class and not ecosystem:
            return results

        raw_sets = []
        if hasattr(self._cer, "get_consumable_set"):
            try:
                raw_sets = self._cer.get_consumable_set(
                    current_class=current_class,
                    ecosystem=ecosystem,
                ) or []
            except Exception as e:
                log.warning(f"[GT] _consumable_set_companions error: {e}")
                return results

        seen = set(exclude_pids)
        for cs in (raw_sets or [])[:2]:
            for item in getattr(cs, "items", []):
                pid  = item.get("part_id", "")
                role = item.get("part_role", "") or item.get("category", "")
                cat  = (item.get("category") or role or "").lower()
                if not pid or pid in seen:
                    continue
                if cat in excl_cats:
                    continue
                part = self._cer.get_part(pid)
                if not part:
                    continue
                seen.add(pid)
                results.append(_part_to_dict(
                    part,
                    role=role or getattr(part, "category", ""),
                    is_mandatory=item.get("is_mandatory", True),
                ))

        return results

    def _get_cs_items(
        self,
        current_class: Optional[str],
        ecosystem: Optional[str],
        exclude_pids: Set[str],
    ) -> List[PartDict]:
        """Lấy items của consumable_set, skip pids đã có. Không filter category."""
        results: List[PartDict] = []
        if not current_class and not ecosystem:
            return results

        raw_sets = []
        if hasattr(self._cer, "get_consumable_set"):
            try:
                raw_sets = self._cer.get_consumable_set(
                    current_class=current_class,
                    ecosystem=ecosystem,
                ) or []
            except Exception as e:
                log.warning(f"[GT] _get_cs_items error: {e}")
                return results

        seen = set(exclude_pids)
        for cs in (raw_sets or [])[:2]:
            for item in getattr(cs, "items", []):
                pid  = item.get("part_id", "")
                role = item.get("part_role", "") or item.get("category", "")
                if not pid or pid in seen:
                    continue
                part = self._cer.get_part(pid)
                if not part:
                    continue
                seen.add(pid)
                results.append(_part_to_dict(
                    part,
                    role=role or getattr(part, "category", ""),
                    is_mandatory=item.get("is_mandatory", True),
                ))

        return results

    def _expand_companions_variants(
        self,
        companions: List[PartDict],
        ecosystem: str,
        current_class: str,
        exclude_pids: Set[str],
        excl_cats: Set[str],
    ) -> List[PartDict]:
        """
        Với mỗi category trong companions thuộc VARIANT_EXPAND_CATS
        → expand thêm tất cả wire-size variants cùng (cat, eco, class).
        """
        expand_pairs: Set[tuple] = set()
        for p in companions:
            cat = p.get("role") or p.get("category", "")
            eco = p.get("ecosystem", "") or ecosystem
            if cat in VARIANT_EXPAND_CATS and cat.lower() not in excl_cats:
                expand_pairs.add((cat, eco))

        if not expand_pairs:
            return []

        all_variants: List[PartDict] = []
        seen = set(exclude_pids)

        for cat, eco in expand_pairs:
            variants = self.expand_wire_variants(
                category=cat,
                ecosystem=eco,
                current_class=current_class,
                exclude_pids=set(seen),
            )
            for v in variants:
                pid = v.get("tokin_part_no", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    all_variants.append(v)

        return all_variants


# ── Singleton factory ──────────────────────────────────────────────────────────

_gt_cache: Dict[int, GraphTraversal] = {}

def get_graph_traversal(cer) -> GraphTraversal:
    """
    Lazy singleton per CER instance.
    Dùng thay vì GraphTraversal(cer) trực tiếp để tránh tạo lại.
    """
    key = id(cer)
    if key not in _gt_cache:
        _gt_cache[key] = GraphTraversal(cer)
    return _gt_cache[key]





