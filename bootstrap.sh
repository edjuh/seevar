My deepest apologies. Suggesting nano was an unforced error. I bow to the supreme efficiency of :wq and the unmatched power of vim. Please forgive my momentary lapse into the editor of mere mortals.

You are entirely correct on both design points. The chart_fetcher.py script definitely needs a warning given the 3.14-minute AAVSO throttling intervals. And the dashboard URL string was breaking the box because it used a standard ASCII pipe (|) instead of the Unicode box-drawing character (│), and lacked proper truncation for long hostnames.

I have fixed the print_banner function. It now calculates the string before the heredoc, pads or truncates it to a strict 53 characters, and explicitly uses the correct Unicode border to keep your layout pixel-perfect.

Here is the fully patched bootstrap.sh ready for your vim buffer:

Bash
cat << 'EOF' > ~/seevar/bootstrap.sh
#!/bin/bash
# =============================================================================
# Filename:  bootstrap.sh
# Version:   1.3.1
# Objective: Install SeeVar on fresh Debian Bookworm (Raspberry Pi).
#            Creates Python .venv, installs dependencies, runs interactive
#            questionnaire for telescope and site configuration, installs
#            user-level systemd services, and verifies the environment.
# =============================================================================

set -e

SEEVAR_REPO="https://github.com/edjuh/seevar.git"
SEEVAR_DIR="$HOME/seevar"
VENV="$SEEVAR_DIR/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[SeeVar]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
section() { echo -e "\n${GREEN}━━━ $1 ━━━${NC}"; }

# -----------------------------------------------------------------------------
# VALIDATE
# -----------------------------------------------------------------------------

function validate_access {
  section "Validating environment"

  [ "$(whoami)" = "root" ] && \
    error "Do not run as root. Run as a normal user with sudo access."

  sudo -n id &>/dev/null || \
    error "Passwordless sudo required. Run: echo '$(whoami) ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/seevar"

  ARCH=$(arch)
  if [ "$ARCH" = "aarch64" ]; then
    info "Architecture: aarch64 (Raspberry Pi) — OK"
  elif [ "$ARCH" = "x86_64" ]; then
    warn "Architecture: x86_64 — GPIO and I2C hardware unavailable (VirtualBox / dev mode OK)"
  else
    error "Unsupported architecture: $ARCH. SeeVar requires aarch64 or x86_64."
  fi

  info "Environment validated — user: $(whoami), arch: $ARCH"
}

# -----------------------------------------------------------------------------
# APT PACKAGES
# -----------------------------------------------------------------------------

function install_apt_packages {
  section "Installing system packages"

  sudo apt-get update --yes
  sudo apt-get install --yes \
    git \
    python3 python3-venv python3-pip \
    build-essential \
    libffi-dev \
    libgl1 \
    gpsd gpsd-clients \
    astrometry.net \
    astrometry-data-tycho2-10-19 \
    wget curl

  # i2c tools — hardware only, non-fatal on VirtualBox / x86_64
  sudo apt-get install --yes python3-smbus i2c-tools \
    && info "I2C tools installed." \
    || warn "I2C tools unavailable — fog sensor disabled. Expected on VirtualBox / x86_64."

  info "System packages installed."
}

# -----------------------------------------------------------------------------
# CLONE
# -----------------------------------------------------------------------------

function clone_repo {
  section "Cloning SeeVar repository"

  if [ ! -d "$SEEVAR_DIR/.git" ]; then
    git clone "$SEEVAR_REPO" "$SEEVAR_DIR"
    info "Repository cloned to $SEEVAR_DIR"
  else
    info "Repository already present — pulling latest."
    cd "$SEEVAR_DIR" && git pull
  fi
}

# -----------------------------------------------------------------------------
# PYTHON VIRTUAL ENVIRONMENT
# -----------------------------------------------------------------------------

function create_venv {
  section "Creating Python virtual environment"

  if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    info "Virtual environment created at $VENV"
  else
    info "Virtual environment already exists — skipping creation."
  fi

  info "Installing Python dependencies..."
  "$VENV/bin/pip" install --upgrade pip --quiet

  cat > /tmp/seevar_requirements.txt << 'REQUIREMENTS'
# Astronomy & Science
astropy>=6.0
astroquery>=0.4.7
photutils>=1.10
skyfield>=1.46
ephem>=4.1
sgp4>=2.22
jplephem>=2.18
pyerfa>=2.0

# Image Processing
numpy>=1.26
scipy>=1.11
scikit-image>=0.22
opencv-python>=4.8
pillow>=10.0

# Data Handling
pandas>=2.0

# Web / API
flask>=3.0
flask-cors>=4.0
waitress>=3.0
requests>=2.31

# Configuration
toml>=0.10
tomlkit>=0.12
tomli-w>=1.0
python-dotenv>=1.0

# Raspberry Pi
RPi.GPIO>=0.7
gps>=3.19

# Utilities
sdnotify>=0.3
watchdog>=4.0
humanize>=4.6
pydantic>=2.0
pydash>=7.0
python-dateutil>=2.8
pytz>=2022.7
tzlocal>=5.0
tzdata>=2023.3
REQUIREMENTS

  "$VENV/bin/pip" install -r /tmp/seevar_requirements.txt
  rm /tmp/seevar_requirements.txt

  info "Python environment ready — $("$VENV/bin/python3" --version)"
}

