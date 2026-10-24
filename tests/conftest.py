"""Test setup: offline model mode, a throwaway database, and no way to reach the network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _recorded_model() -> str:
    for f in sorted((FIXTURES / "replay").glob("*.json")):
        model = json.loads(f.read_text()).get("model")
        if model:
            return model
    return "gemini-3.8-flash"


os.environ["PRAMAN_LLM_MODE"] = "offline"
os.environ["PRAMAN_ANONYMISE"] = "1"
os.environ["PRAMAN_MODEL"] = _recorded_model()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from praman import db, llm
    from praman.config import reset_settings

    monkeypatch.setenv("PRAMAN_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("PRAMAN_LLM_MODE", "offline")
    reset_settings()
    db.close_all()

    def _no_client():
        raise AssertionError("tests must not create a model client")

    monkeypatch.setattr(llm, "_get_client", _no_client)
    yield
    db.close_all()
    reset_settings()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
