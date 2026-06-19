"""
rebuild_index.py — Rebuild FAISS indexes sau khi data thay đổi.

Usage:
    python rebuild_index.py           # Rebuild cả VectorIndex + PQA
    python rebuild_index.py --vec     # Chỉ rebuild VectorIndex
    python rebuild_index.py --pqa     # Chỉ rebuild PQA index
    python rebuild_index.py --force   # Force rebuild dù index đã tồn tại
"""
from __future__ import annotations
import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

# ── Setup logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rebuild_index")

ROOT         = Path(__file__).resolve().parent
INDEX_DIR    = ROOT / "indexes"
VEC_INDEX    = INDEX_DIR / "tokinarc_faiss.index"
VEC_CHUNKS   = INDEX_DIR / "tokinarc_chunks.pkl"
PQA_IDX_DIR  = INDEX_DIR / "procedural_qa_idx"
DATA_FILE    = ROOT / "data" / os.getenv("TOKINARC_DATA_FILE", "tokinarc_data_v19.json")
PQA_KB_FILE  = ROOT / "data" / "procedural_qa_kb.jsonl"


def rebuild_vector_index(force: bool = False) -> bool:
    sys.path.insert(0, str(ROOT))
    try:
        from core.vector_index import build_index, save_index, INDEX_FILE, CHUNKS_FILE
    except ImportError as e:
        log.error(f"Cannot import vector_index: {e}")
        return False

    if not force and VEC_INDEX.exists() and VEC_CHUNKS.exists():
        log.info(f"VectorIndex đã tồn tại ({VEC_INDEX}). Dùng --force để rebuild.")
        return True

    log.info("=== Bắt đầu rebuild VectorIndex ===")
    log.info(f"Data file: {DATA_FILE}")
    t0 = time.time()

    # Xóa index cũ
    for f in [VEC_INDEX, VEC_CHUNKS]:
        if f.exists():
            f.unlink()
            log.info(f"Đã xóa: {f}")

    try:
        index, chunks = build_index(DATA_FILE)
        save_index(index, chunks)
        elapsed = time.time() - t0
        log.info(f"✅ VectorIndex done: {index.ntotal} vectors in {elapsed:.1f}s")
        return True
    except Exception as e:
        log.error(f"❌ VectorIndex failed: {e}")
        return False


def rebuild_pqa_index(force: bool = False) -> bool:
    sys.path.insert(0, str(ROOT))
    try:
        from core.procedural_qa_retriever import ProceduralQARetriever
    except ImportError as e:
        log.error(f"Cannot import procedural_qa_retriever: {e}")
        return False

    if not PQA_KB_FILE.exists():
        log.error(f"PQA KB file không tồn tại: {PQA_KB_FILE}")
        return False

    # Force rebuild: xóa folder cũ
    if force and PQA_IDX_DIR.exists():
        shutil.rmtree(PQA_IDX_DIR)
        log.info(f"Đã xóa PQA index cũ: {PQA_IDX_DIR}")

    log.info("=== Bắt đầu rebuild PQA index ===")
    log.info(f"KB file: {PQA_KB_FILE}")
    t0 = time.time()

    try:
        retriever = ProceduralQARetriever(
            kb_path=PQA_KB_FILE,
            index_dir=PQA_IDX_DIR,
        )
        retriever.build_index(force_rebuild=True)
        elapsed = time.time() - t0
        log.info(f"✅ PQA index done: {retriever._index.ntotal} vectors in {elapsed:.1f}s")
        return True
    except Exception as e:
        log.error(f"❌ PQA index failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Rebuild TOKINARC FAISS indexes")
    parser.add_argument("--vec",   action="store_true", help="Chỉ rebuild VectorIndex")
    parser.add_argument("--pqa",   action="store_true", help="Chỉ rebuild PQA index")
    parser.add_argument("--force", action="store_true", help="Force rebuild dù index đã tồn tại")
    args = parser.parse_args()

    # Mặc định rebuild cả 2 nếu không chỉ định
    do_vec = args.vec or (not args.vec and not args.pqa)
    do_pqa = args.pqa or (not args.vec and not args.pqa)

    results = {}
    t_start = time.time()

    if do_vec:
        results["VectorIndex"] = rebuild_vector_index(force=args.force)

    if do_pqa:
        results["PQA"] = rebuild_pqa_index(force=args.force)

    # Summary
    print()
    print("=" * 50)
    print("REBUILD SUMMARY")
    print("=" * 50)
    all_ok = True
    for name, ok in results.items():
        status = "✅ OK" if ok else "❌ FAILED"
        print(f"  {name}: {status}")
        if not ok:
            all_ok = False
    print(f"  Total time: {time.time()-t_start:.1f}s")
    print("=" * 50)

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
