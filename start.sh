#!/bin/bash
cd /var/www/laval-digital
source venv/bin/activate
exec gunicorn -w 2 --threads 4 --bind 127.0.0.1:5000 app:app
