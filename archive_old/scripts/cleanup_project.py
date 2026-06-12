#!/usr/bin/env python3
"""
cleanup_project.py — Dọn dẹp cấu trúc project TOKINARC
Run từ root repo: python cleanup_project.py
Run dry-run (xem trước, không làm gì): python cleanup_project.py --dry-run
"""
import os, sys, shutil
from pathlib import Path

ROOT = Path(".").resolve()
DRY  = "--dry-run" in sys.argv

def log(action: str, src, dst=None):
    if dst:
        print(f"  {action:<8} {Path(src).name} → {dst}")
    else:
        print(f"  {action:<8} {Path(src).name}")

def mkdir(p: Path):
    if not p.exists():
        if not DRY:
            p.mkdir(parents=True)
        log("MKDIR", p)

def move(src: Path, dst_dir: Path):
    dst = dst_dir / src.name
    if not src.exists():
        return
    if dst.exists():
        log("SKIP", src, f"{dst_dir.name}/ (already exists)")
        return
    log("MOVE", src, dst_dir.name + "/")
    if not DRY:
        shutil.move(str(src), str(dst))

def delete(src: Path):
    if not src.exists():
        return
    log("DELETE", src)
    if not DRY:
        src.unlink()

def delete_dir(src: Path):
    if not src.exists():
        return
    log("RMDIR", src)
    if not DRY:
        shutil.rmtree(str(src))

# ─── Directories ──────────────────────────────────────────────────────────────
TESTS_DIR   = ROOT / "tests"
SCRIPTS_DIR = ROOT / "scripts"

# ─── Files to DELETE (debug/temp) ─────────────────────────────────────────────
DELETE_FILES = [
    ROOT / "check2.py",
    ROOT / "check_aliases.py",
    ROOT / "check_missing.py",
    ROOT / "debug_alias.py",
    ROOT / "debug_v2.py",
]

# ─── Files to MOVE → tests/ ───────────────────────────────────────────────────
MOVE_TO_TESTS = [
    ROOT / "test_bm25_reranker.py",
    ROOT / "test_expert.py",
    ROOT / "test_install_repair.py",
    ROOT / "test_manual.py",
    ROOT / "test_session.py",
    ROOT / "test_wrappers_and_retrieval.py",
]

# ─── Files to MOVE → scripts/ ────────────────────────────────────────────────
MOVE_TO_SCRIPTS = [
    ROOT / "add_product.py",
    ROOT / "apply_catalog_aliases.py",
    ROOT / "catalog_aliases.py",
    ROOT / "show_fails.py",
    ROOT / "query_engine.py",
    ROOT / "check_system.py",
]

# ─── Core files to DELETE (unused) ────────────────────────────────────────────
DELETE_CORE = [
    ROOT / "core" / "eval_dashboard.py",
    ROOT / "core" / "structured_response.py",
    ROOT / "core" / "bm25_search.py",     # replaced by bm25_reranker.py
]

# ─── Run ──────────────────────────────────────────────────────────────────────

print("=" * 60)
print(f"  TOKINARC PROJECT CLEANUP {'(DRY RUN)' if DRY else ''}")
print(f"  Root: {ROOT}")
print("=" * 60)

print("\n[1] Create directories")
mkdir(TESTS_DIR)
mkdir(SCRIPTS_DIR)

print("\n[2] Delete debug/temp files")
for f in DELETE_FILES:
    delete(f)

print("\n[3] Move test files → tests/")
mkdir(TESTS_DIR)
for f in MOVE_TO_TESTS:
    move(f, TESTS_DIR)

# Add __init__.py to tests/
init_test = TESTS_DIR / "__init__.py"
if not init_test.exists():
    log("CREATE", init_test)
    if not DRY:
        init_test.write_text("# tests package\n", encoding="utf-8")

# Add conftest.py for sys.path
conftest = TESTS_DIR / "conftest.py"
if not conftest.exists():
    log("CREATE", conftest)
    if not DRY:
        conftest.write_text(
            'import sys, os\n'
            'sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))\n'
            'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))\n',
            encoding="utf-8"
        )

print("\n[4] Move utility scripts → scripts/")
mkdir(SCRIPTS_DIR)
for f in MOVE_TO_SCRIPTS:
    move(f, SCRIPTS_DIR)

# Add README to scripts/
readme = SCRIPTS_DIR / "README.md"
if not readme.exists():
    log("CREATE", readme)
    if not DRY:
        readme.write_text(
            "# Scripts\n\nUtility scripts — chạy thủ công, không phải server code.\n\n"
            "- `add_product.py` — Thêm part mới vào data JSON\n"
            "- `apply_catalog_aliases.py` — Batch update P/D aliases từ catalog PDF\n"
            "- `catalog_aliases.py` — Mapping data từ CATALOG_02.pdf\n"
            "- `query_engine.py` — CLI query tool\n"
            "- `show_fails.py` — Hiện failed eval cases\n"
            "- `check_system.py` — Audit file dependencies\n",
            encoding="utf-8"
        )

print("\n[5] Delete unused core files")
for f in DELETE_CORE:
    delete(f)

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if DRY:
    print("  DRY RUN complete — không có gì bị thay đổi")
    print("  Chạy lại KHÔNG có --dry-run để apply:")
    print("  python cleanup_project.py")
else:
    print("  ✅ Cleanup complete!")
    print("\n  Cấu trúc sau cleanup:")
    print("  botautoss/")
    print("  ├── main.py")
    print("  ├── vision_endpoint.py")
    print("  ├── eval_500.py / eval_700.py")
    print("  ├── core/          ← chỉ files đang dùng")
    print("  ├── tests/         ← tất cả test_*.py + conftest.py")
    print("  ├── scripts/       ← utility scripts + README.md")
    print("  └── data/")
print("=" * 60)
