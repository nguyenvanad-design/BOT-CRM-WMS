# apply_restructure.py
# TOKINARC Restructure 2026-06 — dọn dead code vào legacy/
# ==========================================================
# Chạy từ repo root:  python apply_restructure.py
# Chạy thử (không move): python apply_restructure.py --dry-run
#
# Các module sau KHÔNG được import bởi bất kỳ đường chạy nào
# (đã verify bằng import graph trên toàn bộ codebase):
#   pipeline_v7.py          (1.986 dòng) — pipeline cũ, main.py không gọi
#   llm_extractor.py        (1.352 dòng) — extractor V1, thay bằng tool-use
#   llm_explanation.py      (1.087 dòng) — chỉ pipeline_v7 import
#   tokinarc_schema_v12.py  (1.850 dòng) — schema cũ, không ai import
#   memory_manager.py         (190 dòng) — không ai import
#   compatibility_matrix.py   (167 dòng) — không ai import
#
# GIỮ LẠI (live path):
#   main.py, llm_orchestrator_v2.py, tool_wrappers.py, data_store.py,
#   retrieval_orchestrator.py, fuzzy_corrector.py, bm25_reranker.py,
#   vector_index.py, graph_traversal.py, tokinarc_cer.py, assembly_kb.py,
#   procedural_qa_retriever.py, session_store.py, confidence_layer.py,
#   order_manager.py, query_logger.py, vision_module.py, system_prompts.py,
#   gemini_resilience.py (giờ được orchestrator REST dùng cho retry)
#
# GIỮ LẠI (CLI tools, không nằm trong server):
#   retrieval_eval.py, rebuild_index.py
#
# UTF-8 NO BOM

from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

DEAD_MODULES = [
    "pipeline_v7.py",
    "llm_extractor.py",
    "llm_explanation.py",
    "tokinarc_schema_v12.py",
    "memory_manager.py",
    "compatibility_matrix.py",
]

# Thư mục có thể chứa các file này (repo root hoặc core/)
SEARCH_DIRS = [Path("."), Path("core")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ in ra sẽ move gì, không move thật")
    args = parser.parse_args()

    legacy = Path("legacy")
    moved, missing = [], []

    for name in DEAD_MODULES:
        src = next((d / name for d in SEARCH_DIRS if (d / name).exists()), None)
        if src is None:
            missing.append(name)
            continue
        dst = legacy / src.relative_to(".")
        if args.dry_run:
            print(f"[dry-run] {src}  →  {dst}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            print(f"[moved]   {src}  →  {dst}")
        moved.append(name)

    if missing:
        print(f"\n[note] không tìm thấy (có thể đã dọn trước đó): {missing}")

    print(f"\nXong: {len(moved)} file"
          + (" (dry-run, chưa move thật)" if args.dry_run else " đã move vào legacy/"))
    print("Khuyến nghị: commit ngay sau khi chạy để git history giữ nguyên nội dung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
