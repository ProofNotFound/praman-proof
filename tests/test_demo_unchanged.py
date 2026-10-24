"""The four demo cases replay exactly as recorded (week 2 must not change them): a fresh offline
run of each listing, in both modes, emits the same events as data/recordings/, ignoring only run
ids, timings and photo URLs."""

import json

import pytest

from praman.agent import run_listing
from praman.config import RECORDINGS_DIR
from praman.tools.fetch import load_cached

VOLATILE = {"run_id", "started_at", "t_ms", "ms", "elapsed_ms"}


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _comparable(events):
    out = []
    for e in events:
        data = json.loads(json.dumps(e["data"], ensure_ascii=False))
        if e["type"] == "listing":
            for p in data["photos"]:
                p.pop("url", None)
        out.append((e["seq"], e["type"], _clean(data)))
    return out


@pytest.mark.parametrize("lid", ["L14", "L06", "L08", "L21"])
@pytest.mark.parametrize("mode", ["agent", "baseline"])
def test_demo_run_matches_its_recording(lid, mode):
    recorded = json.loads((RECORDINGS_DIR / f"{lid}.{mode}.json").read_text())["events"]
    events: list[dict] = []
    run_listing(load_cached(lid), mode, on_event=events.append)
    got, want = _comparable(events), _comparable(recorded)
    for g, w in zip(got, want, strict=False):
        assert g == w, (lid, mode, g[0], g[1])
    assert len(got) == len(want)
