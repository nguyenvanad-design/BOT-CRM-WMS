"""
test_session.py — Test multi-turn session context
==================================================
Kiểm tra bot có nhớ ngữ cảnh qua các turn không.

Usage:
  python test_session.py --url http://127.0.0.1:8000 --key dev-tokinarc-2026
"""

import argparse
import json
import time
import requests

URL      = "http://127.0.0.1:8000"
ENDPOINT = "/api/v5/query"
API_KEY  = "dev-tokinarc-2026"
SESSION  = f"test_session_{int(time.time())}"


def ask(query: str, url: str, key: str, session_id: str) -> dict:
    resp = requests.post(
        f"{url}{ENDPOINT}",
        json={"query": query, "session_id": session_id},
        headers={"X-API-Key": key},
        timeout=30,
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "text": ""}
    return resp.json()


def check(result: dict, expect_parts: list = None, expect_intent: str = None,
          expect_text_contains: list = None) -> tuple[bool, list]:
    """Trả về (passed, danh sách lỗi)."""
    fails = []

    if "error" in result:
        return False, [f"ERROR: {result['error']}"]

    # Intent
    if expect_intent and result.get("intent") != expect_intent:
        fails.append(f"intent={result.get('intent')} ≠ {expect_intent}")

    # Parts phải chứa mã
    if expect_parts:
        parts_raw = result.get("parts") or []
        if isinstance(parts_raw, dict):
            found_codes = set(parts_raw.keys())
        else:
            found_codes = {p.get("tokin_part_no", "") for p in parts_raw if isinstance(p, dict)}
        # Thêm codes trong text
        import re
        found_codes |= set(re.findall(r'\b\d{6}\b', result.get("text", "")))
        missing = [c for c in expect_parts if c not in found_codes]
        if missing:
            fails.append(f"thiếu mã: {missing}")

    # Text chứa từ khoá
    if expect_text_contains:
        text = (result.get("text") or "").lower()
        missing_kw = [kw for kw in expect_text_contains if kw.lower() not in text]
        if missing_kw:
            fails.append(f"text thiếu từ: {missing_kw}")

    return len(fails) == 0, fails


def print_turn(n: int, query: str, result: dict, passed: bool, fails: list):
    icon  = "✅" if passed else "❌"
    intent = result.get("intent", "?")
    band   = result.get("confidence_band", "?")
    parts_raw = result.get("parts") or []
    if isinstance(parts_raw, dict):
        parts_codes = list(parts_raw.keys())[:4]
    else:
        parts_codes = [p.get("tokin_part_no", "") for p in parts_raw[:4] if isinstance(p, dict)]
    text_preview = (result.get("text") or "")[:120].replace("\n", " ")

    print(f"\n  {icon} Turn {n}: {query!r}")
    print(f"     intent={intent} [{band}]  parts={parts_codes}")
    print(f"     text: {text_preview}...")
    if not passed:
        for f in fails:
            print(f"     ⚠️  {f}")


def run_scenario(name: str, turns: list, url: str, key: str):
    """
    turns = list of:
      (query, expect_parts, expect_intent, expect_text_contains)
      expect_parts/intent/text_contains có thể là None nếu không cần check
    """
    sid = f"test_{name}_{int(time.time())}"
    print(f"\n{'='*60}")
    print(f"  SCENARIO: {name}")
    print(f"  session_id: {sid}")
    print(f"{'='*60}")

    total = 0
    passed_count = 0

    for i, (query, exp_parts, exp_intent, exp_text) in enumerate(turns, 1):
        result = ask(query, url, key, sid)
        passed, fails = check(result,
                               expect_parts=exp_parts,
                               expect_intent=exp_intent,
                               expect_text_contains=exp_text)
        print_turn(i, query, result, passed, fails)
        total += 1
        if passed:
            passed_count += 1
        time.sleep(0.3)  # tránh rate limit

    print(f"\n  Kết quả: {passed_count}/{total} turn passed")
    return passed_count, total


