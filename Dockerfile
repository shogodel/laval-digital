FROM python:3.12.9-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --gid 1001 --home /home/appuser appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/tenants/direct /app/backups /app/logs /app/content /app/data \
    && chown -R appuser:appgroup /app/tenants /app/backups /app/logs /app/content /app/data

EXPOSE 5000
USER appuser

# Gevent worker-class: cooperative concurrency without code changes.
# Each worker can handle hundreds of concurrent greenlets, so a single
# worker with --worker-connections 1000 replaces 8 threads + 1 worker.
CMD ["gunicorn", "-w", "1", "--worker-class", "gevent", "--worker-connections", "1000", "--bind", "0.0.0.0:5000", "--timeout", "120", "--graceful-timeout", "120", "--keep-alive", "15", "--max-requests", "10000", "--max-requests-jitter", "2000", "app:app"]