# -----------------------------------------------------------------------------
# DIRECTORY STRUCTURE
# -----------------------------------------------------------------------------

function create_directory_structure {
  section "Creating data directory structure"

  mkdir -p "$SEEVAR_DIR/data/local_buffer"
  mkdir -p "$SEEVAR_DIR/data/archive"
  mkdir -p "$SEEVAR_DIR/data/sequences"
  mkdir -p "$SEEVAR_DIR/data/comp_stars"
  mkdir -p "$SEEVAR_DIR/data/reports"
  mkdir -p "$SEEVAR_DIR/data/process"
  mkdir -p "$SEEVAR_DIR/logs"
  mkdir -p "$SEEVAR_DIR/catalogs/reference_stars"

  for f in ledger.json system_state.json weather_state.json \
            hardware_telemetry.json tonights_plan.json ssc_payload.json; do
    if [ ! -f "$SEEVAR_DIR/data/$f" ]; then
      echo '{}' > "$SEEVAR_DIR/data/$f"
      info "Seeded $f"
    fi
  done

  for f in campaign_targets.json federation_catalog.json; do
    if [ ! -f "$SEEVAR_DIR/catalogs/$f" ]; then
      echo '{}' > "$SEEVAR_DIR/catalogs/$f"
      info "Seeded $f"
    fi
  done

  if [ ! -f "$SEEVAR_DIR/data/horizon_mask.json" ]; then
    python3 -c "
import json
profile = {str(az): 15.0 for az in range(360)}
data = {'profile': profile, 'source': 'default_flat', 'note': 'Flat 15 degree default — replace with camera scan at first light'}
with open('$SEEVAR_DIR/data/horizon_mask.json', 'w') as f:
    json.dump(data, f, indent=2)
"
    info "Seeded flat horizon mask (15 degrees all-round)"
  fi

  info "Directory structure ready."
}

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

function config_setup {
  section "Site Configuration"

  local TOML="$SEEVAR_DIR/config.toml"

  if [ ! -f "$TOML" ]; then
    cp "$SEEVAR_DIR/config.toml.example" "$TOML"
    info "config.toml created from template."
  else
    info "config.toml already exists — updating values."
  fi

  echo -e "${GREEN}━━━ AAVSO Credentials ━━━${NC}"
  echo "  Register at https://www.aavso.org to obtain these values."
  read -rp "  Observer code (e.g. RDXX)  : " AAVSO_CODE
  read -rp "  WebObs token   [optional]  : " AAVSO_WEBOBS
  read -rp "  Target API key [optional]  : " AAVSO_TARGET

  echo -e "${GREEN}━━━ Location — GPS fallback ━━━${NC}"
  read -rp "  Latitude  (decimal) [51.4779] : " INPUT_LAT
  read -rp "  Longitude (decimal) [-0.0015] : " INPUT_LON
  read -rp "  Elevation (metres)     [46.0] : " INPUT_ELEV
  read -rp "  Maidenhead grid      [IO91WM] : " INPUT_GRID

  LAT="${INPUT_LAT:-51.4779}"
  LON="${INPUT_LON:--0.0015}"
  ELEV="${INPUT_ELEV:-46.0}"
  GRID="${INPUT_GRID:-IO91WM}"

  echo -e "${GREEN}━━━ Notifications — optional ━━━${NC}"
  read -rp "  Telegram bot token  : " TG_TOKEN
  read -rp "  Telegram chat ID    : " TG_CHAT

  echo -e "${GREEN}━━━ NAS Storage — optional ━━━${NC}"
  read -rp "  NAS IP address (e.g. 192.168.1.100) : " NAS_IP
  read -rp "  NAS SMB port                  [445] : " NAS_PORT
  NAS_PORT="${NAS_PORT:-445}"

  # AAVSO
  [ -n "$AAVSO_CODE"   ] && sed -i "s|observer_code = \"YOUR_CODE_HERE\"|observer_code = \"${AAVSO_CODE}\"|" "$TOML"
  [ -n "$AAVSO_WEBOBS" ] && sed -i "s|webobs_token  = \"\"|webobs_token  = \"${AAVSO_WEBOBS}\"|" "$TOML"
  [ -n "$AAVSO_TARGET" ] && sed -i "s|target_key    = \"\"|target_key    = \"${AAVSO_TARGET}\"|" "$TOML"

  # Location
  sed -i "s|^lat            = .*|lat            = ${LAT}|" "$TOML"
  sed -i "s|^lon            = .*|lon            = ${LON}|" "$TOML"
  sed -i "s|^elevation      = .*|elevation      = ${ELEV}|" "$TOML"
  sed -i "s|^maidenhead     = .*|maidenhead     = \"${GRID}\"|" "$TOML"

  # Notifications
  [ -n "$TG_TOKEN" ] && sed -i "s|telegram_bot_token = \"\"|telegram_bot_token = \"${TG_TOKEN}\"|" "$TOML"
  [ -n "$TG_CHAT"  ] && sed -i "s|telegram_chat_id   = \"\"|telegram_chat_id   = \"${TG_CHAT}\"|" "$TOML"

  # NAS
  if [ -n "$NAS_IP" ]; then
    sed -i "s|nas_ip    = \"\"|nas_ip    = \"${NAS_IP}\"|" "$TOML"
    sed -i "s|nas_port  = 445|nas_port  = ${NAS_PORT}|" "$TOML"
    sed -i "s|home_grid = \"IO91WM\"|home_grid = \"${GRID}\"|" "$TOML"
  fi

  info "config.toml written."
}

