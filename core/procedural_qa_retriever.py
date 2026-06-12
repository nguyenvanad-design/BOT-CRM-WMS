# core/procedural_qa_retriever.py
from __future__ import annotations
import json
import logging
import os
import pickle
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
import torch
from FlagEmbedding import FlagModel

logger = logging.getLogger(__name__)

_DEFAULT_KB   = Path("data/procedural_qa_kb.jsonl")
_DEFAULT_IDX  = Path("indexes/procedural_qa_idx")

BGE_MODEL_NAME  = "BAAI/bge-m3"
TOP_K_DEFAULT   = 3
SCORE_THRESHOLD = 0.68
BATCH_EMBED     = 64


class ProceduralQARetriever:

    def __init__(
        self,
        kb_path: str | Path = _DEFAULT_KB,
        index_dir: str | Path = _DEFAULT_IDX,
        model_name: str = BGE_MODEL_NAME,
        device: str = "cuda",
        top_k: int = TOP_K_DEFAULT,
        score_threshold: float = SCORE_THRESHOLD,
    ):
        self.kb_path         = Path(kb_path)
        self.index_dir       = Path(index_dir)
        self.model_name      = model_name
        self.device          = device if torch.cuda.is_available() else "cpu"
        self.top_k           = top_k
        self.score_threshold = score_threshold

        self._model: Optional[FlagModel] = None
        self._index: Optional[faiss.Index] = None
        self._records: list[dict] = []

    def build_index(self, force_rebuild: bool = False) -> None:
        faiss_path = self.index_dir / "procedural_qa.faiss"
        meta_path  = self.index_dir / "procedural_qa.meta"

        if not force_rebuild and faiss_path.exists() and meta_path.exists():
            logger.info("[PQA] Index da ton tai, skip build.")
            return

        logger.info("[PQA] Bat dau build index...")
        records   = self._load_kb()
        questions = [r["question"] for r in records]

        model      = self._get_model()
        logger.info(f"[PQA] Embedding {len(questions)} samples (batch={BATCH_EMBED})...")
        embeddings = self._embed_batch(model, questions)

        faiss.normalize_L2(embeddings)
        dim   = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(faiss_path))
        with open(meta_path, "wb") as f:
            pickle.dump(records, f)

        self._index   = index
        self._records = records
        logger.info(f"[PQA] Index built: {index.ntotal} vectors -> {faiss_path}")

    def load_index(self) -> None:
        faiss_path = self.index_dir / "procedural_qa.faiss"
        meta_path  = self.index_dir / "procedural_qa.meta"

        if not faiss_path.exists():
            raise FileNotFoundError(
                f"[PQA] Index chua ton tai: {faiss_path}\nChay build_index() truoc."
            )

        logger.info("[PQA] Loading FAISS index...")
        self._index = faiss.read_index(str(faiss_path))
        with open(meta_path, "rb") as f:
            self._records = pickle.load(f)
        logger.info(f"[PQA] Loaded {self._index.ntotal} vectors, {len(self._records)} records.")

    def retrieve(
        self,
        query: str,
        intent: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        if self._index is None:
            self.load_index()

        k     = top_k or self.top_k
        model = self._get_model()

        qvec = self._embed_batch(model, [query])
        faiss.normalize_L2(qvec)

        if intent:
            return self._retrieve_filtered(qvec, intent, k)
        return self._retrieve_global(qvec, k)

    def _retrieve_global(self, qvec: np.ndarray, k: int) -> list[dict]:
        scores, idxs = self._index.search(qvec, k * 3)
        out = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or float(score) < self.score_threshold:
                continue
            rec = self._records[idx].copy()
            rec["score"] = round(float(score), 4)
            out.append(rec)
            if len(out) >= k:
                break
        return out

    def _retrieve_filtered(self, qvec: np.ndarray, intent: str, k: int) -> list[dict]:
        subset_idx = [i for i, r in enumerate(self._records) if r.get("intent") == intent]
        if not subset_idx:
            logger.debug(f"[PQA] Intent '{intent}' khong co sample, fallback global.")
            return self._retrieve_global(qvec, k)

        all_vecs = np.zeros((self._index.ntotal, self._index.d), dtype=np.float32)
        for i in range(self._index.ntotal):
            self._index.reconstruct(i, all_vecs[i])

        sub_vecs  = all_vecs[subset_idx]
        sub_index = faiss.IndexFlatIP(self._index.d)
        sub_index.add(sub_vecs)

        search_k        = min(k * 3, len(subset_idx))
        scores, loc_idx = sub_index.search(qvec, search_k)

        out = []
        for score, li in zip(scores[0], loc_idx[0]):
            if li < 0 or float(score) < self.score_threshold:
                continue
            rec = self._records[subset_idx[li]].copy()
            rec["score"] = round(float(score), 4)
            out.append(rec)
            if len(out) >= k:
                break

        if not out:
            logger.debug("[PQA] Intent filter miss, fallback global.")
            return self._retrieve_global(qvec, k)

        return out

    def _load_kb(self) -> list[dict]:
        records = []
        with open(self.kb_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info(f"[PQA] Loaded {len(records)} records tu {self.kb_path}")
        return records

    def set_shared_model(self, model) -> None:
        """Inject SentenceTransformer model tu VectorIndex de tranh load lan 2."""
        self._shared_model = model
        logger.info("[PQA] Using shared SentenceTransformer model.")

    def _get_model(self):
        if hasattr(self, "_shared_model") and self._shared_model is not None:
            return self._shared_model
        if self._model is None:
            logger.info(f"[PQA] Loading bge-m3 tren {self.device}...")
            self._model = FlagModel(
                self.model_name,
                use_fp16=(self.device == "cuda"),
                device=self.device,
            )
        return self._model

    def _embed_batch(self, model, texts: list[str]) -> np.ndarray:
        all_embs = []
        for i in range(0, len(texts), BATCH_EMBED):
            batch = texts[i : i + BATCH_EMBED]
            if hasattr(model, "encode"):
                # Thử với show_progress_bar trước, fallback nếu tokenizer không hỗ trợ
                try:
                    emb = model.encode(batch, batch_size=len(batch), show_progress_bar=False)
                except TypeError:
                    emb = model.encode(batch, batch_size=len(batch))
            else:
                emb = model.encode(batch, batch_size=len(batch))
            if not isinstance(emb, np.ndarray):
                emb = np.array(emb)
            all_embs.append(emb)
        return np.vstack(all_embs).astype(np.float32)

    @classmethod
    def load(
        cls,
        kb_path: str | Path = _DEFAULT_KB,
        index_dir: str | Path = _DEFAULT_IDX,
        **kwargs,
    ) -> "ProceduralQARetriever":
        obj = cls(kb_path=kb_path, index_dir=index_dir, **kwargs)
        obj.build_index(force_rebuild=False)
        obj.load_index()
        return obj
