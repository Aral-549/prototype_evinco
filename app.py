"""Hugging Face Spaces Entrypoint (Gradio SDK mode — 100% Free, No Docker / No Card).

Hugging Face Spaces runs `python app.py` and serves traffic on port 7860.
This script applies database migrations, seeds initial demo cases if empty,
collects static assets, and launches Gunicorn to serve the Django REST API.
"""

import os
import subprocess
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
PORT = os.getenv("PORT", "7860")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Add backend directory to Python path
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR))

def run_cmd(cmd, cwd=BACKEND_DIR):
    print(f"==> Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)

if __name__ == "__main__":
    print("==========================================================")
    print("   Starting MarSlick SIH26143 API on Hugging Face Spaces   ")
    print(f"   Port: {PORT} | 16 GB RAM Free Tier                    ")
    print("==========================================================")

    # 1. Run migrations
    run_cmd([sys.executable, "manage.py", "migrate", "--noinput"])

    # 2. Seed demo cases only if database is fresh
    try:
        import django
        django.setup()
        from apps.pipeline.models import PipelineRun
        if not PipelineRun.objects.exists():
            print("==> Fresh database detected. Seeding demo cases...")
            run_cmd([sys.executable, "manage.py", "seed_demo", "--keep"])
        else:
            print("==> Existing cases found; skipping seed.")
    except Exception as e:
        print(f"Note on seed check: {e}")

    # 3. Collect static files for Swagger and Django admin
    run_cmd([sys.executable, "manage.py", "collectstatic", "--noinput"])

    # 4. Launch Gunicorn WSGI server
    print(f"==> Launching Gunicorn on 0.0.0.0:{PORT}...")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "--chdir",
            str(BACKEND_DIR),
            "config.wsgi:application",
            "--bind",
            f"0.0.0.0:{PORT}",
            "--workers",
            "2",
            "--timeout",
            "120",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ],
    )
