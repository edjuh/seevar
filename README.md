# 🔭 SeeVar —Asthonising Automated Variable Star Observatory

![SeeVar Mascot](SeeVar.jpg)

Objective: Transform a consumer smart telescope into a fully autonomous scientific instrument for variable star photometry.

SeeVar is an automated control and data pipeline designed for the Seestar S30-PRO telescope.
Its purpose is simple:
Measure variable stars reliably, every clear night, without human intervention.
Instead of using the telescope as a consumer imaging device, SeeVar treats it as a robotic observatory that plans observations, captures scientific images, processes the data, and prepares results for submission to the AAVSO.

🌌 Mission
SeeVar focuses on long-term monitoring of variable stars, with special attention to:

Long Period Variables (Mira / Semi-Regular)
Cataclysmic Variables during outburst

Observation cadence follows the 5% of period rule — confirmed against AAVSO STWG recommendations for OSC CMOS robotic telescopes.
Photometric results are reported to the AAVSO using the correct TG or CV reporting format.

🛰 Hardware Requirements
The system is intentionally built around robust and inexpensive hardware.
Required Components
Telescope

Seestar S30-PRO

Control Computer

Raspberry Pi running Debian Bookworm

Location Source

USB GPS receiver

The GPS provides:

precise geographic coordinates
accurate UTC time
reliable astronomical timing


Storage (Important)
SD cards are not reliable for continuous scientific operation.
SeeVar therefore requires external USB storage.
Recommended configuration:

2 × 256 GB (or larger) USB flash drives

The drives operate as a mirrored RAID1 array for redundancy.
Benefits:

protects against sudden SD-card failure
prevents loss of scientific data
allows safe long-term unattended operation

The SD card is used only for the operating system.
All observation data and FITS files are written to the mirrored storage.

🧠 System Architecture
SeeVar operates as a deterministic control pipeline consisting of five functional blocks.
Block 1 — Hardware Foundation
Raspberry Pi running Debian Bookworm and the required Python environment.
Block 2 — Telescope Interface
Communication with the telescope uses the ASCOM Alpaca REST protocol on port 32323. This is ZWO's official open standard interface, built into the Seestar firmware. SeeVar controls the full hardware stack directly:

Telescope — slew, track, park, unpark, pulse guide
Camera (Telephoto IMX585) — gain, exposure, image download
Camera (Wide Angle IMX586) — context imaging
Filter Wheel — Dark, IR, LP positions
Focuser — absolute position control
Switch — dew heater control

No phone app required. No session master lock. No intermediate middleware.
Block 3 — Preflight Gatekeeper
Before observations begin the system verifies:

battery level
internal temperature
telescope alignment
storage availability
weather conditions

If conditions are unsafe, the system waits automatically.

Block 4 — Flight Operations
During astronomical darkness the system executes an observing plan.
For each target the telescope:

Slews to the object
Plate-solves to verify pointing
Captures RAW FITS exposures
Records accurate timestamps and metadata

Targets are dynamically scheduled based on:

altitude above the horizon
scientific priority
time since last observation
telescope slew distance


Block 5 — Postflight Processing
After images are captured the pipeline automatically:

retrieves RAW FITS frames
extracts G/R/B/L channels directly from raw Bayer data (no debayering)
performs plate solving
measures stellar brightness via photometry
prepares AAVSO submission reports


📊 The Observatory Ledger
Every action performed by the telescope is recorded.
This provides:

full traceability of observations
automatic recovery after interruptions
accurate scientific logs

If weather interrupts an observation, unfinished targets return to the queue and are attempted again later.

🌦 Weather Awareness
SeeVar evaluates observing conditions using multiple sources:

external weather services
internal image quality checks
plate-solve success monitoring

Future versions may integrate a dedicated cloud sensor for local sky detection.

🖥 Tactical Dashboard
The system includes a live dashboard displaying:

telescope status
storage capacity
battery level
weather conditions
active observing targets

This allows the observatory to be monitored remotely while running autonomously.

🌍 Scaling the Observatory
SeeVar is designed to control multiple telescopes simultaneously.
Possible configurations include:

parallel photometry using several telescopes
coordinated observations from different locations
dedicated spectroscopy instruments

The architecture allows remote telescopes to join the network.

🚧 Beta
SeeVar is currently in beta. Hardware testing begins April 2026 with the ZWO Seestar S30-Pro.
Community testers are welcome. Please report issues via GitHub Issues.
For changes affecting the protocol, state machine, or sequencing:
→ Please do open an issue first to discuss the approach.
PRs without prior discussion may be declined.

🚀 Getting Started
Install on a fresh Raspberry Pi OS Lite (64-bit) — Bookworm:
bashbash <(curl -fsSL https://raw.githubusercontent.com/edjuh/seevar/main/bootstrap.sh)
Bootstrap installs all dependencies, creates the Python environment, runs an
interactive questionnaire for telescope and site configuration, and starts the
three systemd services automatically.
Full installation instructions: INSTALL.md

🌠 Philosophy
SeeVar exists because good hardware deserves serious use.
A small telescope, a Raspberry Pi, and careful automation can produce real scientific observations every clear night.
The sky has always been open to anyone willing to measure it.

"De kosmos is erg groot, en voor een heer alleen is zij eigenlijk te veel. Maar met een groot denkraam komt men een heel eind."
(Vrij naar Heer Bommel)

Full installation instructions: [INSTALL.md](INSTALL.md)

