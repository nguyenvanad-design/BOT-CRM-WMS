# Tokinarc V6 — backend/Dockerfile
# Multi-stage: build deps tầng riêng để tận dụng layer cache.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps cần cho psycopg, pgvector, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài deps trước (tận dụng cache khi requirements không đổi)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy code
COPY . .

RUN python -m compileall -q apps tokinarc 2>/dev/null || true

EXPOSE 8000

# Production command (override trong docker-compose nếu dev)
CMD ["gunicorn", "tokinarc.wsgi:application", \
     "--workers", "3", "--threads", "4", "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-"]
