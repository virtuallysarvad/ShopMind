#!/bin/sh
# Seed demo data on first start in mock mode, then serve the API.
set -e
if [ "${SHOPMIND_WOO_MODE:-mock}" = "mock" ] && [ ! -s /data/shopmind.db ]; then
  echo "First start in mock mode: seeding demo data"
  python -m app.seed
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
