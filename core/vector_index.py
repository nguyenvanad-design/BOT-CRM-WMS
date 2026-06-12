"""

vector_index.py — TOKINARC Phase 6 Vector DB + Rerank

======================================================

Model    : BAAI/bge-m3  (dense retrieval bi-encoder)

Reranker : cross-encoder/ms-marco-MiniLM-L-6-v2  (cross-encoder, optional)

DB       : FAISS IndexFlatIP (inner-product = cosine sau normalize)

Persist  : tokinarc_faiss.index + tokinarc_chunks.pkl

Path     : botautoss root



THAY ĐỔI Phase 6:

  + Thêm class CrossReranker (cross-encoder rerank)

  + VectorIndex.search() tự rerank candidates trước khi trả về

  + Constructor có flag use_reranker (default True, graceful fallback nếu fail)

  + KHÔNG đổi signature search() / search_parts() / search_torches()

    → query_engine.py không cần sửa gì



Pipeline mới trong search():

  query → bge-m3 embed → FAISS top-(k×5) → CrossEncoder rerank → top-k



Cài thêm (nếu chưa có):

  pip install sentence-transformers

"""



import os

import json

import pickle

import time

import logging

from pathlib import Path

from typing import Optional



import faiss

import numpy as np

from sentence_transformers import SentenceTransformer



logger = logging.getLogger("tokinarc.vector_index")



# ── Config ────────────────────────────────────────────────────────────────────

ROOT          = Path(__file__).parent.parent

# FIX (restructure 2026-06): default cũ trỏ tokinarc_data_v11l.json (file đã
# bị xóa) → ủy quyền cho data_store resolve (env TOKINARC_DATA > version cao
# nhất trong data/).
def _default_data_file() -> Path:
    try:
        from core.data_store import _resolve_data_path
        return Path(_resolve_data_path())
    except Exception:
        return ROOT / "data" / "tokinarc_data_v19.json"

DATA_FILE     = _default_data_file()

INDEX_FILE    = ROOT / "indexes" / "tokinarc_faiss.index"

CHUNKS_FILE   = ROOT / "indexes" / "tokinarc_chunks.pkl"

MODEL_NAME    = "BAAI/bge-m3"

# FIX (restructure 2026-06): hardcode "cuda" cũ crash trên máy không có GPU
# (sentence-transformers raise khi torch không thấy CUDA).
def _detect_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

DEVICE        = os.environ.get("TOKINARC_DEVICE", "") or _detect_device()

TOP_K         = 10



# Reranker model — đọc từ env var để A/B test dễ.

# Default ms-marco; đổi qua env: TOKINARC_RERANK_MODEL=BAAI/bge-reranker-v2-m3

RERANK_MODEL  = os.environ.get(

    "TOKINARC_RERANK_MODEL",

    "cross-encoder/ms-marco-MiniLM-L-6-v2",

)



# Rerank: lấy nhiều candidate từ FAISS rồi rerank xuống top_k

# pool size = top_k × RERANK_POOL_MULT

RERANK_POOL_MULT = 5

RERANK_POOL_MAX  = 40   # cap để tránh cross-encoder chậm





# ══════════════════════════════════════════════════════════════════════════════

# CROSS-ENCODER RERANKER

# ══════════════════════════════════════════════════════════════════════════════



class CrossReranker:

    """

    Cross-encoder rerank cho FAISS candidates.



    Bi-encoder (bge-m3) encode query và doc riêng rồi dot product — nhanh,

    pre-compute được, nhưng interaction yếu.

    Cross-encoder encode cặp (query, doc) cùng nhau — chính xác hơn nhiều,

    nhưng không pre-compute được nên chỉ dùng để rerank top-N.



    Benchmark RTX 2060S:

      20 pairs → ~3ms  (cuda)

      20 pairs → ~60ms (cpu)

    """



    def __init__(self, model_name: str = RERANK_MODEL, device: str = DEVICE):

        from sentence_transformers import CrossEncoder

        logger.info(f"[CrossReranker] Loading '{model_name}' on {device}...")

        t0 = time.time()

        self._model = CrossEncoder(model_name, device=device)

        self._device = device

        logger.info(f"[CrossReranker] Ready in {time.time()-t0:.1f}s")



    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:

        """

        Sắp xếp lại candidates theo relevance với query.



        candidates: list of search-result dicts (mỗi dict có key 'text').

        Trả về top_k đã sort. Lỗi → fallback candidates[:top_k].

        """

        if not candidates:

            return candidates



        pool = candidates[:RERANK_POOL_MAX]

        try:

            pairs  = [[query, c.get("text", "")] for c in pool]

            scores = self._model.predict(pairs)

            ranked = sorted(

                zip(scores, pool),

                key=lambda x: float(x[0]),

                reverse=True,

            )

            # Gắn rerank_score vào kết quả để debug / explanation

            out = []

            for s, c in ranked[:top_k]:

                c = dict(c)

                c["rerank_score"] = float(s)

                out.append(c)

            return out

        except Exception as e:

            logger.warning(f"[CrossReranker] Fallback (error: {e})")

            return candidates[:top_k]



    def __repr__(self) -> str:

        return f"CrossReranker(device='{self._device}')"





