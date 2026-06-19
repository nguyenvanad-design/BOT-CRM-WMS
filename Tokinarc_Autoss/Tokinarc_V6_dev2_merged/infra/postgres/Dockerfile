# Tokinarc V6.C-fix — infra/postgres/Dockerfile
#
# FIX BUG V6.B: image postgres:16 chính chủ KHÔNG có `mc` (MinIO client).
# `archive_command='mc pipe ...'` trong docker-compose.yml → WAL archive
# silently fail (do `|| true`). Hệ quả: PITR claim trên giấy, thực tế
# KHÔNG khôi phục được tới điểm thời gian — chỉ có nightly dump.
#
# Image này thêm `mc` binary, fix gốc nguyên nhân.

FROM postgres:16

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && curl -fL https://dl.min.io/client/mc/release/linux-amd64/mc \
       -o /usr/local/bin/mc \
 && chmod +x /usr/local/bin/mc \
 && apt-get remove -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Healthcheck script kiểm tra `mc` cũng sẵn sàng (cấu hình alias chạy ở
# entrypoint custom — xem entrypoint.sh nếu cần thêm setup).
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD pg_isready -U $POSTGRES_USER -d $POSTGRES_DB && which mc
