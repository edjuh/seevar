#!/bin/bash -e
# =============================================================================
# Filename:  bootstrap.sh
# Version:   1.0.0
# Objective: Install SeeVar — Automated Variable Star Observatory
#            Installs dependencies, creates directory structure, configures
#            systemd services, and verifies the environment.
# =============================================================================

set -e

SEEVAR_REPO="https://github.com/smart-underworld/seevar.git"
PYTHON_VERSION="3.13.5"
VENV_NAME="ssc-${PYTHON_VERSION}"
SEEVAR_DIR="$HOME/seevar"

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[SeeVar]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
section() { echo -e "\n${GREEN}━━━ $1 ━━━${NC}"; }

# -----------------------------------------------------------------------------
# VALIDATION
# -----------------------------------------------------------------------------

function validate_access {
  section "Validating environment"

  if [ "$(whoami)" = "root" ]; then
    error "Do not run this script as root. Run as a normal user with sudo access."
  fi

  sudo -n id &>/dev/null || error "User does not have passwordless sudo access required for setup."

  if [ "$(arch)" != "aarch64" ]; then
    error "Unsupported architecture. SeeVar requires a 64-bit Raspberry Pi OS."
  fi

  if [ "$(uname)" != "Linux" ]; then
    error "SeeVar must be installed on Linux."
  fi

  info "Environment validated — user: $(whoami), arch: $(arch)"
}

# -----------------------------------------------------------------------------
# APT PACKAGES
# -----------------------------------------------------------------------------

function install_apt_packages {
  section "Installing system packages"

  sudo apt-get update --yes

  # Detect Debian release
  if grep -q trixie /etc/os-release; then
    NCURSES="libncurses-dev"
  else
    NCURSES="libncurses5-dev libncursesw5-dev"
  fi

  sudo apt-get install --yes \
    git \
    libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev llvm $NCURSES \
    xz-utils tk-dev libgdbm-dev lzma tcl-dev \
    libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
    wget curl make build-essential openssl \
    libgl1 \
    gpsd gpsd-clients \
    astrometry.net \
    python3-smbus i2c-tools

  info "System packages installed."
}

# -----------------------------------------------------------------------------
# PYTHON VIRTUALENV (reuses ALP's pyenv if present)
# -----------------------------------------------------------------------------