# ══════════════════════════════════════════════════════════════════════════════

# CHUNK BUILDERS  (không đổi so với Phase 5)

# ══════════════════════════════════════════════════════════════════════════════



def build_torch_chunk(t: dict) -> dict:

    """Tạo text chunk cho 1 torch."""

    parts_preview = ", ".join(t.get("compatible_parts", [])[:8])

    if len(t.get("compatible_parts", [])) > 8:

        parts_preview += f" ... (+{len(t['compatible_parts'])-8} more)"



    conn = ", ".join(t.get("connection_types", []))

    price = t.get("business", {}).get("price_vnd", 0)

    priority = t.get("business", {}).get("is_priority_sell", False)



    text = (

        f"Torch model: {t['model_code']}. "

        f"Family: {t.get('family', '')}. "

        f"Current class: {t.get('current_class', '')}. "

        f"Ecosystem: {t.get('ecosystem', '')}. "

        f"Cooling: {t.get('cooling', '')}. "

        f"Rated CO2: {t.get('rated_co2_a', '')}A, MAG: {t.get('rated_mag_a', '')}A. "

        f"Duty cycle: {t.get('duty_cycle_pct', '')}%. "

        f"Wire size: {t.get('wire_size', '')}. "

        f"Body type: {t.get('body_type', '')}. "

        f"Mounting: {t.get('mounting', '')}. "

        f"Connection types: {conn}. "

        f"Shock sensor: {t.get('shock_sensor_type', 'NONE')}. "

        f"Compatible parts: {parts_preview}. "

        f"Note: {t.get('note', '')}. "

        f"Price: {price:,} VND. Priority sell: {priority}."

    )

    return {

        "type": "torch",

        "id": t["model_code"],

        "text": text,

        "data": {k: v for k, v in t.items() if k != "compatible_parts"},

        "compatible_parts": t.get("compatible_parts", []),

    }





def build_part_chunk(p: dict) -> dict:

    """Tạo text chunk cho 1 part."""

    torches = ", ".join(p.get("torch_models", [])[:6])

    if len(p.get("torch_models", [])) > 6:

        torches += f" ... (+{len(p['torch_models'])-6} more)"



    used_with = ", ".join(p.get("used_with", []))

    price = (p.get("business") or {}).get("price_vnd") or 0



    # Tên hiển thị ưu tiên tiếng Việt

    name_vi = p.get("display_name_vi", "")

    name_en = p.get("display_name_en", "")

    display = f"{name_vi} / {name_en}" if name_vi else name_en



    # Wire size
    wire_str = ""
    if p.get("wire_size_mm"):
        wire_str = f"{p['wire_size_mm']}mm"
    elif p.get("wire_size_range"):
        wsr = p["wire_size_range"]
        if isinstance(wsr, dict):
            wire_str = f"{wsr.get('min','')}-{wsr.get('max','')}mm"
        else:
            wire_str = str(wsr)
    # Dimensions
    dims = []
    if p.get("inner_dia_mm"):    dims.append(f"phi {p['inner_dia_mm']}mm")
    if p.get("length_mm"):       dims.append(f"{p['length_mm']}L")
    if p.get("total_length_mm"): dims.append(f"{p['total_length_mm']}L")
    if p.get("liner_length_mm"): dims.append(f"{p['liner_length_mm']}mm")
    type_str = p.get("tip_type","") or p.get("nozzle_type","") or ""
    mat_str  = p.get("material","") or p.get("liner_material","") or ""
    eco_vn   = {"N":"he N Panasonic","D":"he D Daihen","WX":"he WX","TIG":"TIG"}.get(p.get("ecosystem",""),"")
    text = (
        f"Part number: {p['tokin_part_no']}. "
        f"Name: {display}. "
        f"Category: {p.get('category', '')}. "
        f"Ecosystem: {p.get('ecosystem', '')} {eco_vn}. "
        f"Current class: {p.get('current_class', '')}. "
        f"Wire size: {wire_str}. "
        f"Dimensions: {' '.join(dims)}. "
        f"Type: {type_str}. "
        f"Material: {mat_str}. "
        f"Used with: {used_with}. "
        f"Compatible torches: {torches}. "
        f"Note: {p.get('note', '')}. "
        f"Price: {price:,} VND."
    )

    return {

        "type": "part",

        "id": p["tokin_part_no"],

        "text": text,

        "data": {k: v for k, v in p.items()

                 if k not in ("torch_models", "used_with", "compatible_with")},

        "torch_models": p.get("torch_models", []),

    }





