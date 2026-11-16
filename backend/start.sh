
#!/usr/bin/env bash
set -euo pipefail

# Go to backend directory
cd "$(dirname "$0")"

# Set correct invoice storage path
export RECEIVAI_DOCLING_STORAGE_ROOT="$(pwd)/storage/invoices"

# Ensure invoice directory exists
mkdir -p "$RECEIVAI_DOCLING_STORAGE_ROOT"

echo "Invoice storage directory ready"

# Start Docling worker
python -m app.services.document_intelligence.worker_server &
WORKER_PID=$!

# Start FastAPI backend
python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" &
API_PID=$!

cleanup() {
  kill "$WORKER_PID" "$API_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
wait -n "$WORKER_PID" "$API_PID"
