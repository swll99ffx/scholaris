#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Scholaris — one-command setup for an Oracle Cloud Always Free Ubuntu VM.
#
# Usage (on the server, as root):
#   sudo PUBLIC_HOST=203.0.113.10.sslip.io bash oracle-setup.sh
#
# The script asks for the site access code (or accepts SITE_PASSWORD from the
# environment). It installs Python, Node and Caddy, builds the frontend, and
# runs the app as a systemd service behind automatic HTTPS.
# Safe to re-run: it updates the code and rebuilds.
# ---------------------------------------------------------------------------
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/swll99ffx/scholaris.git}"
APP_DIR="${APP_DIR:-/opt/scholaris}"
DATA_DIR="${DATA_DIR:-/var/lib/scholaris}"
ENV_FILE="${ENV_FILE:-/etc/scholaris.env}"
SERVICE_USER="${SERVICE_USER:-scholaris}"
NODE_VERSION="${NODE_VERSION:-22.14.0}"
PUBLIC_HOST="${PUBLIC_HOST:-}"
SITE_PASSWORD="${SITE_PASSWORD:-}"
CONTACT_EMAIL="${CONTACT_EMAIL:-}"
LLM_API_KEY="${LLM_API_KEY:-}"

if [[ -z "${PUBLIC_HOST}" ]]; then
  read -r -p "Public hostname (for example 203.0.113.10.sslip.io): " PUBLIC_HOST
fi
PUBLIC_HOST="${PUBLIC_HOST#http://}"
PUBLIC_HOST="${PUBLIC_HOST#https://}"
PUBLIC_HOST="${PUBLIC_HOST%/}"
if [[ -z "${PUBLIC_HOST}" ]]; then
  echo "A public hostname is required." >&2
  exit 1
fi
if [[ "${PUBLIC_HOST}" =~ ^[0-9.]+$ ]]; then
  echo "Use a hostname, not a bare IP: <public-ip>.sslip.io" >&2
  exit 1
fi

NEW_ENV=0
if [[ ! -f "${ENV_FILE}" ]]; then
  NEW_ENV=1
fi
if [[ ${NEW_ENV} -eq 1 && -z "${SITE_PASSWORD}" ]]; then
  read -r -s -p "Access code for the site (min 8 characters): " SITE_PASSWORD
  echo
fi
if [[ ${NEW_ENV} -eq 1 && ${#SITE_PASSWORD} -lt 8 ]]; then
  echo "Use at least 8 characters for the access code." >&2
  exit 1
fi

systemd_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "${value}"
}

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates caddy curl git python3 python3-pip python3-venv \
  sqlite3 xz-utils

# A 1 GB AMD micro needs a little swap for the frontend build.
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [[ "${mem_kb:-0}" -lt 2000000 && ! -f /swapfile ]]; then
  echo "==> Adding a 2 GB swap file (low-memory instance)"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

echo "==> Installing Node.js ${NODE_VERSION} (for the frontend build)"
node_major="$(node -v 2>/dev/null | sed 's/^v//; s/\..*$//' || true)"
if [[ -z "${node_major}" ]] || [[ "${node_major}" -lt 20 ]]; then
  case "$(uname -m)" in
    x86_64) node_arch="x64" ;;
    aarch64 | arm64) node_arch="arm64" ;;
    *)
      echo "Unsupported CPU architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
  node_tmp="$(mktemp -d)"
  curl -fsSL \
    "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
    -o "${node_tmp}/node.tar.xz"
  tar -xJf "${node_tmp}/node.tar.xz" -C /usr/local --strip-components=1
  rm -rf "${node_tmp}"
fi

echo "==> Preparing the service account and directories"
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
install -d -m 0755 "${APP_DIR}"
install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DATA_DIR}"

echo "==> Fetching Scholaris"
if [[ -d "${APP_DIR}/.git" ]]; then
  runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" \
    git -C "${APP_DIR}" fetch --depth=1 origin main
  runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" \
    git -C "${APP_DIR}" reset --hard FETCH_HEAD
else
  git clone --depth=1 "${REPO_URL}" "${APP_DIR}"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
fi

echo "==> Installing Python dependencies"
if [[ ! -x "${APP_DIR}/backend/.venv/bin/python" ]]; then
  runuser -u "${SERVICE_USER}" -- python3 -m venv "${APP_DIR}/backend/.venv"
fi
runuser -u "${SERVICE_USER}" -- "${APP_DIR}/backend/.venv/bin/pip" install --quiet --upgrade pip
runuser -u "${SERVICE_USER}" -- "${APP_DIR}/backend/.venv/bin/pip" install --quiet \
  -r "${APP_DIR}/backend/requirements.txt"

echo "==> Building the frontend"
runuser -u "${SERVICE_USER}" -- env HOME="/home/${SERVICE_USER}" bash -lc \
  "cd '${APP_DIR}/frontend' && npm ci --no-audit --no-fund && npm run build"

echo "==> Writing ${ENV_FILE}"
if [[ ${NEW_ENV} -eq 1 || -n "${SITE_PASSWORD}" ]]; then
  umask 077
  {
    printf 'SITE_PASSWORD=%s\n' "$(systemd_quote "${SITE_PASSWORD}")"
    printf 'SESSION_TTL_SECONDS=2592000\n'
    printf 'APP_ENV=production\n'
    printf 'DATABASE_PATH=%s\n' "$(systemd_quote "${DATA_DIR}/library.sqlite3")"
    if [[ -n "${CONTACT_EMAIL}" ]]; then
      printf 'CONTACT_EMAIL=%s\n' "$(systemd_quote "${CONTACT_EMAIL}")"
    fi
    if [[ -n "${LLM_API_KEY}" ]]; then
      printf 'LLM_API_KEY=%s\n' "$(systemd_quote "${LLM_API_KEY}")"
    fi
  } >"${ENV_FILE}"
  chown root:root "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  NEW_ENV=0
fi

echo "==> Writing the systemd service"
cat >/etc/systemd/system/scholaris.service <<EOF
[Unit]
Description=Scholaris study assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/backend/.venv/bin/python -m uvicorn app.main:app \\
  --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring Caddy (automatic HTTPS)"
cat >/etc/caddy/Caddyfile <<EOF
${PUBLIC_HOST} {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF

systemctl daemon-reload
systemctl enable scholaris
systemctl restart scholaris
systemctl enable caddy
systemctl restart caddy

echo "==> Waiting for the app"
for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "The app did not start. Check: journalctl -u scholaris -n 80 --no-pager" >&2
  exit 1
fi

echo "==> Waiting for the HTTPS certificate"
for _ in $(seq 1 30); do
  if curl -fsS --resolve "${PUBLIC_HOST}:443:127.0.0.1" \
    "https://${PUBLIC_HOST}/api/health" >/dev/null 2>&1; then
    echo
    echo "Scholaris is live: https://${PUBLIC_HOST}"
    echo "Access code: the one you entered (stored in ${ENV_FILE})."
    echo "Logs: journalctl -u scholaris -f"
    exit 0
  fi
  sleep 2
done

echo
echo "The app is running on the VM, but HTTPS is not ready yet."
echo "Check ports 80/443 in the Oracle security list, then run:"
echo "  sudo systemctl status caddy"
echo "  curl -I https://${PUBLIC_HOST}/api/health"
exit 1
