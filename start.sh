#!/bin/bash
cd /var/www/laval-digital
source venv/bin/activate
python app.py > /tmp/flask.log 2>&1
