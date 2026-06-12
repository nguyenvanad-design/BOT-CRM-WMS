"""
core/assembly_kb.py — Assembly Procedural Knowledge Base
=========================================================
Autoss × Tokinarc — Industrial Compatibility Intelligence

Load `assembly_procedures.json` thành in-memory lookup tables.
Cung cấp API tra cứu cho INSTALLATION/REPAIR handler trong query_engine.py.

Đây là **soft procedural knowledge** — KHÔNG phải hard truth.
Hard truth (compatibility, part graph) vẫn nằm ở CER.

API:
  kb = AssemblyKB.from_file("data/assembly_procedures.json")
  kb.get_assembly_sequence(torch_model="YMSA-500W")
  kb.get_torque_spec(category="Tip")
  kb.get_replacement_procedure(category="Liner", torch_model="TK-308RR")
  kb.get_troubleshooting(symptom_query="wire feeding")
  kb.get_liner_length(torch_model="TK-308RR", wire_size="1.2")
  kb.get_warnings(torch_model="YMSA-500W")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TorqueSpec:
    id: str
    component: str
    category: str
    value_nm: Optional[float]   # None for ranges (e.g. "2.5–3 N·m")
    value_display: str
    tool_recommended: str
    applies_to: List[str]
    warning: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "component": self.component,
            "category": self.category,
            "value_nm": self.value_nm,
            "value_display": self.value_display,
            "tool_recommended": self.tool_recommended,
            "applies_to": self.applies_to,
            "warning": self.warning,
            "source": self.source,
        }


@dataclass
class AssemblyStep:
    order: int
    action: str
    part_role: Optional[str] = None
    part_id: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"order": self.order, "action": self.action}
        if self.part_role:
            d["part_role"] = self.part_role
        if self.part_id:
            d["part_id"] = self.part_id
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class AssemblySequence:
    id: str
    name: str
    torch_context: List[str]
    ecosystem: str
    ecosystem_label: str
    steps: List[AssemblyStep]
    warning: Optional[str] = None
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "torch_context": self.torch_context,
            "ecosystem": self.ecosystem,
            "ecosystem_label": self.ecosystem_label,
            "steps": [s.to_dict() for s in self.steps],
            "warning": self.warning,
            "source": self.source,
        }


@dataclass
class ReplacementProcedure:
    id: str
    name: str
    trigger: str
    torch_context: List[str]
    steps: List[AssemblyStep]
    tools: List[str]
    cautions: List[str]
    torque_ref: Optional[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "torch_context": self.torch_context,
            "steps": [s.to_dict() for s in self.steps],
            "tools": self.tools,
            "cautions": self.cautions,
            "torque_ref": self.torque_ref,
            "source": self.source,
        }


@dataclass
class TroubleshootingEntry:
    id: str
    symptom: str
    likely_causes: List[str]
    recommended_action: str
    related_procedures: List[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symptom": self.symptom,
            "likely_causes": self.likely_causes,
            "recommended_action": self.recommended_action,
            "related_procedures": self.related_procedures,
            "source": self.source,
        }


@dataclass
class WarningEntry:
    id: str
    context: str
    text: str
    severity: str
    applies_to: List[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "context": self.context,
            "text": self.text,
            "severity": self.severity,
            "applies_to": self.applies_to,
            "source": self.source,
        }


@dataclass
class LinerLengthEntry:
    part_id: str
    torch_models: List[str]
    liner_length_mm: int
    wire_size_mm: str
    robot_model: Optional[str]
    cable_length_m: Optional[float]
    oring: Optional[str]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part_id": self.part_id,
            "torch_models": self.torch_models,
            "liner_length_mm": self.liner_length_mm,
            "wire_size_mm": self.wire_size_mm,
            "robot_model": self.robot_model,
            "cable_length_m": self.cable_length_m,
            "oring": self.oring,
            "source": self.source,
        }


# ─── Symptom keywords (Vietnamese + English) ──────────────────────────────────

SYMPTOM_KEYWORDS_VI_EN: Dict[str, List[str]] = {
    # Map symptom phrase fragment → relevant troubleshooting IDs
    "wire_feeding": [
        "wire feeding", "kẹt dây", "dây kẹt", "dây hàn không đều",
        "wire feed", "feeding unstable", "feeding khong on",
    ],
    "ground_fault": [
        "ground fault", "chạm mass", "cham mass", "rò điện",
        "ro dien", "earth fault",
    ],
    "gas_leak": [
        "rò khí", "ro khi", "gas leak", "thiếu khí", "thieu khi",
    ],
    "spatter": [
        "spatter", "xỉ", "xi", "dính xỉ", "bắn xỉ",
    ],
    "wear": [
        "mòn nhanh", "mon nhanh", "cháy sớm", "chay som",
        "tip cháy", "wear fast",
    ],
    "overheat": [
        "quá nhiệt", "qua nhiet", "overheat", "nóng quá",
    ],
}


# ─── AssemblyKB ───────────────────────────────────────────────────────────────

class AssemblyKB:
    """
    Procedural knowledge base for assembly/repair/installation.

    Load `assembly_procedures.json` once at startup.
    Provides fast in-memory lookups by torch_model, category, symptom.
    """

    def __init__(
        self,
        torque_specs: List[TorqueSpec],
        assembly_sequences: List[AssemblySequence],
        replacement_procedures: List[ReplacementProcedure],
        troubleshooting: List[TroubleshootingEntry],
        warnings: List[WarningEntry],
        liner_length_table: List[LinerLengthEntry],
        liner_protrusion_table: List[Dict[str, Any]],
        inner_tube_length_table: List[Dict[str, Any]],
        meta: Dict[str, Any],
    ):
        self._torque_specs = torque_specs
        self._assembly_sequences = assembly_sequences
        self._replacement_procedures = replacement_procedures
        self._troubleshooting = troubleshooting
        self._warnings = warnings
        self._liner_length_table = liner_length_table
        self._liner_protrusion_table = liner_protrusion_table
        self._inner_tube_length_table = inner_tube_length_table
        self._meta = meta

        # Build indices for O(1) lookup
        self._torque_by_category: Dict[str, TorqueSpec] = {
            ts.category: ts for ts in torque_specs
        }
        self._torque_by_id: Dict[str, TorqueSpec] = {
            ts.id: ts for ts in torque_specs
        }
        self._assembly_by_torch: Dict[str, List[AssemblySequence]] = {}
        for seq in assembly_sequences:
            for torch in seq.torch_context:
                self._assembly_by_torch.setdefault(torch, []).append(seq)

        self._assembly_by_ecosystem: Dict[str, List[AssemblySequence]] = {}
        for seq in assembly_sequences:
            self._assembly_by_ecosystem.setdefault(seq.ecosystem, []).append(seq)

        self._replacement_by_id: Dict[str, ReplacementProcedure] = {
            rp.id: rp for rp in replacement_procedures
        }
        self._troubleshooting_by_id: Dict[str, TroubleshootingEntry] = {
            ts.id: ts for ts in troubleshooting
        }

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path) -> "AssemblyKB":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssemblyKB":
        torque_specs = [
            TorqueSpec(
                id=ts["id"],
                component=ts["component"],
                category=ts["category"],
                value_nm=float(ts["value_nm"]) if ts.get("value_nm") is not None else None,
                value_display=ts["value_display"],
                tool_recommended=ts.get("tool_recommended", ""),
                applies_to=ts.get("applies_to", []),
                warning=ts.get("warning", ""),
                source=ts.get("source", ""),
            )
            for ts in data.get("torque_specs", [])
        ]

        assembly_sequences = [
            AssemblySequence(
                id=seq["id"],
                name=seq["name"],
                torch_context=seq.get("torch_context", []),
                ecosystem=seq.get("ecosystem", ""),
                ecosystem_label=seq.get("ecosystem_label", ""),
                steps=[
                    AssemblyStep(
                        order=s["order"],
                        action=s["action"],
                        part_role=s.get("part_role"),
                        part_id=s.get("part_id"),
                        note=s.get("note"),
                    )
                    for s in seq.get("steps", [])
                ],
                warning=seq.get("warning"),
                source=seq.get("source", ""),
            )
            for seq in data.get("assembly_sequences", [])
        ]

        replacement_procedures = [
            ReplacementProcedure(
                id=rp["id"],
                name=rp["name"],
                trigger=rp.get("trigger", ""),
                torch_context=rp.get("torch_context", []),
                steps=[
                    AssemblyStep(
                        order=s["order"],
                        action=s["action"],
                        part_role=s.get("part_role"),
                        part_id=s.get("part_id"),
                        note=s.get("note"),
                    )
                    for s in rp.get("steps", [])
                ],
                tools=rp.get("tools", []),
                cautions=rp.get("cautions", []),
                torque_ref=rp.get("torque_ref"),
                source=rp.get("source", ""),
            )
            for rp in data.get("replacement_procedures", [])
        ]

        troubleshooting = [
            TroubleshootingEntry(
                id=ts["id"],
                symptom=ts["symptom"],
                likely_causes=ts.get("likely_causes", []),
                recommended_action=ts.get("recommended_action", ""),
                related_procedures=ts.get("related_procedures", []),
                source=ts.get("source", ""),
            )
            for ts in data.get("troubleshooting", [])
        ]

        warnings = [
            WarningEntry(
                id=w["id"],
                context=w.get("context", ""),
                text=w["text"],
                severity=w.get("severity", "medium"),
                applies_to=w.get("applies_to", []),
                source=w.get("source", ""),
            )
            for w in data.get("warnings", [])
        ]

        liner_length_table = [
            LinerLengthEntry(
                part_id=row["part_id"],
                torch_models=row.get("torch_models", []),
                liner_length_mm=int(row["liner_length_mm"]),
                wire_size_mm=str(row.get("wire_size_mm", "")),
                robot_model=row.get("robot_model"),
                cable_length_m=row.get("cable_length_m"),
                oring=row.get("oring"),
                source=row.get("source", ""),
            )
            for row in data.get("liner_length_table", [])
        ]

        return cls(
            torque_specs=torque_specs,
            assembly_sequences=assembly_sequences,
            replacement_procedures=replacement_procedures,
            troubleshooting=troubleshooting,
            warnings=warnings,
            liner_length_table=liner_length_table,
            liner_protrusion_table=data.get("liner_protrusion_table", []),
            inner_tube_length_table=data.get("inner_tube_length_table", []),
            meta=data.get("meta", {}),
        )

    # ── Lookup API ────────────────────────────────────────────────────────────

    def get_torque_spec(self, category: str) -> Optional[TorqueSpec]:
        """Get torque spec by category (e.g. 'Tip', 'TipBody', 'TipAdapter')."""
        if not category:
            return None
        return self._torque_by_category.get(category)

    def get_torque_by_id(self, torque_id: str) -> Optional[TorqueSpec]:
        return self._torque_by_id.get(torque_id)

    def get_all_torque_specs(self) -> List[TorqueSpec]:
        return list(self._torque_specs)

    def get_assembly_sequence(
        self,
        torch_model: Optional[str] = None,
        ecosystem: Optional[str] = None,
    ) -> List[AssemblySequence]:
        """
        Get assembly sequences for a torch model (exact match) or ecosystem.
        Returns list ordered by relevance (torch-specific first).
        """
        results: List[AssemblySequence] = []
        seen = set()

        if torch_model:
            for seq in self._assembly_by_torch.get(torch_model, []):
                if seq.id not in seen:
                    seen.add(seq.id)
                    results.append(seq)

        if ecosystem:
            for seq in self._assembly_by_ecosystem.get(ecosystem, []):
                if seq.id not in seen:
                    seen.add(seq.id)
                    results.append(seq)

        # Fallback: torch_context "all" or generic sequences
        if not results:
            for seq in self._assembly_sequences:
                ctx_lower = [t.lower() for t in seq.torch_context]
                if any("all" in c or "generic" in c for c in ctx_lower):
                    if seq.id not in seen:
                        seen.add(seq.id)
                        results.append(seq)

        return results

    def get_replacement_procedure(
        self,
        category: Optional[str] = None,
        torch_model: Optional[str] = None,
    ) -> List[ReplacementProcedure]:
        """
        Find replacement procedures by category (Tip/Liner/InnerTube/...)
        and/or torch_model.
        """
        results: List[ReplacementProcedure] = []
        cat_lower = (category or "").lower()

        for rp in self._replacement_procedures:
            # Match by category — check rp.id, rp.name, steps
            matches_cat = False
            if cat_lower:
                if cat_lower in rp.id.lower() or cat_lower in rp.name.lower():
                    matches_cat = True
                else:
                    for step in rp.steps:
                        if step.part_role and cat_lower in step.part_role.lower():
                            matches_cat = True
                            break
            else:
                matches_cat = True

            if not matches_cat:
                continue

            # Match by torch — "all robotic torch models" passes any
            if torch_model:
                ctx_lower = [t.lower() for t in rp.torch_context]
                torch_lower = torch_model.lower()
                if not any(
                    "all" in c or torch_lower in c or c in torch_lower
                    for c in ctx_lower
                ):
                    continue

            results.append(rp)

        return results

    def get_troubleshooting(
        self,
        symptom_query: Optional[str] = None,
    ) -> List[TroubleshootingEntry]:
        """
        Match troubleshooting entries by free-text symptom query.
        Uses both Vietnamese and English keywords.
        """
        if not symptom_query:
            return list(self._troubleshooting)

        q_lower = symptom_query.lower()
        results: List[TroubleshootingEntry] = []
        seen_ids = set()

        # Direct symptom text match
        for ts in self._troubleshooting:
            if ts.id in seen_ids:
                continue
            symptom_lower = ts.symptom.lower()
            if any(token in symptom_lower for token in q_lower.split() if len(token) > 2):
                results.append(ts)
                seen_ids.add(ts.id)

        # Keyword bucket match
        for bucket, keywords in SYMPTOM_KEYWORDS_VI_EN.items():
            if any(kw in q_lower for kw in keywords):
                # Find troubleshooting matching this bucket via simple heuristic
                for ts in self._troubleshooting:
                    if ts.id in seen_ids:
                        continue
                    if bucket in ts.id.lower() or any(
                        kw in ts.symptom.lower() for kw in keywords[:3]
                    ):
                        results.append(ts)
                        seen_ids.add(ts.id)

        return results

    def get_warnings(
        self,
        torch_model: Optional[str] = None,
        severity_min: str = "medium",
    ) -> List[WarningEntry]:
        """Get warnings applicable to a torch_model. Optionally filter by severity."""
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(severity_min, 1)

        results: List[WarningEntry] = []
        for w in self._warnings:
            w_level = severity_order.get(w.severity, 1)
            if w_level < min_level:
                continue

            if not torch_model:
                results.append(w)
                continue

            applies_lower = [t.lower() for t in w.applies_to]
            torch_lower = torch_model.lower()
            if any(
                "all" in t or torch_lower in t or t in torch_lower
                for t in applies_lower
            ):
                results.append(w)

        return results

    def get_liner_length(
        self,
        torch_model: Optional[str] = None,
        wire_size: Optional[str] = None,
        robot_model: Optional[str] = None,
    ) -> List[LinerLengthEntry]:
        """Lookup liner length entries by torch / wire / robot."""
        results: List[LinerLengthEntry] = []
        for row in self._liner_length_table:
            if torch_model and torch_model not in row.torch_models:
                continue
            if wire_size and str(wire_size) not in row.wire_size_mm:
                continue
            if robot_model and row.robot_model:
                if robot_model.lower() not in row.robot_model.lower():
                    continue
            results.append(row)
        return results

    def get_liner_protrusion(self, torch_model: str) -> Optional[Dict[str, Any]]:
        """Get liner protrusion length (mm) for a specific torch."""
        if not torch_model:
            return None
        for row in self._liner_protrusion_table:
            if row.get("torch_model") == torch_model:
                return row
        return None

    def get_inner_tube_length(self, torch_model: str) -> List[Dict[str, Any]]:
        """Get inner tube length for a torch."""
        if not torch_model:
            return []
        return [
            row for row in self._inner_tube_length_table
            if torch_model in row.get("torch_models", [])
        ]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        return {
            "torque_specs": len(self._torque_specs),
            "assembly_sequences": len(self._assembly_sequences),
            "replacement_procedures": len(self._replacement_procedures),
            "troubleshooting": len(self._troubleshooting),
            "warnings": len(self._warnings),
            "liner_length_rows": len(self._liner_length_table),
            "liner_protrusion_rows": len(self._liner_protrusion_table),
            "inner_tube_rows": len(self._inner_tube_length_table),
        }

    def meta_info(self) -> Dict[str, Any]:
        return dict(self._meta)


# ─── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/assembly_procedures.json"

    print(f"Loading {path}...")
    kb = AssemblyKB.from_file(path)
    print(f"✓ Loaded. Stats: {kb.stats()}")
    print(f"  Meta: {kb.meta_info().get('version', '?')}")

    print("\n--- Test 1: get_torque_spec('Tip') ---")
    t = kb.get_torque_spec("Tip")
    if t:
        print(f"  {t.component}: {t.value_display}, tool: {t.tool_recommended}")

    print("\n--- Test 2: get_assembly_sequence(torch='YMSA-500W') ---")
    seqs = kb.get_assembly_sequence(torch_model="YMSA-500W")
    for seq in seqs:
        print(f"  [{seq.id}] {seq.name} ({len(seq.steps)} steps)")

    print("\n--- Test 3: get_troubleshooting(query='kẹt dây') ---")
    troubles = kb.get_troubleshooting("kẹt dây")
    for tr in troubles:
        print(f"  [{tr.id}] {tr.symptom}")
        print(f"    Action: {tr.recommended_action[:80]}")

    print("\n--- Test 4: get_liner_length(torch='TK-308RR', wire='1.2') ---")
    rows = kb.get_liner_length(torch_model="TK-308RR", wire_size="1.2")
    for r in rows[:3]:
        print(f"  part {r.part_id}: {r.liner_length_mm}mm (robot={r.robot_model})")

    print("\n--- Test 5: get_warnings(torch='YMSA-500W') ---")
    warns = kb.get_warnings(torch_model="YMSA-500W")
    for w in warns[:3]:
        print(f"  [{w.severity.upper()}] {w.text[:80]}")
