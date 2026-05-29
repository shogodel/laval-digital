#!/bin/bash
set -euo pipefail
cd /var/www/laval-digital
source venv/bin/activate
exec gunicorn \
    -w 1 \
    --threads 8 \
    --worker-class gthread \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    --graceful-timeout 120 \
    --keep-alive 15 \
    --max-requests 10000 \
    --max-requests-jitter 2000 \
    --capture-output \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    app:app
