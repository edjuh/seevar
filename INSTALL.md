# SeeVar — Installation Guide

> **Target platform:** Raspberry Pi (any model with 64-bit support)
> **Operating system:** Debian Bookworm 64-bit (Raspberry Pi OS)
> **Version:** 1.3.1

---

## What you need

| Item              | Notes                                         |
| ----------------- | --------------------------------------------- |
| Raspberry Pi      | Pi 4 or Pi 5 recommended                      |
| SD card           | 16 GB minimum — OS only, no data stored here  |
| 2 × USB drive     | 256 GB or larger — RAID1 data archive         |
| USB GPS receiver  | Required for accurate timestamps and location |
| Seestar telescope | S30, S30-Pro, or S50                          |

The telescope IP address does not need to be known at install time.
You can set it to `TBD` during the questionnaire and update `config.toml` later.

---

## Step 1 — Flash the SD card

Use **Raspberry Pi Imager 2.0** (or later).

1. Select **Raspberry Pi OS (64-bit)** — Bookworm
2. Click the **gear icon** (OS Customisation) before writing:

| Field             | Value                                              |
| ----------------- | -------------------------------------------------- |
| Hostname          | Your choice — e.g. `seevar`, `observatory`, `mypi` |
| Enable SSH        | ✓ — Use password authentication                    |
| Username          | Your chosen username (e.g. `ed`)                   |
| Password          | Set a strong password                              |
| Locale / timezone | Set to your location                               |
| WiFi              | Set if connecting wirelessly                       |

3. Write the card, insert into Pi, power on.

---

## Step 2 — First SSH connection

Wait ~60 seconds for first boot, then:

```bash
ssh <username>@<hostname>.local
```

---

## Step 3 — Enable passwordless sudo

Bootstrap requires passwordless sudo for system package installation.

```bash
echo "$(whoami) ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/seevar
```

---

## Step 4 — Run bootstrap

```bash
curl -fsSL https://raw.githubusercontent.com/edjuh/seevar/main/bootstrap.sh | bash
```

Or if you prefer to inspect it first:

```bash
wget https://raw.githubusercontent.com/edjuh/seevar/main/bootstrap.sh
less bootstrap.sh
bash bootstrap.sh
```

### Bootstrap will:

* Install system packages via `apt`
* Clone the repository to `~/seevar`
* Create a Python virtual environment at `~/seevar/.venv`
* Install all Python dependencies
* Run the telescope questionnaire — model, name, IP
* Run the site questionnaire — AAVSO credentials, location, optional Telegram and NAS
* Create the data directory structure and seed empty state files
* Install and enable the four user-level systemd services:

  * Dashboard
  * Orchestrator
  * Weather
  * GPS
* Run a sanity check
* Print a summary

**Total time:** ~10–15 minutes on a Pi 5 (longer on Pi 4)

---

## Step 5 — Set telescope IP

Once your telescope is on the network, find its IP address in:

* the Seestar app
* or your router’s DHCP table

Then edit `config.toml`:

```toml
[[seestars]]

name  = "Metius"
model = "S30-Pro"
ip    = "192.168.1.x"     # ← set this
mount = "altaz"
```

Then regenerate the fleet schema:

```bash
cd ~/seevar
python3 core/hardware/fleet_mapper.py
```

---

## Step 6 — Run chart_fetcher overnight

The seed catalog bundled with SeeVar contains **442 targets** for 40°–60°N.
You can start observing immediately.

To refresh or expand:

```bash
cd ~/seevar
python3 core/preflight/chart_fetcher.py
```

⚠️ This is slow (~3.14 min/query due to AAVSO throttling) — run overnight.

---

## Step 7 — Managing the observatory

SeeVar runs as **user-level systemd services**:

```bash
systemctl --user status seevar-orchestrator
systemctl --user stop seevar-weather
systemctl --user restart seevar-dashboard
```

Dashboard:

```
http://<hostname>.local:5050
```

---

## Astrometry.net index files

Plate solving requires index files matched to your telescope’s field of view.

| Model   | FOV   | Recommended indexes |
| ------- | ----- | ------------------- |
| S30     | ~4.5° | index-4107 → 4110   |
| S30-Pro | ~4.0° | index-4107 → 4110   |
| S50     | ~2.5° | index-4108 → 4111   |

Install via:

```bash
sudo apt install astrometry-data-tycho2-10-19
```

Or download from:
http://data.astrometry.net/4100/

---

## Configuration reference

* `~/seevar/config.toml` — runtime config
* `~/seevar/config.toml.example` — annotated template

### Key settings

| Setting              | Location          | Notes                   |
| -------------------- | ----------------- | ----------------------- |
| `observer_code`      | `[aavso]`         | Required                |
| `simulation_mode`    | `[planner]`       | Set `true` for dry runs |
| `ip`                 | `[[seestars]]`    | Telescope IP            |
| `telegram_bot_token` | `[notifications]` | Optional                |
| `nas_ip`             | `[network]`       | Optional                |

---

## Logs

```
~/seevar/logs/orchestrator.log
~/seevar/logs/dashboard.log
~/seevar/logs/weather.log
~/seevar/logs/gps.log
```

---

## Uninstall / reinstall

```bash
systemctl --user stop seevar-dashboard seevar-orchestrator seevar-weather seevar-gps
systemctl --user disable seevar-dashboard seevar-orchestrator seevar-weather seevar-gps
rm ~/.config/systemd/user/seevar-*.service
systemctl --user daemon-reload
rm -rf ~/seevar
```

Then re-run bootstrap from Step 4.

