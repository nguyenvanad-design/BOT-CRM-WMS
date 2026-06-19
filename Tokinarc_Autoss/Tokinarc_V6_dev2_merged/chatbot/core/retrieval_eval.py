# core/retrieval_eval.py
# TOKINARC Retrieval Eval Runner
# ================================
# Chạy eval_700 benchmark để đo accuracy Tier 1 retrieval pipeline.
#
# Input:  eval_700.json — 700 test cases
# Output: console report + logs/eval_700_report.csv
#
# Usage:
#   python -m core.retrieval_eval
#   python -m core.retrieval_eval --n 100
#   python -m core.retrieval_eval --out logs/report.csv
#   python -m core.retrieval_eval --failed-only
#   python -m core.retrieval_eval --intent LOOKUP
#
# Test case format (eval_700.json):
#   {
#     "id": "E0001",
#     "query": "béc N 350A 1.2mm",
#     "intent": "SEARCH_BY_DESC",
#     "expected_part_nos": ["002003", "002001"],
#     "tier": 1,
#     "note": ""
#   }
#
# Evaluation criteria:
#   PASS     = ít nhất 1 expected_part_nos xuất hiện trong top-k results
#   PASS_FUZZY = expected tìm thấy nhưng sau rank top-k (warning)
#   FAIL     = không tìm thấy expected
#   OOS_PASS = expected_part_nos=[] VÀ bot trả về rỗng ✅
#   OOS_FAIL = expected_part_nos=[] NHƯNG bot trả về kết quả ❌
#   SKIP     = expected_part_nos=[] nhưng intent không phải OOS → bỏ qua
#
# UTF-8 NO BOM

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("tokinarc.retrieval_eval")

# ── Default paths ──────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EVAL_PATH = _REPO_ROOT / "eval_700.json"
_DEFAULT_OUT_PATH  = _REPO_ROOT / "logs" / "eval_700_report.csv"
# FIX (restructure): dùng cùng resolver với production (data_store)
# — trước đây eval hardcode v14 trong khi prod chạy v19 → benchmark sai data.
try:
    from core.data_store import _resolve_data_path as _rdp
    _DEFAULT_DATA_PATH = Path(_rdp())
except Exception:
    _DEFAULT_DATA_PATH = _REPO_ROOT / "data" / "tokinarc_data_v19.json"
TOP_K = 10


# ══════════════════════════════════════════════════════════════════════════════
# Result dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CaseResult:
    case_id:         str
    query:           str
    intent:          str           # FIX 1: thêm intent field — eval_700 dùng intent, không dùng tier-string
    tier:            int           # FIX 1: tier là int (1/2/0), không phải string
    status:          str           # PASS | PASS_FUZZY | FAIL | OOS_PASS | OOS_FAIL | SKIP | ERROR
    stage:           str
    expected:        List[str]     = field(default_factory=list)
    got_part_nos:    List[str]     = field(default_factory=list)
    matched_at_rank: int           = -1
    corrections:     List[str]     = field(default_factory=list)
    latency_ms:      float         = 0.0
    note:            str           = ""
    error:           str           = ""

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "OOS_PASS")

    @property
    def skipped(self) -> bool:
        return self.status == "SKIP"


# ══════════════════════════════════════════════════════════════════════════════
# Evaluator
# ══════════════════════════════════════════════════════════════════════════════

# FIX 2: intent nào cần trả rỗng khi expected=[]
_OOS_INTENTS = {"OUT_OF_SCOPE"}
# Intent nào expected=[] là do data chưa đủ → SKIP, không count FAIL
_SKIP_IF_EMPTY = {"REPAIR", "INSTALLATION", "AGGREGATE", "COMPARISON",
                  "COMPATIBILITY_CHECK", "UPSELL"}


