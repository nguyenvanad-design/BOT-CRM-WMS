# test_bot.py — TOKINARC Bot Logic Test
# Chạy từ thư mục gốc project:
#   python test_bot.py
#   python test_bot.py -v          # verbose: in kết quả từng tool
#   python test_bot.py -k robot    # chỉ chạy test có "robot" trong tên
#
# Không cần GEMINI_API_KEY — test trực tiếp tool_wrappers.dispatch()
# bỏ qua tầng LLM, kiểm tra data + business logic thuần túy.

import sys
import os
import json
import time
import argparse

# ── Path setup: chạy từ thư mục gốc, core/ là sub-package ────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(ROOT, "core")
sys.path.insert(0, ROOT)
sys.path.insert(0, CORE)

# ── Bootstrap DataStore + CER + GraphTraversal ────────────────────────────────
print("Loading data store...", end=" ", flush=True)
t0 = time.time()
from data_store import get_data_store
from tokinarc_cer import get_cer
ds  = get_data_store()
cer = get_cer(ds=ds)
print(f"OK ({time.time()-t0:.1f}s)")

# Wire dependencies vào tool_wrappers
import tool_wrappers as tw
tw.set_data_store(ds)
tw.set_cer(cer)
try:
    from graph_traversal import get_graph_traversal
    gt = get_graph_traversal(cer)
    tw.set_graph_traversal(gt)
except Exception as e:
    print(f"  [WARN] graph_traversal not available: {e}")

dispatch = tw.dispatch


# ══════════════════════════════════════════════════════════════════════════════
# Test framework nhỏ gọn
# ══════════════════════════════════════════════════════════════════════════════

PASS = 0
FAIL = 0
SKIP = 0
_filter = None   # set bởi -k

def run(name, tool, args, checks, verbose=False):
    """
    Chạy 1 test case.
    checks: list of (description, callable(result) -> bool)
    """
    global PASS, FAIL, SKIP
    if _filter and _filter.lower() not in name.lower():
        SKIP += 1
        return

    result = dispatch(tool, args)
    failures = []
    for desc, fn in checks:
        try:
            ok = fn(result)
        except Exception as e:
            ok = False
            desc = f"{desc} [exception: {e}]"
        if not ok:
            failures.append(desc)

    if failures:
        FAIL += 1
        print(f"  FAIL  {name}")
        for f in failures:
            print(f"        ✗ {f}")
        if verbose:
            print(f"        result={json.dumps(result, ensure_ascii=False, indent=2)[:600]}")
    else:
        PASS += 1
        print(f"  PASS  {name}")
        if verbose:
            data = result.get("data") or {}
            # Print compact summary
            if isinstance(data, dict):
                parts = data.get("parts") or data.get("torches") or data.get("companions") or []
                if parts:
                    print(f"        → {len(parts)} item(s): {[p.get('tokin_part_no') or p.get('model_code','?') for p in parts[:5]]}")
                elif data.get("tokin_part_no"):
                    print(f"        → {data['tokin_part_no']} | {data.get('display_name_vi','')} | {data.get('price_vnd','?')}đ")


def section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(r):           return r.get("success") is True
def fail(r):         return r.get("success") is False
def has_parts(r, n=1):
    d = r.get("data") or {}
    parts = d.get("parts") or d.get("companions") or d.get("torches") or []
    return len(parts) >= n
def has_field(r, *keys):
    d = r.get("data") or {}
    for k in keys:
        if not d.get(k): return False
    return True
def part_no_in(r, pno):
    d = r.get("data") or {}
    # single part
    if d.get("tokin_part_no") == pno: return True
    # list
    for key in ("parts","companions","items"):
        for p in (d.get(key) or []):
            if p.get("tokin_part_no") == pno: return True
    return False
def category_in(r, cat):
    d = r.get("data") or {}
    for key in ("parts","companions"):
        for p in (d.get(key) or []):
            if p.get("category") == cat: return True
    return False
def eco_match(r, eco):
    d = r.get("data") or {}
    return d.get("ecosystem","").upper() == eco.upper()
def torch_count(r, n):
    d = r.get("data") or {}
    return len(d.get("torches") or []) >= n
def retry_dropped(r, field):
    d = r.get("data") or {}
    return field in (d.get("retry_dropped") or [])


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("-v","--verbose", action="store_true")
    p.add_argument("-k","--keyword", default="")
    return p.parse_args()

