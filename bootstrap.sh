#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Filename: bootstrap.sh
# Version: 1.4.17 (Infrastructure Baseline)
# Objective: Validates OS architecture, enforces the ssc-3.13.5 virtual environment, and installs locked dependencies.
# -----------------------------------------------------------------------------
set -e

# Dynamically resolve the absolute path of the directory containing this script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
REQ_FILE="$PROJECT_DIR/requirements.txt"

echo "[BLOCK 1] Initializing Hardware & OS Foundation Audit..."
echo "[BLOCK 1] Project Directory resolved to: $PROJECT_DIR"

# 1. OS & Architecture Validation
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "[FATAL] Architecture $ARCH detected. S30-PRO Federation requires aarch64 (64-bit)."
    exit 1
fi

OS_VERSION=$(grep -Po '(?<=^VERSION_CODENAME=).*' /etc/os-release)
if [ "$OS_VERSION" != "bookworm" ]; then
    echo "[FATAL] OS $OS_VERSION detected. S30-PRO Federation requires Debian 12 (Bookworm)."
    exit 1
fi
echo "[OK] OS Baseline: Debian Bookworm (aarch64) verified."

# 2. System Dependencies (GPS & Time)
echo "[BLOCK 1] Verifying System-Level APT packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq gpsd gpsd-clients chrony
echo "[OK] gpsd and chrony verified."

# 3. Virtual Environment & Python Dependencies
echo "[BLOCK 1] Auditing Python Environment..."
if [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo "[FATAL] Virtual environment not found at $VENV_DIR."
    echo "Please ensure the Seestar ALP base installation (Python 3.13.5) has been executed."
    exit 1
fi

echo "[BLOCK 1] Enforcing requirements.txt..."
"$VENV_DIR/bin/python3" -m pip install --upgrade pip -q
"$VENV_DIR/bin/python3" -m pip install -r "$REQ_FILE" -q
echo "[OK] Python dependencies locked and verified."

echo "======================================================="
echo "[SUCCESS] Block 1: Infrastructure Baseline Secured."
echo "======================================================="