class RetrievalEvaluator:

    def __init__(self, orchestrator=None, top_k: int = TOP_K):
        self._orch = orchestrator
        self.top_k = top_k

    @property
    def orch(self):
        if self._orch is None:
            from core.retrieval_orchestrator import get_retrieval_orchestrator
            self._orch = get_retrieval_orchestrator()
        return self._orch

    def run(
        self,
        cases:       List[dict],
        verbose:     bool = False,
        failed_only: bool = False,
    ) -> List[CaseResult]:
        results: List[CaseResult] = []
        n = len(cases)

        for i, tc in enumerate(cases, 1):
            case_id   = tc.get("id", f"E{i:04d}")
            query     = tc.get("query", "")
            expected  = [str(p) for p in (tc.get("expected_part_nos") or [])]
            intent    = tc.get("intent", "")
            tier      = tc.get("tier", 1)           # FIX 1: int
            note      = tc.get("note", "")

            # FIX 3: field names thống nhất với eval_700.json schema
            # eval_700 không có expected_category/ecosystem/current_class riêng
            # → extract từ note hoặc để None
            category  = tc.get("category")
            ecosystem = tc.get("ecosystem")
            cc        = tc.get("current_class")
            wire      = tc.get("wire_size_mm")

            is_oos    = (not expected)

            cr = CaseResult(
                case_id=case_id, query=query,
                intent=intent, tier=tier,
                status="", stage="", expected=expected, note=note,
            )

            # FIX 2: SKIP nếu expected=[] nhưng intent không phải OOS
            # (data chưa đủ, không nên count vào accuracy)
            if is_oos and intent not in _OOS_INTENTS:
                cr.status = "SKIP"
                cr.stage  = "skip"
                results.append(cr)
                if verbose:
                    _print_case(cr, i, n)
                elif i % 50 == 0:
                    print(f"  ... {i}/{n}", end="\r", flush=True)
                continue

            try:
                t_start = time.perf_counter()
                result = self.orch.retrieve(
                    query         = query,
                    ecosystem     = ecosystem,
                    current_class = cc,
                    wire_size_mm  = float(wire) if wire else None,
                    category      = category,
                    top_k         = self.top_k,
                )
                cr.latency_ms   = (time.perf_counter() - t_start) * 1000  # FIX 4: đo latency ở đây, không dùng result.latency_ms (có thể None)
                cr.stage        = getattr(result, "stage", "unknown")
                cr.corrections  = getattr(result, "corrections", []) or []
                # FIX 5: result.parts có thể là list of dict hoặc list of object
                raw_parts = getattr(result, "parts", []) or []
                cr.got_part_nos = []
                for p in raw_parts:
                    if isinstance(p, dict):
                        pno = p.get("tokin_part_no", "")
                    else:
                        pno = getattr(p, "tokin_part_no", "")
                    if pno:
                        cr.got_part_nos.append(pno)

                if is_oos:
                    # OOS_INTENTS: mong muốn bot không trả kết quả
                    cr.status = "OOS_PASS" if not cr.got_part_nos else "OOS_FAIL"
                else:
                    got_upper = [p.upper() for p in cr.got_part_nos]
                    match_rank = -1
                    for exp in expected:
                        exp_u = exp.upper()
                        if exp_u in got_upper:
                            rank = got_upper.index(exp_u) + 1
                            if match_rank < 0 or rank < match_rank:
                                match_rank = rank

                    # Also try fuzzy: check beyond top_k
                    if match_rank < 0:
                        all_upper = [p.upper() for p in cr.got_part_nos]
                        for exp in expected:
                            if exp.upper() in all_upper:
                                match_rank = all_upper.index(exp.upper()) + 1
                                break

                    cr.matched_at_rank = match_rank
                    if 1 <= match_rank <= self.top_k:
                        cr.status = "PASS"
                    elif match_rank > self.top_k:
                        cr.status = "PASS_FUZZY"
                    else:
                        cr.status = "FAIL"

            except Exception as e:
                cr.status = "ERROR"
                cr.error  = str(e)
                log.warning(f"[eval] {case_id} error: {e}")

            results.append(cr)

            if not failed_only or not cr.passed:
                if verbose or not cr.passed:
                    _print_case(cr, i, n)
            elif i % 50 == 0:
                print(f"  ... {i}/{n}", end="\r", flush=True)

        return results

    def report(self, results: List[CaseResult]) -> dict:
        total   = len(results)
        skipped = sum(1 for r in results if r.skipped)
        active  = total - skipped   # cases thực sự được eval

        passed   = sum(1 for r in results if r.passed)
        failed   = sum(1 for r in results if r.status == "FAIL")
        errored  = sum(1 for r in results if r.status == "ERROR")
        oos_pass = sum(1 for r in results if r.status == "OOS_PASS")
        oos_fail = sum(1 for r in results if r.status == "OOS_FAIL")
        fuzzy    = sum(1 for r in results if r.status == "PASS_FUZZY")

        # FIX 1: group by intent (không phải tier-string)
        by_intent: Dict[str, Counter] = defaultdict(Counter)
        for r in results:
            if not r.skipped:
                by_intent[r.intent][r.status] += 1

        # FIX 1: by_tier dùng int tier
        by_tier: Dict[int, Counter] = defaultdict(Counter)
        for r in results:
            if not r.skipped:
                by_tier[r.tier][r.status] += 1

        by_stage: Counter = Counter(
            r.stage for r in results if r.stage and r.stage != "skip"
        )

        rank_dist: Counter = Counter()
        for r in results:
            if r.status == "PASS" and r.matched_at_rank >= 1:
                rank_dist[r.matched_at_rank] += 1

        lats = [r.latency_ms for r in results if r.status not in ("SKIP","ERROR")]
        avg_lat = sum(lats) / len(lats) if lats else 0.0
        p50_lat = _percentile(lats, 50)
        p95_lat = _percentile(lats, 95)

        n_corrected = sum(1 for r in results if r.corrections)

        # accuracy trên active cases (loại trừ SKIP)
        accuracy = round(passed / active * 100, 2) if active else 0.0

        return {
            "total":       total,
            "active":      active,
            "skipped":     skipped,
            "passed":      passed,
            "failed":      failed,
            "fuzzy":       fuzzy,
            "errored":     errored,
            "oos_pass":    oos_pass,
            "oos_fail":    oos_fail,
            "accuracy":    accuracy,
            "by_intent":   {k: dict(v) for k, v in sorted(by_intent.items())},
            "by_tier":     {k: dict(v) for k, v in sorted(by_tier.items())},
            "by_stage":    dict(by_stage),
            "rank_dist":   dict(sorted(rank_dist.items())),
            "latency_avg_ms": round(avg_lat, 1),
            "latency_p50_ms": round(p50_lat, 1),
            "latency_p95_ms": round(p95_lat, 1),
            "fuzzy_corrected": n_corrected,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _percentile(data: list, pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    f, c = int(k), int(k) + 1
    if c >= len(s):
        return s[-1]
    return s[f] + (s[c] - s[f]) * (k - f)


def _print_case(cr: CaseResult, i: int, total: int):
    icon = {
        "PASS": "✅", "OOS_PASS": "✅", "PASS_FUZZY": "🟡",
        "FAIL": "❌", "OOS_FAIL": "⚠️", "ERROR": "💥", "SKIP": "⏭️",
    }.get(cr.status, "?")
    corr = f" [{','.join(cr.corrections[:2])}]" if cr.corrections else ""
    rank = f" @rank{cr.matched_at_rank}" if cr.matched_at_rank >= 1 else ""
    print(
        f"  {icon} [{i:3d}/{total}] {cr.case_id:8s} {cr.intent:20s} "
        f"{cr.status:10s}{rank:8s} | {cr.query[:40]:40s}"
        f"{corr} ({cr.latency_ms:.0f}ms)"
    )


def _print_report(stats: dict):
    active = stats["active"]
    print()
    print("=" * 72)
    print("  TOKINARC RETRIEVAL EVAL REPORT")
    print("=" * 72)
    print(f"  Total cases   : {stats['total']}  (active={active}, skipped={stats['skipped']})")
    print(f"  PASS          : {stats['passed']:4d}  ({stats['accuracy']:.1f}% of active)")
    print(f"  FAIL          : {stats['failed']:4d}")
    if stats["fuzzy"]:
        print(f"  PASS_FUZZY    : {stats['fuzzy']:4d}  (found but rank > top_k)")
    if stats["errored"]:
        print(f"  ERROR         : {stats['errored']:4d}")
    if stats["oos_pass"] or stats["oos_fail"]:
        print(f"  OOS_PASS      : {stats['oos_pass']:4d}")
        print(f"  OOS_FAIL      : {stats['oos_fail']:4d}")
    print()

    print("  By intent:")
    for intent, counts in stats["by_intent"].items():
        total_i = sum(counts.values())
        pass_i  = counts.get("PASS", 0) + counts.get("OOS_PASS", 0)
        pct = pass_i / total_i * 100 if total_i else 0
        bar = "█" * int(pct / 5)
        print(f"    {intent:25s}: {pass_i:3d}/{total_i:3d}  {pct:5.1f}%  {bar}")

    print()
    print("  By tier:")
    for tier, counts in stats["by_tier"].items():
        total_t = sum(counts.values())
        pass_t  = counts.get("PASS", 0) + counts.get("OOS_PASS", 0)
        pct = pass_t / total_t * 100 if total_t else 0
        bar = "█" * int(pct / 5)
        print(f"    Tier {tier}: {pass_t:3d}/{total_t:3d}  {pct:5.1f}%  {bar}")

    print()
    print("  By retrieval stage:")
    for stage, cnt in sorted(stats["by_stage"].items(), key=lambda x: -x[1]):
        print(f"    {stage:15s}: {cnt:4d}")

    print()
    print("  Rank distribution (PASS cases):")
    rank_total = sum(stats["rank_dist"].values())
    cumulative = 0
    for rank, cnt in sorted(stats["rank_dist"].items()):
        pct = cnt / rank_total * 100 if rank_total else 0
        cumulative += cnt
        cum_pct = cumulative / rank_total * 100 if rank_total else 0
        print(f"    Rank {rank:2d}: {cnt:4d}  ({pct:.1f}%)  cumulative={cum_pct:.1f}%")

    print()
    print(f"  FuzzyCorrector applied: {stats['fuzzy_corrected']} cases")
    print(f"  Latency avg={stats['latency_avg_ms']}ms  "
          f"p50={stats['latency_p50_ms']}ms  "
          f"p95={stats['latency_p95_ms']}ms")
    print("=" * 72)


def _write_csv(results: List[CaseResult], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "id", "intent", "tier", "status", "stage", "matched_at_rank",
            "query", "expected", "got_top3", "corrections",
            "latency_ms", "note", "error",
        ])
        for r in results:
            w.writerow([
                r.case_id, r.intent, r.tier, r.status, r.stage,
                r.matched_at_rank if r.matched_at_rank >= 0 else "",
                r.query,
                "|".join(r.expected),
                "|".join(r.got_part_nos[:3]),
                "|".join(r.corrections[:3]),
                round(r.latency_ms, 1),
                r.note,
                r.error,
            ])
    print(f"\n  📄 CSV report → {path}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="TOKINARC Retrieval Eval Runner")
    parser.add_argument("--eval",        default=str(_DEFAULT_EVAL_PATH))
    parser.add_argument("--data",        default=str(_DEFAULT_DATA_PATH))
    parser.add_argument("--out",         default=str(_DEFAULT_OUT_PATH))
    parser.add_argument("--n",           type=int, default=0,
                        help="Chỉ chạy n cases đầu (0 = tất cả)")
    parser.add_argument("--top-k",       type=int, default=TOP_K)
    parser.add_argument("--intent",      default="",
                        help="Filter theo intent: LOOKUP|SEARCH_BY_DESC|...")
    parser.add_argument("--tier",        type=int, default=0,
                        help="Filter theo tier: 0=tất cả, 1=exact, 2=related")
    parser.add_argument("--verbose",     action="store_true")
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--no-csv",      action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    eval_path = Path(args.eval)
    if not eval_path.exists():
        print(f"❌ eval file không tìm thấy: {eval_path}")
        sys.exit(1)

    with open(eval_path, encoding="utf-8") as f:
        cases: List[dict] = json.load(f)

    # FIX 1: filter dùng intent field, không phải tier string
    if args.intent:
        cases = [c for c in cases if c.get("intent","").upper() == args.intent.upper()]
        print(f"  Filter intent={args.intent}: {len(cases)} cases")

    if args.tier:
        cases = [c for c in cases if c.get("tier") == args.tier]
        print(f"  Filter tier={args.tier}: {len(cases)} cases")

    if args.n:
        cases = cases[:args.n]

    print(f"\n🚀 Running eval: {len(cases)} cases, top_k={args.top_k}")
    print(f"   eval: {eval_path}")
    print(f"   data: {args.data}\n")

    try:
        from core.data_store import get_data_store
        ds = get_data_store(args.data)
        print(f"✅ DataStore loaded: {len(ds.parts)} parts")
    except Exception as e:
        print(f"❌ DataStore failed: {e}")
        sys.exit(1)

    from core.retrieval_orchestrator import RetrievalOrchestrator
    orch = RetrievalOrchestrator(ds=ds)
    evaluator = RetrievalEvaluator(orchestrator=orch, top_k=args.top_k)

    t0 = time.perf_counter()
    results = evaluator.run(cases, verbose=args.verbose, failed_only=args.failed_only)
    elapsed = time.perf_counter() - t0

    active = [r for r in results if not r.skipped]
    print(f"\n  Total wall time: {elapsed:.1f}s  ({elapsed/len(active)*1000:.1f}ms/active case)")

    stats = evaluator.report(results)
    _print_report(stats)

    if not args.no_csv:
        _write_csv(results, Path(args.out))

    # Exit: 0 nếu accuracy ≥ 80% (threshold thực tế cho v1)
    threshold = 0.80
    sys.exit(0 if stats["accuracy"] >= threshold * 100 else 1)


if __name__ == "__main__":
    main()
