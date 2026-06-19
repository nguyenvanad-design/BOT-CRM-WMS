"""
check_system.py — Kiểm tra toàn bộ file hệ thống TOKINARC
Run từ root repo: python check_system.py
"""
import os, sys, ast, importlib.util
from pathlib import Path
from collections import defaultdict

ROOT = Path(".")
CORE = ROOT / "core"

# ── 1. Liệt kê tất cả .py files ──────────────────────────────────────────────
def find_py_files(base: Path) -> list:
    files = []
    for p in sorted(base.rglob("*.py")):
        if any(x in str(p) for x in ["__pycache__", ".venv", "venv", "node_modules"]):
            continue
        files.append(p)
    return files

root_files = [f for f in ROOT.glob("*.py") if f.name != "check_system.py"]
core_files = list(CORE.glob("*.py")) if CORE.exists() else []
test_files = list((ROOT / "tests").glob("*.py")) if (ROOT / "tests").exists() else []
data_files = list(ROOT.glob("data/*.py")) if ROOT.exists() else []

all_py = root_files + core_files + test_files + data_files

# ── 2. Parse imports từ mỗi file ─────────────────────────────────────────────
def get_imports(filepath: Path) -> set:
    imports = set()
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split(".")[0]
                    imports.add(base)
                    # core.xxx → xxx
                    if node.module.startswith("core."):
                        imports.add(node.module[5:].split(".")[0])
    except Exception:
        pass
    return imports

# Module name của mỗi file
def mod_name(p: Path) -> str:
    name = p.stem
    return name

file_imports = {}
for f in all_py:
    file_imports[f] = get_imports(f)

# ── 3. Build dependency graph ──────────────────────────────────────────────────
local_modules = {mod_name(f): f for f in all_py}
imported_by = defaultdict(set)  # module → set of files that import it

for f, imps in file_imports.items():
    for imp in imps:
        if imp in local_modules:
            imported_by[imp].add(f)

# ── 4. Report ─────────────────────────────────────────────────────────────────
print("=" * 65)
print("  TOKINARC SYSTEM FILE AUDIT")
print("=" * 65)

USED_BY_MAIN = set()

def check_file(f: Path, indent=""):
    mod = mod_name(f)
    imps = file_imports.get(f, set())
    local_deps = [i for i in imps if i in local_modules and i != mod]
    users = imported_by.get(mod, set())
    return local_deps, users

# ── Core files ────────────────────────────────────────────────────────────────
KNOWN_ENTRY = {"main", "uvicorn"}

print("\n📁 ROOT/")
for f in sorted(root_files, key=lambda x: x.name):
    users = imported_by.get(mod_name(f), set())
    status = "✅ ENTRY" if f.name == "main.py" else (
             "✅ USED" if users else "⚠️  UNUSED")
    print(f"  {status:<12} {f.name}")

print("\n📁 core/")
CORE_CRITICAL = {
    "data_store", "pipeline_v7", "llm_extractor", "llm_orchestrator_v2",
    "tool_wrappers", "retrieval_orchestrator", "bm25_reranker",
    "session_store", "system_prompts", "gemini_resilience",
    "graph_traversal", "vector_index", "vision_module",
    "ds_result_adapter", "fuzzy_corrector", "llm_explanation",
    "tokinarc_cer", "query_logger", "bm25_search",
}
if CORE.exists():
    for f in sorted(core_files, key=lambda x: x.name):
        mod = mod_name(f)
        users = imported_by.get(mod, set())
        n_users = len(users)
        if f.name.startswith("__"):
            continue
        if mod in CORE_CRITICAL:
            status = f"✅ CORE({n_users})"
        elif n_users > 0:
            status = f"✅ USED({n_users})"
        else:
            status = "⚠️  UNUSED"
        print(f"  {status:<14} {f.name}")

print("\n📁 tests/")
for f in sorted(test_files, key=lambda x: x.name):
    print(f"  🧪 TEST       {f.name}")

# ── 5. Dependency check cho main.py ──────────────────────────────────────────
print("\n" + "=" * 65)
print("  MAIN.PY IMPORTS (direct)")
print("=" * 65)
main_f = ROOT / "main.py"
if main_f.exists():
    main_imps = get_imports(main_f)
    for imp in sorted(main_imps):
        if imp in local_modules:
            print(f"  → {imp}")

# ── 6. Missing files ──────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  MISSING FILES (imported but not found)")
print("=" * 65)
all_imported = set()
for imps in file_imports.values():
    all_imported.update(imps)

STDLIB = {"os","sys","re","json","time","logging","pathlib","typing","dataclasses",
          "threading","collections","functools","itertools","math","random","copy",
          "datetime","traceback","importlib","abc","io","hashlib","base64","urllib",
          "asyncio","contextlib","warnings","unicodedata","difflib","enum","uuid"}
THIRD_PARTY = {"fastapi","uvicorn","pydantic","starlette","google","rank_bm25",
               "sentence_transformers","faiss","numpy","torch","transformers",
               "httpx","aiofiles","PIL","cv2"}

missing = []
for imp in sorted(all_imported):
    if imp in local_modules: continue
    if imp in STDLIB: continue
    if imp in THIRD_PARTY: continue
    if imp.startswith("_"): continue
    missing.append(imp)

if missing:
    for m in missing:
        print(f"  ❓ {m}")
else:
    print("  ✅ Không có file nào bị thiếu")

print("\n" + "=" * 65)
UNUSED = [f for f in core_files
          if not f.name.startswith("__")
          and mod_name(f) not in CORE_CRITICAL
          and not imported_by.get(mod_name(f))]
print(f"  UNUSED files: {len(UNUSED)}")
for f in UNUSED:
    print(f"  ⚠️  {f}")
print("=" * 65)
