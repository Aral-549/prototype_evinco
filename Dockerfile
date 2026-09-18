FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# Install system dependencies required for OpenCV, image processing, and builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pre-install CPU-optimized PyTorch wheels to avoid bulky CUDA wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy entire repository
COPY . /app/

# Hugging Face Spaces runs with user ID 1000
RUN useradd -m -u 1000 user && \
    mkdir -p /app/backend/media /app/backend/staticfiles && \
    chown -R user:user /app

USER user
WORKDIR /app/backend

EXPOSE 7860

CMD ["/app/start.sh"]
