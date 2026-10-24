#!/usr/bin/env bash
# The presenter's own screen: Praman with real brand and product names (anonymising off), on this
# laptop only (127.0.0.1:8001). Run it next to scripts/share.sh, which keeps the shared link and
# phones anonymised.
#   bash scripts/demo_real.sh
# It uses its OWN copy of the database (data/praman_real.db): a run made here stores real names in
# its events, and the shared server must never be able to serve those.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PRAMAN_REAL_PORT:-8001}"
REAL_DB="data/praman_real.db"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is busy. Stop the other server first."
  exit 1
fi

if [[ ! -f "$REAL_DB" ]]; then
  if [[ -f data/praman.db ]]; then
    cp data/praman.db "$REAL_DB"   # start from the saved answers, so known pages replay instantly
  fi
fi

if [[ ! -f frontend/dist/index.html ]]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

export PRAMAN_LLM_MODE="${PRAMAN_LLM_MODE:-replay}"
export PRAMAN_ANONYMISE=0
export PRAMAN_DB_PATH="$REAL_DB"
export PRAMAN_LIVE_VISION_MODEL="${PRAMAN_LIVE_VISION_MODEL:-gemini-3.5-flash-lite}"

echo
echo "  Real names ON (this laptop only):  http://127.0.0.1:${PORT}"
echo "  Do NOT share this address or put it behind a tunnel."
echo
exec uv run uvicorn praman.api:app --host 127.0.0.1 --port "$PORT"
