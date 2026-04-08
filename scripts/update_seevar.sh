#!/usr/bin/env bash
# Filename: scripts/update_seevar.sh
# Version: 1.0.0
# Objective: Fast-forward a local SeeVar checkout, refresh Python dependencies, and run lightweight sanity checks.

set -euo pipefail

BRANCH="${1:-main}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python"

cd "$ROOT_DIR"

echo "[update] fetching origin"
git fetch origin

echo "[update] switching to $BRANCH"
git checkout "$BRANCH"

echo "[update] pulling latest changes"
git pull --ff-only origin "$BRANCH"

echo "[update] ensuring local data directory exists"
mkdir -p "$ROOT_DIR/data"

if [[ -x "$VENV_PY" ]]; then
  echo "[update] refreshing pip and requirements"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r requirements.txt

  echo "[update] running syntax check"
  "$VENV_PY" -m py_compile $(git ls-files '*.py')
else
  echo "[update] warning: no .venv at $VENV_PY, skipped dependency refresh and syntax check"
fi

echo "[update] done"
