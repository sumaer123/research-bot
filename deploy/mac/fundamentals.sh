#!/usr/bin/env bash
# Weekly fundamentals sweep on the Mac — the launchd twin of
# systemd/eqr-fundamentals.service (launchd has no ExecStartPost, so the chain
# lives here): screener sweep + reference, then features and both sleeve ranks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] fundamentals start"
"$ROOT/.venv/bin/eqr" fundamentals --rate 1.5
"$ROOT/.venv/bin/eqr" features
"$ROOT/.venv/bin/eqr" rank --sleeve L
"$ROOT/.venv/bin/eqr" rank --sleeve S
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] fundamentals done"
