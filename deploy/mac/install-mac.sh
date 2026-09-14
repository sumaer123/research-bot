#!/usr/bin/env bash
# Idempotent install of the Sumaer Research Bot as launchd user agents on this Mac —
# the macOS twin of deploy/install.sh (Ubuntu/systemd). Re-run after every pull; it
# re-renders the plists from deploy/mac/launchd/, reloads only what it manages, and
# leaves data/ and .env alone.
#
#   deploy/mac/install-mac.sh            # install / refresh all four agents
#   deploy/mac/install-mac.sh --remove   # unload and delete them
#
# Jobs (all exec .venv/bin/python; chains live in deploy/mac/jobs.py):
#       com.eqr.web (dashboard + advisor API, 127.0.0.1:8801, KeepAlive),
#       com.eqr.refresh (19:45 daily), com.eqr.fundamentals (Sat 02:00),
#       com.eqr.digest (07:30 daily). No backup agent: restic/B2 is a VM concern;
#       on the Mac data/ sits on the local disk (Time Machine covers it).
#
# Logs go to ~/Library/Logs/eqr/ on purpose: launchd cannot write under ~/Desktop
# or ~/Documents (TCC), and a job whose log path is protected dies with exit 78.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGS="$HOME/Library/Logs/eqr"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=(com.eqr.web com.eqr.refresh com.eqr.fundamentals com.eqr.digest)

if [ "${1:-}" = "--remove" ]; then
  for l in "${LABELS[@]}"; do
    launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
    rm -f "$AGENTS/$l.plist"
  done
  echo "eqr launchd agents removed"
  exit 0
fi

[ -x "$ROOT/.venv/bin/python" ] || { echo "no venv at $ROOT/.venv — run: uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e '.[dev]'" >&2; exit 1; }
# The agents exec .venv/bin/python directly (never the eqr console script, which
# is a /bin/sh trampoline): the project sits under ~/Downloads, TCC lets only a
# binary holding the Downloads grant run there, and launchd cannot prompt. TCC
# keys the grant to the REAL executable, so check that path. A shell that cannot
# read the TCC db reports "unknown" rather than failing the install.
PY_REAL="$(cd "$ROOT/.venv/bin" && cd "$(dirname "$(readlink python)")" && pwd -P)/$(basename "$(readlink "$ROOT/.venv/bin/python")")"
GRANT="$(sqlite3 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" \
  "select auth_value from access where service='kTCCServiceSystemPolicyDownloadsFolder' and client='$PY_REAL'" 2>/dev/null || echo unknown)"
case "$GRANT" in
  2) echo "TCC: $PY_REAL holds the Downloads grant";;
  unknown|"") echo "TCC: could not read the grant for $PY_REAL (db not readable from this shell) — if agents exit 126, grant it under System Settings > Privacy & Security > Files and Folders";;
  *) echo "TCC: $PY_REAL does NOT hold the Downloads grant (auth_value=$GRANT); the agents will exit 126 until it is granted under System Settings > Privacy & Security > Files and Folders" >&2; exit 1;;
esac
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
# A .env line like `NAME=   # note` makes python-dotenv read "# note" as the
# VALUE — the first install shipped one and pointed the database at a comment.
# Refuse to load agents over a poisoned file; fixing .env is the owner's call.
if grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=[[:space:]]*#' "$ROOT/.env"; then
  echo "refusing: $ROOT/.env has an inline comment after an empty value (dotenv reads it as the value):" >&2
  grep -En '^[A-Za-z_][A-Za-z0-9_]*=[[:space:]]*#' "$ROOT/.env" | cut -d= -f1 >&2
  echo "put comments on their own lines (see .env.example), then re-run" >&2
  exit 1
fi
case "$ROOT" in "$HOME/Desktop"*|"$HOME/Documents"*) echo "refusing: $ROOT is under a TCC-protected folder; launchd jobs cannot run from there" >&2; exit 1;; esac
mkdir -p "$LOGS" "$AGENTS"

for l in "${LABELS[@]}"; do
  sed -e "s#__ROOT__#$ROOT#g" -e "s#__LOGS__#$LOGS#g" "$ROOT/deploy/mac/launchd/$l.plist" > "$AGENTS/$l.plist"
  plutil -lint -s "$AGENTS/$l.plist"
  launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$AGENTS/$l.plist"
done

# The web agent starts on load; the calendar agents wait for their slot.
launchctl kickstart -k "$DOMAIN/com.eqr.web"
sleep 3
for l in "${LABELS[@]}"; do
  printf '%-22s %s\n' "$l" "$(launchctl print "$DOMAIN/$l" 2>/dev/null | awk '/state =/{print $3; exit}')"
done
curl -s -o /dev/null -w 'web /health -> HTTP %{http_code}\n' http://127.0.0.1:8801/health || echo "web /health -> not reachable yet"
echo "eqr installed from $ROOT; logs in $LOGS"
