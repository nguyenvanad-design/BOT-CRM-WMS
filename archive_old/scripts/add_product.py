"""
add_product.py — TOKINARC safe product addition script
=======================================================
Thêm part/torch/consumable_set mới vào tokinarc_data JSON an toàn.

Features:
  - Validate schema trước khi ghi
  - Kiểm tra duplicate part_no
  - Kiểm tra part_id references hợp lệ
  - Auto version bump
  - Smoke test sau khi thêm
  - Backup trước khi ghi

Usage:
  # Thêm 1 part từ JSON file:
  python add_product.py --data tokinarc_data_v14.json --add-part part.json

  # Thêm từ inline JSON:
  python add_product.py --data tokinarc_data_v14.json \\
      --part-json '{"tokin_part_no":"099001","category":"Tip",...}'

  # Thêm consumable set:
  python add_product.py --data tokinarc_data_v14.json --add-set set.json

  # Dry run (validate only, không ghi):
  python add_product.py --data tokinarc_data_v14.json --add-part part.json --dry-run

  # List all parts trong category:
  python add_product.py --data tokinarc_data_v14.json --list Tip
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────────────

REQUIRED_PART_FIELDS = ["tokin_part_no", "category", "ecosystem", "display_name_vi"]
VALID_CATEGORIES = {
    "Tip", "Nozzle", "Insulator", "Orifice", "TipBody", "TipAdapter",
    "Liner", "LinerORing", "InnerTube", "WaveWasher", "Tool",
    "TorchBody", "CableAssembly", "PowerCable", "GasHose",
    "Collet", "ColletBody", "GasLensColletBody", "GasLensInsulator",
    "CeramicNozzle", "LavaNozzle", "BackCap", "Gasket",
    "TungstenElectrode", "Handle", "GuideTube", "InsulationCollar",
    "InsulationSpacer", "RobotBracket", "RobotFlange", "ORing",
    "WXCenterCeramic", "WXNozzleSpacer", "WXNozzleAdapter",
    "WXNozzleNut", "WXCoverRubber", "WXNozzleSleeve", "AlignmentFixture",
}
VALID_ECOSYSTEMS = {"N", "D", "WX", "TIG", "TCC", "UNIVERSAL", "HYBRID", "MAN"}
VALID_CURRENT_CLASSES = {
    "80A", "125A", "150A", "180A", "200A", "225A", "250A",
    "280A", "300A", "310A", "350A", "400A", "410A", "500A",
    "ALL", "varies",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_data(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict, path: str, dry_run: bool = False) -> str:
    if dry_run:
        print(f"  [DRY RUN] would write to {path}")
        return path

    # Backup
    backup = path + f".bak_{int(time.time())}"
    shutil.copy2(path, backup)
    print(f"  Backup: {backup}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved:  {path}")
    return path


def bump_version(data: dict) -> str:
    meta = data.setdefault("meta", {})
    ver  = meta.get("version", "v1")
    # v14 → v15, v14a → v14b
    m = re.match(r"^(v\d+)([a-z]?)$", ver)
    if m:
        base, suffix = m.groups()
        new_ver = base + (chr(ord(suffix) + 1) if suffix else "a")
    else:
        new_ver = ver + "a"
    meta["version"] = new_ver
    return new_ver


# ─── Validators ───────────────────────────────────────────────────────────────

def validate_part(part: dict, existing_pnos: set) -> list[str]:
    errors = []

    # Required fields
    for f in REQUIRED_PART_FIELDS:
        if not part.get(f):
            errors.append(f"Thiếu field bắt buộc: '{f}'")

    pno = part.get("tokin_part_no", "")

    # Part no format — 6 digits hoặc alphanumeric (WX parts có prefix)
    if pno and not re.match(r"^[A-Z0-9]{5,12}$", pno.upper()):
        errors.append(f"tokin_part_no '{pno}' có format lạ (expected 6-digit or alphanumeric ≤12)")

    # Duplicate check
    if pno and pno in existing_pnos:
        errors.append(f"tokin_part_no '{pno}' đã tồn tại trong data")

    # Category
    cat = part.get("category", "")
    if cat and cat not in VALID_CATEGORIES:
        errors.append(f"category '{cat}' không hợp lệ. Valid: {sorted(VALID_CATEGORIES)[:5]}...")

    # Ecosystem
    eco = part.get("ecosystem", "")
    if eco and eco not in VALID_ECOSYSTEMS:
        errors.append(f"ecosystem '{eco}' không hợp lệ. Valid: {sorted(VALID_ECOSYSTEMS)}")

    # Current class
    cc = part.get("current_class", "")
    if cc and cc not in VALID_CURRENT_CLASSES:
        errors.append(f"current_class '{cc}' không hợp lệ. Valid: {sorted(VALID_CURRENT_CLASSES)}")

    # Business info
    biz = part.get("business", {})
    if biz:
        price = biz.get("price_vnd")
        is_contact = biz.get("is_contact_price", False)
        if not price and not is_contact:
            errors.append("business.price_vnd trống và is_contact_price=False — cần điền giá hoặc set is_contact_price=true")

    return errors


def validate_consumable_set(cs: dict, existing_pnos: set, existing_set_ids: set) -> list[str]:
    errors = []

    if not cs.get("set_id"):
        errors.append("Thiếu set_id")
    elif cs["set_id"] in existing_set_ids:
        errors.append(f"set_id '{cs['set_id']}' đã tồn tại")

    if not cs.get("ecosystem"):
        errors.append("Thiếu ecosystem")
    if not cs.get("torch_current_class"):
        errors.append("Thiếu torch_current_class")

    items = cs.get("items", [])
    if not items:
        errors.append("items rỗng — consumable set phải có ít nhất 1 item")

    mandatory_count = sum(1 for i in items if i.get("is_mandatory"))
    if mandatory_count == 0:
        errors.append("Không có item nào is_mandatory=true")

    for item in items:
        pid = item.get("part_id", "")
        if not pid:
            errors.append("item thiếu part_id")
        elif pid not in existing_pnos:
            errors.append(f"item part_id '{pid}' không tồn tại trong parts")

    return errors


# ─── Smoke test ───────────────────────────────────────────────────────────────

def smoke_test(data: dict, new_pno: Optional[str] = None,
               new_set_id: Optional[str] = None) -> list[str]:
    """Quick smoke test sau khi thêm."""
    errors = []
    parts_map = {p["tokin_part_no"]: p for p in data.get("parts", [])}

    # Check consumable sets reference valid parts
    for cs in data.get("consumable_sets", []):
        for item in cs.get("items", []):
            pid = item.get("part_id", "")
            if pid and pid not in parts_map:
                errors.append(f"consumable_set '{cs['set_id']}' → item '{pid}' không tồn tại")

    # Check new part nếu có
    if new_pno and new_pno not in parts_map:
        errors.append(f"New part '{new_pno}' không tìm thấy sau khi thêm")

    # Check new set nếu có
    if new_set_id:
        found = any(cs["set_id"] == new_set_id for cs in data.get("consumable_sets", []))
        if not found:
            errors.append(f"New set '{new_set_id}' không tìm thấy sau khi thêm")

    return errors


# ─── Actions ──────────────────────────────────────────────────────────────────

def add_part(data: dict, part: dict, dry_run: bool = False) -> bool:
    existing_pnos = {p["tokin_part_no"] for p in data.get("parts", [])}

    print(f"\n[ADD PART] {part.get('tokin_part_no')} — {part.get('display_name_vi','')[:60]}")
    print(f"  category={part.get('category')}  ecosystem={part.get('ecosystem')}  cc={part.get('current_class','')}")

    errors = validate_part(part, existing_pnos)
    if errors:
        print("  ❌ VALIDATION FAILED:")
        for e in errors:
            print(f"    - {e}")
        return False

    print("  ✅ Validation OK")

    if not dry_run:
        data["parts"].append(part)
        new_ver = bump_version(data)
        data["meta"]["patch"] = (
            f"{new_ver}: +part {part['tokin_part_no']} "
            f"({part.get('category')} {part.get('ecosystem','')})"
        )
        print(f"  Version bumped → {new_ver}")

        smoke_errors = smoke_test(data, new_pno=part["tokin_part_no"])
        if smoke_errors:
            print("  ❌ SMOKE TEST FAILED:")
            for e in smoke_errors: print(f"    - {e}")
            # Rollback
            data["parts"].pop()
            return False
        print("  ✅ Smoke test OK")
    return True


def add_consumable_set(data: dict, cs: dict, dry_run: bool = False) -> bool:
    existing_pnos   = {p["tokin_part_no"] for p in data.get("parts", [])}
    existing_set_ids = {c["set_id"] for c in data.get("consumable_sets", [])}

    print(f"\n[ADD SET] {cs.get('set_id')} — {cs.get('display_name_vi','')[:60]}")
    print(f"  eco={cs.get('ecosystem')} cc={cs.get('torch_current_class')} items={len(cs.get('items',[]))}")

    errors = validate_consumable_set(cs, existing_pnos, existing_set_ids)
    if errors:
        print("  ❌ VALIDATION FAILED:")
        for e in errors: print(f"    - {e}")
        return False

    print("  ✅ Validation OK")

    if not dry_run:
        data["consumable_sets"].append(cs)
        new_ver = bump_version(data)
        data["meta"]["patch"] = f"{new_ver}: +consumable_set {cs['set_id']}"
        print(f"  Version bumped → {new_ver}")

        smoke_errors = smoke_test(data, new_set_id=cs["set_id"])
        if smoke_errors:
            print("  ❌ SMOKE TEST FAILED:")
            for e in smoke_errors: print(f"    - {e}")
            data["consumable_sets"].pop()
            return False
        print("  ✅ Smoke test OK")
    return True


def list_parts(data: dict, category: str):
    parts = [p for p in data.get("parts", [])
             if p.get("category", "").lower() == category.lower()]
    print(f"\nCategory '{category}': {len(parts)} parts")
    for p in sorted(parts, key=lambda x: x["tokin_part_no"]):
        eco = p.get("ecosystem", "")
        cc  = p.get("current_class", "")
        biz = p.get("business", {}) or {}
        price = f"{biz['price_vnd']:,}đ" if biz.get("price_vnd") else "liên hệ"
        print(f"  {p['tokin_part_no']:12s} {eco:10s} {cc:6s} {price:12s}  {p.get('display_name_vi','')[:50]}")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="TOKINARC add_product — safe data update tool")
    ap.add_argument("--data",      required=True, help="Path to tokinarc_data_vXX.json")
    ap.add_argument("--add-part",  help="JSON file chứa part mới")
    ap.add_argument("--part-json", help="Inline JSON string cho part mới")
    ap.add_argument("--add-set",   help="JSON file chứa consumable_set mới")
    ap.add_argument("--set-json",  help="Inline JSON string cho consumable_set mới")
    ap.add_argument("--list",      help="List parts theo category (e.g. --list Tip)")
    ap.add_argument("--dry-run",   action="store_true", help="Validate only, không ghi file")
    ap.add_argument("--out",       help="Output path (default: ghi đè file input)")
    args = ap.parse_args()

    if not Path(args.data).exists():
        print(f"❌ File không tìm thấy: {args.data}")
        sys.exit(1)

    data = load_data(args.data)
    out_path = args.out or args.data

    print(f"Loaded: {args.data}")
    print(f"  parts={len(data.get('parts',[]))}  "
          f"torches={len(data.get('torches',[]))}  "
          f"sets={len(data.get('consumable_sets',[]))}  "
          f"version={data.get('meta',{}).get('version','?')}")

    # ── List ──────────────────────────────────────────────────────────────────
    if args.list:
        list_parts(data, args.list)
        return

    # ── Add part ──────────────────────────────────────────────────────────────
    if args.add_part or args.part_json:
        if args.add_part:
            with open(args.add_part, encoding="utf-8") as f:
                part = json.load(f)
        else:
            part = json.loads(args.part_json)

        ok = add_part(data, part, dry_run=args.dry_run)
        if ok and not args.dry_run:
            save_data(data, out_path, dry_run=False)
        elif not ok:
            sys.exit(1)

    # ── Add consumable set ────────────────────────────────────────────────────
    elif args.add_set or args.set_json:
        if args.add_set:
            with open(args.add_set, encoding="utf-8") as f:
                cs = json.load(f)
        else:
            cs = json.loads(args.set_json)

        ok = add_consumable_set(data, cs, dry_run=args.dry_run)
        if ok and not args.dry_run:
            save_data(data, out_path, dry_run=False)
        elif not ok:
            sys.exit(1)

    else:
        print("Không có action nào. Dùng --add-part, --add-set, hoặc --list.")
        ap.print_help()


if __name__ == "__main__":
    main()
