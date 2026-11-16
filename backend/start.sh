
#!/usr/bin/env bash
set -euo pipefail

# Start Docling worker
python -m app.services.document_intelligence.worker_server &
WORKER_PID=$!

# Start FastAPI backend
python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" &
API_PID=$!

# Stop both processes if either one exits
cleanup() {
  kill "$WORKER_PID" "$API_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
wait -n "$WORKER_PID" "$API_PID"
