#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# NoteKey — Oracle Cloud VM setup script
# Supports both Oracle Linux 9 (dnf) and Ubuntu 22.04+ (apt)
#
# Usage:
#   sudo bash setup.sh <GITHUB_REPO_URL>
#
# Example:
#   sudo bash setup.sh https://github.com/Pojusammy/notekey.git
# ──────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="${1:?Usage: setup.sh <GITHUB_REPO_URL>}"

APP_DIR="/opt/notekey"
VENV_DIR="${APP_DIR}/venv"
SERVICE_USER="notekey"

# Detect package manager
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
else
    echo "ERROR: Neither dnf nor apt found" >&2
    exit 1
fi

echo "──── 1/7  System packages ($PKG_MGR) ────"
if [ "$PKG_MGR" = "dnf" ]; then
    # Oracle Linux 9 / RHEL 9
    dnf install -y oracle-epel-release-el9 || dnf install -y epel-release || true
    dnf install -y python3.11 python3.11-pip python3.11-devel \
        nginx certbot python3-certbot-nginx ffmpeg git \
        gcc gcc-c++ libffi-devel
    # Open firewall ports
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
else
    # Ubuntu / Debian
    apt-get update && apt-get upgrade -y
    apt-get install -y python3.11 python3.11-venv python3-pip \
        nginx certbot python3-certbot-nginx ffmpeg git
fi

echo "──── 2/7  Service user ────"
id -u "$SERVICE_USER" &>/dev/null || useradd -r -s /bin/false -m -d "$APP_DIR" "$SERVICE_USER"
mkdir -p "$APP_DIR"
chown "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

echo "──── 3/7  Clone repo ────"
if [ -d "${APP_DIR}/.git" ]; then
    sudo -u "$SERVICE_USER" git -C "$APP_DIR" pull
else
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "──── 4/7  Python venv + deps ────"
sudo -u "$SERVICE_USER" python3.11 -m venv "$VENV_DIR"
sudo -u "$SERVICE_USER" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "${VENV_DIR}/bin/pip" install --no-cache-dir \
    -r "${APP_DIR}/backend/requirements.txt"

echo "──── 5/7  Environment file ────"
ENV_FILE="${APP_DIR}/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    sudo -u "$SERVICE_USER" cp "${APP_DIR}/backend/.env.example" "$ENV_FILE"
    echo ""
    echo "  ⚠  Edit ${ENV_FILE} with your Supabase credentials before starting!"
    echo "     nano ${ENV_FILE}"
    echo ""
fi

echo "──── 6/7  systemd service ────"
cp "${APP_DIR}/deploy/notekey-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable notekey-api

echo "──── 7/7  Nginx ────"
# Basic HTTP config (certbot will upgrade to HTTPS later)
cat > /etc/nginx/conf.d/notekey.conf <<'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }
}
NGINX

# Remove default configs that conflict
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true

# SELinux: allow Nginx to connect to upstream
if command -v setsebool &>/dev/null; then
    setsebool -P httpd_can_network_connect 1 || true
fi

nginx -t && systemctl enable --now nginx && systemctl reload nginx

echo ""
echo "════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit ${ENV_FILE} with your Supabase credentials"
echo "  2. Start the API:  sudo systemctl start notekey-api"
echo "  3. Verify:         curl http://localhost:8000/health"
echo "════════════════════════════════════════════════"
