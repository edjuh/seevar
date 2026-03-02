#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Filename: setup_wizard.py
# Version: 1.4.17 (Infrastructure Baseline)
# Objective: Interactive CLI for configuring storage, weather APIs, and science credentials.
# -----------------------------------------------------------------------------

import os
import sys

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def ask(question, default=""):
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    answer = input(prompt).strip()
    return answer if answer else default

def main():
    clear_screen()
    print("="*65)
    print(" 🔭 S30-PRO FEDERATION : SETUP WIZARD")
    print("="*65)
    print("Welcome to the Seestar Federation. The pipeline is already")
    print("pre-loaded with the current Master Catalog and sequence data.")
    print("\nYou only need to provide an AAVSO Observer Code and API keys")
    print("if you intend to run automated catalog updates or submit")
    print("official photometric data to the Alert Corps.")
    print("Press ENTER to accept the default values in brackets.\n")

    # Storage Block
    print("[ STORAGE & ARCHIVE ]")
    source_dir = ask("Seestar Downloads directory", "~/seestar_downloads")
    usb1 = ask("Primary USB Archive (Drive 1)", "/mnt/usb1/astro_archive")
    usb2 = ask("Secondary USB Archive (Drive 2)", "/mnt/usb2/astro_archive")
    lifeboat = ask("Local Fallback directory (AP Mode)", "~/seestar_organizer/data/local_buffer")

    # Weather Block
    print("\n[ WEATHER & SAFETY GATE ]")
    print("The Preflight Gatekeeper requires a weather provider to prevent rain/cloud damage.")
    weather_provider = ask("Weather Provider (open-meteo / openweathermap)", "open-meteo").lower()
    weather_key = ""
    if weather_provider == "openweathermap":
        weather_key = ask("OpenWeatherMap API Key", "")

    # Science Block
    print("\n[ SCIENCE & PHOTOMETRY ]")
    print("If you do not have an AAVSO code, are with the BAA (British Astronomical")
    print("Association), or are just testing the system, leave this blank.")
    aavso_code = ask("Observer Code", "")

    print("\nGenerating config.toml...")

    # Build the strict TOML configuration
    toml_content = f"""# =============================================================================
# Filename: config.toml
# Version: 1.4.17 (Infrastructure Baseline)
# Objective: Active configuration for hardware, storage, weather, and science parameters.
# =============================================================================

[hardware]
# Mount type is dynamically queried from the Seestar ALP bridge.
default_exposure = 10

[storage]
source_dir = "{source_dir}"
usb_drive_1 = "{usb1}"
usb_drive_2 = "{usb2}"
lifeboat_dir = "{lifeboat}"

[weather]
provider = "{weather_provider}"
api_key = "{weather_key}"
max_cloud_cover_pct = 50.0

[alpaca]
simulate = false

[aavso]
# Required for automated sequence updates and official submissions.
observer_code = "{aavso_code}"

[location]
# ⚠️ LIVE GPS OVERRIDE ACTIVE ⚠️
# Preflight strictly prioritizes live 3D GPS locks written to /dev/shm/discovery.json.
# Default Fallback: Royal Observatory, Greenwich.
lat = 51.4779
lon = -0.0015
elevation = 46.0
"""

    # Dynamically resolve project root to save the config
    PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(PROJECT_DIR, "config.toml")
    
    with open(config_path, "w") as f:
        f.write(toml_content)

    print(f"✅ SUCCESS! Configuration written to: {config_path}")
    print("="*65)

# Add this logic to your setup_wizard.py
import subprocess

def check_storage_infrastructure():
    print("\n[STORAGE AUDIT] Verifying RAID1 Mount...")
    
    # Check if mounted
    mount_check = subprocess.run(['mountpoint', '-q', '/mnt/raid'])
    if mount_check.returncode != 0:
        print("❌ CRITICAL: /mnt/raid is not mounted! The Data Factory will fail.")
        # Attempt to mount if in fstab
        os.system("sudo mount /mnt/raid && echo '✅ Recovered: RAID Mounted.'")
    else:
        print("✅ RAID1 is mounted and ready.")

    # Check symlink
    data_path = Path("~/seestar_organizer/data").expanduser()
    if not data_path.is_symlink():
        print("⚠️  Warning: ~/seestar_organizer/data is a local folder, not a RAID link.")
        # Logic to move data and create link would go here

if __name__ == "__main__":
    main()