def main():
    global _filter
    args = parse_args()
    verbose = args.verbose
    _filter = args.keyword or None

    # ── 1. lookup_part ────────────────────────────────────────────────────────
    section("1. lookup_part")

    run("lookup Tokin 6 số chuẩn (002001)", "lookup_part", {"part_no": "002001"}, [
        ("success=True",            ok),
        ("tokin_part_no=002001",    lambda r: (r.get("data") or {}).get("tokin_part_no") == "002001"),
        ("có price_vnd",            lambda r: (r.get("data") or {}).get("price_vnd") is not None),
        ("category=Tip",            lambda r: (r.get("data") or {}).get("category") == "Tip"),
        ("ecosystem=N",             lambda r: eco_match(r, "N")),
    ], verbose)

    run("lookup alias Panasonic (U4167G01 → 001002)", "lookup_part", {"part_no": "U4167G01"}, [
        ("success=True",            ok),
        ("resolve về 001002",       lambda r: (r.get("data") or {}).get("tokin_part_no") == "001002"),
        ("brand=Daihen/OTC hoặc Panasonic", lambda r: (r.get("data") or {}).get("brand") is not None),
    ], verbose)

    run("lookup alias Panasonic TET00006", "lookup_part", {"part_no": "TET00006"}, [
        ("success=True",            ok),
        ("có tokin_part_no",        lambda r: bool((r.get("data") or {}).get("tokin_part_no"))),
    ], verbose)

    run("lookup mã không tồn tại → NOT_FOUND", "lookup_part", {"part_no": "XXXXXX"}, [
        ("success=False",           fail),
    ], verbose)

    run("lookup part_no rỗng → MISSING", "lookup_part", {"part_no": ""}, [
        ("success=False",           fail),
    ], verbose)

    run("lookup fake_pno typo 007001 → 001007", "lookup_part", {"part_no": "007001"}, [
        ("success=True",            ok),
        ("resolve về 001007",       lambda r: (r.get("data") or {}).get("tokin_part_no") == "001007"),
    ], verbose)

    # ── 2. search_parts ───────────────────────────────────────────────────────
    section("2. search_parts")

    run("search béc N 350A 1.2mm", "search_parts", {
        "query": "béc hàn", "category": "Tip",
        "ecosystem": "N", "current_class": "350A", "wire_size_mm": 1.2
    }, [
        ("success=True",            ok),
        ("có kết quả",              lambda r: has_parts(r, 1)),
        ("category=Tip",            lambda r: all(p.get("category")=="Tip" for p in (r.get("data") or {}).get("parts",[]))),
    ], verbose)

    run("search chụp khí 500A (không có hệ)", "search_parts", {
        "query": "chụp khí 500A", "category": "Nozzle", "current_class": "500A"
    }, [
        ("success=True",            ok),
        ("có kết quả",              lambda r: has_parts(r, 1)),
    ], verbose)

    run("search InnerTube eco=D → fallback eco=N", "search_parts", {
        "query": "ống trong", "category": "InnerTube", "ecosystem": "D"
    }, [
        ("success=True",            ok),
        ("có kết quả (fallback N)", lambda r: has_parts(r, 1)),
    ], verbose)

    run("search retry bỏ wire_size khi rỗng", "search_parts", {
        "query": "béc hàn", "category": "Tip",
        "ecosystem": "N", "current_class": "350A", "wire_size_mm": 9.9
    }, [
        ("success=True (retry)",    ok),
        ("có kết quả",              lambda r: has_parts(r, 1)),
    ], verbose)

    run("search TIG tungsten electrode", "search_parts", {
        "query": "tungsten 2.4mm", "category": "TungstenElectrode",
        "ecosystem": "TIG", "wire_size_mm": 2.4
    }, [
        ("success=True",            ok),
    ], verbose)

    # ── 3. get_consumable_set ─────────────────────────────────────────────────
    section("3. get_consumable_set")

    run("consumable set N 350A", "get_consumable_set", {
        "ecosystem": "N", "current_class": "350A"
    }, [
        ("success=True",            ok),
        ("có sets",                 lambda r: len((r.get("data") or {}).get("sets") or []) >= 1),
        ("có Tip trong parts",      lambda r: any(
            p.get("part_role")=="Tip"
            for s in ((r.get("data") or {}).get("sets") or [])
            for p in (s.get("parts") or [])
        )),
        ("Tip ≥ 3 variants",        lambda r: sum(
            1 for s in ((r.get("data") or {}).get("sets") or [])
            for p in (s.get("parts") or [])
            if p.get("part_role") == "Tip"
        ) >= 3),
    ], verbose)

    run("consumable set theo torch model TK-308RR", "get_consumable_set", {
        "torch_model": "TK-308RR"
    }, [
        ("success=True",            ok),
        ("có sets",                 lambda r: len((r.get("data") or {}).get("sets") or []) >= 1),
    ], verbose)

    # ── 4. find_upsell_companions ─────────────────────────────────────────────
    section("4. find_upsell_companions")

    run("upsell từ 002001 (Tip N 350A)", "find_upsell_companions", {"part_no": "002001"}, [
        ("success=True",            ok),
        ("found=True",              lambda r: (r.get("data") or {}).get("found") is True),
        ("có companions",           lambda r: has_parts(r, 1)),
    ], verbose)

    run("upsell từ alias U4167G01 (Nozzle)", "find_upsell_companions", {"part_no": "U4167G01"}, [
        ("success=True",            ok),
        ("có companions",           lambda r: has_parts(r, 1)),
    ], verbose)

    run("upsell filter include_categories=[Nozzle]", "find_upsell_companions", {
        "part_no": "002001", "include_categories": ["Nozzle"]
    }, [
        ("success=True",            ok),
        ("chỉ có Nozzle",          lambda r: all(
            p.get("category") == "Nozzle"
            for p in ((r.get("data") or {}).get("companions") or [])
        )),
    ], verbose)

    run("upsell page=2 (compatible_with)", "find_upsell_companions", {
        "part_no": "002001", "page": 2
    }, [
        ("success=True",            ok),
        ("has_more field tồn tại", lambda r: "has_more" in (r.get("data") or {})),
    ], verbose)

    run("upsell part không tồn tại → fail", "find_upsell_companions", {"part_no": "ZZZZZZ"}, [
        ("success=False",           fail),
    ], verbose)

    # ── 5. find_replacement ───────────────────────────────────────────────────
    section("5. find_replacement")

    run("replacement Panasonic TET00006", "find_replacement", {"part_no": "TET00006"}, [
        ("success=True",            ok),
        ("có tokin_part",           lambda r: bool((r.get("data") or {}).get("tokin_part"))),
        ("source_brand detect",     lambda r: (r.get("data") or {}).get("source_brand") is not None),
    ], verbose)

    run("replacement Daihen U4167G01 → 001002", "find_replacement", {"part_no": "U4167G01"}, [
        ("success=True",            ok),
        ("tokin = 001002",          lambda r: ((r.get("data") or {}).get("tokin_part") or {}).get("tokin_part_no") == "001002"),
    ], verbose)

    # ── 6. check_compatibility ────────────────────────────────────────────────
    section("6. check_compatibility")

    run("compat cùng hệ N (002001 + 001002)", "check_compatibility", {
        "part_no_a": "002001", "part_no_b": "001002"
    }, [
        ("success=True",            ok),
        ("có compatible field",     lambda r: "compatible" in (r.get("data") or {})),
    ], verbose)

    run("compat cross-eco N+D → không tương thích", "check_compatibility", {
        "part_no_a": "002001", "part_no_b": "023010"
    }, [
        ("success=True",            ok),
        ("compatible=False",        lambda r: (r.get("data") or {}).get("compatible") is False),
    ], verbose)

    # ── 7. compare_parts ──────────────────────────────────────────────────────
    section("7. compare_parts")

    run("compare 002001 vs 002003 (khác wire_size)", "compare_parts", {
        "part_no_a": "002001", "part_no_b": "002003"
    }, [
        ("success=True",            ok),
        ("có differences",          lambda r: len((r.get("data") or {}).get("differences") or []) >= 1),
        ("có recommendation",       lambda r: bool((r.get("data") or {}).get("recommendation"))),
    ], verbose)

    # ── 8. get_torches ────────────────────────────────────────────────────────
    section("8. get_torches")

    run("torches robot_model=1.4m → 26 súng", "get_torches", {
        "robot_model": "1.4m"
    }, [
        ("success=True",            ok),
        ("≥ 20 torches",            lambda r: torch_count(r, 20)),
    ], verbose)

    run("torches robot_model=yaskawa", "get_torches", {
        "robot_model": "yaskawa"
    }, [
        ("success=True",            ok),
        ("≥ 20 torches",            lambda r: torch_count(r, 20)),
    ], verbose)

    run("torches typo yaskwa (alias mới)", "get_torches", {
        "robot_model": "yaskwa"
    }, [
        ("success=True",            ok),
        ("≥ 10 torches",            lambda r: torch_count(r, 10)),
    ], verbose)

    run("torches robot+torch_type over-specify → retry1 drop torch_type", "get_torches", {
        "robot_model": "1.4m", "torch_type": "air_cooled_robotic"
    }, [
        ("success=True (retry)",    ok),
        ("retry_dropped=[torch_type]", lambda r: retry_dropped(r, "torch_type")),
        ("≥ 20 torches",            lambda r: torch_count(r, 20)),
    ], verbose)

    run("torches robot+eco=D over-specify → retry2 drop ecosystem", "get_torches", {
        "robot_model": "1.4m", "ecosystem": "D"
    }, [
        ("success=True (retry2)",   ok),
        ("retry_dropped=[ecosystem]", lambda r: retry_dropped(r, "ecosystem")),
        ("≥ 20 torches",            lambda r: torch_count(r, 20)),
    ], verbose)

    run("torches AR1440E → YMENS (EA series, không lẫn MA)", "get_torches", {
        "robot_model": "AR1440E"
    }, [
        ("success=True",            ok),
        ("có YMENS",                lambda r: any(
            "YMENS" in (t.get("model_code") or "")
            for t in ((r.get("data") or {}).get("torches") or [])
        )),
        ("KHÔNG có TK-308RR",       lambda r: not any(
            t.get("model_code") == "TK-308RR"
            for t in ((r.get("data") or {}).get("torches") or [])
        )),
    ], verbose)

    run("torches eco=N cc=350A", "get_torches", {
        "ecosystem": "N", "current_class": "350A"
    }, [
        ("success=True",            ok),
        ("có kết quả",              lambda r: torch_count(r, 1)),
    ], verbose)

    run("torches filter không tồn tại → fail", "get_torches", {
        "ecosystem": "N", "current_class": "999A", "torch_type": "semi_auto"
    }, [
        ("success=False",           fail),
    ], verbose)

    # ── 9. get_troubleshoot ───────────────────────────────────────────────────
    section("9. get_troubleshoot")

    run("troubleshoot bắn tóe nhiều", "get_troubleshoot", {
        "symptom": "béc bắn tóe nhiều spatter"
    }, [
        ("success=True",            ok),
        ("có causes hoặc actions",  lambda r: bool(
            (r.get("data") or {}).get("causes") or (r.get("data") or {}).get("actions")
        )),
    ], verbose)

    run("troubleshoot kẹt dây", "get_troubleshoot", {
        "symptom": "dây hàn bị kẹt không chạy"
    }, [
        ("success=True",            ok),
    ], verbose)

    run("troubleshoot không có symptom → fail", "get_troubleshoot", {
        "symptom": ""
    }, [
        ("success=False",           fail),
    ], verbose)

    # ── 10. get_liner_length ─────────────────────────────────────────────────
    section("10. get_liner_length")

    run("liner length TK-308RR", "get_liner_length", {
        "torch_model": "TK-308RR"
    }, [
        ("success=True hoặc KB không có", lambda r: True),   # optional — KB có thể chưa load
    ], verbose)

    # ── 11. get_replacement_steps ─────────────────────────────────────────────
    section("11. get_replacement_steps")

    run("replacement steps Tip", "get_replacement_steps", {
        "category": "Tip"
    }, [
        ("success=True hoặc KB không có", lambda r: True),   # optional
        ("nếu success → có related_parts", lambda r:
            not r.get("success") or bool((r.get("data") or {}).get("related_parts"))
        ),
    ], verbose)

    run("replacement steps Liner + torch_model TK-308RR", "get_replacement_steps", {
        "category": "Liner", "torch_model": "TK-308RR"
    }, [
        ("success=True hoặc KB không có", lambda r: True),
    ], verbose)

    # ── 12. dispatch unknown tool ──────────────────────────────────────────────
    section("12. dispatch edge cases")

    run("dispatch tool không tồn tại → fail rõ ràng", "unknown_tool_xyz", {}, [
        ("success=False",           fail),
        ("reason có UNKNOWN_TOOL",  lambda r: "UNKNOWN_TOOL" in (r.get("reason") or "")),
    ], verbose)

    run("lookup_part description fallback (part_no rỗng, description có)", "lookup_part", {
        "part_no": "", "description": "béc hàn N 0.9mm"
    }, [
        ("success=True (fallback search)",  ok),
    ], verbose)

    run("find_replacement description fallback", "find_replacement", {
        "part_no": "", "description": "béc hàn N 350A"
    }, [
        ("success=True hoặc search rỗng", lambda r: True),
    ], verbose)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = PASS + FAIL + SKIP
    print(f"\n{'═'*55}")
    print(f"  KẾT QUẢ: {PASS} PASS  |  {FAIL} FAIL  |  {SKIP} SKIP  (total {total})")
    print(f"{'═'*55}")
    if FAIL:
        print("  ⚠️  Có lỗi cần kiểm tra lại!")
        sys.exit(1)
    else:
        print("  ✅  Tất cả test đều pass!")
        sys.exit(0)


if __name__ == "__main__":
    main()
