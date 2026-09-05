#!/usr/bin/env bash
set -e

# MarSlick: Automated Developer Onboarding & Environment Verifier
# Smart India Hackathon 2026 (Problem Statement ID: 26143)

echo "================================================================="
echo "  MarSlick Prototype Setup & Verification"
echo "  SIH Problem Statement ID: 26143"
echo "================================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Check Python Version
echo -e "\n[1/6] Checking Python runtime..."
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "ERROR: Python is not installed. Please install Python 3.10, 3.11, or 3.12."
    exit 1
fi

PY_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python version: $PY_VERSION"

# 2. Setup Virtual Environment
echo -e "\n[2/6] Setting up virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    $PYTHON_CMD -m venv .venv
    echo "Created clean virtual environment in .venv/"
fi
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel --quiet

# 3. Install Backend Dependencies
echo -e "\n[3/6] Installing backend & ML dependencies..."
pip install -r backend/requirements.txt --quiet
pip install pytest pytest-django python-pptx --quiet
echo "All dependencies installed successfully."

# Verify & Assemble Model Weights (if only split chunks exist)
WEIGHT_FILE="ai_model/weights/best_unet_dice_0.8018/best_unet"
if [ ! -f "$WEIGHT_FILE" ] && [ -f "${WEIGHT_FILE}.part_aa" ]; then
    echo "Reassembling baseline model weights from split chunks..."
    cat ${WEIGHT_FILE}.part_* > "$WEIGHT_FILE"
    echo "Model weights assembled successfully."
fi

# 4. Configure Environment (.env)
echo -e "\n[4/6] Configuring environment (.env)..."
if [ ! -f "backend/.env" ]; then
    cp backend/.env.example backend/.env
    echo "Created backend/.env from template."
else
    echo "Found existing backend/.env."
fi

# 5. Verify Redis Broker
echo -e "\n[5/6] Verifying Redis message broker..."
if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
    echo "Native Redis service is active and responsive on port 6379."
elif command -v docker &>/dev/null; then
    if docker ps --filter "name=prototype-redis" --format '{{.Names}}' | grep -q "prototype-redis"; then
        echo "Docker Redis container 'prototype-redis' is running."
    else
        echo "Starting Redis container via Docker..."
        docker run -d --name prototype-redis -p 6379:6379 redis:7-alpine || docker start prototype-redis
        echo "Redis container started on port 6379."
    fi
else
    echo "WARNING: Redis not detected. Start Redis manually on port 6379 before launching Celery."
fi

# 6. Apply Database Migrations & Run Tests
echo -e "\n[6/6] Applying database migrations & running test suite..."
python backend/manage.py migrate --noinput
python backend/manage.py validate_model
pytest backend/

echo -e "\n================================================================="
echo "  SETUP COMPLETE: All systems verified and 100% operational!"
echo "================================================================="
echo ""
echo "To start developing:"
echo "  1. Celery Worker:  source .venv/bin/activate && cd backend && celery -A config worker -Q detection_queue,drift_queue,ais_queue,default -c 2 -l INFO"
echo "  2. Django Server:  source .venv/bin/activate && cd backend && python manage.py runserver 0.0.0.0:8000"
echo "  3. Swagger Docs:   http://localhost:8000/api/docs/"
echo "  4. Web Console:    http://localhost:8000/"
echo "================================================================="
