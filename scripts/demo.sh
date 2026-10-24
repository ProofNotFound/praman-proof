#!/usr/bin/env bash
# Build the frontend (if present), start the API in replay mode and open the app.
#   bash scripts/demo.sh            # replay mode (cached answers; live call only on a miss)
#   PRAMAN_LLM_MODE=offline bash scripts/demo.sh   # never touches the network
#   PRAMAN_PORT=8010 bash scripts/demo.sh          # another port
set -euo pipefail
cd "$(dirname "$0")/.."

export PRAMAN_LLM_MODE="${PRAMAN_LLM_MODE:-replay}"
export PRAMAN_ANONYMISE="${PRAMAN_ANONYMISE:-1}"
PORT="${PRAMAN_PORT:-8000}"

if [[ -f frontend/package.json ]]; then
  if command -v npm >/dev/null 2>&1 && node --version >/dev/null 2>&1; then
    echo "Building the frontend…"
    if ! (cd frontend && npm ci --no-audit --no-fund && npm run build); then
      echo "Frontend build failed; the API still serves /api and the last build (if any)."
    fi
  else
    echo "Node isn't working here (needs Node 22); serving the last frontend build if there is one."
  fi
fi

# Port 8000 is often taken (e.g. by Docker or OrbStack); the built app uses relative /api URLs,
# so any free port works.
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
if port_busy "$PORT"; then
  for p in $(seq 8001 8020); do
    if ! port_busy "$p"; then
      echo "Port $PORT is busy; using $p."
      PORT="$p"
      break
    fi
  done
fi

URL="http://127.0.0.1:${PORT}"
echo "Starting Praman on ${URL} (model answers: ${PRAMAN_LLM_MODE}, anonymise: ${PRAMAN_ANONYMISE})"
uv run uvicorn praman.api:app --host 127.0.0.1 --port "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -s "${URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
echo "Praman is running at ${URL}. Press Ctrl+C to stop."
wait $SERVER
