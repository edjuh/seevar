#!/usr/bin/env python3
import os
import time
from pathlib import Path

def print_step(step, msg):
    print(f"\n\033[95m[STEP {step}]\033[0m \033[1m{msg}\033[0m")
    time.sleep(1)

def main():
    # Resolve project root relative to this script's location (utils/ -> root)
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    print("\n" + "="*60)
    print("🔭 S30-PRO FEDERATION: CATALOG REBUILD SEQUENCE")
    print("="*60)

    # 1. HARVEST
    print_step(1, "Harvester: Pulling AAVSO Field-of-View Targets...")
    os.system("python3 core/preflight/harvester.py")

    # 2. LIBRARIAN
    print_step(2, "Librarian: Sanitizing and Merging to Master Catalog...")
    os.system("python3 core/preflight/librarian.py")

    # 3. VALIDATOR
    print_step(3, "Validator: Cross-referencing ASAS-SN Magnitude Limits...")
    os.system("python3 core/preflight/asassn_validator.py")

    # 4. AUDIT
    print_step(4, "Audit: Applying Scientific Cadence & Ledger History...")
    os.system("python3 core/preflight/audit.py")

    print("\n" + "="*60)
    print("✅ REBUILD COMPLETE. Current Data Purity:")
    os.system("ls -lSh data/*.json | awk '{print $5, $9}'")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
