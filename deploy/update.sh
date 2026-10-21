#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Scholaris — update an existing Oracle always-free deployment.
#
#   sudo bash /opt/scholaris/deploy/update.sh
#
# Pulls the latest main branch, reinstalls Python dependencies, rebuilds the
# frontend and restarts the service. Your access code, database and notes are
# untouched.
# ---------------------------------------------------------------------------
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/scholaris}"
SERVICE_USER="${SERVICE_USER:-scholaris}"
ENV_FILE="${ENV_FILE:-/etc/scholaris.env}"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "Scholaris is not installed at ${APP_DIR}. Run oracle-setup.sh first." >&2
  exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Run oracle-setup.sh first." >&2
  exit 1
fi

echo "==> Fetching the latest code"
runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" \
  git -C "${APP_DIR}" fetch --depth=1 origin main
runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" \
  git -C "${APP_DIR}" reset --hard FETCH_HEAD

echo "==> Installing Python dependencies"
runuser -u "${SERVICE_USER}" -- "${APP_DIR}/backend/.venv/bin/pip" install --quiet \
  -r "${APP_DIR}/backend/requirements.txt"

echo "==> Rebuilding the frontend"
runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" bash -lc \
  "cd '${APP_DIR}/frontend' && npm ci --no-audit --no-fund && npm run build"

echo "==> Restarting Scholaris"
systemctl restart scholaris

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    host="$(awk '/^[^[:space:]#]/ {print $1; exit}' /etc/caddy/Caddyfile)"
    echo "Updated. Check https://${host}"
    exit 0
  fi
  sleep 1
done

echo "The service did not become healthy. Check: journalctl -u scholaris -n 80 --no-pager" >&2
exit 1