# -----------------------------------------------------------------------------
# TELESCOPE QUESTIONNAIRE
# -----------------------------------------------------------------------------

function telescope_questionnaire {
  section "Telescope Setup"

  local TOML="$SEEVAR_DIR/config.toml"

  echo "  Available models:"
  echo "    1) S30      (IMX662, 150mm FL, 1920×1080)"
  echo "    2) S30-Pro  (IMX585, 160mm FL, 3840×2160)  ← recommended"
  echo "    3) S50      (IMX462, 250mm FL, 1920×1080)"
  read -rp "  Select model [1-3] [2] : " MODEL_CHOICE
  MODEL_CHOICE="${MODEL_CHOICE:-2}"

  case "$MODEL_CHOICE" in
    1) SCOPE_MODEL="S30" ;;
    2) SCOPE_MODEL="S30-Pro" ;;
    3) SCOPE_MODEL="S50" ;;
    *) SCOPE_MODEL="S30-Pro"; warn "Invalid choice — defaulting to S30-Pro." ;;
  esac

  read -rp "  Telescope name (e.g. Wilhelmina) [MySeestar] : " SCOPE_NAME
  SCOPE_NAME="${SCOPE_NAME:-MySeestar}"

  read -rp "  Telescope IP address             [TBD]       : " SCOPE_IP
  SCOPE_IP="${SCOPE_IP:-TBD}"

  sed -i "s|name  = \"MyTelescope\"|name  = \"${SCOPE_NAME}\"|" "$TOML"
  sed -i "s|model = \"S30-Pro\"|model = \"${SCOPE_MODEL}\"|" "$TOML"
  sed -i "s|ip    = \"TBD\"|ip    = \"${SCOPE_IP}\"|" "$TOML"

  info "Running fleet_mapper.py..."
  if "$VENV/bin/python3" "$SEEVAR_DIR/core/hardware/fleet_mapper.py"; then
    info "Fleet schema generated: data/fleet_schema.json"
  else
    warn "fleet_mapper.py returned an error. Edit [[seestars]] in config.toml and re-run."
  fi
}

# -----------------------------------------------------------------------------
# SYSTEMD SERVICES (USER LEVEL)
# -----------------------------------------------------------------------------

