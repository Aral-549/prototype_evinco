#!/bin/bash
set -e

PORT="${PORT:-7860}"

echo "==> Running database migrations..."
python manage.py migrate --noinput

echo "==> Seeding demo cases if database is fresh..."
python manage.py seed_demo --keep || true

echo "==> Collecting static assets..."
python manage.py collectstatic --noinput

echo "==> Starting Gunicorn on port ${PORT}..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
