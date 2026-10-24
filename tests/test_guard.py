"""Public-server guards: no internal addresses, access code, limits (offline)."""

import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from praman import guard
from praman.api import app
from praman.config import reset_settings


@pytest.fixture
def public(monkeypatch):
    """A public server in replay mode with a key and an access code."""
    monkeypatch.setenv("PRAMAN_PUBLIC_MODE", "1")
    monkeypatch.setenv("PRAMAN_LLM_MODE", "replay")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("PRAMAN_ACCESS_CODE", "open-sesame")
    reset_settings()
    guard.limits.reset()
    monkeypatch.setattr("praman.api.run_listing", lambda *a, **k: None)  # gates only, no runs
    with TestClient(app) as c:
        yield c
    guard.limits.reset()


def _addrs(*ips):
    return lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips
    ]


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "192.168.1.9", "169.254.169.254", "100.64.0.1", "::1", "fd00::1"],
)
def test_internal_addresses_are_not_public(ip):
    assert not guard._is_public_ip(ip)


def test_public_address_is_public():
    assert guard._is_public_ip("8.8.8.8")


def test_ensure_public_url_blocks_internal_hosts_and_odd_ports(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _addrs("93.184.216.34"))
    guard.ensure_public_url(httpx.URL("https://shop.example/products/x"))
    with pytest.raises(guard.BlockedAddress):
        guard.ensure_public_url(httpx.URL("https://shop.example:8080/products/x"))
    with pytest.raises(guard.BlockedAddress):
        guard.ensure_public_url(httpx.URL("ftp://shop.example/x"))
    monkeypatch.setattr(socket, "getaddrinfo", _addrs("93.184.216.34", "10.1.2.3"))
    with pytest.raises(guard.BlockedAddress):  # one private answer is enough to refuse
        guard.ensure_public_url(httpx.URL("https://shop.example/"))


def test_request_hook_only_checks_in_public_mode(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _addrs("127.0.0.1"))
    req = httpx.Request("GET", "http://localhost/")
    guard.request_hook(req)  # not a public server: nothing is checked
    monkeypatch.setenv("PRAMAN_PUBLIC_MODE", "1")
    reset_settings()
    with pytest.raises(guard.BlockedAddress):
        guard.request_hook(req)


def test_health_says_when_live_checks_need_a_code(public):
    h = public.get("/api/health").json()
    assert h["live_checks"] is True and h["needs_access_code"] is True


def test_new_page_needs_the_access_code(public):
    body = {"url": "https://shop.example/products/x", "mode": "agent"}
    r = public.post("/api/runs", json=body)
    assert r.status_code == 401 and "access code" in r.json()["detail"]
    r = public.post("/api/runs", json=body, headers={"X-Access-Code": "wrong"})
    assert r.status_code == 401


def test_live_checks_are_off_without_a_configured_code(public, monkeypatch):
    monkeypatch.setenv("PRAMAN_ACCESS_CODE", "")
    reset_settings()
    r = public.post("/api/runs", json={"url": "https://shop.example/products/x", "mode": "agent"})
    assert r.status_code == 403 and "switched off" in r.json()["detail"]


def test_internal_address_is_refused_even_with_the_code(public, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _addrs("169.254.169.254"))
    r = public.post(
        "/api/runs",
        json={"url": "http://metadata.example/products/x", "mode": "agent"},
        headers={"X-Access-Code": "open-sesame"},
    )
    assert r.status_code == 400 and "public web page" in r.json()["detail"]


def test_demo_cases_need_no_code_but_other_seed_listings_do(public):
    assert public.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).status_code == 200
    r = public.post("/api/runs", json={"listing_id": "L01", "mode": "agent"})
    assert r.status_code == 401


def test_per_address_limit_and_daily_cap(public, monkeypatch):
    monkeypatch.setenv("PRAMAN_LIVE_PER_IP_HOUR", "2")
    reset_settings()
    hdr = {"X-Access-Code": "open-sesame", "X-Forwarded-For": "1.1.1.1"}
    # A seed listing that isn't a demo case counts as a live check but never fetches a page
    for _ in range(2):
        assert public.post("/api/runs", json={"listing_id": "L01"}, headers=hdr).status_code == 200
    r = public.post("/api/runs", json={"listing_id": "L01"}, headers=hdr)
    assert r.status_code == 429 and "hourly" in r.json()["detail"]
    monkeypatch.setenv("PRAMAN_LIVE_PER_IP_HOUR", "50")
    monkeypatch.setenv("PRAMAN_LIVE_DAILY_CAP", "2")
    reset_settings()
    hdr["X-Forwarded-For"] = "2.2.2.2"  # another caller, but the day is already used up
    r = public.post("/api/runs", json={"listing_id": "L01"}, headers=hdr)
    assert r.status_code == 429 and "Today" in r.json()["detail"]


