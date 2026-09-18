#!/usr/bin/env bash
# ==============================================================================
# EVINCO MarSlick — Quick Azure Update & Service Restart Script
# Run this on the Azure VM: sudo ./update_azure.sh
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}       Updating MarSlick on Azure VM                              ${NC}"
echo -e "${BLUE}==================================================================${NC}"

# 1. Pull latest code from GitHub
echo -e "\n${YELLOW}[Step 1/4] Pulling latest code from GitHub...${NC}"
cd "${PROJECT_DIR}"
if [[ -d ".git" ]]; then
    sudo -u "$TARGET_USER" git pull origin main
fi

# 2. Build Next.js frontend
echo -e "\n${YELLOW}[Step 2/4] Rebuilding Next.js frontend...${NC}"
cd "${PROJECT_DIR}/frontend"
sudo -u "$TARGET_USER" npm run build
cd "${PROJECT_DIR}"

# 3. Update Nginx configuration and reload
echo -e "\n${YELLOW}[Step 3/4] Updating Nginx configuration...${NC}"
if [[ -f "${PROJECT_DIR}/setup_ssl_and_routes.sh" ]]; then
    # Run the route update section
    bash "${PROJECT_DIR}/setup_ssl_and_routes.sh"
else
    nginx -t
    systemctl reload nginx
fi

# 4. Restart Frontend Service
echo -e "\n${YELLOW}[Step 4/4] Restarting systemd services...${NC}"
systemctl restart marslick-frontend
systemctl restart marslick-backend || true

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}✅ MarSlick update successfully applied to Azure!                ${NC}"
echo -e "${GREEN}==================================================================${NC}"
echo -e "Frontend live at: https://evinco-sih.centralindia.cloudapp.azure.com/"
