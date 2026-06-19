# Tokinarc V6 — chatbot/Dockerfile (chatbot THẬT v8.0)
# FastAPI + Gemini function-calling + retrieval (FAISS/BM25/PQA) + vision.
# Khác bản sidecar cũ: cần torch + sentence-transformers + faiss, và bundle
# sẵn data/ + indexes/ vào image. Model embedding BAAI/bge-m3 tải runtime
# (cache vào /root/.cache/huggingface — mount volume nếu muốn tránh tải lại).

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

# build-essential cho rank-bm25/faiss wheels; curl cho healthcheck; git cho HF.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài deps trước (layer cache). torch CPU theo requirements; nếu cần GPU,
# build với base image CUDA + cài torch cu124 (xem ghi chú trong requirements.txt).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy toàn bộ chatbot (core/, data/, indexes/, main.py, vision_*, ...)
COPY . .

EXPOSE 8080

# Chatbot thật chạy uvicorn main:app port 8080 (khớp main.py __main__).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--log-level", "info"]