def build_consumable_set_chunk(cs: dict) -> dict:

    """Tạo text chunk cho 1 consumable set."""

    parts = ", ".join(cs.get("parts", []))

    torch_list = ", ".join(cs.get("compatible_torches", [])[:6])

    text = (

        f"Consumable set: {cs.get('set_id', '')}. "

        f"Name: {cs.get('name', '')}. "

        f"Ecosystem: {cs.get('ecosystem', '')}. "

        f"Parts included: {parts}. "

        f"Compatible torches: {torch_list}. "

        f"Note: {cs.get('note', '')}."

    )

    return {

        "type": "consumable_set",

        "id": cs.get("set_id", ""),

        "text": text,

        "data": cs,

        "torch_models": cs.get("compatible_torches", []),

    }





# ══════════════════════════════════════════════════════════════════════════════

# INDEX BUILDER  (không đổi so với Phase 5)

# ══════════════════════════════════════════════════════════════════════════════



def build_index(data_file: Path = DATA_FILE) -> tuple[faiss.Index, list[dict]]:

    """Load JSON, tạo chunks, embed với bge-m3, build FAISS index."""

    print(f"[1/4] Loading data from {data_file.name}...")

    with open(data_file, encoding="utf-8") as f:

        data = json.load(f)



    torches  = data.get("torches", [])

    parts    = data.get("parts", [])

    con_sets = data.get("consumable_sets", [])

    print(f"      Torches: {len(torches)}, Parts: {len(parts)}, "

          f"Consumable sets: {len(con_sets)}")



    # Build chunks

    chunks: list[dict] = []

    for t in torches:

        chunks.append(build_torch_chunk(t))

    for p in parts:

        chunks.append(build_part_chunk(p))

    for cs in con_sets:

        chunks.append(build_consumable_set_chunk(cs))

    print(f"      Total chunks: {len(chunks)}")



    # Load model

    print(f"\n[2/4] Loading {MODEL_NAME} on {DEVICE}...")

    t0 = time.time()

    model = SentenceTransformer(MODEL_NAME, device=DEVICE)

    print(f"      Model loaded in {time.time()-t0:.1f}s")



    # Embed

    print(f"\n[3/4] Embedding {len(chunks)} chunks (batch_size=32)...")

    t0 = time.time()

    texts = [c["text"] for c in chunks]

    embeddings = model.encode(

        texts,

        batch_size=32,

        show_progress_bar=True,

        normalize_embeddings=True,   # chuẩn hóa để IP = cosine

        convert_to_numpy=True,

    )

    print(f"      Embedding done in {time.time()-t0:.1f}s, shape={embeddings.shape}")



    # Build FAISS

    print(f"\n[4/4] Building FAISS IndexFlatIP (dim={embeddings.shape[1]})...")

    dim   = embeddings.shape[1]

    index = faiss.IndexFlatIP(dim)

    index.add(embeddings.astype(np.float32))

    print(f"      Index built. Total vectors: {index.ntotal}")



    return index, chunks





