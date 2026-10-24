"""Public-server guards: no fetching of internal addresses, an access code, and usage limits.

All of it is off unless PRAMAN_PUBLIC_MODE is set, so local runs and tests behave as before.
"""

from __future__ import annotations

import hmac
import ipaddress
import socket
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException, Request

from praman.config import Settings, get_settings

ALLOWED_PORTS = {None, 80, 443}


class BlockedAddress(httpx.TransportError):
    """The address isn't a public web server (private, loopback, link-local or an odd port)."""


def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_global
    except ValueError:
        return False


def ensure_public_url(url: httpx.URL) -> None:
    """Raise BlockedAddress unless every address the host resolves to is a public one."""
    if url.scheme not in ("http", "https") or url.port not in ALLOWED_PORTS or not url.host:
        raise BlockedAddress("That address isn't a public web page.")
    try:
        infos = socket.getaddrinfo(url.host, url.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise BlockedAddress("That address couldn't be found.") from e
    if not infos or not all(_is_public_ip(str(i[4][0])) for i in infos):
        raise BlockedAddress("That address isn't a public web page.")


def request_hook(request: httpx.Request) -> None:
    """httpx request hook: runs for every request, redirects included."""
    if get_settings().praman_public_mode:
        ensure_public_url(request.url)


# ---------------------------------------------------------------------------
# Access code and limits for checks that cost model calls or crawl another site


class _Limits:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._day_count = 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._day, self._day_count = "", 0

    def take(self, who: str, per_hour: int, per_day: int) -> str | None:
        """Count one use; returns the reason in plain words if a limit is reached."""
        now = time.monotonic()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        with self._lock:
            if today != self._day:
                self._day, self._day_count = today, 0
            hits = self._hits[who]
            while hits and now - hits[0] > 3600:
                hits.popleft()
            if len(hits) >= per_hour:
                return "You've reached the hourly limit for live checks. Try again later."
            if self._day_count >= per_day:
                return "Today's live checks are used up. The case files still work."
            hits.append(now)
            self._day_count += 1
        return None


limits = _Limits()


def client_id(request: Request) -> str:
    """The caller's address. Behind the host's proxy, the last X-Forwarded-For entry is its own."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd.strip():
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def is_local_presenter(request: Request) -> bool:
    """A request made on the server's own machine, not through the tunnel or a host's proxy: the
    presenter's laptop. Forwarded requests carry X-Forwarded-For and the visitor's address."""
    host = request.client.host if request.client else ""
    return not request.headers.get("x-forwarded-for") and host in ("127.0.0.1", "::1")


def live_checks_enabled(s: Settings) -> bool:
    """Whether a page that isn't a recorded case can be checked: live mode, or replay with a key."""
    has_key = s.has_api_key or s.has_groq_key
    return s.praman_llm_mode == "live" or (s.praman_llm_mode == "replay" and has_key)


def require_live_access(request: Request) -> None:
    """In public mode, a live check needs the access code (unless access is open), then counts
    against the limits."""
    s = get_settings()
    if not s.praman_public_mode:
        return
    if not s.praman_open_access:
        code = s.praman_access_code.strip()
        if not code:
            raise HTTPException(
                403, "Live checks are switched off on this server. Open a case file."
            )
        given = request.headers.get("x-access-code", "").strip()
        if not hmac.compare_digest(given.encode(), code.encode()):
            raise HTTPException(401, "Enter the access code to run a live check.")
    if is_local_presenter(request):
        return  # the limits keep visitors from using up the quota, not the presenter
    why = limits.take(client_id(request), s.praman_live_per_ip_hour, s.praman_live_daily_cap)
    if why:
        raise HTTPException(429, why)


# ---------------------------------------------------------------------------
# Reviewer access: who may decide a claim or sign a report

REVIEWER_KEY_HEADER = "X-Reviewer-Key"
ROLE_HEADER = "X-Praman-Role"


def reviewer_keys(s: Settings) -> dict[str, str]:
    """{key: reviewer name} from PRAMAN_REVIEWERS ("Asha:key1, Ravi:key2")."""
    out: dict[str, str] = {}
    for part in s.praman_reviewers.split(","):
        name, _, key = part.partition(":")
        if name.strip() and len(key.strip()) >= 8:
            out[key.strip()] = name.strip()
    return out


def reviewer_access(request: Request) -> str:
    """How this caller becomes a reviewer: "key" (named keys on the server), "role" (the demo
    role switch: a local server, or the presenter's own laptop) or "off" (a public server's
    visitors when no keys are set)."""
    s = get_settings()
    if reviewer_keys(s):
        return "key"
    if s.praman_public_mode and not is_local_presenter(request):
        return "off"
    return "role"


def require_reviewer(request: Request) -> str | None:
    """The signed-in reviewer's name ("key" mode), None in "role" mode; else 401/403."""
    access = reviewer_access(request)
    if access == "key":
        given = request.headers.get(REVIEWER_KEY_HEADER, "").strip().encode()
        name = None
        for key, who in reviewer_keys(get_settings()).items():
            if hmac.compare_digest(given, key.encode()):
                name = who
        if not name:
            raise HTTPException(401, "Enter a valid reviewer key to decide claims or sign.")
        return name
    if access == "off":
        raise HTTPException(
            403, "Sign-off is off on this public server: no reviewer keys are set up."
        )
    if request.headers.get(ROLE_HEADER, "").strip().lower() != "reviewer":
        raise HTTPException(403, "Only a reviewer can do this. Switch the role to Reviewer.")
    return None
