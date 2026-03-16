# SeeVar — Installation Guide

> **Target platform:** Raspberry Pi (any model with 64-bit support)
> **Operating system:** Debian Bookworm 64-bit (Raspberry Pi OS)
> **Version:** 1.1.0

---

## What you need

| Item | Notes |
|------|-------|
| Raspberry Pi | Pi 4 or Pi 5 recommended |
| SD card | 16 GB minimum — OS only, no data stored here |
| 2 × USB drive | 256 GB or larger — RAID1 data archive |
| USB GPS receiver | Required for accurate timestamps and location |
| Seestar telescope | S30, S30-Pro, or S50 |

The telescope IP address does not need to be known at install time.
You can set it to `TBD` during the questionnaire and update `config.toml` later.

---

## Step 1 — Flash the SD card

Use **Raspberry Pi Imager 2.0** (or later).

1. Select **Raspberry Pi OS (64-bit)** — Bookworm
2. Click the **gear icon** (OS Customisation) before writing:

| Field | Value |
|-------|-------|
| Hostname | Your choice — e.g. `seevar`, `observatory`, `mypi` |
| Enable SSH | ✓ — Use password authentication |
| Username | Your chosen username (e.g. `ed`) |
| Password | Set a strong password |
| Locale / timezone | Set to your location |
| WiFi | Set if connecting wirelessly |

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

Bootstrap will:

1. Install system packages via apt
2. Clone the repository to `~/seevar`
3. Create a Python virtual environment at `~/seevar/.venv`
4. Install all Python dependencies
5. Run the **telescope questionnaire** — model, name, IP
6. Run the **site questionnaire** — AAVSO credentials, location, optional Telegram and NAS
7. Create the data directory structure and seed empty state files
8. Install and enable the three systemd services
9. Run a sanity check
10. Print a summary

Total time: approximately 10–15 minutes on a Pi 5, longer on a Pi 4
(Python dependency build includes compiled packages).

---

## Step 5 — Set telescope IP

Once your telescope is on the network, find its IP address in the Seestar app
or your router's DHCP table. Then edit `config.toml`:

```toml
[[seestars]]
name  = "Wilhelmina"
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

The seed catalog bundled with SeeVar contains 442 targets and reference stars
for 40°–60°N. It is sufficient to start observing immediately.

To refresh or expand the catalog, run the chart fetcher once.
This takes several hours due to AAVSO API throttling — run it overnight:

```bash
cd ~/seevar
python3 core/preflight/chart_fetcher.py
```

---

## Step 7 — Start the observatory

```bash
sudo systemctl start seevar-weather
sudo systemctl start seevar-orchestrator
sudo systemctl start seevar-dashboard
```

Dashboard: **http://\<hostname\>.local:5050**

---

## What the dashboard shows on first start

| Indicator | Expected state | Reason |
|-----------|---------------|--------|
| SEESTAR (LINK) | NO SIGNAL | Telescope not connected yet — normal |
| BRIDGE | red | Seestar ALP not running — not required |
| GPS (LOCK) | yellow or green | Depends on GPS hardware |
| WEATHER | CLOUDY / OK | Live from open-meteo |
| FOG (VIS) | DISCONNECTED | MLX90614 sensor not installed — normal |

Red LEDs on SEESTAR and BRIDGE are expected until the telescope is on the network.
The pipeline will run in simulation until a live connection is established.

---

## Astrometry.net index files

Plate solving requires index files matched to your telescope's field of view.
These are not included in the repository.

| Model | FOV | Recommended index files |
|-------|-----|------------------------|
| S30 | ~4.5° | index-4107 to index-4110 |
| S30-Pro | ~4.0° | index-4107 to index-4110 |
| S50 | ~2.5° | index-4108 to index-4111 |

Install via apt:

```bash
sudo apt install astrometry-data-tycho2-10-19
```

Or download directly from: http://data.astrometry.net/4100/

---

## Configuration reference

`~/seevar/config.toml` — all runtime settings.
`~/seevar/config.toml.example` — annotated template.

Key settings after install:

| Setting | Location | Default | Notes |
|---------|----------|---------|-------|
| `observer_code` | `[aavso]` | — | Your AAVSO code — required for submissions |
| `simulation_mode` | `[planner]` | `false` | Set `true` for dry runs without hardware |
| `ip` | `[[seestars]]` | `TBD` | Telescope IP — update when known |
| `telegram_bot_token` | `[notifications]` | `""` | Optional session alerts |
| `nas_ip` | `[network]` | `""` | Optional NAS archive |

---

## Logs

```
~/seevar/logs/orchestrator.log
~/seevar/logs/dashboard.log
~/seevar/logs/weather.log
```

---

## Uninstall / reinstall

To start fresh on the same SD card:

```bash
sudo systemctl stop seevar-dashboard seevar-orchestrator seevar-weather
sudo systemctl disable seevar-dashboard seevar-orchestrator seevar-weather
sudo rm /etc/systemd/system/seevar-*.service
sudo systemctl daemon-reload
rm -rf ~/seevar
```

Then re-run bootstrap from Step 4.