def test_scan_of_a_new_store_needs_the_code(public):
    r = public.post("/api/scans", json={"url": "https://shop.example"})
    assert r.status_code == 401


def test_local_server_is_unchanged():
    with TestClient(app) as c:  # not public mode (the default): no code, no limits
        h = c.get("/api/health").json()
        assert h["needs_access_code"] is False and h["live_checks"] is False
        r = c.post("/api/runs", json={"url": "https://shop.example/products/x", "mode": "agent"})
        assert r.status_code == 409 and "live mode" in r.json()["detail"]


def test_photos_fall_back_to_the_masked_recording_photos(monkeypatch, tmp_path):
    """A fresh deploy has no downloaded photo files (they aren't in git): demo photos still show."""
    monkeypatch.setattr("praman.tools.fetch.IMAGES_DIR", tmp_path / "no-images")
    with TestClient(app) as c:
        r = c.get("/api/photos/L14/7")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert c.get("/api/photos/L14/99").status_code == 404


def test_a_groq_key_alone_enables_live_checks(monkeypatch):
    from praman.config import Settings

    base = {"praman_llm_mode": "replay", "_env_file": None}
    assert not guard.live_checks_enabled(Settings(**base))
    assert guard.live_checks_enabled(Settings(groq_api_key="gsk", **base))
    assert guard.live_checks_enabled(Settings(gemini_api_key="g", **base))


def test_the_presenters_own_laptop_needs_the_code_but_not_the_limits(monkeypatch):
    from starlette.requests import Request

    def req(host, headers=()):
        hs = [(k.lower().encode(), v.encode()) for k, v in headers]
        return Request({"type": "http", "headers": hs, "client": (host, 5000)})

    assert guard.is_local_presenter(req("127.0.0.1"))
    assert guard.is_local_presenter(req("::1"))
    assert not guard.is_local_presenter(req("127.0.0.1", [("X-Forwarded-For", "1.1.1.1")]))
    assert not guard.is_local_presenter(req("125.20.42.122"))

    monkeypatch.setenv("PRAMAN_PUBLIC_MODE", "1")
    monkeypatch.setenv("PRAMAN_ACCESS_CODE", "open-sesame")
    monkeypatch.setenv("PRAMAN_LIVE_PER_IP_HOUR", "1")
    reset_settings()
    guard.limits.reset()
    local = req("127.0.0.1", [("X-Access-Code", "open-sesame")])
    for _ in range(3):
        guard.require_live_access(local)  # no 429 for the presenter
    with pytest.raises(guard.HTTPException) as e:
        guard.require_live_access(req("127.0.0.1"))  # still needs the code
    assert e.value.status_code == 401
    visitor = req("127.0.0.1", [("X-Access-Code", "open-sesame"), ("X-Forwarded-For", "9.9.9.9")])
    guard.require_live_access(visitor)
    with pytest.raises(guard.HTTPException) as e:
        guard.require_live_access(visitor)  # visitors keep the hourly limit
    assert e.value.status_code == 429
    guard.limits.reset()


def test_open_access_needs_no_code_but_keeps_the_limits(public, monkeypatch):
    monkeypatch.setenv("PRAMAN_OPEN_ACCESS", "1")
    monkeypatch.setenv("PRAMAN_LIVE_PER_IP_HOUR", "2")
    reset_settings()
    assert public.get("/api/health").json()["needs_access_code"] is False
    hdr = {"X-Forwarded-For": "5.5.5.5"}  # a visitor, no access code
    for _ in range(2):
        assert public.post("/api/runs", json={"listing_id": "L01"}, headers=hdr).status_code == 200
    r = public.post("/api/runs", json={"listing_id": "L01"}, headers=hdr)
    assert r.status_code == 429 and "hourly" in r.json()["detail"]
    # internal addresses are still refused, code or no code
    monkeypatch.setattr(socket, "getaddrinfo", _addrs("169.254.169.254"))
    r = public.post(
        "/api/runs",
        json={"url": "http://metadata.example/products/x", "mode": "agent"},
        headers={"X-Forwarded-For": "6.6.6.6"},
    )
    assert r.status_code == 400
    # and the default stays locked: without the setting a missing code means no live checks
    monkeypatch.setenv("PRAMAN_OPEN_ACCESS", "")
    monkeypatch.setenv("PRAMAN_ACCESS_CODE", "")
    reset_settings()
    r = public.post("/api/runs", json={"listing_id": "L01"}, headers={"X-Forwarded-For": "7.7.7.7"})
    assert r.status_code == 403


