# Deploying Praman (one container: API + web app)

The `Dockerfile` builds the web app and serves it from the API on one origin, so server-sent events work and there is no CORS to set up. `render.yaml` is the Render blueprint for it.

## What runs on the public server

| What a visitor does | What happens |
|---|---|
| Opens a demo case (L14, L06, L08, L21), either mode | Replays the recorded model answers through the real agent and API. No key used, no cost, same events as the recording. |
| Opens the recorded store scan | Served from the scan cache. |
| Pastes a new product URL, scans a new store, or runs another seed listing | Needs the **access code**, then counts against a per-address hourly limit and a daily cap. Uses the model, so the Gemini key is needed. |
| Any request that would fetch an internal address (localhost, private ranges, cloud metadata, ports other than 80/443), including redirects | Refused ("That address isn't a public web page."). |

`PRAMAN_PUBLIC_MODE=1` switches those guards on (`praman/guard.py`). It is on in the `Dockerfile`; locally it is off, so nothing changes for development or tests. With no `PRAMAN_ACCESS_CODE` set, live checks are switched off and only the recorded cases work.

## Settings

| Variable | Value | Notes |
|---|---|---|
| `PRAMAN_LLM_MODE` | `replay` | Recorded answers first; a call the recordings don't cover goes to the model. |
| `PRAMAN_PUBLIC_MODE` | `1` | Guards on. |
| `PRAMAN_GROQ_REASONING` | `medium` (default) | How long the Groq reasoning model thinks on claim extraction, evidence judging and consistency checks; `low` is faster but made the judge too lenient (23 Oct). Planning and rewrite calls always use `low`. |
| `GROQ_API_KEY` | your key | Secret. Enter it in the host's dashboard only. |
| `PRAMAN_LIVE_MODEL` | `groq:openai/gpt-oss-120b` | The model tried first for live text calls (claims, evidence judging, consistency, rewrites). Empty = Gemini only. |
| `PRAMAN_LIVE_SHORT_MODEL` | `groq:llama-3.3-70b-versatile` | Optional. Planning and rewording calls go here first, then to the main model. Groq counts tokens per model, so this leaves room for the heavy calls. |
| `PRAMAN_LIVE_VISION_MODEL` | empty | Optional, e.g. `groq:qwen/qwen3.8-27b`. Groq takes 3 photos per request, so more photos are split into groups of 3, read in parallel and joined; without this setting photo calls use Gemini. |
| `GEMINI_API_KEY` | your key | Secret. Reads pack photos and is the fallback when Groq fails. Without it the app still plays every demo case. |
| `PRAMAN_ACCESS_CODE` | a word you choose | Secret. Share it only with people who should run live checks. |
| `PRAMAN_REVIEWERS` | `Name:key, Name2:key2` | Secret. Named reviewers; keys of 8+ characters. With it set, deciding a claim or signing needs a key and the report is signed with the key's name. Without it, a public server refuses sign-off to visitors (the presenter's own laptop keeps the role switch). |
| `PRAMAN_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Tried after the models above fail. |
| `PRAMAN_SEARCH_MODELS` | `groq:openai/gpt-oss-120b, groq:openai/gpt-oss-20b` | Optional. Groq models with browser search, tried in order for the material web search; empty = `PRAMAN_LIVE_MODEL` when it is a gpt-oss model. Gemini is never used for the search. |
| `PRAMAN_LIVE_PER_IP_HOUR` | `6` (default) | Live checks per address per hour. |
| `PRAMAN_LIVE_DAILY_CAP` | `20` (default) | Live checks per day for the whole server (resets at 00:00 UTC and on restart). |

## Render

1. Push the branch to GitHub (the repo is private; Render needs access to it).
2. Render dashboard → New → Blueprint → pick the repo and branch. It reads `render.yaml`.
3. Set `GROQ_API_KEY`, `GEMINI_API_KEY` and `PRAMAN_ACCESS_CODE` when asked.
4. Wait for the build (several minutes: it builds the frontend and installs Python packages).
5. Open `https://<service>.onrender.com/api/health`: expect `"ok": true`, `"llm_mode": "replay"`, `"needs_access_code": true`.
6. Open the site, play L14, then try the Store scan screen and the compare view.

The free plan sleeps when idle, and the first request after that takes about a minute. For the event, either switch the service to a paid plan for the weekend or open the site 10 minutes before you go on and keep a tab open.

## Limits to know

- The disk is not persistent. Runs, new-store letters and fetched pages vanish on restart or redeploy; the demo cases and recorded scan do not depend on them.
- Photo files are not in git. The demo cases show their masked recording photos (`data/recordings/photos/`). A new live page downloads its own photos while it runs.
- The address check resolves the host name just before connecting; it does not pin the connection to the address it checked.
- The access code is a speed bump for a demo, not authentication.
- Keep the Vercel mirror (`https://praman-proof.vercel.app`) as the fallback: it needs no server.

## Which model answers what

Recorded demo cases never call a model. For a live check, `praman/llm.py` tries, in order: `PRAMAN_LIVE_MODEL` (Groq), then `PRAMAN_MODEL` (Gemini), then `PRAMAN_FALLBACK_MODEL`. A model with no key is skipped. A 429 "try again in Ns" is waited out for N seconds (at most 12) before the next attempt. A Groq daily limit (429 "per day") is not retried. The replay cache key still uses `PRAMAN_MODEL`, so answers recorded with Gemini keep replaying; the model that actually answered is stored on each cached row and shown on the call. The cost figure in reports uses Gemini's price estimate for every provider.

## Open access, real names (24 Oct 2026)
`render.yaml` now sets `PRAMAN_OPEN_ACCESS=1` (no access code; the per-visitor limit of 15 an hour and the daily cap of 60 still apply, and internal addresses are still never fetched) and `PRAMAN_ANONYMISE=0` (real store and product names). A server where `PRAMAN_OPEN_ACCESS` is unset behaves as before: no code, no live checks. On an existing Render service these are set in the dashboard under Environment; the blueprint only applies when it is synced. Demo cases still play their recorded photos (brand marks blurred); pages checked live show their own photos.
