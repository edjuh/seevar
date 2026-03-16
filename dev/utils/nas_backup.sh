#!/bin/bash
# 🛰️ SeeVar: Sovereign Snapshot Utility
# Version: 1.3.0
# Objective: Backup SeeVar code and logic to NAS.

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BASE_DEST="/mnt/astronas/backup"
SNAPSHOT_DEST="$BASE_DEST/seevar_$TIMESTAMP"
SOURCE_DIR="/home/ed/seevar"

echo "📦 Initiating SeeVar Snapshot..."
mkdir -p "$SNAPSHOT_DEST"

rsync -av --delete \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='data/' \
  --exclude='logs/*.log' \
  --exclude='.git/' \
  "$SOURCE_DIR/" "$SNAPSHOT_DEST/"

ln -sfn "$SNAPSHOT_DEST" "$BASE_DEST/seevar_latest"
find "$BASE_DEST" -maxdepth 1 -name "seevar_*" -type d -mtime +30 -exec rm -rf {} +

echo "✅ SeeVar Snapshot secured at: $SNAPSHOT_DEST"