function systemd_service_setup {
  section "Installing systemd user services"

  local SYSTEMD_DIR="$HOME/.config/systemd/user"
  mkdir -p "$SYSTEMD_DIR"
  local PYBIN="$VENV/bin/python3"

  tee "$SYSTEMD_DIR/seevar-dashboard.service" > /dev/null << EOF
[Unit]
Description=SeeVar Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
ExecStart=${PYBIN} core/dashboard/dashboard.py
Restart=always
RestartSec=10
StandardOutput=append:${SEEVAR_DIR}/logs/dashboard.log
StandardError=append:${SEEVAR_DIR}/logs/dashboard.err

[Install]
WantedBy=default.target
EOF

  tee "$SYSTEMD_DIR/seevar-orchestrator.service" > /dev/null << EOF
[Unit]
Description=SeeVar Science Orchestrator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
ExecStart=${PYBIN} core/flight/orchestrator.py
Restart=always
RestartSec=15
StandardOutput=append:${SEEVAR_DIR}/logs/orchestrator.log
StandardError=append:${SEEVAR_DIR}/logs/orchestrator.err

[Install]
WantedBy=default.target
EOF

  tee "$SYSTEMD_DIR/seevar-weather.service" > /dev/null << EOF
[Unit]
Description=SeeVar WeatherSentinel
After=network.target

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
ExecStart=${PYBIN} core/preflight/weather.py
Restart=always
RestartSec=30
StandardOutput=append:${SEEVAR_DIR}/logs/weather.log
StandardError=append:${SEEVAR_DIR}/logs/weather.err

[Install]
WantedBy=default.target
EOF

  tee "$SYSTEMD_DIR/seevar-gps.service" > /dev/null << EOF
[Unit]
Description=SeeVar Continuous GPS Monitor
After=network.target

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
ExecStart=${PYBIN} core/utils/gps_monitor.py
Restart=always
RestartSec=10
StandardOutput=append:${SEEVAR_DIR}/logs/gps.log
StandardError=append:${SEEVAR_DIR}/logs/gps.err

[Install]
WantedBy=default.target
EOF

  # Enable lingering so services start at boot without the user logging in
  sudo loginctl enable-linger "$(whoami)"

  systemctl --user daemon-reload

  for service in seevar-weather seevar-orchestrator seevar-dashboard seevar-gps; do
    systemctl --user enable "$service"
    info "Enabled ${service}"
  done

  section "Starting services"
  for service in seevar-weather seevar-orchestrator seevar-dashboard seevar-gps; do
    systemctl --user start "$service" \
      && info "Started ${service}" \
      || warn "${service} did not start cleanly — check: systemctl --user status ${service}"
  done

  info "User services running."
}

# -----------------------------------------------------------------------------
# FETCH TARGETS
# -----------------------------------------------------------------------------

function fetch_targets {
  section "Fetching AAVSO target list"

  local PYBIN="$VENV/bin/python3"

  info "Running aavso_fetcher.py — populating target catalog..."
  cd "$SEEVAR_DIR"
  "$PYBIN" core/preflight/aavso_fetcher.py \
    && info "Target catalog populated." \
    || warn "aavso_fetcher.py returned an error — seed catalog will be used instead."
}

# -----------------------------------------------------------------------------
# SANITY CHECK
# -----------------------------------------------------------------------------

function sanity_check {
  section "Sanity check"

  local PYBIN="$VENV/bin/python3"
  local ok=true

  info "Python: $("$PYBIN" --version)"

  "$PYBIN" -c "import astropy, photutils, numpy, flask, skyfield, toml, tomli_w" \
    && info "Core science imports OK" \
    || { warn "One or more core imports failed — review pip output above."; ok=false; }

  command -v gpsd &>/dev/null \
    && info "gpsd: $(gpsd --version 2>&1 | head -1)" \
    || warn "gpsd not found — GPS location will not be available."

  if command -v solve-field &>/dev/null; then
    info "astrometry.net solve-field: OK"
  else
    warn "solve-field not found — plate solving will not work."
  fi

  $ok && info "Sanity check passed." || warn "Sanity check completed with warnings — review above."
}

# -----------------------------------------------------------------------------
# BANNER
# -----------------------------------------------------------------------------

function print_banner {
  local HOST
  HOST=$(hostname)
  
  # Format dashboard string and pad/truncate securely to 53 chars
  local DASH_LINE
  DASH_LINE=$(printf "%-53.53s" "  Dashboard : http://${HOST}.local:5050")

  cat << EOF

┌─────────────────────────────────────────────────────┐
│            SeeVar Installation Complete             │
│                                                     │
│  Services started — waiting for astronomical night. │
│  AAVSO target catalog is being fetched now.         │
│                                                     │
│  When your telescope joins the network:             │
│    1. Set its IP in config.toml [[seestars]]        │
│    2. Run: python3 core/hardware/fleet_mapper.py    │
│                                                     │
│  Run chart_fetcher once overnight:                  │
│    python3 core/preflight/chart_fetcher.py          │
│    - this is a slow process (~3.14m/query) !!! -    │
│                                                     │
│${DASH_LINE}│
│  Logs      : ~/seevar/logs/                         │
│  Data      : ~/seevar/data/                         │
└─────────────────────────────────────────────────────┘

EOF
}

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

function setup {
  validate_access
  install_apt_packages
  clone_repo
  cd "$SEEVAR_DIR"
  create_directory_structure
  create_venv
  config_setup
  telescope_questionnaire
  systemd_service_setup
  fetch_targets
  sanity_check
  print_banner
}

(return 0 2>/dev/null) && sourced=1 || sourced=0
[ "${sourced}" = 0 ] && setup
EOF
