#!/usr/bin/env bash
# Tokinarc V6.C-fix — infra/scripts/worker_entrypoint.sh
#
# Khởi 2 background process trong worker container:
#   1. LISTEN/NOTIFY listener — process events từ Postgres
#   2. Cron — định kỳ refresh MV, critic batch, promote golden, backup
#
# Khi listener crash, restart sau 5s. Không để worker im lặng chết.
set -euo pipefail

cd /app

# ── 1. Cron jobs ─────────────────────────────────────────────────────────────
echo "0 * * * * cd /app && python manage.py refresh_mv --group=hourly >> /var/log/refresh_mv.log 2>&1"  > /tmp/crontab
echo "5 0 * * * cd /app && python manage.py refresh_mv --group=daily  >> /var/log/refresh_mv.log 2>&1" >> /tmp/crontab
echo "0 * * * * cd /app && python manage.py run_critic_batch          >> /var/log/critic.log 2>&1"     >> /tmp/crontab
echo "5 * * * * cd /app && python manage.py promote_golden            >> /var/log/promote.log 2>&1"    >> /tmp/crontab

if command -v crontab > /dev/null; then
  crontab /tmp/crontab
  service cron start || cron
  echo "[entrypoint] cron started"
else
  echo "[entrypoint] WARN: crontab không có — bỏ qua scheduled jobs"
fi

# ── 2. LISTEN/NOTIFY listener (long-running) ─────────────────────────────────
echo "[entrypoint] starting eventbus listener..."
while true; do
  python manage.py run_eventbus_listener || {
    echo "[entrypoint] listener crashed, restart sau 5s..."
    sleep 5
  }
done
