#!/bin/bash
# 🛰️ SeeVar: Sovereign Snapshot Utility
# Version: 1.3.6
# Objective: Backup SeeVar code and logic to dynamically defined NAS targets.
#            SMB/CIFS-safe: avoids symlinks and permission sync errors.

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Dynamically find the SeeVar root directory
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Extract the NAS primary_dir dynamically from config.toml
NAS_DIR=$(awk -F '"' '/^[[:space:]]*primary_dir[[:space:]]*=/{print $2; exit}' "$SOURCE_DIR/config.toml" 2>/dev/null)
[ -n "$NAS_DIR" ] || NAS_DIR="/mnt/astronas/"
BASE_DEST="${NAS_DIR%/}/backup"
SNAPSHOT_DEST="$BASE_DEST/seevar_$TIMESTAMP"

# Explicitly mapping to the exact symlink target
RAID_DATA_DIR="/mnt/raid1/data"

echo "📦 Initiating SeeVar Snapshot from $SOURCE_DIR..."
mkdir -p "$SNAPSHOT_DEST"

# Backup the main SeeVar directory (excluding the data/ symlink to prevent SMB errors)
rsync -rtv --delete \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='logs/*.log' \
  --exclude='.git/' \
  --exclude='data/' \
  "$SOURCE_DIR/" "$SNAPSHOT_DEST/"

echo "📦 Initiating Data Snapshot from $RAID_DATA_DIR..."
mkdir -p "$SNAPSHOT_DEST/data"

# Explicitly backup durable RAID1 data only.
# Raw/cached FITS and WCS products are transient and should not flood NAS snapshots.
if [ -d "$RAID_DATA_DIR" ]; then
  rsync -rtv --delete \
    --exclude='local_buffer/' \
    --exclude='verify_buffer/' \
    --exclude='calibrated_buffer/' \
    --exclude='process/' \
    --exclude='archive/' \
    "$RAID_DATA_DIR/" "$SNAPSHOT_DEST/data/"
else
  echo "⚠️ Warning: RAID data directory $RAID_DATA_DIR not found. Skipping data backup."
fi

# SMB mounts often reject symlinks. Write a pointer file instead.
echo "$SNAPSHOT_DEST" > "$BASE_DEST/seevar_latest_pointer.txt"

# Cleanup old backups (older than 30 days)
find "$BASE_DEST" -maxdepth 1 -name "seevar_*" -type d -mtime +30 -exec rm -rf {} +

echo "✅ SeeVar Snapshot secured at: $SNAPSHOT_DEST"
