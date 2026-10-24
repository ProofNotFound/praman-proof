#!/usr/bin/env bash
# Run Praman on this laptop and share it at a free public link (Cloudflare quick tunnel; no account).
#   bash scripts/share.sh                       # replay mode: demo cases instant, new pages live
#   PRAMAN_ACCESS_CODE=mycode bash scripts/share.sh   # choose the access code yourself
# Public mode is on: live checks need the access code and count against per-visitor and daily limits,
# and the server never fetches internal addresses. The link lasts while this script runs.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v cloudflared >/dev/null || { echo "Install the tunnel first: brew install cloudflared"; exit 1; }

export PRAMAN_LLM_MODE="${PRAMAN_LLM_MODE:-replay}"
export PRAMAN_ANONYMISE="${PRAMAN_ANONYMISE:-1}"
export PRAMAN_PUBLIC_MODE=1
export PRAMAN_LIVE_DAILY_CAP="${PRAMAN_LIVE_DAILY_CAP:-40}"
# Photos on the quick Gemini model: the main one timed out often during testing
export PRAMAN_LIVE_VISION_MODEL="${PRAMAN_LIVE_VISION_MODEL:-gemini-3.5-flash-lite}"
# No access code by default: anyone with the link may run a live check, within the limits.
# PRAMAN_OPEN_ACCESS=0 brings the code back (a fresh one is printed unless you set it).
export PRAMAN_OPEN_ACCESS="${PRAMAN_OPEN_ACCESS:-1}"
export PRAMAN_LIVE_PER_IP_HOUR="${PRAMAN_LIVE_PER_IP_HOUR:-15}"
if [[ "$PRAMAN_OPEN_ACCESS" != "1" && -z "${PRAMAN_ACCESS_CODE:-}" ]]; then
  PRAMAN_ACCESS_CODE="$(openssl rand -hex 4)"
fi
export PRAMAN_ACCESS_CODE="${PRAMAN_ACCESS_CODE:-}"
PORT="${PRAMAN_PORT:-8000}"

# Real brand names (PRAMAN_ANONYMISE=0): its own database copy, so unmasked events can never be
# served by the anonymised server. Run it on another port next to the normal one:
#   PRAMAN_ANONYMISE=0 PRAMAN_PORT=8002 bash scripts/share.sh
if [[ "$PRAMAN_ANONYMISE" == "0" ]]; then
  REAL_DB="data/praman_real.db"
  if [[ ! -f "$REAL_DB" && -f data/praman.db ]]; then cp data/praman.db "$REAL_DB"; fi
  export PRAMAN_DB_PATH="$REAL_DB"
  echo "Real brand names are ON for this link (own database: $REAL_DB)."
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is busy. Stop the other server first (or set PRAMAN_PORT)."
  exit 1
fi

if [[ ! -f frontend/dist/index.html ]]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

LOG="$(mktemp -t praman-tunnel)"
uv run uvicorn praman.api:app --host 127.0.0.1 --port "$PORT" &
SERVER=$!
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >"$LOG" 2>&1 &
TUNNEL=$!
trap 'kill $SERVER $TUNNEL 2>/dev/null || true; rm -f "$LOG"' EXIT INT TERM

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [[ -n "$URL" ]] && curl -s "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1 && break
  sleep 1
done
if [[ -z "$URL" ]]; then
  echo "The tunnel didn't start; its log:"
  cat "$LOG"
  exit 1
fi

echo
echo "  Praman is live at:  ${URL}"
echo "  On this laptop:     http://127.0.0.1:${PORT}"
if [[ "$PRAMAN_OPEN_ACCESS" == "1" ]]; then
  echo "  No access code needed: anyone with the link can check a new product"
  echo "  (limits: ${PRAMAN_LIVE_PER_IP_HOUR} an hour per visitor, ${PRAMAN_LIVE_DAILY_CAP} a day in all)."
else
  echo "  Access code for live checks:  ${PRAMAN_ACCESS_CODE}"
fi
echo "  Press Ctrl+C to stop both."
echo
wait $SERVER
