#!/usr/bin/env bash
# Tokinarc V6.B — scripts/backup.sh
# pg_dump nightly → MinIO bucket tokinarc-backup. WAL archive cho PITR cấu hình
# riêng trong postgresql.conf (archive_command). Gọi bởi cron (B.1 §6):
#   0 3 * * *  cd /app && bash scripts/backup.sh >> /var/log/tokinarc/backup.log 2>&1
set -euo pipefail

: "${PGHOST:?missing}" "${PGUSER:?missing}" "${PGDATABASE:?missing}" "${PGPASSWORD:?missing}"
: "${MINIO_BACKUP_ALIAS:=backup}"   # mc alias đã cấu hình trỏ tới MinIO
TS="$(date +%F_%H%M)"
DUMP_KEY="${MINIO_BACKUP_ALIAS}/tokinarc-backup/dump/tokinarc_${TS}.dump"

echo "[$(date -Is)] Bắt đầu backup → ${DUMP_KEY}"

# 1. Logical dump (custom format, nén sẵn). PGPASSWORD lấy từ env.
pg_dump -Fc -h "$PGHOST" -U "$PGUSER" "$PGDATABASE" \
  | mc pipe "$DUMP_KEY"

# 2. Dọn dump cũ hơn 30 ngày
mc rm --recursive --force --older-than 30d \
  "${MINIO_BACKUP_ALIAS}/tokinarc-backup/dump/" || true

# 3. Dọn WAL cũ hơn 14 ngày
mc rm --recursive --force --older-than 14d \
  "${MINIO_BACKUP_ALIAS}/tokinarc-backup/wal/" || true

echo "[$(date -Is)] ✅ Backup hoàn tất: ${DUMP_KEY}"

# ── Test restore (chạy thủ công/cron tháng trên staging) ──────────────────────
# mc cp backup/tokinarc-backup/dump/tokinarc_XXXX.dump /tmp/r.dump
# pg_restore -h staging -U tokinarc -d tokinarc_restore --clean /tmp/r.dump
# Sau đó replay WAL tới thời điểm mong muốn để xác nhận PITR.
