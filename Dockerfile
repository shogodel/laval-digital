FROM python:3.12-slim-bookworm

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

CMD ["gunicorn", "-w", "2", "--threads", "4", "--bind", "0.0.0.0:5000", "app:app"]
