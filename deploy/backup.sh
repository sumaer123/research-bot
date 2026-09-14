#!/usr/bin/env bash
# restic backup of the data directory (DuckDB, raw archives, documents, reports).
# Needs RESTIC_REPOSITORY, RESTIC_PASSWORD, B2_ACCOUNT_ID, B2_ACCOUNT_KEY in /opt/eqr/.env.
set -euo pipefail
cd /opt/eqr
if [ -z "${RESTIC_REPOSITORY:-}" ]; then echo "RESTIC_REPOSITORY unset; skipping backup"; exit 0; fi
restic backup data --exclude 'data/raw/nse/bhav' --exclude 'data/raw/nse/mto' --exclude 'data/packs' --tag eqr --quiet
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune --quiet