def save_index(index: faiss.Index, chunks: list[dict],

               index_file: Path = INDEX_FILE, chunks_file: Path = CHUNKS_FILE):

    faiss.write_index(index, str(index_file))

    with open(chunks_file, "wb") as f:

        pickle.dump(chunks, f)

    print(f"\n✅ Saved: {index_file.name} ({index_file.stat().st_size/1024:.1f} KB)")

    print(f"✅ Saved: {chunks_file.name} ({chunks_file.stat().st_size/1024:.1f} KB)")





def load_index(index_file: Path = INDEX_FILE,

               chunks_file: Path = CHUNKS_FILE) -> tuple[faiss.Index, list[dict]]:

    t0 = time.time()

    index  = faiss.read_index(str(index_file))

    with open(chunks_file, "rb") as f:

        chunks = pickle.load(f)

    print(f"[load_index] {index.ntotal} vectors loaded in {time.time()-t0:.2f}s")

    return index, chunks





# ══════════════════════════════════════════════════════════════════════════════

# QUERY  +  RERANK

# ══════════════════════════════════════════════════════════════════════════════



class VectorIndex:

    """

    Wrapper dùng trong query_engine.py.



    Usage (giữ nguyên — không đổi so với Phase 5):

        vi = VectorIndex()

        results = vi.search("béc hàn TK-308RR", top_k=5)



    Phase 6: thêm rerank tự động bên trong search().

        vi = VectorIndex(use_reranker=True)   # default

        vi = VectorIndex(use_reranker=False)  # tắt rerank, hành vi như Phase 5



    Pipeline search():

        query → bge-m3 embed → FAISS top-(k×5) → CrossEncoder rerank → top-k

    """



    def __init__(self, auto_build: bool = True,

                 use_reranker: Optional[bool] = None,

                 rerank_device: str = DEVICE):

        # use_reranker=None → đọc env var TOKINARC_RERANK (default bật).

        # Truyền True/False trực tiếp để override env var.

        if use_reranker is None:

            use_reranker = os.environ.get("TOKINARC_RERANK", "1") == "1"



        self._model: Optional[SentenceTransformer] = None

        self._index: Optional[faiss.Index] = None

        self._chunks: Optional[list[dict]] = None

        self._reranker: Optional[CrossReranker] = None

        self._use_reranker = use_reranker

        self._rerank_device = rerank_device



        # Load FAISS index

        if INDEX_FILE.exists() and CHUNKS_FILE.exists():

            self._index, self._chunks = load_index()

        elif auto_build:

            print("[VectorIndex] Index not found — building from scratch...")

            self._index, self._chunks = build_index()

            save_index(self._index, self._chunks)

        else:

            raise FileNotFoundError(

                "Index not found. Run vector_index.py directly to build."

            )



        # Load reranker (lazy-safe: nếu fail thì tắt, không crash)

        if use_reranker:

            try:

                self._reranker = CrossReranker(device=rerank_device)

            except Exception as e:

                print(f"[VectorIndex] Reranker disabled (load failed: {e})")

                self._reranker = None

                self._use_reranker = False



    def _get_model(self) -> SentenceTransformer:

        if self._model is None:

            print(f"[VectorIndex] Loading model {MODEL_NAME}...")

            self._model = SentenceTransformer(MODEL_NAME, device=DEVICE)

        return self._model



    def search(self, query: str, top_k: int = TOP_K,

               filter_type: Optional[str] = None,

               rerank: Optional[bool] = None) -> list[dict]:

        """

        Tìm kiếm vector + rerank.



        Args:

            query       : câu query

            top_k       : số kết quả cuối cùng

            filter_type : 'torch' | 'part' | 'consumable_set' | None (all)

            rerank      : None = dùng setting mặc định của instance;

                          True/False = override cho lần gọi này



        Pipeline:

            1. bge-m3 embed query

            2. FAISS search top-(k × RERANK_POOL_MULT)  ← lấy dư để rerank

            3. lọc filter_type

            4. CrossEncoder rerank pool → top_k  (nếu bật)



        Trả về: list of dicts {score, rerank_score?, type, id, text, data, ...}

        Kết quả vẫn sort theo relevance — query_engine.py không cần đổi gì.

        """

        do_rerank = self._use_reranker if rerank is None else rerank

        do_rerank = do_rerank and (self._reranker is not None)



        model = self._get_model()

        q_vec = model.encode(

            [query],

            normalize_embeddings=True,

            convert_to_numpy=True,

        ).astype(np.float32)



        # Lấy pool lớn hơn top_k để rerank có không gian sắp xếp

        if do_rerank:

            pool_k = min(top_k * RERANK_POOL_MULT, RERANK_POOL_MAX)

        else:

            pool_k = top_k

        # Nếu có filter thì cần lấy thêm vì sẽ bị lọc bớt

        search_k = pool_k * 5 if filter_type else pool_k



        scores, indices = self._index.search(q_vec, search_k)



        # Gom candidates (đã lọc filter_type)

        candidates: list[dict] = []

        for score, idx in zip(scores[0], indices[0]):

            if idx < 0:

                continue

            chunk = self._chunks[idx]

            if filter_type and chunk["type"] != filter_type:

                continue

            candidates.append({

                "score": float(score),   # FAISS cosine score

                **chunk,

            })

            if len(candidates) >= pool_k:

                break



        # Rerank pool → top_k

        if do_rerank and candidates:

            return self._reranker.rerank(query, candidates, top_k=top_k)

        return candidates[:top_k]



    def search_torches(self, query: str, top_k: int = 5) -> list[dict]:

        return self.search(query, top_k=top_k, filter_type="torch")



    def search_parts(self, query: str, top_k: int = 5) -> list[dict]:

        return self.search(query, top_k=top_k, filter_type="part")





