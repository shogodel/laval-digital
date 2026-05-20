#!/bin/bash
set -e
cd /var/www/laval-digital
source venv/bin/activate
exec gunicorn -w 2 --threads 4 --bind 0.0.0.0:5000 app:app
