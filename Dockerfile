FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx-light \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt apscheduler pywebpush

COPY . .

RUN mkdir -p /app/tenants/direct /app/tenants/resellers /app/backups /app/logs /app/content /app/data

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "--threads", "4", "--bind", "0.0.0.0:5000", "app:app"]
