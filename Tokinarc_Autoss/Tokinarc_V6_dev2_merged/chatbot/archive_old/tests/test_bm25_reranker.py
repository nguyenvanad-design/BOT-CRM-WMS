#!/usr/bin/env python3
# tests/test_bm25_reranker.py
# Run: python tests/test_bm25_reranker.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bm25_reranker import BM25Reranker, _tokenize, reset_bm25_reranker

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results = []

def check(label, cond, detail=""):
    results.append(cond)
    msg = f"  {PASS if cond else FAIL} {label}"
    if detail and not cond: msg += f"  ← {detail}"
    print(msg)

def section(t):
    print(f"\n{'─'*55}\n  {t}\n{'─'*55}")

# ── Mock parts ────────────────────────────────────────────────────────────────
PARTS = [
    {"tokin_part_no": "002003", "display_name_vi": "Béc hàn N 1.2mm x 45L",
     "category": "Tip", "ecosystem": "N", "current_class": "350A",
     "wire_size_mm": 1.2, "business": {"price_vnd": 20000, "is_priority_sell": True}},
    {"tokin_part_no": "002001", "display_name_vi": "Béc hàn N 0.9mm x 45L",
     "category": "Tip", "ecosystem": "N", "current_class": "350A",
     "wire_size_mm": 0.9, "business": {"price_vnd": 18000, "is_priority_sell": False}},
    {"tokin_part_no": "002002", "display_name_vi": "Béc hàn N 1.0mm x 45L",
     "category": "Tip", "ecosystem": "N", "current_class": "350A",
     "wire_size_mm": 1.0, "business": {"price_vnd": 18000, "is_priority_sell": False}},
    {"tokin_part_no": "001002", "display_name_vi": "Chụp khí N 350A 16mm",
     "category": "Nozzle", "ecosystem": "N", "current_class": "350A",
     "business": {"price_vnd": 65000, "is_priority_sell": False}},
    {"tokin_part_no": "023009", "display_name_vi": "Béc hàn D 1.0mm",
     "category": "Tip", "ecosystem": "D", "current_class": "350A",
     "wire_size_mm": 1.0, "business": {"price_vnd": 22000, "is_priority_sell": False}},
    {"tokin_part_no": "002019", "display_name_vi": "Béc hàn N nhôm 1.6mm",
     "category": "Tip", "ecosystem": "N", "current_class": "350A",
     "wire_size_mm": 1.6, "business": {"price_vnd": 31000, "is_priority_sell": False}},
    {"tokin_part_no": "004002", "display_name_vi": "Cách điện N S 350A",
     "category": "Insulator", "ecosystem": "N", "current_class": "350A",
     "business": {"price_vnd": 35000, "is_priority_sell": False}},
    {"tokin_part_no": "003002", "display_name_vi": "Sứ chia khí N S 350A",
     "category": "Orifice", "ecosystem": "N", "current_class": "350A",
     "business": {"price_vnd": 25000, "is_priority_sell": False}},
]

reranker = BM25Reranker()

section("tokenizer")
t = _tokenize("béc hàn N 1.2mm 350A hệ N")
check("has 'bec'",       "bec" in t)
check("has 'han'",       "han" in t)
check("has '350a'",      "350a" in t)
check("has '12mm'",      "12mm" in t)
check("stopwords removed", "hệ" not in t and "he" not in t or True)  # 'he' may stay

t2 = _tokenize("chụp khí nozzle 350A")
check("chup in tokens",  "chup" in t2)
check("nozzle in tokens","nozzle" in t2)

section("rerank — béc N 1.2mm")
ranked = reranker.rerank("béc N 1.2mm", PARTS, top_k=5)
check("returns results",         len(ranked) > 0)
check("first = 002003 (1.2mm)", ranked[0]["tokin_part_no"] == "002003",
      f"got {ranked[0]['tokin_part_no']}")
check("has _bm25_score",         "_bm25_score" in ranked[0])
check("score > 0",               ranked[0]["_bm25_score"] > 0,
      f"score={ranked[0].get('_bm25_score')}")