function python_virtualenv_setup {
  section "Configuring Python environment"

  # Bootstrap pyenv if not already installed
  if [ ! -d "$HOME/.pyenv" ]; then
    info "Installing pyenv..."
    curl https://pyenv.run | bash

    cat <<_EOF >> "$HOME/.bashrc"

# start seevar
export PYENV_ROOT="\$HOME/.pyenv"
[[ -d \$PYENV_ROOT/bin ]] && export PATH="\$PYENV_ROOT/bin:\$PATH"
eval "\$(pyenv init -)"
eval "\$(pyenv virtualenv-init -)"
# end seevar
_EOF
  else
    info "pyenv already present — skipping install."
  fi

  export PYENV_ROOT="$HOME/.pyenv"
  [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
  eval "$(pyenv init -)"
  eval "$(pyenv virtualenv-init -)"

  # Install Python version if needed
  if [ ! -d "$HOME/.pyenv/versions/${PYTHON_VERSION}" ]; then
    info "Installing Python ${PYTHON_VERSION}..."
    pyenv install "${PYTHON_VERSION}"
  else
    info "Python ${PYTHON_VERSION} already installed — skipping."
  fi

  # Create virtualenv if needed
  if [ ! -d "$HOME/.pyenv/versions/${VENV_NAME}" ]; then
    info "Creating virtualenv ${VENV_NAME}..."
    pyenv virtualenv "${PYTHON_VERSION}" "${VENV_NAME}"
  else
    info "Virtualenv ${VENV_NAME} already exists — skipping."
  fi

  pyenv global "${VENV_NAME}"

  info "Installing SeeVar Python dependencies..."
  pip install --upgrade pip

  pip install --break-system-packages 2>/dev/null || true  # suppress if not needed

  pip install - <<'REQUIREMENTS'
# --- Astronomy & Science -----------------------------------------------------
astropy==7.1.0
astroquery==0.4.11.dev10199
photutils==2.3.0
skyfield==1.53
ephem==4.2
sgp4==2.25
jplephem==2.24
pyerfa==2.0.1.5

# --- Image Processing --------------------------------------------------------
numpy==2.3.2
scipy==1.17.0
scikit-image==0.25.2
opencv-python==4.10.0.84
pillow==11.3.0

# --- Data Handling -----------------------------------------------------------
pandas==2.3.1

# --- Web / API ---------------------------------------------------------------
flask==3.1.1
flask-cors==6.0.1
waitress==3.0.2
requests==2.32.5

# --- Configuration -----------------------------------------------------------
toml==0.10.2
tomlkit==0.13.3
python-dotenv==1.2.1

# --- Raspberry Pi Hardware ---------------------------------------------------
RPi.GPIO==0.7.1
gps==3.19

# --- Optional: Fog / IR Cloud Sensor (MLX90614) ------------------------------
# Only required if you have an MLX90614 infrared sensor wired to the Pi.
# Comment out if not using fog_monitor.py hardware.
adafruit-circuitpython-mlx90614
Adafruit-Blinka==8.69.0

# --- Utilities ---------------------------------------------------------------
sdnotify==0.3.2
watchdog==6.0.0
humanize==4.12.3
pydantic==2.11.7
pydash==8.0.5
python-dateutil==2.9.0.post0
pytz==2022.7.1
tzlocal==5.3.1
tzdata==2025.3
REQUIREMENTS

  info "Python environment ready."
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

  # Seed empty state files — written at runtime, must exist on first boot
  for f in ledger.json system_state.json weather_state.json hardware_telemetry.json tonights_plan.json ssc_payload.json; do
    if [ ! -f "$SEEVAR_DIR/data/$f" ]; then
      echo '{}' > "$SEEVAR_DIR/data/$f"
      info "Seeded empty $f"
    fi
  done

  # Seed empty catalogs — populated by preflight fetcher after config
  for f in campaign_targets.json federation_catalog.json; do
    if [ ! -f "$SEEVAR_DIR/catalogs/$f" ]; then
      echo '{}' > "$SEEVAR_DIR/catalogs/$f"
      info "Seeded empty $f"
    fi
  done

  info "Directory structure ready."
}

# -----------------------------------------------------------------------------
# CONFIG — Interactive questionnaire
# -----------------------------------------------------------------------------

function config_setup {
  section "Configuring SeeVar"

  if [ ! -f "$SEEVAR_DIR/config.toml" ]; then
    cp "$SEEVAR_DIR/config.toml.example" "$SEEVAR_DIR/config.toml"
    info "config.toml created from template."
  else
    info "config.toml already exists — re-running credential setup."
  fi

  echo ""
  echo -e "${GREEN}━━━ AAVSO Credentials ━━━${NC}"
  echo "  Register at https://www.aavso.org to obtain these values."
  echo ""
  read -rp "  Observer code (e.g. RDXX)  : " AAVSO_CODE
  read -rp "  WebObs token               : " AAVSO_WEBOBS
  read -rp "  Target API key             : " AAVSO_TARGET

  echo ""
  echo -e "${GREEN}━━━ Location Fallback (used if GPS is unavailable) ━━━${NC}"
  echo "  Press Enter to keep the Greenwich defaults."
  echo ""
  read -rp "  Latitude  (decimal, e.g. 52.3874) [51.4779] : " INPUT_LAT
  read -rp "  Longitude (decimal, e.g.  4.6462) [-0.0015] : " INPUT_LON
  read -rp "  Elevation (metres)                [46.0]    : " INPUT_ELEV
  read -rp "  Maidenhead grid (4 or 6 char)     [IO91WM]  : " INPUT_GRID

  LAT="${INPUT_LAT:-51.4779}"
  LON="${INPUT_LON:--0.0015}"
  ELEV="${INPUT_ELEV:-46.0}"
  GRID="${INPUT_GRID:-IO91WM}"

  echo ""
  echo -e "${GREEN}━━━ Notifications (optional) ━━━${NC}"
  echo "  Create a Telegram bot via @BotFather. Press Enter to skip."
  echo ""
  read -rp "  Telegram bot token  : " TG_TOKEN
  read -rp "  Telegram chat ID    : " TG_CHAT

  echo ""
  echo -e "${GREEN}━━━ NAS Storage (optional) ━━━${NC}"
  echo "  Press Enter to skip if you have no NAS."
  echo ""
  read -rp "  NAS IP address (e.g. 192.168.1.100) : " NAS_IP
  read -rp "  NAS SMB port                [445]    : " NAS_PORT

  NAS_PORT="${NAS_PORT:-445}"

  # Write all values into config.toml
  TOML="$SEEVAR_DIR/config.toml"

  # AAVSO
  sed -i "s|observer_code = .*|observer_code = \"${AAVSO_CODE}\"|" "$TOML"
  sed -i "s|webobs_token = .*|webobs_token = \"${AAVSO_WEBOBS}\"|" "$TOML"
  sed -i "s|target_key = .*|target_key = \"${AAVSO_TARGET}\"|" "$TOML"

  # Location
  sed -i "s|^lat = .*|lat = ${LAT}|" "$TOML"
  sed -i "s|^lon = .*|lon = ${LON}|" "$TOML"
  sed -i "s|^elevation = .*|elevation = ${ELEV}|" "$TOML"
  sed -i "s|^maidenhead = .*|maidenhead = \"${GRID}\"|" "$TOML"

  # Notifications (only write if supplied)
  if [ -n "$TG_TOKEN" ]; then
    sed -i "s|telegram_bot_token = .*|telegram_bot_token = \"${TG_TOKEN}\"|" "$TOML"
  fi
  if [ -n "$TG_CHAT" ]; then
    sed -i "s|telegram_chat_id = .*|telegram_chat_id = \"${TG_CHAT}\"|" "$TOML"
  fi

  # NAS (only write if supplied)
  if [ -n "$NAS_IP" ]; then
    sed -i "s|^nas_ip = .*|nas_ip = \"${NAS_IP}\"|" "$TOML"
    sed -i "s|^nas_port = .*|nas_port = ${NAS_PORT}|" "$TOML"
    sed -i "s|^home_grid = .*|home_grid = \"${GRID}\"|" "$TOML"
  fi

  info "config.toml written."
}

# -----------------------------------------------------------------------------
# FETCH TARGETS — run aavso_fetcher, schedule chart_fetcher overnight
# -----------------------------------------------------------------------------

function fetch_targets {
  section "Fetching AAVSO target list"

  local pybin="$HOME/.pyenv/versions/${VENV_NAME}/bin/python3"

  info "Running aavso_fetcher.py — this takes ~10 seconds..."
  cd "$SEEVAR_DIR"
  "$pybin" core/preflight/aavso_fetcher.py \
    && info "Target list fetched successfully." \
    || warn "aavso_fetcher.py returned an error — check logs before starting."

  echo ""
  warn "chart_fetcher.py must be run separately — it takes several hours (Pi-Minute throttle)."
  warn "Run it overnight with:"
  warn "  cd ~/seevar && python3 core/preflight/chart_fetcher.py"
  echo ""
}

# -----------------------------------------------------------------------------
# SYSTEMD SERVICES
# -----------------------------------------------------------------------------

function systemd_service_setup {
  section "Installing systemd services"

  local user
  user=$(whoami)
  local pybin="$HOME/.pyenv/versions/${VENV_NAME}/bin/python3"

  for service in seevar-dashboard seevar-orchestrator seevar-weather; do
    local src="$SEEVAR_DIR/systemd/${service}.service"
    local tmp="/tmp/${service}.service"

    sed \
      -e "s|/home/[^/]*/seevar|$SEEVAR_DIR|g" \
      -e "s|^User=.*|User=${user}|" \
      -e "s|/home/[^/]*/.pyenv/versions/${VENV_NAME}/bin/python3|${pybin}|g" \
      "$src" > "$tmp"

    sudo chown root:root "$tmp"
    sudo mv "$tmp" "/etc/systemd/system/${service}.service"
    info "Installed ${service}.service"
  done

  sudo systemctl daemon-reload

  for service in seevar-dashboard seevar-orchestrator seevar-weather; do
    sudo systemctl enable "$service"
    info "Enabled ${service}"
  done

  info "Systemd services installed. Start manually after completing config.toml."
}

# -----------------------------------------------------------------------------
# SANITY CHECK
# -----------------------------------------------------------------------------

function sanity_check {
  section "Running sanity checks"

  local ok=true

  # Python version
  local pyver
  pyver=$(python3 --version 2>&1)
  info "Python: $pyver"

  # Key imports
  python3 -c "import astropy, photutils, numpy, flask, skyfield, toml" \
    && info "Core science imports OK" \
    || { warn "One or more core imports failed — check requirements.txt install."; ok=false; }

  # GPSD
  if command -v gpsd &>/dev/null; then
    info "gpsd: $(gpsd --version 2>&1 | head -1)"
  else
    warn "gpsd not found — GPS location will not be available."
  fi

  # astrometry.net
  if command -v solve-field &>/dev/null; then
    info "astrometry.net solve-field: OK"
  else
    warn "solve-field not found — plate solving will not work. Install index files separately."
  fi

  # config.toml
  if grep -q "YOUR_" "$SEEVAR_DIR/config.toml" 2>/dev/null; then
    warn "config.toml still contains placeholder values — edit before starting."
  else
    info "config.toml appears populated."
  fi

  if $ok; then
    info "Sanity check passed."
  else
    warn "Sanity check completed with warnings — review above before starting."
  fi
}

# -----------------------------------------------------------------------------
# BANNER
# -----------------------------------------------------------------------------

function print_banner {
  local host
  host=$(hostname)
  cat <<_EOF

┌─────────────────────────────────────────────┐
│        SeeVar Installation Complete         │
│                                             │
│  Start the observatory:                     │
│    sudo systemctl start seevar-weather      │
│    sudo systemctl start seevar-orchestrator │
│    sudo systemctl start seevar-dashboard    │
│                                             │
│  Dashboard:  http://${host}.local:5050     │
│  Logs:       ~/seevar/logs/                 │
│  Data:       ~/seevar/data/                 │
│                                             │
│  ⚠️  Run chart_fetcher overnight:           │
│    cd ~/seevar                              │
│    python3 core/preflight/chart_fetcher.py  │
└─────────────────────────────────────────────┘

_EOF
}

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

function setup {
  validate_access
  install_apt_packages

  # Clone repo if running bootstrap standalone (not from inside the repo)
  if [ ! -d "$SEEVAR_DIR" ]; then
    info "Cloning SeeVar repository..."
    git clone "$SEEVAR_REPO" "$SEEVAR_DIR"
  else
    info "SeeVar directory already exists at $SEEVAR_DIR — skipping clone."
  fi

  cd "$SEEVAR_DIR"

  create_directory_structure
  config_setup
  python_virtualenv_setup
  systemd_service_setup
  fetch_targets
  sanity_check
  print_banner
}

# Run setup if executed directly, allow sourcing for testing
(return 0 2>/dev/null) && sourced=1 || sourced=0
if [ "${sourced}" = 0 ]; then
  setup
fi
