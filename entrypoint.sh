#!/bin/sh
chown -R appuser:appgroup /app/logs /app/tenants /app/backups /app/content /app/data
exec "$@"
