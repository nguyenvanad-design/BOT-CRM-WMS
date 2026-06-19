#!/usr/bin/env bash
# Tokinarc V6.C-fix — infra/scripts/gen_keys.sh
#
# Sinh cặp RSA cho JWT RS256. Chạy 1 lần khi setup môi trường:
#   bash infra/scripts/gen_keys.sh
# Output: infra/secrets/jwt_private.pem + infra/secrets/jwt_public.pem
#
# Docker compose mount 2 file này vào /run/secrets/jwt_{private,public}.
# QUAN TRỌNG: KHÔNG commit secrets/ vào git — đã có .gitignore.
set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "$0")/../secrets" && pwd)"
mkdir -p "$SECRETS_DIR"

PRIV="$SECRETS_DIR/jwt_private.pem"
PUB="$SECRETS_DIR/jwt_public.pem"

if [[ -f "$PRIV" || -f "$PUB" ]]; then
  echo "❌ Key đã tồn tại tại $SECRETS_DIR/. Xóa thủ công nếu muốn tạo lại."
  exit 1
fi

echo "[gen_keys] Tạo RSA private key (2048 bit)..."
openssl genrsa -out "$PRIV" 2048 2>/dev/null

echo "[gen_keys] Trích xuất public key..."
openssl rsa -in "$PRIV" -pubout -out "$PUB" 2>/dev/null

chmod 600 "$PRIV"
chmod 644 "$PUB"

echo "✅ Đã sinh:"
echo "   $PRIV  (mode 600 — KHÔNG commit)"
echo "   $PUB   (mode 644 — KHÔNG commit)"
echo ""
echo "Tiếp:"
echo "  1. docker compose lên: postgres + Django đọc key này qua secrets"
echo "  2. Test JWKS: curl https://<host>/.well-known/jwks.json"
echo "  3. Rotate sau 90 ngày — bump JWT_KID env, regenerate."
