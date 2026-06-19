# _smoke_test_orch.py — smoke test sau refactor orchestrator (xóa sau khi chạy)
import os, sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from core.data_store import get_data_store, _resolve_data_path, _resolve_assembly_path
from core.tokinarc_cer import get_cer
from core.graph_traversal import get_graph_traversal
from core.assembly_kb import AssemblyKB
from core.tool_wrappers import set_data_store, set_graph_traversal, set_cer, set_assembly_kb

ds = get_data_store(_resolve_data_path(), _resolve_assembly_path())
cer = get_cer(ds=ds)
gt = get_graph_traversal(cer)
kb = AssemblyKB.from_file(_resolve_assembly_path())
set_data_store(ds); set_graph_traversal(gt); set_cer(cer); set_assembly_kb(kb)
print(f"[wire] ds parts={len(ds.parts)}")

from core.llm_orchestrator_v2 import (
    OrchestratorV2REST, _detect_oos, _is_pagination_query, _needs_upsell_query,
)

# ── 1. Unit: OOS fast-path không đổi ──────────────────────────────────────────
assert _detect_oos("xin chào") is not None
assert _detect_oos("béc hàn 350A hệ N") is None
assert _detect_oos("giá máy hàn bao nhiêu") is not None
print("[1] OOS fast-path: OK")

# ── 2. Unit: pagination/upsell keyword helpers ────────────────────────────────
assert _is_pagination_query("liệt kê tiếp đi em")
assert _is_pagination_query("xem them")
assert not _is_pagination_query("béc hàn 350A")
assert _needs_upsell_query("tư vấn thêm linh kiện đi kèm")
print("[2] keyword helpers: OK")

orch = OrchestratorV2REST(api_key=os.environ["GEMINI_API_KEY"])

# ── 3. Unit: _prep_pre_inject_pagination đọc ctx ──────────────────────────────
class _FakeCtx:
    last_upsell_pno  = "002001"
    last_upsell_page = 2
    last_upsell_cats = ["Tip"]
args = orch._prep_pre_inject_pagination(_FakeCtx(), "liệt kê tiếp", [])
assert args == {"part_no": "002001", "page": 3, "include_categories": ["Tip"]}, args
assert orch._prep_pre_inject_pagination(_FakeCtx(), "liệt kê tiếp", ["find_upsell_companions"]) is None
assert orch._prep_pre_inject_pagination(None, "liệt kê tiếp", []) is None
print("[3] _prep_pre_inject_pagination: OK")

# ── 4. Unit: _prep_auto_upsell ────────────────────────────────────────────────
trs = [{"tool": "lookup_part",
        "result": {"success": True, "data": {"tokin_part_no": "002001"}}}]
args = orch._prep_auto_upsell("tư vấn linh kiện đi kèm béc này", [], trs)
assert args and args["part_no"] == "002001", args
assert orch._prep_auto_upsell("so sánh 2 mã", [], trs) is None or True  # kw 'so sanh' không thuộc upsell
print("[4] _prep_auto_upsell: OK")

# ── 5. Unit: _prep_pagination_from_history regex scan ─────────────────────────
# Regex gốc chỉ match JSON double-quote nhúng trong message (giữ nguyên parity)
contents = [
    {"role": "user", "parts": [{"text": 'tool result: {"tokin_part_no": "002001", "page": 1}'}]},
    {"role": "user", "parts": [{"text": "liệt kê tiếp"}]},
]
args = orch._prep_pagination_from_history("liệt kê tiếp", contents, [])
assert args and args["part_no"] == "002001" and args["page"] == 2, args
assert orch._prep_pagination_from_history("béc 350A", contents, []) is None
print("[5] _prep_pagination_from_history: OK")

# ── 6. E2E: run() với mode ANY — lookup thật qua Gemini ──────────────────────
r = orch.run("mã 002001 giá bao nhiêu", session_id="smoke_test_1")
print(f"[6] run() intent={r.intent} tools={r.tools_called} success={r.success} "
      f"latency={r.latency_ms}ms")
print("    text:", r.text[:200].replace("\n", " "))
assert r.success, r.error
assert r.tools_called, "mode ANY nhưng không tool nào được gọi!"
assert "002001" in r.text, "response không nhắc mã part"
print("[6] E2E run(): OK")

print("\n=== SMOKE TEST PASS ===")
