"""
eval_llm.py — TOKINARC LLM End-to-End Eval
===========================================
Gọi /api/v2/query với từng case trong eval_700.json,
extract part_nos từ tool_results, so sánh với expected_part_nos.

Usage:
  python eval_llm.py --url http://127.0.0.1:8000 --key dev-tokinarc-2026
  python eval_llm.py --workers 3 --limit 50   # chạy thử 50 case
  python eval_llm.py --intent UPSELL           # chỉ chạy 1 intent
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

_REPO = Path(__file__).parent
_EVAL_PATH = _REPO / "eval_700.json"
_OUT_PATH  = _REPO / "logs" / "eval_llm_report.csv"

SKIP_INTENTS = {"REPAIR", "INSTALLATION", "AGGREGATE"}  # trả text, không có part_nos

def call_api(query: str, session_id: str, url: str, key: str, timeout: int = 30) -> dict:
    payload = json.dumps({"query": query, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"{url}/api/v2/query",
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def extract_part_nos(response: dict) -> list[str]:
    """Extract tất cả tokin_part_no từ tool_results."""
    found = []
    for tr in response.get("tool_results", []):
        data = (tr.get("result") or {}).get("data") or {}
        # Single part (lookup_part)
        if "tokin_part_no" in data and data["tokin_part_no"]:
            found.append(str(data["tokin_part_no"]))
        # List of parts (search_parts, get_consumable_set, etc.)
        for p in data.get("parts") or []:
            if isinstance(p, dict) and p.get("tokin_part_no"):
                found.append(str(p["tokin_part_no"]))
        # consumable_set items
        for item in data.get("items") or []:
            if isinstance(item, dict):
                for p in item.get("parts") or []:
                    if isinstance(p, dict) and p.get("tokin_part_no"):
                        found.append(str(p["tokin_part_no"]))
    return list(dict.fromkeys(found))  # dedup, preserve order

def evaluate_case(case: dict, url: str, key: str, args_delay: float = 0.0) -> dict:
    cid    = case["id"]
    query  = case["query"]
    intent = case["intent"]
    expected = [str(e) for e in (case.get("expected_part_nos") or [])]
    note   = case.get("note", "")
    tier   = case.get("tier", 0)

    # SKIP cases
    is_oos = (not expected and intent == "OUT_OF_SCOPE")
    is_skip = (not expected and intent not in ("OUT_OF_SCOPE",) and
               "[no_tokin_equivalent]" in note)

    if is_skip:
        return {"id": cid, "intent": intent, "tier": tier,
                "status": "SKIP", "query": query, "latency_ms": 0,
                "expected": expected, "got": [], "note": note}

    time.sleep(args_delay)
    t0 = time.perf_counter()
    try:
        resp = call_api(query, f"eval-{cid}", url, key)
        latency = (time.perf_counter() - t0) * 1000
    except Exception as e:
        import traceback
        print(f"    [ERROR] {cid}: {type(e).__name__}: {e}")
        return {"id": cid, "intent": intent, "tier": tier,
                "status": "ERROR", "query": query, "latency_ms": 0,
                "expected": expected, "got": [], "note": str(e)}

    got = extract_part_nos(resp)

    if is_oos:
        # OOS: bot không được trả part nào
        status = "OOS_PASS" if not got else "OOS_FAIL"
    elif not expected:
        status = "SKIP"
    else:
        hit = any(e in got for e in expected)
        status = "PASS" if hit else "FAIL"

    return {
        "id": cid, "intent": intent, "tier": tier,
        "status": status, "query": query,
        "latency_ms": round(latency, 1),
        "expected": expected, "got": got,
        "llm_intent": resp.get("intent", ""),
        "tools_called": resp.get("tools_called", []),
        "note": note,
    }

def run_eval(args):
    with open(_EVAL_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    if args.intent:
        cases = [c for c in cases if c["intent"] == args.intent.upper()]
    if args.limit:
        cases = cases[:args.limit]

    print(f"🚀 LLM Eval: {len(cases)} cases → {args.url}/api/v2/query")
    print(f"   workers={args.workers}  timeout={args.timeout}s\n")

    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(evaluate_case, c, args.url, args.key, args.delay): c for c in cases}
        for fut in as_completed(futures, timeout=None):
            r = fut.result()
            results.append(r)
            done += 1
            status_icon = {"PASS":"✅","FAIL":"❌","SKIP":"⏭️","OOS_PASS":"✅","OOS_FAIL":"⚠️","ERROR":"💥"}.get(r["status"],"?")
            print(f"  {status_icon} [{done:3d}/{len(cases)}] {r['id']:8s} {r['intent']:20s} {r['status']:10s} | {r['query'][:45]:<45} ({r['latency_ms']:.0f}ms)")

    # Sort by id
    results.sort(key=lambda r: r["id"])

    # Stats
    counts = Counter(r["status"] for r in results)
    active = [r for r in results if r["status"] not in ("SKIP",)]
    pass_active = sum(1 for r in active if r["status"] in ("PASS","OOS_PASS"))
    total_active = len(active)

    print(f"\n{'='*72}")
    print(f"  TOKINARC LLM EVAL REPORT")
    print(f"{'='*72}")
    print(f"  Total cases   : {len(results)}  (active={total_active}, skipped={counts['SKIP']})")
    print(f"  PASS          : {counts['PASS']:4d}")
    print(f"  FAIL          : {counts['FAIL']:4d}")
    print(f"  OOS_PASS      : {counts['OOS_PASS']:4d}")
    print(f"  OOS_FAIL      : {counts['OOS_FAIL']:4d}")
    print(f"  ERROR         : {counts['ERROR']:4d}")
    if total_active:
        print(f"  Accuracy      : {pass_active/total_active*100:.1f}% of active")

    print(f"\n  By intent:")
    by_intent = defaultdict(list)
    for r in results:
        by_intent[r["intent"]].append(r)
    for intent in sorted(by_intent):
        grp = by_intent[intent]
        act = [r for r in grp if r["status"] != "SKIP"]
        p   = sum(1 for r in act if r["status"] in ("PASS","OOS_PASS"))
        pct = p/len(act)*100 if act else 0
        bar = "█" * int(pct/5)
        print(f"    {intent:25s}: {p:3d}/{len(act):3d}  {pct:5.1f}%  {bar}")

    # Latency
    lats = [r["latency_ms"] for r in results if r["status"] not in ("SKIP","ERROR") and r["latency_ms"] > 0]
    if lats:
        lats.sort()
        print(f"\n  Latency avg={sum(lats)/len(lats):.0f}ms  p50={lats[len(lats)//2]:.0f}ms  p95={lats[int(len(lats)*0.95)]:.0f}ms")

    # CSV
    _OUT_PATH.parent.mkdir(exist_ok=True)
    with open(_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id","intent","tier","status","query","latency_ms","expected","got","llm_intent","tools_called","note"])
        w.writeheader()
        for r in results:
            w.writerow({**r, "expected": "|".join(r.get("expected",[])), "got": "|".join(r.get("got",[])), "tools_called": "|".join(r.get("tools_called",[]))})

    print(f"\n  📄 CSV → {_OUT_PATH}")
    print(f"{'='*72}\n")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",     default="http://127.0.0.1:8000")
    ap.add_argument("--key",     default="dev-tokinarc-2026")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--limit",   type=int, default=0)
    ap.add_argument("--intent",  default="")
    ap.add_argument("--delay", type=float, default=3.0)
    run_eval(ap.parse_args())
