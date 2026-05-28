FROM python:3.12.9-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --gid 1001 --no-create-home appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/tenants/direct /app/backups /app/logs /app/content /app/data \
    && chown -R appuser:appgroup /app/tenants /app/backups /app/logs /app/content /app/data

EXPOSE 5000
USER appuser

CMD ["gunicorn", "-w", "1", "--threads", "8", "--worker-class", "gthread", "--bind", "0.0.0.0:5000", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "5", "--max-requests", "10000", "--max-requests-jitter", "2000", "app:app"]
