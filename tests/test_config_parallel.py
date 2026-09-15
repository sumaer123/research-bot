"""T1: Parallel / web-research settings. Defaults live in code so an unset var is safe;
an explicitly-empty EQR_WEB_ALLOWED_DOMAINS means 'allow all' (the override)."""
from pathlib import Path

import pytest

PARALLEL_VARS = ("EQR_PARALLEL_ENABLED", "EQR_PARALLEL_MCP_URL", "EQR_PARALLEL_MAX_CALLS_PER_RUN",
                 "EQR_WEB_ALLOWED_DOMAINS", "EQR_WEB_LOOKBACK_DAYS", "EQR_WEB_FETCH_TOP_K")


@pytest.fixture()
def clean_env(monkeypatch):
    for v in PARALLEL_VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_defaults(clean_env):
    from eqr.config import settings
    s = settings()
    assert s.parallel_enabled is True
    assert s.parallel_mcp_url == "https://search.parallel.ai/mcp"
    assert s.parallel_max_calls_per_run == 8
    assert s.web_lookback_days == 180
    assert s.web_fetch_top_k == 3
    assert "nseindia.com" in s.web_allowed_domains and "screener.in" in s.web_allowed_domains
    assert s.web_dir == s.data_dir / "web"


def test_enabled_toggle(clean_env):
    from eqr.config import settings
    clean_env.setenv("EQR_PARALLEL_ENABLED", "0")
    assert settings().parallel_enabled is False
    clean_env.setenv("EQR_PARALLEL_ENABLED", "true")
    assert settings().parallel_enabled is True


def test_explicit_empty_domains_allows_all(clean_env):
    from eqr.config import settings
    clean_env.setenv("EQR_WEB_ALLOWED_DOMAINS", "")
    assert settings().web_allowed_domains == ()          # empty = no client-side filter


def test_domains_parsed_and_trimmed(clean_env):
    from eqr.config import settings
    clean_env.setenv("EQR_WEB_ALLOWED_DOMAINS", " a.com , b.co.in ,")
    assert settings().web_allowed_domains == ("a.com", "b.co.in")


def test_env_example_documents_the_new_names():
    root = Path(__file__).resolve().parent.parent
    text = (root / ".env.example").read_text()
    for name in PARALLEL_VARS:
        assert name in text, name
