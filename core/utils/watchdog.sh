#!/bin/bash
# Seestar Federation - RAID Symlink Watchdog
TARGET="/mnt/raid1/data"
LINK="$HOME/seestar_organizer/data"

echo "[WATCHDOG] Checking RAID Heartbeat..."

if [ -d "$TARGET" ]; then
    if [ -L "$LINK" ]; then
        if [ "$(readlink -f "$LINK")" != "$TARGET" ]; then
            echo "[WARN] Link misaligned. Re-pointing to $TARGET"
            ln -sf "$TARGET" "$LINK"
        else
            echo "[OK] RAID Link is healthy."
        fi
    else
        echo "[FIX] Creating missing symlink to $TARGET"
        ln -s "$TARGET" "$LINK"
    fi
else
    echo "[FATAL] RAID NOT MOUNTED AT $TARGET"
    exit 1
fi
