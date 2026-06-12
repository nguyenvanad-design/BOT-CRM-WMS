"""
TOKINARC — Verify Restructure Fixes
=====================================
Chạy từ repo root:
    python verify_fixes.py

Không cần install thêm gì — chỉ dùng stdlib.
"""

import pathlib
import py_compile
import sys
import urllib.error

ROOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

PASS = "✅"
FAIL = "❌"
results = []

def check(ok: bool, desc: str):
    results.append(ok)
    print(f"  {PASS if ok else FAIL}  {desc}")

# ──────────────────────────────────────────────────────────────
print("=" * 60)
print("1. SYNTAX CHECK")
print("=" * 60)

FILES = [
    ROOT / "main.py",
    ROOT / "core" / "llm_orchestrator_v2.py",
    ROOT / "core" / "session_store.py",
    ROOT / "core" / "gemini_resilience.py",
    ROOT / "core" / "retrieval_eval.py",
]
for f in FILES:
    if not f.exists():
        check(False, f"{f.name} — FILE NOT FOUND")
        continue
    try:
        py_compile.compile(str(f), doraise=True)
        check(True, f"{f.name}")
    except py_compile.PyCompileError as e:
        check(False, f"{f.name}: {e}")

# ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("2. KEY FIXES PRESENT")
print("=" * 60)

def read(f): return pathlib.Path(f).read_text(encoding="utf-8", errors="replace")

MAIN   = ROOT / "main.py"
ORCH   = ROOT / "core" / "llm_orchestrator_v2.py"
SS     = ROOT / "core" / "session_store.py"
GR     = ROOT / "core" / "gemini_resilience.py"
EVAL   = ROOT / "core" / "retrieval_eval.py"

# main.py
m = read(MAIN)
check("C:\\Users\\ADMIN"        not in m, "main.py — hardcode Windows path ĐÃ XÓA")
check("_resolve_data_path"      in m,     "main.py — dùng data_store resolver")
check("TOKINARC_ENV"            in m,     "main.py — fail-fast production env")
check("secrets.compare_digest"  in m,     "main.py — constant-time key compare")
check("_key_ok"                 in m,     "main.py — helper _key_ok")
check("TOKINARC_CORS_ORIGINS"   in m,     "main.py — CORS configurable qua env")
check("TOKINARC_BLOCKED_SUBNETS" in m,    "main.py — IP blacklist ra env")
check("backend = "              in m,     "main.py — log SessionStore backend đúng")
check("in-memory, TTL=30min)"  not in m,  "main.py — bỏ hardcode 'in-memory' trong log")

# llm_orchestrator_v2.py
o = read(ORCH)
check("using key:"             not in o,  "llm_orchestrator_v2.py — log API key ĐÃ XÓA")
check("retry_http"              in o,     "llm_orchestrator_v2.py — wire retry vào _post")
check("REQUEST_BUDGET_S"        in o,     "llm_orchestrator_v2.py — deadline tổng request")
check("last_upsell_pno"         in o,     "llm_orchestrator_v2.py — field upsell chính thức")
check('__dict__["_last_upsell' not in o,  "llm_orchestrator_v2.py — hack __dict__ ĐÃ XÓA")

# session_store.py
s = read(SS)
check("last_upsell_pno"   in s,  "session_store.py — field last_upsell_pno")
check("last_upsell_page"  in s,  "session_store.py — field last_upsell_page")
check("last_upsell_cats"  in s,  "session_store.py — field last_upsell_cats")
check('"last_upsell_pno"' in s,  "session_store.py — serialize trong _to_json")
check("_mask_url"        in s,  "session_store.py — hàm _mask_url che password Redis")
check("***"             in s,  "session_store.py — mask dùng ***")

# gemini_resilience.py
g = read(GR)
check("def retry_http"          in g, "gemini_resilience.py — hàm retry_http")
check("urllib.error.HTTPError"  in g, "gemini_resilience.py — classify HTTP error")

