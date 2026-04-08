#!/usr/bin/env bash
# Filename: scripts/update_seevar.sh
# Version: 1.1.0
# Objective: Compatibility wrapper around the repo-root upgrade helper for existing local checkouts.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${1:-main}"

SEEVAR_BRANCH="$BRANCH" exec "$ROOT_DIR/upgrade.sh" "$ROOT_DIR"