def main(url: str, key: str):
    grand_total = 0
    grand_passed = 0

    # ══════════════════════════════════════════════════════════════════
    # Scenario 1: Cơ bản — hỏi béc rồi hỏi đồ đi kèm
    # ══════════════════════════════════════════════════════════════════
    p, t = run_scenario("S1_basic_followup", [
        ("béc hàn hệ N 350A 1.2mm",
         ["002003"], None, None),  # SEARCH_BY_DESC hoặc LOOKUP đều OK

        ("chụp khí đi kèm",
         ["001001", "001002", "001003"], None, ["chụp"]),

        ("giá bao nhiêu",
         None, "LOOKUP", ["đ"]),

        ("mua thêm 50 cái",
         None, None, None),  # inject parts → UPSELL hoặc LOOKUP

        ("cho tôi thêm cách điện nha",
         None, None, ["cách điện"]),

        ("đặt hàng",
         None, None, None),
    ], url, key)
    grand_passed += p; grand_total += t

    # ══════════════════════════════════════════════════════════════════
    # Scenario 2: Eco persistence — nói hệ N một lần, các turn sau nhớ
    # ══════════════════════════════════════════════════════════════════
    p, t = run_scenario("S2_eco_persistence", [
        ("vật tư tiêu hao súng hàn hệ N 350A",
         None, "CONSUMABLE_SET", ["350"]),  # text dùng "N 350A" không phải "hệ n"

        ("béc 1.2mm",           # không nói hệ → phải inject N
         None, None, ["002003", "hệ n", "n"]),

        ("còn loại nào khác không",
         None, None, None),

        ("thêm chụp khí đi",
         None, None, ["chụp"]),
    ], url, key)
    grand_passed += p; grand_total += t

    # ══════════════════════════════════════════════════════════════════
    # Scenario 3: UPSELL filter_category persistence
    # ══════════════════════════════════════════════════════════════════
    p, t = run_scenario("S3_upsell_filter", [
        ("vừa mua béc hàn 002001, cần thêm chụp khí",
         ["001001", "001002", "001003"], "UPSELL", ["chụp"]),

        ("còn loại nào khác không",  # filter Nozzle phải giữ
         None, None, ["chụp", "001"]),  # text dùng "Chụp khí" không phải "nozzle"

        ("giá cái 001002 bao nhiêu",
         None, "LOOKUP", ["đ"]),
    ], url, key)
    grand_passed += p; grand_total += t

    # ══════════════════════════════════════════════════════════════════
    # Scenario 4: Price follow-up ngắn
    # ══════════════════════════════════════════════════════════════════
    p, t = run_scenario("S4_price_followup", [
        ("033203 là gì",
         ["033203"], "LOOKUP", None),

        ("giá bao nhiêu",          # inject 033203 từ session
         None, "LOOKUP", ["đ"]),

        ("bao nhiêu tiền",         # lần nữa
         None, "LOOKUP", ["đ"]),

        ("còn hàng không",
         None, None, None),
    ], url, key)
    grand_passed += p; grand_total += t

    # ══════════════════════════════════════════════════════════════════
    # Scenario 5: Torch → consumable set
    # ══════════════════════════════════════════════════════════════════
    p, t = run_scenario("S5_torch_context", [
        ("súng TK-308RR thông số",
         None, "LOOKUP", ["350"]),  # model_code uppercase trong text

        ("vật tư tiêu hao đi với nó",   # "nó" → pronoun → inject torch
         None, None, None),  # CONSUMABLE_SET hoặc UPSELL đều OK, parts đúng

        ("béc 1.2mm loại nào",
         None, None, None),
    ], url, key)
    grand_passed += p; grand_total += t

    # ══════════════════════════════════════════════════════════════════
    # TỔNG KẾT
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    pct = grand_passed / grand_total * 100 if grand_total else 0
    print(f"  TỔNG: {grand_passed}/{grand_total} ({pct:.0f}%)")
    print(f"{'='*60}")

    if grand_passed == grand_total:
        print("  ✅ Tất cả turn passed — session memory hoạt động tốt!")
    else:
        failed = grand_total - grand_passed
        print(f"  ⚠️  {failed} turn cần xem lại")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", default="dev-tokinarc-2026")
    args = ap.parse_args()
    main(args.url, args.key)
