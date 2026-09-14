#!/usr/bin/env bash
# Morning digest on the Mac — the launchd twin of systemd/eqr-digest.service.
# Without TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID in .env the CLI prints
# {"sent": false, "reason": "...unset"} and exits 0; set them and the next run sends.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
"$ROOT/.venv/bin/eqr" digest --send
