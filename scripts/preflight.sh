#!/usr/bin/env bash
# Morning-of-the-event checks (W5). Makes no model calls and needs no network: the API runs in
# offline mode on a spare port with a throwaway database. Prints PASS or FAIL per check and
# exits non-zero if any check fails.
#   bash scripts/preflight.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/praman-preflight.XXXXXX")"
API_PID=""
PREVIEW_PID=""
cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null
  [[ -n "$PREVIEW_PID" ]] && kill "$PREVIEW_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

ok() { printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf 'FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '      %s\n' "$2"; FAIL=$((FAIL + 1)); }
free_port() { uv run --quiet python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

echo "Praman preflight · $(date '+%d %b %Y %H:%M') · logs in $LOGDIR"
echo

# 1. Tools
if command -v uv >/dev/null 2>&1; then ok "uv installed ($(uv --version 2>/dev/null))"; else bad "uv installed" "Install uv: https://docs.astral.sh/uv/"; fi
NODE_V="$(node --version 2>/dev/null || true)"
if [[ "$NODE_V" == v22.* ]]; then ok "Node 22 ($NODE_V)"; else bad "Node 22" "Found '${NODE_V:-none}'; the frontend needs Node 22 LTS."; fi
if command -v npm >/dev/null 2>&1; then ok "npm installed"; else bad "npm installed"; fi
if command -v curl >/dev/null 2>&1; then ok "curl installed"; else bad "curl installed" "Needed by the checks below."; fi
if uv run --quiet python -c "import praman, cv2, fastapi, selectolax" >"$LOGDIR/python.log" 2>&1; then
  ok "Python environment (praman, OpenCV, FastAPI)"
else
  bad "Python environment" "Run: uv sync   (see $LOGDIR/python.log)"
fi
if [[ -d frontend/node_modules ]]; then ok "frontend/node_modules present"; else bad "frontend/node_modules present" "Run: cd frontend && npm ci"; fi

# 2. Build the frontend
if (cd frontend && npm run build) >"$LOGDIR/build.log" 2>&1; then
  ok "Frontend builds (frontend/dist)"
else
  bad "Frontend builds" "See $LOGDIR/build.log"
fi

# 3. Every recording validates, and the demo runs still match them event for event
if uv run --quiet pytest -q tests/test_recordings.py tests/test_demo_unchanged.py >"$LOGDIR/recordings.log" 2>&1; then
  ok "Recordings validate (core and bundled) and the 4 demo cases replay exactly as recorded"
else
  bad "Recordings validate" "See $LOGDIR/recordings.log"
fi
if (cd frontend && npx vitest run tests/recordings.test.ts tests/scan.test.ts tests/urls.test.ts) >"$LOGDIR/recordings-ts.log" 2>&1; then
  ok "Bundled recordings, scan and URL keys validate against the TypeScript contract"
else
  bad "Bundled recordings (TypeScript contract)" "See $LOGDIR/recordings-ts.log"
fi

# 4. API in offline mode plays L14 to run_finished
API_PORT="$(free_port)"
PRAMAN_LLM_MODE=offline PRAMAN_ANONYMISE=1 PRAMAN_DB_PATH="$LOGDIR/preflight.db" \
  uv run uvicorn praman.api:app --host 127.0.0.1 --port "$API_PORT" >"$LOGDIR/api.log" 2>&1 &
API_PID=$!
API="http://127.0.0.1:${API_PORT}"
for _ in $(seq 1 60); do curl -sf "$API/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
if curl -sf "$API/api/health" | grep -q '"llm_mode":"offline"'; then
  ok "API starts in offline mode ($API)"
  RUN_ID="$(curl -sf -X POST "$API/api/runs" -H 'Content-Type: application/json' \
    -d '{"listing_id":"L14","mode":"agent"}' | uv run --quiet python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' 2>/dev/null)"
  if [[ -n "$RUN_ID" ]] && curl -sN --max-time 60 "$API/api/runs/$RUN_ID/events" >"$LOGDIR/l14.sse" 2>&1 \
    && grep -q '^event: run_finished' "$LOGDIR/l14.sse"; then
    N_EVENTS="$(grep -c '^event:' "$LOGDIR/l14.sse")"
    if grep -q '^event: error' "$LOGDIR/l14.sse"; then
      bad "L14 plays to run_finished" "An error event came first; see $LOGDIR/l14.sse"
    else
      ok "L14 plays to run_finished over SSE ($N_EVENTS events, run $RUN_ID)"
    fi
  else
    bad "L14 plays to run_finished" "See $LOGDIR/l14.sse and $LOGDIR/api.log"
  fi
  if curl -sf "$API/" | grep -qi '<div id="root"'; then ok "API serves the built app at /"; else bad "API serves the built app at /"; fi
else
  bad "API starts in offline mode" "See $LOGDIR/api.log"
fi
kill "$API_PID" 2>/dev/null; wait "$API_PID" 2>/dev/null; API_PID=""

# 5. npm run demo serves the app and the bundled recordings with no Praman server
DEMO_PORT="$(free_port)"
(cd frontend && npx vite preview --port "$DEMO_PORT" --strictPort) >"$LOGDIR/demo.log" 2>&1 &
PREVIEW_PID=$!
DEMO="http://127.0.0.1:${DEMO_PORT}"
for _ in $(seq 1 40); do curl -sf "$DEMO/" >/dev/null 2>&1 && break; sleep 0.5; done
DEMO_OK=1
for path in / /demo/index.json /demo/L14.agent.json /demo/L06.agent.json /demo/L08.agent.json /demo/L21.agent.json \
  /demo/scan_demo.json /demo/urls.json /demo/eval.json /demo/photos/L14/7.jpg /scan /eval; do
  curl -sf -o /dev/null "$DEMO$path" || { DEMO_OK=0; echo "      missing: $path"; }
done
if [[ "$DEMO_OK" == 1 ]]; then ok "npm run demo serves the app and every bundled file ($DEMO)"; else bad "npm run demo serves the app" "See $LOGDIR/demo.log"; fi
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "NOTE  Something listens on :8000; 'npm run demo' proxies /api there, so it will use that server instead of the recordings."
fi
kill "$PREVIEW_PID" 2>/dev/null; wait "$PREVIEW_PID" 2>/dev/null; PREVIEW_PID=""

echo
echo "$PASS passed, $FAIL failed."
[[ "$FAIL" == 0 ]] && echo "PREFLIGHT PASS" || echo "PREFLIGHT FAIL"
exit "$FAIL"
