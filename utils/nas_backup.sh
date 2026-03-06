#!/bin/bash
# 🛰️ S30-PRO Federation: Point-in-Time Code Snapshot

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BASE_DEST="/mnt/astronas/backup"
SNAPSHOT_DEST="$BASE_DEST/federation_$TIMESTAMP"
SOURCE_DIR="/home/ed/seestar_organizer"

echo "📦 Initiating snapshot: federation_$TIMESTAMP..."
mkdir -p "$SNAPSHOT_DEST"

# Sync only code, docs, and config to the timestamped directory
rsync -av \
  --exclude='venv/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='data/' \
  --exclude='logs/*.log' \
  --exclude='.git/' \
  --exclude='s30_storage/' \
  --exclude='images/' \
  "$SOURCE_DIR/" "$SNAPSHOT_DEST/"

# Create/Update a 'latest' symlink pointing to this specific backup
ln -sfn "$SNAPSHOT_DEST" "$BASE_DEST/latest"

echo "✅ Federation Snapshot secured at: $SNAPSHOT_DEST"
echo "🔗 'latest' pointer updated."
