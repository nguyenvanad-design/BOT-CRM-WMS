"""
Tokinarc V6.C — apps/catalog/management/commands/seed_from_json.py

Phiên bản đã sửa 9 lỗi field-name của V6.B (xem V6.C.1 §4):
  1. Torch dùng display_name_vi (không phải display_name)
  2. Pricing flatten từ business sub-object — cả Torch lẫn Part
  3. CompatibilityEdge dùng from_part/to_part/relation_type (không src/dst/edge_type)
  4. Normalize 22 entries shape cũ (from/to/relation/weight) sang shape chuẩn
  5. TorchPartMapping được explode: 1 (torch, part_no, role) = 1 row
  6. ConsumableSet hỗ trợ cả 2 shape: items[] và parts[]
  7. ConsumableSetItem dùng part_id/part_no, default_quantity, part_role
  8. NegativeRule giữ tất cả field rare trong JSONField extras
  9. Lưu SeedMeta cho audit

Dùng:
    python manage.py seed_from_json data/tokinarc_data_v19.json
    python manage.py seed_from_json data/tokinarc_data_v19.json --truncate
    python manage.py seed_from_json data/tokinarc_data_v19.json --dry-run
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import (
    CategoryVocabulary,
    CompatibilityEdge,
    ConsumableSet,
    ConsumableSetItem,
    GasFlowEdge,
    NegativeRule,
    Part,
    PartNoAlias,
    ProcessEdge,
    SeedMeta,
    Torch,
    TorchPartMapping,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

_NEGATIVE_RULE_CORE_FIELDS = {
    "rule_id", "description",
    "from_category", "to_category",
    "from_ecosystem", "to_ecosystem", "from_current_class",
    "relation_type", "incompatibility_reason",
    "confidence", "source",
}

_TORCH_CORE_FIELDS = {
    "model_code", "display_name_vi", "display_name_en",
    "family", "ecosystem", "current_class", "body_type", "cooling",
    "process", "welding_process", "wire_size",
    "rated_dc_a", "rated_co2_a", "rated_mag_a", "rated_mig_a",
    "duty_cycle_pct", "duty_co2_pct", "duty_mag_pct", "weight_g",
    "has_shock_sensor", "shock_sensor_type",
    "has_cylinder", "has_air_cylinder", "is_detachable", "is_ultralight",
    "mounting", "connection_types", "connector_type",
    "compatible_parts", "editorial_picks", "tpm_count",
    "business", "notes", "note", "source",
}

_PART_CORE_FIELDS = {
    "tokin_part_no", "category", "ecosystem", "current_class",
    "display_name_vi", "display_name_en",
    "wire_size_mm", "total_length_mm", "body_length_mm",
    "thread_type", "material", "tip_type", "wire_material",
    "supported_processes",
    "p_part_nos", "d_part_nos", "o_part_nos",
    "p_model_codes", "d_model_codes", "o_model_codes",
    "compatible_with", "used_with", "torch_models",
    "applicable_torches", "editorial_picks",
    "business", "specs", "source", "confidence", "notes", "note",
}


def _dec(v: Any) -> Decimal | None:
    """Convert tới Decimal, trả None nếu invalid hoặc rỗng."""
    if v in (None, "", "N/A", "n/a"):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int_or_none(v: Any) -> int | None:
    if v in (None, "", "N/A"):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _notes_of(r: dict) -> str:
    """JSON dùng cả 'notes' và 'note' tùy nhóm — gom làm một."""
    return r.get("notes") or r.get("note") or ""


# ─── Command ─────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Seed catalog từ tokinarc_data_v19.json (12 nhóm, idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("json_path")
        parser.add_argument("--truncate", action="store_true",
                            help="Xóa toàn bộ catalog trước khi seed")
        parser.add_argument("--dry-run", action="store_true",
                            help="Đọc + validate, KHÔNG commit")

    def handle(self, json_path, truncate=False, dry_run=False, **kwargs):
        p = Path(json_path)
        if not p.exists():
            raise CommandError(f"Không tìm thấy {p}")

        with p.open(encoding="utf-8") as f:
            data = json.load(f)

        # Đếm raw để cảnh báo drift
        real_counts = {
            "torches":             len(data.get("torches", [])),
            "parts":               len(data.get("parts", [])),
            "compatibility_edges": len(data.get("compatibility_edges", [])),
            "torch_part_mappings": len(data.get("torch_part_mappings", [])),
            "process_edges":       len(data.get("process_edges", [])),
            "gas_flow_edges":      len(data.get("gas_flow_edges", [])),
            "consumable_sets":     len(data.get("consumable_sets", [])),
            "negative_rules":      len(data.get("negative_rules", [])),
            "category_vocabulary": len(data.get("category_vocabulary", [])),
            "fake_pno_aliases":    len(data.get("fake_pno_aliases", {})),
        }
        meta_stats = data.get("meta", {}).get("stats", {})
        for k_meta, k_real in [
            ("part_count", "parts"),
            ("torch_count", "torches"),
            ("compatibility_edge_count", "compatibility_edges"),
            ("tpm_count", "torch_part_mappings"),
        ]:
            declared = meta_stats.get(k_meta)
            actual = real_counts[k_real]
            if declared is not None and declared != actual:
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ meta.stats.{k_meta}={declared} ≠ actual={actual} (dùng actual)"
                ))

        if dry_run:
            self.stdout.write(self.style.NOTICE(f"DRY RUN — đã đọc {p}, counts: {real_counts}"))
            return

        with transaction.atomic():
            if truncate:
                self._truncate()
            self._seed_torches(data.get("torches", []))
            self._seed_parts(data.get("parts", []))
            self._seed_compat(data.get("compatibility_edges", []))
            tpm_exploded = self._seed_tpm(data.get("torch_part_mappings", []))
            self._seed_process(data.get("process_edges", []))
            self._seed_gasflow(data.get("gas_flow_edges", []))
            self._seed_consumable(data.get("consumable_sets", []))
            self._seed_negative(data.get("negative_rules", []))
            self._seed_vocab(data.get("category_vocabulary", []))
            self._seed_aliases(data.get("fake_pno_aliases", {}))
            self._save_meta(data, real_counts | {"tpm_exploded": tpm_exploded})
            self._validate(data)

        self.stdout.write(self.style.SUCCESS(
            f"✅ Seed xong (v{data.get('meta', {}).get('version', '?')}): "
            f"{real_counts['torches']} torches, "
            f"{real_counts['parts']} parts, "
            f"{real_counts['compatibility_edges']} edges, "
            f"{tpm_exploded} TPM rows (exploded từ {real_counts['torch_part_mappings']})."
        ))

    # ── truncate ────────────────────────────────────────────────────────────
    def _truncate(self):
        # Thứ tự: item trước, parent sau
        for M in (
            ConsumableSetItem, ConsumableSet,
            GasFlowEdge, ProcessEdge,
            NegativeRule, CategoryVocabulary, PartNoAlias,
            TorchPartMapping, CompatibilityEdge,
            Part, Torch, SeedMeta,
        ):
            M.objects.all().delete()
        self.stdout.write(self.style.WARNING("⚠  Đã truncate toàn bộ catalog."))

    # ── 1. torches ──────────────────────────────────────────────────────────
    def _seed_torches(self, rows):
        objs = []
        for r in rows:
            business = r.get("business") or {}
            # specs = tất cả field không nằm trong _TORCH_CORE_FIELDS
            specs = {k: v for k, v in r.items() if k not in _TORCH_CORE_FIELDS}
            objs.append(Torch(
                model_code        = r["model_code"],
                display_name_vi   = r.get("display_name_vi", r["model_code"]),
                display_name_en   = r.get("display_name_en", ""),
                family            = r.get("family", ""),
                ecosystem         = r.get("ecosystem", ""),
                current_class     = r.get("current_class", ""),
                body_type         = r.get("body_type", ""),
                cooling           = r.get("cooling") or r.get("cooling_type") or "",
                process           = r.get("process", []),
                welding_process   = r.get("welding_process", []),
                wire_size         = r.get("wire_size", ""),
                rated_dc_a        = _int_or_none(r.get("rated_dc_a")),
                rated_co2_a       = _int_or_none(r.get("rated_co2_a")),
                rated_mag_a       = _int_or_none(r.get("rated_mag_a")),
                rated_mig_a       = _int_or_none(r.get("rated_mig_a")),
                duty_cycle_pct    = _int_or_none(r.get("duty_cycle_pct") or r.get("duty_pct")),
                duty_co2_pct      = _int_or_none(r.get("duty_co2_pct")),
                duty_mag_pct      = _int_or_none(r.get("duty_mag_pct")),
                weight_g          = _int_or_none(r.get("weight_g")),
                has_shock_sensor  = r.get("has_shock_sensor") or r.get("has_built_in_shock_sensor") or False,
                shock_sensor_type = r.get("shock_sensor_type", ""),
                has_cylinder      = r.get("has_cylinder", False),
                has_air_cylinder  = r.get("has_air_cylinder", False),
                is_detachable     = r.get("is_detachable", False),
                is_ultralight     = r.get("is_ultralight", False),
                mounting          = r.get("mounting", ""),
                connection_types  = r.get("connection_types", []),
                connector_type    = r.get("connector_type", ""),
                compatible_parts  = r.get("compatible_parts", []),
                editorial_picks   = r.get("editorial_picks", []),
                tpm_count         = r.get("tpm_count", 0),
                # business flattened
                price_vnd         = _dec(business.get("price_vnd")),
                price_unit        = business.get("price_unit", "cái"),
                price_note        = business.get("price_note", ""),
                is_contact_price  = business.get("is_contact_price", False),
                is_priority_sell  = business.get("is_priority_sell", False),
                price_updated     = business.get("price_updated", ""),
                price_tier        = business.get("price_tier", ""),
                specs             = specs,
                notes             = _notes_of(r),
                source            = r.get("source", ""),
            ))

        Torch.objects.bulk_create(
            objs, update_conflicts=True,
            unique_fields=["model_code"],
            update_fields=[
                "display_name_vi", "display_name_en",
                "family", "ecosystem", "current_class", "body_type", "cooling",
                "process", "welding_process", "wire_size",
                "rated_dc_a", "rated_co2_a", "rated_mag_a", "rated_mig_a",
                "duty_cycle_pct", "duty_co2_pct", "duty_mag_pct", "weight_g",
                "has_shock_sensor", "shock_sensor_type",
                "has_cylinder", "has_air_cylinder", "is_detachable", "is_ultralight",
                "mounting", "connection_types", "connector_type",
                "compatible_parts", "editorial_picks", "tpm_count",
                "price_vnd", "price_unit", "price_note",
                "is_contact_price", "is_priority_sell",
                "price_updated", "price_tier",
                "specs", "notes", "source",
            ],
            batch_size=500,
        )

    # ── 2. parts ────────────────────────────────────────────────────────────
    def _seed_parts(self, rows):
        objs = []
        for r in rows:
            business = r.get("business") or {}
            specs = {k: v for k, v in r.items() if k not in _PART_CORE_FIELDS}
            # JSON đôi khi đã có 'specs' sub-object — merge vào
            if "specs" in r and isinstance(r["specs"], dict):
                specs = {**r["specs"], **specs}
            objs.append(Part(
                tokin_part_no    = r["tokin_part_no"],
                category         = r.get("category", ""),
                ecosystem        = r.get("ecosystem", ""),
                current_class    = r.get("current_class", ""),
                display_name_vi  = r.get("display_name_vi", ""),
                display_name_en  = r.get("display_name_en", ""),
                wire_size_mm     = _dec(r.get("wire_size_mm")),
                total_length_mm  = _dec(r.get("total_length_mm")),
                body_length_mm   = _dec(r.get("body_length_mm")),
                thread_type      = r.get("thread_type", ""),
                material         = r.get("material", ""),
                tip_type         = r.get("tip_type", ""),
                wire_material    = r.get("wire_material", ""),
                supported_processes = r.get("supported_processes", []),
                p_part_nos       = r.get("p_part_nos", []),
                d_part_nos       = r.get("d_part_nos", []),
                o_part_nos       = r.get("o_part_nos", []),
                p_model_codes    = r.get("p_model_codes", []),
                d_model_codes    = r.get("d_model_codes", []),
                o_model_codes    = r.get("o_model_codes", []),
                compatible_with  = r.get("compatible_with", []),
                used_with        = r.get("used_with", []),
                torch_models     = r.get("torch_models", []),
                applicable_torches = r.get("applicable_torches", []),
                editorial_picks  = r.get("editorial_picks", []),
                price_vnd        = _dec(business.get("price_vnd")),
                price_unit       = business.get("price_unit", "cái"),
                price_note       = business.get("price_note", ""),
                is_contact_price = business.get("is_contact_price", False),
                is_priority_sell = business.get("is_priority_sell", False),
                price_updated    = business.get("price_updated", ""),
                price_tier       = business.get("price_tier", ""),
                specs            = specs,
                source           = r.get("source", ""),
                confidence       = _dec(r.get("confidence")) or Decimal("1.0"),
                notes            = _notes_of(r),
            ))

        Part.objects.bulk_create(
            objs, update_conflicts=True,
            unique_fields=["tokin_part_no"],
            update_fields=[
                "category", "ecosystem", "current_class",
                "display_name_vi", "display_name_en",
                "wire_size_mm", "total_length_mm", "body_length_mm",
                "thread_type", "material", "tip_type", "wire_material",
                "supported_processes",
                "p_part_nos", "d_part_nos", "o_part_nos",
                "p_model_codes", "d_model_codes", "o_model_codes",
                "compatible_with", "used_with", "torch_models",
                "applicable_torches", "editorial_picks",
                "price_vnd", "price_unit", "price_note",
                "is_contact_price", "is_priority_sell",
                "price_updated", "price_tier",
                "specs", "source", "confidence", "notes",
            ],
            batch_size=500,
        )

    # ── 3. compatibility_edges ──────────────────────────────────────────────
    def _seed_compat(self, rows):
        """
        Normalize 5 shape về 1: from_part/to_part/relation_type/priority_rank/
        is_mandatory/confidence/note/source/result_part.
        """
        seen = set()
        objs = []
        for r in rows:
            # Normalize tên field
            src = r.get("from_part") or r.get("from")
            dst = r.get("to_part")   or r.get("to")
            if not (src and dst):
                continue
            rel = r.get("relation_type") or r.get("relation") or "compatible_with"
            key = (src, dst, rel)
            if key in seen:
                continue
            seen.add(key)
            conf = _dec(r.get("confidence"))
            if conf is None and "weight" in r:
                conf = _dec(r.get("weight"))
            if conf is None:
                conf = Decimal("1.0")
            objs.append(CompatibilityEdge(
                from_part     = src,
                to_part       = dst,
                relation_type = rel,
                priority_rank = r.get("priority_rank", 0),
                is_mandatory  = r.get("is_mandatory", False),
                confidence    = conf,
                note          = r.get("note", "") or "",
                source        = r.get("source", "") or "",
                result_part   = r.get("result_part", "") or "",
            ))
        CompatibilityEdge.objects.bulk_create(objs, ignore_conflicts=True, batch_size=2000)

    # ── 4. torch_part_mappings (EXPLODE) ────────────────────────────────────
    def _seed_tpm(self, rows) -> int:
        """
        1 TPM JSON row = 1 (torch_model, ref_no, role) + part_nos[].
        Explode thành N (torch_model, part_no, role, ref_no) rows.
        """
        torch_set = set(Torch.objects.values_list("model_code", flat=True))
        part_set  = set(Part.objects.values_list("tokin_part_no", flat=True))

        objs = []
        skipped_torch = 0
        skipped_part  = 0
        for r in rows:
            tm = r.get("torch_model")
            if tm not in torch_set:
                skipped_torch += 1
                continue
            role    = r.get("part_role", "")
            ref_no  = str(r.get("ref_no", ""))
            mand    = r.get("is_mandatory", False)
            conf    = _dec(r.get("confidence")) or Decimal("1.0")
            note    = r.get("note", "") or ""
            src     = r.get("source", "") or ""
            robot   = r.get("robot_model", "") or ""
            conn    = r.get("connection_type", "") or ""
            wsa     = r.get("wire_size_applicability", []) or []
            for pno in r.get("part_nos", []):
                if pno not in part_set:
                    skipped_part += 1
                    continue
                objs.append(TorchPartMapping(
                    torch_model  = tm,
                    part_no      = pno,
                    part_role    = role,
                    ref_no       = ref_no,
                    is_mandatory = mand,
                    confidence   = conf,
                    note         = note,
                    source       = src,
                    robot_model  = robot,
                    connection_type = conn,
                    wire_size_applicability = wsa,
                ))
        TorchPartMapping.objects.bulk_create(objs, ignore_conflicts=True, batch_size=2000)

        if skipped_torch or skipped_part:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ TPM: skipped {skipped_torch} torch refs, {skipped_part} part refs"
            ))
        return len(objs)

    # ── 5. process_edges ────────────────────────────────────────────────────
    def _seed_process(self, rows):
        part_set = set(Part.objects.values_list("tokin_part_no", flat=True))
        objs, skipped = [], 0
        seen = set()
        for r in rows:
            fp = r.get("from_part")
            if fp not in part_set:
                skipped += 1
                continue
            tp = r.get("to_process")
            rel = r.get("relation_type", "supports_process")
            key = (fp, tp, rel)
            if key in seen:
                continue
            seen.add(key)
            objs.append(ProcessEdge(
                from_part     = fp,
                to_process    = tp,
                relation_type = rel,
                is_preferred  = r.get("is_preferred", False),
                note          = r.get("note", "") or "",
                source        = r.get("source", "") or "",
            ))
        ProcessEdge.objects.bulk_create(objs, ignore_conflicts=True, batch_size=500)
        if skipped:
            self.stdout.write(self.style.WARNING(f"  ⚠ process_edges: skipped {skipped} orphan refs"))

    # ── 6. gas_flow_edges ───────────────────────────────────────────────────
    def _seed_gasflow(self, rows):
        part_set = set(Part.objects.values_list("tokin_part_no", flat=True))
        objs = []
        for r in rows:
            fo, tn = r.get("from_orifice"), r.get("to_nozzle")
            if fo not in part_set or tn not in part_set:
                continue
            objs.append(GasFlowEdge(
                from_orifice  = fo,
                to_nozzle     = tn,
                relation_type = r.get("relation_type", "fits_in_nozzle"),
                reason        = r.get("reason", "") or "",
                source        = r.get("source", "") or "",
            ))
        GasFlowEdge.objects.bulk_create(objs, ignore_conflicts=True, batch_size=500)

    # ── 7. consumable_sets (+ items) — hỗ trợ cả 2 shape ────────────────────
    def _seed_consumable(self, sets):
        part_set = set(Part.objects.values_list("tokin_part_no", flat=True))

        for s in sets:
            cs, _ = ConsumableSet.objects.update_or_create(
                set_id=s["set_id"],
                defaults=dict(
                    display_name_vi      = s.get("display_name_vi") or s.get("display_name", ""),
                    torch_current_class  = s.get("torch_current_class", ""),
                    ecosystem            = s.get("ecosystem", ""),
                    cooling_method       = s.get("cooling_method") or s.get("cooling", ""),
                    default_wire_size_mm = _dec(s.get("default_wire_size_mm")),
                    torch_models         = s.get("torch_models", []),
                    notes                = _notes_of(s),
                ),
            )
            # Items có thể nằm ở 'items' (shape mới) hoặc 'parts' (shape cũ)
            items = s.get("items") or s.get("parts") or []
            ConsumableSetItem.objects.filter(consumable_set=cs).delete()
            new_items = []
            for it in items:
                if isinstance(it, str):
                    pno = it
                    role, prio, mand, qty, note = "", 0, False, 1, ""
                elif isinstance(it, dict):
                    # JSON có 3 tên: part_id / part_no / part
                    pno = it.get("part_id") or it.get("part_no") or it.get("part")
                    role = it.get("part_role") or it.get("role", "")
                    prio = it.get("priority_rank", 0)
                    mand = it.get("is_mandatory", False)
                    # default_quantity (mới) hoặc qty (cũ)
                    qty  = it.get("default_quantity") or it.get("qty") or 1
                    note = it.get("note", "")
                else:
                    continue
                if not pno or pno not in part_set:
                    continue
                new_items.append(ConsumableSetItem(
                    consumable_set   = cs,
                    part_no          = pno,
                    part_role        = role,
                    priority_rank    = prio,
                    is_mandatory     = mand,
                    default_quantity = qty,
                    note             = note,
                ))
            ConsumableSetItem.objects.bulk_create(new_items, ignore_conflicts=True)

    # ── 8. negative_rules ───────────────────────────────────────────────────
    def _seed_negative(self, rows):
        for r in rows:
            extras = {k: v for k, v in r.items() if k not in _NEGATIVE_RULE_CORE_FIELDS}
            NegativeRule.objects.update_or_create(
                rule_id=r["rule_id"],
                defaults=dict(
                    description            = r.get("description", ""),
                    from_category          = r.get("from_category", ""),
                    to_category            = r.get("to_category", ""),
                    from_ecosystem         = r.get("from_ecosystem", ""),
                    to_ecosystem           = r.get("to_ecosystem", ""),
                    from_current_class     = r.get("from_current_class", ""),
                    relation_type          = r.get("relation_type", "incompatible_with"),
                    incompatibility_reason = r.get("incompatibility_reason", ""),
                    confidence             = _dec(r.get("confidence")) or Decimal("1.0"),
                    source                 = r.get("source", ""),
                    extras                 = extras,
                ),
            )

    # ── 9. category_vocabulary ──────────────────────────────────────────────
    def _seed_vocab(self, rows):
        for r in rows:
            CategoryVocabulary.objects.update_or_create(
                en_term=r["en_term"],
                defaults=dict(
                    vi_term       = r.get("vi_term", ""),
                    part_category = r.get("part_category", ""),
                    vi_aliases    = r.get("vi_aliases", []),
                ),
            )

    # ── 10. fake_pno_aliases ────────────────────────────────────────────────
    def _seed_aliases(self, aliases: dict):
        part_set = set(Part.objects.values_list("tokin_part_no", flat=True))
        for fake_pno, info in aliases.items():
            primary = info.get("primary")
            if primary not in part_set:
                continue
            PartNoAlias.objects.update_or_create(
                fake_pno=fake_pno,
                defaults=dict(
                    primary = primary,
                    alts    = info.get("alts", []),
                    note    = info.get("note", ""),
                ),
            )

    # ── 11. Save SeedMeta ──────────────────────────────────────────────────
    def _save_meta(self, data, counts):
        SeedMeta.objects.update_or_create(
            id=1,
            defaults=dict(
                version   = data.get("meta", {}).get("version", "?"),
                json_meta = data.get("meta", {}),
                counts    = counts,
            ),
        )

    # ── 12. Validate ───────────────────────────────────────────────────────
    def _validate(self, data):
        idx = data.get("torch_model_index", [])
        torch_set = set(Torch.objects.values_list("model_code", flat=True))
        missing = [c for c in idx if c not in torch_set]
        if missing:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {len(missing)} torch trong torch_model_index chưa seed: {missing[:5]}..."
            ))
