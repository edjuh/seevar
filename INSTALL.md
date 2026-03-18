# SeeVar — Installation Guide

> **Target platform:** Raspberry Pi (any model with 64-bit support)
> **Operating system:** Debian Bookworm 64-bit (Raspberry Pi OS)
> **Version:** 1.3.1

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
