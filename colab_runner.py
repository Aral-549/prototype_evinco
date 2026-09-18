#!/usr/bin/env python3
"""Colab / Remote Runner for MarSlick SIH26143 Backend.

Usage on Google Colab:
    python colab_runner.py

This script:
1. Installs remaining dependencies (PyTorch is pre-installed on Colab).
2. Downloads the Cloudflare Tunnel binary (`cloudflared`).
3. Runs database migrations and seeds reproducible demo cases.
4. Starts Django on 127.0.0.1:8000.
5. Exposes the backend via Cloudflare Tunnel and prints the public HTTPS URL.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

def run_cmd(cmd, check=True):
    print(f"[*] Executing: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)

def install_cloudflared():
    if shutil.which("cloudflared"):
        print("[+] cloudflared is already installed.")
        return "cloudflared"

    dest = Path("/usr/local/bin/cloudflared")
    if dest.exists() and os.access(dest, os.X_OK):
        print("[+] /usr/local/bin/cloudflared is ready.")
        return str(dest)

    print("[*] Downloading cloudflared binary...")
    url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
    run_cmd(["curl", "-sL", url, "-o", "/tmp/cloudflared"])
    run_cmd(["chmod", "+x", "/tmp/cloudflared"])
    try:
        run_cmd(["cp", "/tmp/cloudflared", "/usr/local/bin/cloudflared"], check=False)
        return "/usr/local/bin/cloudflared"
    except Exception:
        return "/tmp/cloudflared"

def main():
    print("==================================================================")
    print("       MarSlick SIH26143 — Google Colab Backend Runner            ")
    print("==================================================================")

    # 1. Install necessary dependencies (skip heavy PyTorch re-download if present)
    print("\n[Step 1/5] Verifying Python dependencies...")
    run_cmd([
        sys.executable, "-m", "pip", "install", "-q",
        "Django>=5.0",
        "djangorestframework>=3.15",
        "drf-spectacular>=0.27",
        "django-cors-headers>=4.3",
        "gunicorn>=21.2",
        "whitenoise>=6.6",
        "shapely>=2.0",
        "geojson>=3.0",
        "segmentation-models-pytorch>=0.3.4",
        "timm>=1.0.0",
        "safetensors>=0.4.0",
    ])

    # 2. Setup Cloudflared
    print("\n[Step 2/5] Setting up Cloudflare Tunnel...")
    cf_bin = install_cloudflared()

    # 3. Database migrations
    print("\n[Step 3/5] Applying database migrations...")
    run_cmd([sys.executable, "backend/manage.py", "migrate", "--noinput"])

    # 4. Seed demo data
    print("\n[Step 4/5] Checking demo cases...")
    try:
        run_cmd([sys.executable, "backend/manage.py", "seed_demo", "--keep"])
    except Exception as e:
        print(f"Note on seed_demo: {e}")

    # 5. Start Django in background
    print("\n[Step 5/5] Launching Django backend...")
    django_proc = subprocess.Popen(
        [sys.executable, "backend/manage.py", "runserver", "127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait 2 seconds for Django to initialize
    time.sleep(2)

    # 6. Start Cloudflared tunnel and capture public URL
    print("\n[*] Establishing public HTTPS tunnel...")
    tunnel_proc = subprocess.Popen(
        [cf_bin, "tunnel", "--url", "http://127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    public_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    for line in iter(tunnel_proc.stdout.readline, ""):
        match = url_pattern.search(line)
        if match:
            public_url = match.group(0)
            break

    if public_url:
        print("\n" + "=" * 68)
        print("🎉 SUCCESS! MarSlick Backend is LIVE on Google Colab!")
        print("=" * 68)
        print(f"\n  👉 Public Backend URL:  {public_url}\n")
        print("  Next steps for Vercel Frontend deployment:")
        print("  1. In Vercel Project Settings -> Environment Variables, set:")
        print(f"     BACKEND_ORIGIN = {public_url}")
        print("     MARSLICK_API_KEY = marslick-demo-key-2026")
        print("  2. Deploy/Redeploy your Vercel frontend.")
        print("=" * 68 + "\n")
    else:
        print("[!] Could not automatically parse tunnel URL. Check tunnel logs below:")

    # Keep alive and print logs
    try:
        while True:
            line = tunnel_proc.stdout.readline()
            if not line and tunnel_proc.poll() is not None:
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[*] Shutting down servers...")
        django_proc.terminate()
        tunnel_proc.terminate()

if __name__ == "__main__":
    main()