# retrieval_eval.py
e = read(EVAL)
check("_resolve_data_path"    in e,  "retrieval_eval.py — dùng chung resolver với prod")
check("tokinarc_data_v14" not in e,  "retrieval_eval.py — hardcode v14 ĐÃ XÓA")

# ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("3. SMOKE TESTS")
print("=" * 60)

# Test A: upsell fields roundtrip Redis serialize/deserialize
try:
    from session_store import SessionContext, RedisSessionStore
    ctx = SessionContext(session_id="verify_test")
    ctx.last_upsell_pno  = "002001"
    ctx.last_upsell_page = 3
    ctx.last_upsell_cats = ["Tip", "Nozzle"]
    r    = RedisSessionStore.__new__(RedisSessionStore)
    raw  = RedisSessionStore._to_json(r, ctx)
    ctx2 = RedisSessionStore._from_json(r, raw)
    ok = (ctx2.last_upsell_pno == "002001"
          and ctx2.last_upsell_page == 3
          and ctx2.last_upsell_cats == ["Tip", "Nozzle"])
    check(ok, "session_store — upsell roundtrip serialize → deserialize")
except Exception as ex:
    check(False, f"session_store — upsell roundtrip: {ex}")

# Test B: retry_http retry on 503
try:
    import gemini_resilience as gr
    gr._RETRY_DELAYS = [0, 0]
    calls = {"n": 0}
    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", 503, "unavail", {}, None)
        return "ok"
    result = gr.retry_http(_flaky, "verify")
    check(result == "ok" and calls["n"] == 3,
          "gemini_resilience — retry_http: 2x retry 503 rồi thành công")
except Exception as ex:
    check(False, f"gemini_resilience — retry_http 503: {ex}")

# Test C: retry_http no retry on 400
try:
    def _bad():
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)
    try:
        gr.retry_http(_bad, "verify400")
        check(False, "gemini_resilience — retry_http 400: phải raise ngay")
    except urllib.error.HTTPError as ex:
        check(ex.code == 400,
              "gemini_resilience — retry_http 400: không retry, raise ngay")
except Exception as ex:
    check(False, f"gemini_resilience — retry_http 400: {ex}")

# Test E: Redis URL masking
try:
    from session_store import RedisSessionStore
    url    = "rediss://default:gQAAAAAAAiA1AAIg@cute-whippet-139317.upstash.io:6379"
    masked = RedisSessionStore._mask_url(url)
    ok     = "gQAAAA" not in masked and "***" in masked
    check(ok, f"session_store — _mask_url che password: {masked}")
except Exception as ex:
    check(False, f"session_store — _mask_url: {ex}")


try:
    import re
    m2 = re.search(r"REQUEST_BUDGET_S\s*=.*?(\d+)", read(ORCH))
    check(m2 and int(m2.group(1)) == 25,
          f"llm_orchestrator_v2.py — REQUEST_BUDGET_S default = {m2.group(1) if m2 else '?'}s")
except Exception as ex:
    check(False, f"REQUEST_BUDGET_S: {ex}")

# Test E: _key_ok dùng compare_digest (không phải ==)
try:
    src = read(MAIN)
    ok  = ("secrets.compare_digest" in src and "_key_ok" in src
           and "api_key != VALID_API_KEY" not in src)
    check(ok, "main.py — auth dùng compare_digest, bỏ != VALID_API_KEY")
except Exception as ex:
    check(False, f"main.py auth: {ex}")

# ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
total  = len(results)
passed = sum(results)
failed = total - passed
if failed == 0:
    print(f"KẾT QUẢ: {PASS} {passed}/{total} PASS — tất cả fix đã áp dụng đúng")
else:
    print(f"KẾT QUẢ: {FAIL} {passed}/{total} PASS — {failed} mục FAIL (xem chi tiết trên)")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
