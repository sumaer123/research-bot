"""Job runner for the Mac launchd agents.

launchd execs this file's interpreter, and that choice is the whole point.

The project lives under ~/Downloads, which macOS guards with TCC. A launchd
agent gets no prompt, so whatever binary launchd execs must already hold the
Downloads-folder grant — and TCC keys the grant to the real executable. The uv
Python this venv points at holds it (so does Homebrew's node, which is why the
Dobby worker runs from the same tree); Apple's /bin/sh and bash never will.
The first cut of these agents ran the `eqr` console script — a `#!/bin/sh`
trampoline — and every spawn died with exit 126, "Operation not permitted",
39 respawns before anyone looked. So each agent execs `.venv/bin/python`
directly with this script, and every step below is a child of that granted
process (children inherit the parent's TCC responsibility).

Mirrors the systemd units in deploy/systemd/ (launchd has no ExecStartPost):

    jobs.py refresh        eqr refresh; eqr reference --from <45 days ago>
    jobs.py fundamentals   eqr fundamentals --rate 1.5; features; rank L; rank S
    jobs.py digest         eqr digest --send   (prints "sent": false until Telegram is set)

Check the grant without guessing (run from a terminal that can read the TCC db):

    sqlite3 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" \
      "select client, auth_value from access where service='kTCCServiceSystemPolicyDownloadsFolder'"
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def chains(today: date | None = None) -> dict[str, list[list[str]]]:
    """The eqr sub-commands each job runs, in order. `today` is injectable for tests."""
    today = today or date.today()
    return {
        "refresh": [
            ["refresh"],
            ["reference", "--from", (today - timedelta(days=45)).isoformat()],
        ],
        "fundamentals": [
            ["fundamentals", "--rate", "1.5"],
            ["features"],
            ["rank", "--sleeve", "L"],
            ["rank", "--sleeve", "S"],
        ],
        "digest": [["digest", "--send"]],
    }


def main(argv: list[str]) -> int:
    known = chains()
    job = argv[1] if len(argv) > 1 else ""
    if job not in known:
        print(f"usage: jobs.py {{{'|'.join(known)}}}", file=sys.stderr)
        return 2
    stamp = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    print(f"[{stamp()}] {job} start", flush=True)
    for step in known[job]:
        print(f"[{stamp()}] eqr {' '.join(step)}", flush=True)
        subprocess.run([sys.executable, "-m", "eqr.cli", *step], cwd=ROOT, check=True)
    print(f"[{stamp()}] {job} done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
