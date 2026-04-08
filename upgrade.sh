#!/usr/bin/env bash
# Filename: upgrade.sh
# Version: 1.0.0
# Objective: Upgrade an existing SeeVar checkout in-place without overwriting local config.toml.

set -euo pipefail

TARGET_DIR="${1:-$PWD}"
BRANCH="${SEEVAR_BRANCH:-main}"
VENV_PY="$TARGET_DIR/.venv/bin/python"

if [[ ! -d "$TARGET_DIR/.git" ]]; then
  echo "[upgrade] error: $TARGET_DIR is not a git checkout"
  echo "[upgrade] usage: cd ~/seevar && curl -fsSL https://raw.githubusercontent.com/edjuh/seevar/main/upgrade.sh | bash"
  exit 1
fi

cd "$TARGET_DIR"

echo "[upgrade] working tree: $TARGET_DIR"
echo "[upgrade] branch: $BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[upgrade] error: local changes detected; please commit or stash them first"
  git status --short
  exit 1
fi

echo "[upgrade] fetching origin"
git fetch origin

echo "[upgrade] switching to $BRANCH"
git checkout "$BRANCH"

echo "[upgrade] pulling latest changes"
git pull --ff-only origin "$BRANCH"

echo "[upgrade] ensuring local data directory exists"
mkdir -p "$TARGET_DIR/data"

if [[ -x "$VENV_PY" ]]; then
  echo "[upgrade] refreshing pip and requirements"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r requirements.txt

  echo "[upgrade] running syntax check"
  "$VENV_PY" -m py_compile $(git ls-files '*.py')
else
  echo "[upgrade] warning: no .venv at $VENV_PY, skipped dependency refresh and syntax check"
fi

echo "[upgrade] config.toml was not modified"
echo "[upgrade] done"
