"""Settings from environment (.env loaded once). Paths are absolute."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

IST = ZoneInfo("Asia/Kolkata")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v in (None, ""):
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Curated Indian financial-news domains used by default. This is the code default so an UNSET
# var is safe (restricted). Setting EQR_WEB_ALLOWED_DOMAINS to the empty string is the explicit
# opt-out ("allow all", i.e. no client-side domain filter).
DEFAULT_WEB_ALLOWED_DOMAINS = (
    "nseindia.com", "bseindia.com", "screener.in", "moneycontrol.com",
    "economictimes.indiatimes.com", "business-standard.com", "livemint.com",
)


def _domains(name: str) -> tuple[str, ...]:
    v = os.environ.get(name)
    if v is None:
        return DEFAULT_WEB_ALLOWED_DOMAINS
    return tuple(d.strip() for d in v.split(",") if d.strip())


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    rate_limit_s: float
    proxy: str
    advisor_token: str
    web_host: str
    web_port: int
    telegram_token: str
    telegram_chat_id: str
    anthropic_api_key: str
    claude_model: str
    risk_free_pct: float
    parallel_enabled: bool
    parallel_mcp_url: str
    parallel_max_calls_per_run: int
    web_allowed_domains: tuple[str, ...]
    web_lookback_days: int
    web_fetch_top_k: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "eqr.duckdb"

    @property
    def web_dir(self) -> Path:
        return self.data_dir / "web"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def packs_dir(self) -> Path:
        return self.data_dir / "packs"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def settings() -> Settings:
    data_dir = Path(_env("EQR_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
    return Settings(
        data_dir=data_dir,
        rate_limit_s=float(_env("EQR_RATE_LIMIT_S", "1.0")),
        proxy=_env("EQR_PROXY"),
        advisor_token=_env("EQR_ADVISOR_TOKEN"),
        web_host=_env("EQR_WEB_HOST", "127.0.0.1"),
        web_port=int(_env("EQR_WEB_PORT", "8801")),
        telegram_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        claude_model=_env("EQR_CLAUDE_MODEL", "claude-opus-5"),
        risk_free_pct=float(_env("EQR_RISK_FREE_PCT", "6.0")),
        parallel_enabled=_bool("EQR_PARALLEL_ENABLED", True),
        parallel_mcp_url=_env("EQR_PARALLEL_MCP_URL", "https://search.parallel.ai/mcp"),
        parallel_max_calls_per_run=int(_env("EQR_PARALLEL_MAX_CALLS_PER_RUN", "8")),
        web_allowed_domains=_domains("EQR_WEB_ALLOWED_DOMAINS"),
        web_lookback_days=int(_env("EQR_WEB_LOOKBACK_DAYS", "180")),
        web_fetch_top_k=int(_env("EQR_WEB_FETCH_TOP_K", "3")),
    )
