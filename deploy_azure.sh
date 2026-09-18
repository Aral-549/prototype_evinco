#!/usr/bin/env bash
# ==============================================================================
# MarSlick (SIH 26143) — Automated Azure VM Production Deployment Script
# Tested on Ubuntu 22.04 / 24.04 LTS (x64)
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}       MarSlick SIH26143 — Automated Azure VM Deployment          ${NC}"
echo -e "${BLUE}==================================================================${NC}"

# 1. Require root / sudo
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[ERROR] This script must be run with sudo: sudo ./deploy_azure.sh${NC}" 
   exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"

echo -e "\n${YELLOW}[Step 1/7] Updating system packages and installing dependencies...${NC}"
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    git \
    nginx

# 2. Install Node.js 20 LTS if not present or too old
if ! command -v node &> /dev/null || [[ $(node -v | cut -d'.' -f1 | tr -d 'v') -lt 18 ]]; then
    echo -e "\n${YELLOW}[Step 2/7] Installing Node.js 20 LTS...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
else
    echo -e "\n${GREEN}[Step 2/7] Node.js is already installed ($(node -v)).${NC}"
fi

# 3. Setup Python Virtual Environment for Backend
echo -e "\n${YELLOW}[Step 3/7] Setting up Python backend virtualenv and PyTorch...${NC}"
VENV_PATH="${PROJECT_DIR}/.venv"
if [[ ! -d "$VENV_PATH" ]]; then
    sudo -u "$TARGET_USER" python3 -m venv "$VENV_PATH"
fi

# Pre-install CPU-optimized PyTorch wheels to prevent downloading 2.5GB CUDA packages
sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install --no-cache-dir --upgrade pip
sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install backend dependencies
sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install --no-cache-dir -r "${PROJECT_DIR}/backend/requirements.txt"

# 4. Run Django Migrations, Seed Demo Data, and Collect Static Files
echo -e "\n${YELLOW}[Step 4/7] Preparing database and static assets...${NC}"
mkdir -p "${PROJECT_DIR}/backend/media" "${PROJECT_DIR}/backend/staticfiles"
chown -R "$TARGET_USER:$TARGET_USER" "${PROJECT_DIR}/backend/media" "${PROJECT_DIR}/backend/staticfiles"

sudo -u "$TARGET_USER" "$VENV_PATH/bin/python" "${PROJECT_DIR}/backend/manage.py" migrate --noinput
sudo -u "$TARGET_USER" "$VENV_PATH/bin/python" "${PROJECT_DIR}/backend/manage.py" seed_demo --keep || true
sudo -u "$TARGET_USER" "$VENV_PATH/bin/python" "${PROJECT_DIR}/backend/manage.py" collectstatic --noinput

# 5. Build Next.js Frontend
echo -e "\n${YELLOW}[Step 5/7] Installing dependencies and building Next.js frontend...${NC}"
cd "${PROJECT_DIR}/frontend"
sudo -u "$TARGET_USER" npm install
sudo -u "$TARGET_USER" npm run build
cd "${PROJECT_DIR}"

# 6. Configure systemd services
echo -e "\n${YELLOW}[Step 6/7] Creating systemd background services (24/7 persistence)...${NC}"

# Backend service (Gunicorn)
cat <<EOF > /etc/systemd/system/marslick-backend.service
[Unit]
Description=MarSlick Django REST API Service
After=network.target

[Service]
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${PROJECT_DIR}/backend
ExecStart=${VENV_PATH}/bin/gunicorn config.wsgi:application \\
    --bind 127.0.0.1:8000 \\
    --workers 2 \\
    --timeout 120 \\
    --access-logfile - \\
    --error-logfile -
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=PORT=8000

[Install]
WantedBy=multi-user.target
EOF

# Frontend service (Next.js)
cat <<EOF > /etc/systemd/system/marslick-frontend.service
[Unit]
Description=MarSlick Next.js Frontend Service
After=network.target

[Service]
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${PROJECT_DIR}/frontend
ExecStart=$(which npm) start -- -p 3000
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=BACKEND_ORIGIN=http://127.0.0.1:8000
Environment=MARSLICK_API_KEY=marslick-demo-key-2026

[Install]
WantedBy=multi-user.target
EOF

# 7. Configure Nginx Reverse Proxy
echo -e "\n${YELLOW}[Step 7/7] Configuring Nginx reverse proxy on Port 80...${NC}"

cat <<'EOF' > /etc/nginx/sites-available/marslick
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Maximum file upload size (for large satellite SAR imagery)
    client_max_body_size 100M;

    # Frontend (Next.js UI)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Next.js API Proxy (attaches secret API key and forwards to Django)
    location /api/proxy/ {
        proxy_pass http://127.0.0.1:3000/proxy/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend APIs
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }

    # Uploaded & Generated Imagery (SAR images, masks, probabilities)
    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Swagger Documentation and Django Admin Static Assets
    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable Nginx site
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/marslick /etc/nginx/sites-enabled/marslick
nginx -t
systemctl restart nginx

# Reload and start systemd services
systemctl daemon-reload
systemctl enable --now marslick-backend
systemctl enable --now marslick-frontend

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 DEPLOYMENT COMPLETE! MarSlick is running 24/7 on Azure!        ${NC}"
echo -e "${GREEN}==================================================================${NC}"
PUBLIC_IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')
echo -e "\n  👉 Open your browser at:  ${BLUE}http://${PUBLIC_IP}/${NC}"
echo -e "  👉 API Swagger Docs:      ${BLUE}http://${PUBLIC_IP}/api/docs/${NC}"
echo -e "\nBoth services will automatically reboot if the server restarts."
echo -e "To view backend logs:   sudo journalctl -u marslick-backend -f"
echo -e "To view frontend logs:  sudo journalctl -u marslick-frontend -f"
echo -e "${GREEN}==================================================================${NC}\n"
