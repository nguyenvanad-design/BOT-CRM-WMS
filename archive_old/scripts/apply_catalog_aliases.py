#!/usr/bin/env python3
"""
apply_catalog_aliases.py
Batch update tokinarc_data_v14.json với aliases từ CATALOG_02.pdf
Run: python apply_catalog_aliases.py [data_path]
"""
import json, sys, os
from catalog_aliases import CATALOG_ALIASES

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/tokinarc_data_v14.json"
BACKUP    = DATA_PATH + ".bak"

# Load
with open(DATA_PATH, encoding="utf-8") as f:
    d = json.load(f)

# Backup
with open(BACKUP, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False)
print(f"Backup: {BACKUP}")

stats = {"updated": 0, "p_added": 0, "d_added": 0, "o_added": 0, "not_found": 0}
not_found = []

for pno, aliases in CATALOG_ALIASES.items():
    # Find part
    part = next((p for p in d["parts"] if p["tokin_part_no"] == pno), None)
    if not part:
        stats["not_found"] += 1
        not_found.append(pno)
        continue

    changed = False

    # Update p_part_nos
    p_new = aliases.get("p", [])
    if p_new:
        existing = set(part.get("p_part_nos") or [])
        added = [x for x in p_new if x not in existing]
        if added:
            part["p_part_nos"] = list(existing) + added
            stats["p_added"] += len(added)
            changed = True

    # Update d_part_nos
    d_new = aliases.get("d", [])
    if d_new:
        existing = set(part.get("d_part_nos") or [])
        added = [x for x in d_new if x not in existing]
        if added:
            part["d_part_nos"] = list(existing) + added
            stats["d_added"] += len(added)
            changed = True

    # Update o_part_nos (OTC)
    o_new = aliases.get("o", [])
    if o_new:
        existing = set(part.get("o_part_nos") or [])
        added = [x for x in o_new if x not in existing]
        if added:
            part["o_part_nos"] = list(existing) + added
            stats["o_added"] += len(added)
            changed = True

    if changed:
        stats["updated"] += 1

# Bump patch note
d["meta"]["patch"] = (d["meta"].get("patch","") +
    f" +catalog02_aliases(p={stats['p_added']},d={stats['d_added']},o={stats['o_added']})")

# Save
with open(DATA_PATH, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"\nResults:")
print(f"  Parts updated:    {stats['updated']}")
print(f"  P aliases added:  {stats['p_added']}")
print(f"  D aliases added:  {stats['d_added']}")
print(f"  O aliases added:  {stats['o_added']}")
print(f"  Parts not found:  {stats['not_found']}")
if not_found:
    print(f"  Not found list:   {not_found[:20]}")
print(f"\nSaved: {DATA_PATH}")