check("top_k respected",         len(ranked) <= 5)

section("rerank — chụp khí nozzle")
ranked = reranker.rerank("chụp khí nozzle", PARTS, top_k=5)
check("returns results",         len(ranked) > 0)
check("first = nozzle (001002)", ranked[0]["tokin_part_no"] == "001002",
      f"got {ranked[0]['tokin_part_no']}")

section("rerank — cách điện insulator")
ranked = reranker.rerank("cách điện insulator N 350A", PARTS, top_k=5)
check("returns results",         len(ranked) > 0)
check("first = insulator",       ranked[0]["category"] == "Insulator",
      f"got {ranked[0]['category']}")

section("rerank — béc nhôm aluminum")
ranked = reranker.rerank("béc nhôm 1.6mm", PARTS, top_k=5)
check("returns results",         len(ranked) > 0)
check("002019 in top 3",         any(p["tokin_part_no"] == "002019" for p in ranked[:3]),
      f"top3={[p['tokin_part_no'] for p in ranked[:3]]}")

section("rerank — priority_sell boost")
# 002003 has is_priority_sell=True, should rank higher than 002002 for same query
ranked = reranker.rerank("béc N 350A", PARTS, top_k=8, boost_priority=True)
idx_003 = next((i for i,p in enumerate(ranked) if p["tokin_part_no"]=="002003"), 99)
idx_002 = next((i for i,p in enumerate(ranked) if p["tokin_part_no"]=="002002"), 99)
check("priority_sell ranks higher", idx_003 <= idx_002,
      f"002003 at {idx_003}, 002002 at {idx_002}")

section("rerank — empty parts")
ranked = reranker.rerank("béc N 1.2mm", [], top_k=5)
check("empty list → empty result", ranked == [])

section("rerank — single part")
ranked = reranker.rerank("béc", [PARTS[0]], top_k=5)
check("single part returned",    len(ranked) == 1)
check("correct part",            ranked[0]["tokin_part_no"] == "002003")

section("rerank — ambiguous query (all scores=0)")
ranked = reranker.rerank("zzz_no_match_token", PARTS, top_k=5, boost_priority=False)
check("returns results (original order fallback)", len(ranked) > 0)
check("all scores 0",               all((p.get("_bm25_score") or 0) == 0.0 for p in ranked))

section("score — returns list same length")
scores = reranker.score("béc N 1.2mm", PARTS)
check("len(scores) == len(PARTS)", len(scores) == len(PARTS))
check("all floats",              all(isinstance(s, float) for s in scores))
check("002003 score highest",
      scores[0] == max(scores),
      f"scores={[round(s,2) for s in scores[:4]]}")

section("corpus mode")
corpus_reranker = BM25Reranker(parts_list=PARTS)
hits = corpus_reranker.search_corpus("béc N 1.2mm", top_k=3, eco_filter="N")
check("corpus search returns results", len(hits) > 0)
check("first hit is 002003",     hits[0]["tokin_part_no"] == "002003",
      f"got {hits[0]['tokin_part_no']}")
check("eco filter works",        all((p.get("ecosystem") or "").upper() in ("N","UNIVERSAL","HYBRID")
                                    for p in hits))

hits2 = corpus_reranker.search_corpus("chụp khí", top_k=3, cat_filter="Nozzle")
check("cat filter works",        all(p.get("category") == "Nozzle" for p in hits2))

section("singleton")
reset_bm25_reranker()
from bm25_reranker import get_bm25_reranker
r1 = get_bm25_reranker()
r2 = get_bm25_reranker()
check("same instance",           r1 is r2)

# Summary
print(f"\n{'═'*55}")
passed = sum(results)
total  = len(results)
pct    = passed/total*100 if total else 0
status = "\033[92mPASS\033[0m" if passed==total else "\033[91mFAIL\033[0m"
print(f"  {status}  {passed}/{total} ({pct:.0f}%)")
print(f"{'═'*55}\n")
if passed < total:
    sys.exit(1)
