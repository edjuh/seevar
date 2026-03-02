#!/bin/bash
# 🛰️ S30-PRO Federation: Daily Code Backup
# Versioned Path: /mnt/astronas/1.1/backup

BACKUP_DEST="/mnt/astronas/1.4/backup"
SOURCE_DIR="/home/ed/seestar_organizer"

mkdir -p "$BACKUP_DEST"

# Sync only code, docs, and config
rsync -av --delete \
  --exclude='venv/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='data/' \
  --exclude='logs/*.log' \
  --exclude='.git/' \
  "$SOURCE_DIR/" "$BACKUP_DEST/"

echo "✅ Federation Backup to $BACKUP_DEST completed."