# ══════════════════════════════════════════════════════════════════════════════

# CLI: build index / test

# ══════════════════════════════════════════════════════════════════════════════



if __name__ == "__main__":

    import argparse



    parser = argparse.ArgumentParser(description="TOKINARC Vector Index Builder")

    parser.add_argument("--rebuild", action="store_true",

                        help="Force rebuild even if index exists")

    parser.add_argument("--query", type=str, default="",

                        help="Test query after build")

    parser.add_argument("--no-rerank", action="store_true",

                        help="Tắt rerank khi test query")

    parser.add_argument("--compare", action="store_true",

                        help="So sánh kết quả có rerank vs không rerank")

    args = parser.parse_args()



    if args.rebuild or not INDEX_FILE.exists():

        index, chunks = build_index()

        save_index(index, chunks)

    else:

        print(f"Index already exists ({INDEX_FILE}). Use --rebuild to force.")

        index, chunks = load_index()



    # Test query

    if args.query:

        logging.basicConfig(level=logging.INFO)



        if args.compare:

            # So sánh side-by-side

            print(f"\n🔍 Compare query: '{args.query}'\n")

            vi = VectorIndex(auto_build=False, use_reranker=True)

            vi._model = SentenceTransformer(MODEL_NAME, device=DEVICE)

            vi._index = index

            vi._chunks = chunks



            no_rr = vi.search(args.query, top_k=5, rerank=False)

            with_rr = vi.search(args.query, top_k=5, rerank=True)



            print(f"{'NO RERANK (bge-m3 only)':<40} | {'WITH RERANK (cross-encoder)'}")

            print("-" * 85)

            for i in range(5):

                a = no_rr[i] if i < len(no_rr) else None

                b = with_rr[i] if i < len(with_rr) else None

                a_str = f"{a['id']:20s} {a['score']:.3f}" if a else ""

                b_str = (f"{b['id']:20s} rr={b.get('rerank_score',0):.2f}"

                         if b else "")

                print(f"  [{i+1}] {a_str:<36} | {b_str}")

        else:

            print(f"\n🔍 Test query: '{args.query}' "

                  f"(rerank={'OFF' if args.no_rerank else 'ON'})")

            vi = VectorIndex(auto_build=False, use_reranker=not args.no_rerank)

            vi._model = SentenceTransformer(MODEL_NAME, device=DEVICE)

            vi._index = index

            vi._chunks = chunks



            results = vi.search(args.query, top_k=5,

                                rerank=not args.no_rerank)

            for i, r in enumerate(results):

                rr = (f" rerank={r['rerank_score']:.3f}"

                      if "rerank_score" in r else "")

                print(f"  [{i+1}] faiss={r['score']:.4f}{rr} | "

                      f"{r['type']:15s} | {r['id']:20s}")

                print(f"       {r['text'][:120]}...")