def test_one_page_is_fetched_at_a_time(public, monkeypatch):
    from praman import api
    from praman.tools.fetch import FetchError

    monkeypatch.setattr(api, "FETCH_WAIT_S", 0.05)
    body = {"url": "https://shop.example/products/x", "mode": "agent"}
    hdr = {"X-Access-Code": "open-sesame"}
    api._fetch_gate.acquire()  # another visitor's page is being fetched
    try:
        r = public.post("/api/runs", json=body, headers=hdr)
        assert r.status_code == 503 and "busy" in r.json()["detail"]
    finally:
        api._fetch_gate.release()

    def failing_fetch(url):
        raise FetchError("couldn't read that page")

    monkeypatch.setattr(api, "fetch_listing", failing_fetch)
    r = public.post("/api/runs", json=body, headers=hdr)
    assert r.status_code == 400  # a failed fetch still answers plainly and frees the gate
    assert api._fetch_gate.acquire(blocking=False)
    api._fetch_gate.release()


def _finished_l14(client):
    run_id = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    t0 = time.monotonic()
    while True:  # the worker writes the run row
        r = client.get(f"/api/runs/{run_id}")
        if r.status_code == 200 and r.json()["run"]["status"] != "running":
            break
        assert time.monotonic() - t0 < 20
        time.sleep(0.05)
    return run_id


def test_reviewer_keys_name_the_signer(monkeypatch):
    monkeypatch.setenv("PRAMAN_REVIEWERS", "Asha Rao:k3y-asha-0001, Ravi:k3y-ravi-0002")
    reset_settings()
    with TestClient(app) as c:
        assert c.get("/api/health").json()["reviewer_access"] == "key"
        run_id = _finished_l14(c)
        v = next(
            v
            for v in c.get(f"/api/runs/{run_id}").json()["verdicts"]
            if v["label"] == "Needs review"
        )
        url = f"/api/runs/{run_id}/reviews/{v['claim_id']}"
        body = {"name": "Someone Else", "decision": "agree"}
        # The role switch alone isn't enough, and a wrong key is refused
        assert c.post(url, json=body, headers={"X-Praman-Role": "reviewer"}).status_code == 401
        assert c.post(url, json=body, headers={"X-Reviewer-Key": "guess-1234"}).status_code == 401
        r = c.post(url, json=body, headers={"X-Reviewer-Key": "k3y-asha-0001"})
        assert r.status_code == 200 and r.json()["reviewer"] == "Asha Rao"  # not the typed name
        for other in c.get(f"/api/runs/{run_id}").json()["verdicts"]:
            if other["label"] == "Needs review" and other["claim_id"] != v["claim_id"]:
                u = f"/api/runs/{run_id}/reviews/{other['claim_id']}"
                assert c.post(u, json=body, headers={"X-Reviewer-Key": "k3y-ravi-0002"}).is_success
        approve = f"/api/runs/{run_id}/approve"
        r = c.post(approve, json={"name": "Typed"}, headers={"X-Reviewer-Key": "k3y-ravi-0002"})
        assert r.status_code == 200 and r.json()["approved_by"] == "Ravi"
        # A signed report keeps its signer
        r = c.post(approve, json={"name": "Typed"}, headers={"X-Reviewer-Key": "k3y-asha-0001"})
        assert r.status_code == 409
        assert c.get(f"/api/runs/{run_id}").json()["run"]["approved_by"] == "Ravi"
    reset_settings()


def test_public_server_without_keys_refuses_visitors_sign_off(public):
    assert public.get("/api/health").json()["reviewer_access"] == "off"
    r = public.post(
        "/api/runs/L14-a-x/approve",
        json={"name": "Visitor"},
        headers={"X-Praman-Role": "reviewer", "X-Forwarded-For": "7.7.7.7"},
    )
    assert r.status_code == 403 and "reviewer keys" in r.json()["detail"]


def test_short_or_nameless_keys_are_ignored(monkeypatch):
    monkeypatch.setenv("PRAMAN_REVIEWERS", "Asha:short, :no-name-key-123, Ravi:long-enough-1")
    reset_settings()
    from praman.config import get_settings

    assert guard.reviewer_keys(get_settings()) == {"long-enough-1": "Ravi"}
    reset_settings()
