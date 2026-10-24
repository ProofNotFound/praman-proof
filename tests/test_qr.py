"""W4: QR codes on pack photos. Codes are generated with cv2.QRCodeEncoder; no network."""

import cv2
import numpy as np
import pytest

from praman import agent
from praman.agent import TOOLS, ToolCall, act_decode_qr, default_next, options_for
from praman.events import validate_event
from praman.models import Photo, QrCode
from praman.rules import match_rules
from praman.run import RunContext
from praman.tools.qr import decode_image, has_stored_codes, listing_codes
from praman.verdict import ClaimState, decide_verdict
from tests.helpers import claim, listing

SAME = "https://shop.example/pages/compost-certificate"
OTHER = "https://qr-short.example/a1b2"


def qr_png(path, *texts, noise=False):
    """A white canvas with one QR code per text, side by side."""
    enc = cv2.QRCodeEncoder.create()
    tiles = []
    for t in texts:
        q = cv2.resize(enc.encode(t), None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
        tiles.append(cv2.copyMakeBorder(q, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255))
    h = max(t.shape[0] for t in tiles)
    img = np.hstack(
        [
            cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=255)
            for t in tiles
        ]
    )
    if noise:
        rng = np.random.default_rng(7)
        mask = rng.random(img.shape) < 0.45
        img = img.copy()
        img[mask] = 255 - img[mask]
    cv2.imwrite(str(path), img)
    return path


def test_decodes_same_and_other_domain_codes_with_boxes(tmp_path):
    codes = decode_image(qr_png(tmp_path / "two.png", SAME, OTHER))
    assert {c.data for c in codes} == {SAME, OTHER}
    for c in codes:
        y0, x0, y1, x1 = c.box_2d
        assert 0 <= y0 < y1 <= 1000 and 0 <= x0 < x1 <= 1000
    left = next(c for c in codes if c.data == SAME)
    assert left.box_2d[3] <= 520  # the first code sits in the left half


def test_unreadable_code_gives_nothing(tmp_path):
    assert decode_image(qr_png(tmp_path / "noisy.png", SAME, noise=True)) == []
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((200, 200), 255, np.uint8))
    assert decode_image(blank) == []
    assert decode_image(tmp_path / "missing.png") == []


def _qr_listing(codes_by_photo):
    lst = listing(title="Compostable bags", body="100% compostable bags.", n_photos=3)
    lst.photos = [
        Photo(index=i, url=f"https://cdn.example/{i}.jpg", qr=codes_by_photo.get(i, []))
        for i in (1, 2, 3)
    ]
    return lst


def test_planner_is_offered_decode_qr_only_after_photos_and_only_with_stored_codes():
    lst = _qr_listing({3: [QrCode(data=OTHER, box_2d=[100, 100, 300, 300])]})
    ctx = RunContext(lst, "agent")
    c = claim("100% compostable bags")
    c.rule_ids = match_rules(c, lst)
    state = ClaimState(claim=c, rule_ids=c.rule_ids, searched=["text"])
    assert "decode_qr" not in options_for(ctx, state)  # photos not looked at yet
    state.searched.append("photos")
    opts = options_for(ctx, state)
    assert "decode_qr" in opts and "photo 3" in opts["decode_qr"]
    assert default_next(opts).tool == "decode_qr"  # text → photos → QR → registry → link
    # A listing cached before W4 (qr is None) is never offered the tool: recorded runs stay as-is
    old = _qr_listing({})
    for p in old.photos:
        p.qr = None
    assert not has_stored_codes(old)
    ctx_old = RunContext(old, "agent")
    assert "decode_qr" not in options_for(
        ctx_old, ClaimState(claim=c, rule_ids=c.rule_ids, searched=["text", "photos"])
    )
    assert "decode_qr" in TOOLS and ToolCall(tool="decode_qr", why="x").tool == "decode_qr"


def test_same_site_code_is_followed_and_other_domain_is_noted(monkeypatch):
    lst = _qr_listing(
        {
            2: [QrCode(data=SAME, box_2d=[100, 100, 300, 300])],
            3: [QrCode(data=OTHER, box_2d=[500, 500, 700, 700])],
        }
    )
    opened = []

    def fake_page(url, listing_):
        opened.append(url)
        return {
            "url": url,
            "text": "Compostable bags are certified to EN 13432 by TÜV.",
            "certificates": ["EN 13432", "TÜV"],
        }

    monkeypatch.setattr(agent, "fetch_linked_page", fake_page)
    events: list[dict] = []
    ctx = RunContext(lst, "agent", on_event=events.append)
    c = claim("100% compostable bags")
    c.rule_ids = match_rules(c, lst)
    ctx.set_claims([c])
    state = ClaimState(claim=c, rule_ids=c.rule_ids, searched=["text", "photos"])
    summary = act_decode_qr(ctx, state, use_model=False)
    assert opened == [SAME]  # only the store's own link is opened (CLAUDE.md rule 10)
    assert "not followed" in summary and "qr" in state.searched
    by_kind = {e.kind: e for e in state.evidence}
    same = by_kind["disclosure_link"]
    assert same.qr == {
        "domain": "shop.example",
        "followed": True,
        "path": "/pages/compost-certificate",
    }
    assert same.photo_index == 2 and same.crop_box == (100, 100, 300, 300)
    off = by_kind["qr_link"]
    assert off.detail == "QR code links to qr-short.example; not followed"
    assert off.covers_claim == "no" and off.qr == {"domain": "qr-short.example", "followed": False}
    for e in events:
        validate_event(e)
    ev_events = [e["data"] for e in events if e["type"] == "evidence"]
    assert any(d.get("qr", {}).get("followed") is False for d in ev_events)
    # The claim stays Needs review with that reason
    v = decide_verdict(state).verdict
    assert v.label.value == "Needs review"
    assert v.reason.startswith("QR code links to qr-short.example; not followed")
    assert off.id in v.evidence_ids


def test_listing_codes_prefers_stored_codes():
    lst = _qr_listing({1: [QrCode(data="hello")]})
    assert listing_codes(lst) == {1: [QrCode(data="hello")]}


@pytest.mark.parametrize("text", ["plain text on the pack"])
def test_text_codes_are_read_but_not_followed(monkeypatch, text):
    lst = _qr_listing({1: [QrCode(data=text, box_2d=[1, 1, 50, 50])]})
    monkeypatch.setattr(agent, "fetch_linked_page", lambda *a: pytest.fail("no link to open"))
    ctx = RunContext(lst, "agent")
    c = claim("100% compostable bags")
    c.rule_ids = match_rules(c, lst)
    ctx.set_claims([c])
    state = ClaimState(claim=c, rule_ids=c.rule_ids, searched=["text", "photos"])
    out = act_decode_qr(ctx, state, use_model=False)
    assert "not a link" in out and state.evidence == []
