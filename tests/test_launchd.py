"""The macOS deployment assets: launchd templates and their wrapper scripts.

The Ubuntu path is covered by systemd unit files a human reads; the Mac path is
rendered by install-mac.sh from templates, so a typo in a template would only
surface at 19:45 the next day as a job that never ran. These pin the shape.
"""
from __future__ import annotations

import os
import plistlib
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "deploy" / "mac"
LAUNCHD = MAC / "launchd"

EXPECTED = {
    "com.eqr.web": None,
    "com.eqr.refresh": {"Hour": 19, "Minute": 45},
    "com.eqr.fundamentals": {"Weekday": 6, "Hour": 2, "Minute": 0},
    "com.eqr.digest": {"Hour": 7, "Minute": 30},
}


def _render(label: str) -> dict:
    text = (LAUNCHD / f"{label}.plist").read_text()
    assert "__ROOT__" in text and "__LOGS__" in text, f"{label}: template must carry both placeholders"
    rendered = text.replace("__ROOT__", "/opt/eqr").replace("__LOGS__", "/var/log/eqr")
    return plistlib.loads(rendered.encode())


def test_every_agent_renders_to_a_valid_plist_with_its_label():
    for label in EXPECTED:
        d = _render(label)
        assert d["Label"] == label
        assert d["WorkingDirectory"] == "/opt/eqr"
        assert d["ProgramArguments"][0].startswith("/opt/eqr/")
        assert d["StandardOutPath"].startswith("/var/log/eqr/")
        assert d["StandardErrorPath"].startswith("/var/log/eqr/")


def test_schedules_mirror_the_systemd_timers():
    for label, cal in EXPECTED.items():
        d = _render(label)
        if cal is None:
            assert d["KeepAlive"] is True and d["RunAtLoad"] is True
            assert "StartCalendarInterval" not in d
        else:
            assert d["StartCalendarInterval"] == cal
            assert "KeepAlive" not in d


def test_web_agent_binds_loopback_on_8801():
    args = _render("com.eqr.web")["ProgramArguments"]
    assert args[1:] == ["web", "--host", "127.0.0.1", "--port", "8801"]


def test_wrapper_scripts_are_executable_and_chain_the_right_commands():
    for name, needles in {
        "refresh.sh": ["eqr\" refresh", "reference --from", "date -v-45d"],
        "fundamentals.sh": ["fundamentals --rate 1.5", "features", "rank --sleeve L", "rank --sleeve S"],
        "digest.sh": ["digest --send"],
        "install-mac.sh": ["Library/Logs/eqr", "launchctl bootstrap", "plutil -lint", "--remove"],
    }.items():
        p = MAC / name
        assert p.stat().st_mode & stat.S_IXUSR, f"{name} must be executable"
        text = p.read_text()
        assert text.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in text
        for needle in needles:
            assert needle in text, f"{name} lacks {needle!r}"


def test_logs_live_under_library_logs_not_a_tcc_protected_folder():
    # launchd cannot write under ~/Desktop or ~/Documents; a job logging there dies
    # with exit 78. The installer owns the log root; every template must log through it.
    installer = (MAC / "install-mac.sh").read_text()
    assert 'LOGS="$HOME/Library/Logs/eqr"' in installer
    for p in LAUNCHD.glob("*.plist"):
        text = p.read_text()
        assert text.count("__LOGS__/") == 2, f"{p.name} must route stdout and stderr through __LOGS__"
