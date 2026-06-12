# core/bm25_reranker.py
# TOKINARC BM25 Reranker
# ======================
# Rerank search results theo BM25 relevance score.
# Không dùng external library — implement BM25 Okapi thuần Python.
# Wire vào search_parts tool để tăng chất lượng kết quả.
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

log = logging.getLogger("tokinarc.bm25_reranker")

# BM25 params
K1 = 1.5
B  = 0.75


def _normalize(text: str) -> str:
    """Bỏ dấu, lower, giữ alphanumeric + space."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s.]", " ", text)
    return text.strip()


def _tokenize(text: str) -> List[str]:
    return _normalize(text).split()


def _build_doc_text(part: dict) -> str:
    """Ghép các field quan trọng thành 1 string để index."""
    parts_text = [
        part.get("tokin_part_no", ""),
        part.get("display_name_vi", ""),
        part.get("display_name_en", ""),
        part.get("category", ""),
        part.get("ecosystem", ""),
        part.get("current_class", ""),
        str(part.get("wire_size_mm", "")),
        " ".join(part.get("p_part_nos") or []),
        " ".join(part.get("d_part_nos") or []),
        " ".join(part.get("o_part_nos") or []),
        part.get("note", ""),
    ]
    return " ".join(filter(None, parts_text))


class BM25Reranker:
    """
    BM25 Okapi index trên parts list.
    Built once at startup, reused for every search.
    """

    def __init__(self, parts_list: List[dict]):
        self._parts  = parts_list
        self._n      = len(parts_list)
        self._avgdl  = 0.0
        self._df: dict  = {}   # term → doc frequency
        self._tf: list  = []   # list of Counter per doc

        self._build(parts_list)
        log.info(f"[BM25Reranker] indexed {self._n} parts, avgdl={self._avgdl:.1f}")

    def _build(self, parts: List[dict]):
        tf_list = []
        total_len = 0

        for part in parts:
            tokens = _tokenize(_build_doc_text(part))
            tf = Counter(tokens)
            tf_list.append(tf)
            total_len += len(tokens)
            for term in tf:
                self._df[term] = self._df.get(term, 0) + 1

        self._tf    = tf_list
        self._avgdl = total_len / max(self._n, 1)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log((self._n - df + 0.5) / (df + 0.5) + 1)

    def score(self, query: str, doc_idx: int) -> float:
        tokens = _tokenize(query)
        tf     = self._tf[doc_idx]
        dl     = sum(tf.values())
        score  = 0.0
        for term in set(tokens):
            if term not in tf:
                continue
            idf_v = self._idf(term)
            tf_v  = tf[term]
            num   = tf_v * (K1 + 1)
            den   = tf_v + K1 * (1 - B + B * dl / self._avgdl)
            score += idf_v * num / den
        return score

    def rerank(
        self,
        query: str,
        parts: List[dict],
        top_k: int = 20,
        min_score: float = 0.0,
    ) -> List[Tuple[float, dict]]:
        """
        Rerank danh sách parts theo BM25 score với query.

        Returns: List[(score, part_dict)] sorted desc by score.
        """
        if not parts or not query.strip():
            return [(1.0, p) for p in parts[:top_k]]

        # Build temp index cho subset nếu cần
        # Nếu part có trong self._parts → dùng cached TF
        # Nếu không → score = 0 (không rerank)
        pno_to_idx = {p.get("tokin_part_no", ""): i
                      for i, p in enumerate(self._parts)}

        scored = []
        for part in parts:
            pno = part.get("tokin_part_no", "")
            idx = pno_to_idx.get(pno)
            if idx is not None:
                s = self.score(query, idx)
            else:
                # Part không trong main index → score từ text trực tiếp
                tokens = _tokenize(query)
                doc_text = _normalize(_build_doc_text(part))
                s = sum(1.0 for t in tokens if t in doc_text) / max(len(tokens), 1)
            # Priority boost: is_priority_sell=True → +15%
            # Giúp parts phổ biến (002003) không bị đẩy xuống bởi variants ít dùng
            biz = part.get("business") or {}
            if biz.get("is_priority_sell", False):
                s *= 1.15

            if s >= min_score:
                scored.append((s, part))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


# ── Singleton ──────────────────────────────────────────────────────────────────

_reranker: Optional[BM25Reranker] = None


def get_bm25_reranker(parts_list: Optional[List[dict]] = None) -> BM25Reranker:
    """
    Singleton factory.
    - Lần đầu: bắt buộc truyền parts_list (gọi từ lifespan)
    - Sau đó: gọi không args để lấy instance
    """
    global _reranker
    if _reranker is None:
        if not parts_list:
            raise RuntimeError(
                "BM25Reranker chưa được khởi tạo. "
                "Gọi get_bm25_reranker(parts_list) từ lifespan trước."
            )
        _reranker = BM25Reranker(parts_list)
    return _reranker


def rerank_parts(
    query: str,
    parts: List[dict],
    top_k: int = 15,
) -> List[dict]:
    """
    Convenience function — rerank list[dict] parts và trả list đã sort.
    Trả nguyên list nếu reranker chưa init (safe fallback).
    """
    global _reranker
    if _reranker is None or not query.strip():
        return parts[:top_k]
    try:
        scored = _reranker.rerank(query, parts, top_k=top_k)
        return [p for _, p in scored]
    except Exception as e:
        log.warning(f"[BM25Reranker] rerank failed: {e} — returning original order")
        return parts[:top_k]
