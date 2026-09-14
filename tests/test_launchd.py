"""The macOS deployment assets: launchd templates and their wrapper scripts.

The Ubuntu path is covered by systemd unit files a human reads; the Mac path is
rendered by install-mac.sh from templates, so a typo in a template would only
surface at 19:45 the next day as a job that never ran. These pin the shape.
"""
from __future__ import annotations

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
        # The project sits under ~/Downloads (TCC): launchd must exec the venv's
        # Python itself, which holds the Downloads grant — never a /bin/sh or bash
        # trampoline, which does not. The first cut did, and every spawn exited 126.
        assert d["ProgramArguments"][0] == "/opt/eqr/.venv/bin/python"
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
    assert args[1:] == ["-m", "eqr.cli", "web", "--host", "127.0.0.1", "--port", "8801"]


def test_calendar_agents_run_the_job_runner_with_their_own_job():
    for label in ("com.eqr.refresh", "com.eqr.fundamentals", "com.eqr.digest"):
        args = _render(label)["ProgramArguments"]
        assert args[1:] == ["/opt/eqr/deploy/mac/jobs.py", label.rsplit(".", 1)[1]]


def test_job_runner_chains_mirror_the_systemd_units():
    import importlib.util
    from datetime import date

    spec = importlib.util.spec_from_file_location("eqr_mac_jobs", MAC / "jobs.py")
    jobs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jobs)
    chains = jobs.chains(date(2026, 9, 14))
    assert chains["refresh"] == [["refresh"], ["reference", "--from", "2026-07-31"]]
    assert chains["fundamentals"] == [
        ["fundamentals", "--rate", "1.5"], ["features"], ["rank", "--sleeve", "L"], ["rank", "--sleeve", "S"],
    ]
    assert chains["digest"] == [["digest", "--send"]]
    assert jobs.main(["jobs.py"]) == 2          # no job → usage, nothing run
    assert jobs.main(["jobs.py", "nope"]) == 2


def test_installer_is_executable_and_checks_what_matters():
    p = MAC / "install-mac.sh"
    assert p.stat().st_mode & stat.S_IXUSR, "install-mac.sh must be executable"
    text = p.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    for needle in ["Library/Logs/eqr", "launchctl bootstrap", "plutil -lint", "--remove",
                   ".venv/bin/python", "kTCCServiceSystemPolicyDownloadsFolder"]:
        assert needle in text, f"install-mac.sh lacks {needle!r}"


def test_logs_live_under_library_logs_not_a_tcc_protected_folder():
    # launchd cannot write under ~/Desktop or ~/Documents; a job logging there dies
    # with exit 78. The installer owns the log root; every template must log through it.
    installer = (MAC / "install-mac.sh").read_text()
    assert 'LOGS="$HOME/Library/Logs/eqr"' in installer
    for p in LAUNCHD.glob("*.plist"):
        text = p.read_text()
        assert text.count("__LOGS__/") == 2, f"{p.name} must route stdout and stderr through __LOGS__"


def test_env_example_parses_to_empty_values_not_comments():
    # python-dotenv reads `NAME=   # note` as the value "# note". The first Mac
    # install copied such a file to .env and pointed the database at a comment.
    from dotenv import dotenv_values

    values = dotenv_values(ROOT / ".env.example")
    poisoned = {k: v for k, v in values.items() if v and v.lstrip().startswith("#")}
    assert poisoned == {}, poisoned
    assert values["EQR_DATA_DIR"] == "" and values["EQR_ADVISOR_TOKEN"] == "" and values["EQR_PROXY"] == ""
    installer = (MAC / "install-mac.sh").read_text()
    assert "=[[:space:]]*#" in installer, "install-mac.sh must refuse a poisoned .env"
