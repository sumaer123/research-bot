#!/usr/bin/env bash
# Daily EOD refresh on the Mac — the launchd twin of systemd/eqr-refresh.service.
# prices, index, snapshots, factors, universe, quality; then corporate reference
# for the trailing 45 days (BSD date, so -v-45d rather than GNU's -d '-45 days').
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] refresh start"
"$ROOT/.venv/bin/eqr" refresh
"$ROOT/.venv/bin/eqr" reference --from "$(date -v-45d +%Y-%m-%d)"
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] refresh done"
