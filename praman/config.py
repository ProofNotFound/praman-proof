"""Settings from the environment and .env (TRD §13). Never log secret values."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
LISTINGS_DIR = CACHE_DIR / "listings"
IMAGES_DIR = CACHE_DIR / "images"
RULES_PATH = DATA_DIR / "rules.json"
RULE_PACKS_DIR = DATA_DIR / "rule_packs"
SEED_PATH = DATA_DIR / "listings_seed.csv"
CPCB_PATH = DATA_DIR / "cpcb_certified.csv"
RECORDINGS_DIR = DATA_DIR / "recordings"
REPLAY_DIR = ROOT / "tests" / "fixtures" / "replay"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

CPCB_LIST_DATE = "2023-10-26"
CPCB_LIST_DATE_TEXT = "26 Oct 2023"
USER_AGENT = "PramanResearchBot/0.1 (student hackathon project)"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)

    gemini_api_key: str = Field(default="", repr=False)
    praman_model: str = "gemini-3.8-flash"  # the model the replay fixtures were recorded with
    praman_fallback_model: str = ""
    # Live calls can go to another provider first. "groq:<model id>" is Groq; empty means the
    # models above. The replay cache key still uses praman_model, so recorded runs keep replaying.
    groq_api_key: str = Field(default="", repr=False)
    praman_live_model: str = ""  # text-only calls, e.g. groq:openai/gpt-oss-120b
    # Groq models tried in order for the web search ("groq:openai/gpt-oss-120b, groq:openai/gpt-oss-20b");
    # empty = the live model above when it is a gpt-oss model. Gemini is never used for the search.
    praman_search_models: str = ""
    praman_live_vision_model: str = ""  # calls with photos, e.g. groq:qwen/qwen3.8-27b
    # Short calls (planning, rewording) on a second model: Groq counts tokens per model, so this
    # leaves more room for the heavy calls, e.g. groq:llama-3.3-70b-versatile
    praman_live_short_model: str = ""
    praman_groq_reasoning: Literal["low", "medium", "high"] = "medium"  # gpt-oss thinking effort
    praman_llm_mode: Literal["live", "replay", "offline"] = "replay"
    praman_max_photos: int = 5
    praman_max_followups: int = 2
    praman_timeout_s: int = 45
    praman_groq_timeout_s: int = 20  # one Groq request; a stuck one gives way to the next model
    praman_db_path: str = "data/praman.db"
    praman_anonymise: bool = True
    # A server on the public internet (docs/DEPLOY.md): internal addresses are never fetched, and
    # checks beyond the demo cases need the access code, a per-address limit and a daily cap.
    praman_public_mode: bool = False
    praman_access_code: str = Field(default="", repr=False)
    # Public server with no access code: anyone may run a live check, still within the limits below
    # and the guard against internal addresses. Off unless set, so a missing code stays locked.
    praman_open_access: bool = False
    # Named reviewers and their keys, "Asha:key1, Ravi:key2". When set, deciding a claim and
    # signing a report need a key, and the server signs with the name tied to it. A public server
    # without them refuses sign-off to visitors (the presenter's own laptop keeps the role switch).
    praman_reviewers: str = Field(default="", repr=False)
    praman_live_per_ip_hour: int = 6
    praman_live_daily_cap: int = 20
    # Estimate when .env leaves prices empty: Flash list prices ($0.30 in, $2.50 out per M) at ₹88/$
    praman_price_in_per_m_inr: float = 26.4
    praman_price_out_per_m_inr: float = 220.0
    # Budgets (TRD §8.1)
    praman_max_tool_calls: int = 30
    praman_max_model_calls: int = 12
    praman_max_wall_s: int = 90

    @property
    def db_path(self) -> Path:
        p = Path(self.praman_db_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def has_api_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_groq_key(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Forget cached settings (tests change env vars between cases)."""
    get_settings.cache_clear()
