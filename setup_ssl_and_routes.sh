#!/usr/bin/env bash
# ==============================================================================
# EVINCO SIH 2026 — Automated HTTPS & Unified Multi-Project Nginx Setup
# Connects both Project 1 (MarSlick) and Project 2 (MoSPI PAIMANA) under standard HTTPS
# ==============================================================================

set -euo pipefail

DOMAIN="evinco-sih.centralindia.cloudapp.azure.com"
EMAIL="shaik2.mitmpl2025@learner.manipal.edu"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[ERROR] This script must be run with sudo: sudo ./setup_ssl_and_routes.sh${NC}" 
   exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}       Configuring Domain & HTTPS for ${DOMAIN}                   ${NC}"
echo -e "${BLUE}==================================================================${NC}"

# 1. Clean up any stray conf.d files and configure unified Nginx configuration
echo -e "\n${YELLOW}[Step 1/5] Writing unified Nginx configuration...${NC}"
rm -f /etc/nginx/conf.d/paimana_routes.conf /etc/nginx/conf.d/*paimana*
cat <<EOF > /etc/nginx/sites-available/marslick
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 100M;

    # ── Project 1: MarSlick Frontend (Next.js Port 3000) ─────────
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Project 1: Next.js API Proxy (attaches secret API key) ───────────
    location /api/proxy/ {
        proxy_pass http://127.0.0.1:3000/proxy/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Project 1: MarSlick Backend (Django Port 8000) ───────────
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Project 2: MoSPI PAIMANA Next.js Frontend (Port 3001) ───
    location /paimana {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Project 2: MoSPI PAIMANA FastAPI Backend (Port 8001) ─────
    location /dashboard {
        proxy_pass http://127.0.0.1:8001/dashboard;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8001/docs;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8001/openapi.json;
        proxy_set_header Host \$host;
    }

    # PAIMANA API Endpoints (portfolio, predict, analytics, health)
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8001/api/v1/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # MarSlick API Endpoints (runs, dossiers) - takes priority due to longer prefix
    location /api/v1/pipeline/ {
        proxy_pass http://127.0.0.1:8000/api/v1/pipeline/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/marslick /etc/nginx/sites-enabled/marslick
nginx -t
systemctl reload nginx

# 2. Acquire / Renew SSL Certificate for the new domain
echo -e "\n${YELLOW}[Step 2/5] Obtaining Let's Encrypt SSL Certificate...${NC}"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" --redirect || {
    echo -e "${YELLOW}[!] Warning: Certbot exited with an error. Attempting installer re-run...${NC}"
    certbot install --cert-name "${DOMAIN}" || true
}

# 3. Seed demo cases into MarSlick Django database
echo -e "\n${YELLOW}[Step 3/5] Seeding demo forensic cases into database...${NC}"
VENV_PATH="${PROJECT_DIR}/.venv"
if [[ -f "${VENV_PATH}/bin/python" ]]; then
    sudo -u "$TARGET_USER" "${VENV_PATH}/bin/python" "${PROJECT_DIR}/backend/manage.py" seed_demo --keep || true
fi

# 4. Rebuild frontend and update systemd service configuration
echo -e "\n${YELLOW}[Step 4/5] Building updated frontend and configuring services...${NC}"
if [[ -d "${PROJECT_DIR}/frontend" ]]; then
    cd "${PROJECT_DIR}/frontend"
    sudo -u "$TARGET_USER" npm run build
    cd "${PROJECT_DIR}"
fi

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

# 4b. Rebuild and configure PAIMANA Next.js frontend (port 3001)
P2_DIR="/home/${TARGET_USER}/prototype2_evinco"
if [[ -d "${P2_DIR}/hackathon-frontend-starter" ]]; then
    echo -e "\n${YELLOW}[Building PAIMANA Next.js frontend for /paimana]...${NC}"
    cd "${P2_DIR}"
    sudo -u "$TARGET_USER" git pull || true
    cd "${P2_DIR}/hackathon-frontend-starter"
    sudo -u "$TARGET_USER" npm install || true
    sudo -u "$TARGET_USER" npm run build
    
    cat <<EOF > /etc/systemd/system/paimana-frontend.service
[Unit]
Description=PAIMANA Next.js Frontend Service
After=network.target

[Service]
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${P2_DIR}/hackathon-frontend-starter
ExecStart=$(which npm) start -- -p 3001
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=3001

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable paimana-frontend
    systemctl restart paimana-frontend
    cd "${PROJECT_DIR}"
fi

systemctl daemon-reload
systemctl restart marslick-backend
systemctl restart marslick-frontend
systemctl restart paimana-backend || true
systemctl restart nginx

# 5. Summary
echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 ALL SET! Both projects are live on standard HTTPS for judges!  ${NC}"
echo -e "${GREEN}==================================================================${NC}"
echo -e "\n  👉 Project 1 (MarSlick Forensic):       ${BLUE}https://${DOMAIN}/${NC}"
echo -e "  👉 Project 2 (MoSPI PAIMANA Next.js):   ${BLUE}https://${DOMAIN}/paimana${NC}"
echo -e "  👉 Project 2 (Executive Command HTML):  ${BLUE}https://${DOMAIN}/dashboard${NC}"
echo -e "  👉 Project 2 (API Swagger Docs):        ${BLUE}https://${DOMAIN}/docs${NC}"
echo -e "\nBoth projects work seamlessly on mobile phones (4G/5G/Wi-Fi) with valid SSL!"
echo -e "${GREEN}==================================================================${NC}\n"
