#!/bin/bash
set -euo pipefail
cd /var/www/laval-digital
source venv/bin/activate
exec gunicorn \
    -w 2 \
    --threads 4 \
    --worker-class gthread \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 10000 \
    --max-requests-jitter 2000 \
    --capture-output \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    app:app
