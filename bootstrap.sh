#!/bin/bash
# =============================================================================
# Filename:  bootstrap.sh
# Version:   1.6.0
# Objective: Install SeeVar on fresh Debian Bookworm (Raspberry Pi).
#            Creates Python .venv, installs dependencies, runs interactive
#            questionnaire for telescope and site configuration, installs
#            user-level systemd services, runs initial full preflight pipeline,
#            and verifies the environment.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

SEEVAR_REPO="https://github.com/edjuh/seevar.git"
SEEVAR_DIR="${SEEVAR_DIR:-$HOME/seevar}"
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

  PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
  PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
  PY_VERSION="${PY_MAJOR}.${PY_MINOR}"

  if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python 3.11+ required. Detected ${PY_VERSION}."
  fi

  if [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -eq 11 ]; then
    info "Python ${PY_VERSION} — fully supported."
  elif [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -eq 12 ]; then
    info "Python ${PY_VERSION} — supported."
  elif [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 13 ]; then
    warn "Python ${PY_VERSION} detected. SeeVar is tested primarily on 3.11-3.12."
    warn "Most features should work, but some platform-specific wheels may lag."
  fi

  info "Environment validated — user: $(whoami), arch: $ARCH, python: ${PY_VERSION}"
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
    gpsd python3-gps \
    wget curl \
    cifs-utils

  sudo apt-get install --yes --no-install-recommends \
    astrometry.net \
    astrometry-data-tycho2-10-19

  sudo apt-get install --yes python3-smbus i2c-tools \
    && info "I2C tools installed." \
    || warn "I2C tools unavailable — fog sensor disabled. Expected on VirtualBox / x86_64."

  info "System packages installed."
}

# -----------------------------------------------------------------------------
# CLONE / UPDATE
# -----------------------------------------------------------------------------

function clone_repo {
  section "Cloning SeeVar repository"

  if [ ! -d "$SEEVAR_DIR/.git" ]; then
    git clone "$SEEVAR_REPO" "$SEEVAR_DIR"
    info "Repository cloned to $SEEVAR_DIR"
  else
    info "Repository already present — refreshing."
    cd "$SEEVAR_DIR"

    if [ -n "$(git status --porcelain)" ]; then
      warn "Repository has local changes. Skipping automatic git pull."
      warn "Review with: cd \"$SEEVAR_DIR\" && git status"
    else
      git fetch --all
      git pull --ff-only
      info "Repository updated."
    fi
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

  "$VENV/bin/pip" install \
    "astropy>=7.0,<8.0" \
    "astroquery>=0.4.11,<0.5" \
    "photutils>=2.3,<3.0" \
    "skyfield>=1.53,<2.0" \
    "ephem>=4.2,<5.0" \
    "sgp4>=2.25,<3.0" \
    "jplephem>=2.24,<3.0" \
    "pyerfa>=2.0,<3.0" \
    "numpy>=2.3,<3.0" \
    "scipy>=1.17,<2.0" \
    "scikit-image>=0.25,<1.0" \
    "opencv-python>=4.10,<5.0" \
    "pillow>=11.0,<12.0" \
    "pandas>=2.3,<3.0" \
    "flask>=3.1,<4.0" \
    "flask-cors>=6.0,<7.0" \
    "waitress>=3.0,<4.0" \
    "requests>=2.32,<3.0" \
    "toml>=0.10,<1.0" \
    "tomlkit>=0.13,<1.0" \
    "tomli-w>=1.2,<2.0" \
    "python-dotenv>=1.2,<2.0" \
    "gps>=3.19,<4.0" \
    "sdnotify>=0.3,<1.0" \
    "watchdog>=6.0,<7.0" \
    "humanize>=4.12,<5.0" \
    "pydantic>=2.11,<3.0" \
    "pydash>=8.0,<9.0" \
    "python-dateutil>=2.9,<3.0" \
    "pytz>=2022.7,<2026.0" \
    "tzlocal>=5.3,<6.0" \
    "tzdata>=2025.3,<2026.0" \
    "paramiko>=3.4,<4.0" \
    "clear-outside-apy>=1.0.0,<2.0"

  if [ "$PY_MINOR" -ge 13 ] 2>/dev/null; then
    "$VENV/bin/pip" install "rpi-lgpio" \
      && info "GPIO: rpi-lgpio installed (Python 3.13+ compatible)." \
      || warn "GPIO: rpi-lgpio install failed — fog sensor disabled."
  else
    "$VENV/bin/pip" install "RPi.GPIO>=0.7,<1.0" \
      && info "GPIO: RPi.GPIO installed." \
      || warn "GPIO: RPi.GPIO install failed — fog sensor disabled. Expected on x86_64."
  fi

  info "Python environment ready — $("$VENV/bin/python3" --version)"
}

# -----------------------------------------------------------------------------
# DIRECTORY STRUCTURE
# -----------------------------------------------------------------------------

function create_directory_structure {
  section "Creating data directory structure"

  if [ -L "$SEEVAR_DIR/data" ] && [ -d "$SEEVAR_DIR/data" ]; then
    info "'data' is a symlink to external storage — leaving it in place."
  elif [ -L "$SEEVAR_DIR/data" ] && [ ! -d "$SEEVAR_DIR/data" ]; then
    warn "Dangling 'data' symlink detected. Removing it to fall back to local storage."
    rm "$SEEVAR_DIR/data"
    mkdir -p "$SEEVAR_DIR/data"
  else
    mkdir -p "$SEEVAR_DIR/data"
  fi

  if [ -L "$SEEVAR_DIR/logs" ] && [ -d "$SEEVAR_DIR/logs" ]; then
    info "'logs' is a symlink to external storage — leaving it in place."
  elif [ -L "$SEEVAR_DIR/logs" ] && [ ! -d "$SEEVAR_DIR/logs" ]; then
    warn "Dangling 'logs' symlink detected. Removing it to fall back to local storage."
    rm "$SEEVAR_DIR/logs"
    mkdir -p "$SEEVAR_DIR/logs"
  else
    mkdir -p "$SEEVAR_DIR/logs"
  fi

  mkdir -p "$SEEVAR_DIR/data/local_buffer"
  mkdir -p "$SEEVAR_DIR/data/archive"
  mkdir -p "$SEEVAR_DIR/data/dark_library"
  mkdir -p "$SEEVAR_DIR/data/bias_library"
  mkdir -p "$SEEVAR_DIR/data/flat_library"
  mkdir -p "$SEEVAR_DIR/data/sequences"
  mkdir -p "$SEEVAR_DIR/data/comp_stars"
  mkdir -p "$SEEVAR_DIR/data/reports"
  mkdir -p "$SEEVAR_DIR/data/process"
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
# TOML UPDATE HELPER
# -----------------------------------------------------------------------------

function toml_set {
  local toml_file="$1"
  local key_path="$2"
  local value="$3"
  local value_type="${4:-string}"

  "$VENV/bin/python3" - "$toml_file" "$key_path" "$value" "$value_type" <<'PYEOF'
import sys
from pathlib import Path
import tomlkit

toml_path = Path(sys.argv[1])
key_path = sys.argv[2].split(".")
raw_value = sys.argv[3]
value_type = sys.argv[4]

text = toml_path.read_text(encoding="utf-8")
data = tomlkit.parse(text)

if value_type == "float":
    value = float(raw_value)
elif value_type == "int":
    value = int(raw_value)
elif value_type == "bool":
    value = raw_value.lower() in ("1", "true", "yes", "on")
else:
    value = raw_value

node = data
for part in key_path[:-1]:
    if part.isdigit():
        node = node[int(part)]
    else:
        node = node[part]

last = key_path[-1]
if last.isdigit():
    node[int(last)] = value
else:
    node[last] = value

toml_path.write_text(tomlkit.dumps(data), encoding="utf-8")
PYEOF
}

# -----------------------------------------------------------------------------
# GPS / UART SETUP
# -----------------------------------------------------------------------------

function setup_gps {
  section "GPS / UART setup"

  if [ "$(arch)" != "aarch64" ]; then
    warn "Skipping GPS/UART setup — not running on aarch64."
    return
  fi

  local CONFIG="/boot/firmware/config.txt"

  if ! grep -q "dtoverlay=uart0" "$CONFIG" 2>/dev/null; then
    sudo tee -a "$CONFIG" > /dev/null <<'UARTEOF'

# --- SeeVar GPS / UART ---
dtoverlay=uart0
enable_uart=1
dtparam=uart0=on
UARTEOF
    info "UART overlay added to config.txt"
  else
    info "UART overlay already present in config.txt — skipping."
  fi

  if sudo raspi-config nonint get_serial_cons 2>/dev/null | grep -q "0"; then
    info "Serial console already disabled."
  else
    sudo raspi-config nonint do_serial_hw 0
    sudo raspi-config nonint do_serial_cons 1
    info "Serial console disabled — /dev/ttyAMA0 is free for gpsd."
  fi

  sudo tee /etc/default/gpsd > /dev/null <<'GPSDEOF'
DEVICES="/dev/ttyAMA0"
GPSD_OPTIONS="-n"
START_DAEMON="true"
USBAUTO="false"
GPSDEOF

  sudo systemctl enable gpsd
  sudo systemctl restart gpsd \
    && info "gpsd configured and running on /dev/ttyAMA0" \
    || warn "gpsd failed to start — check: systemctl status gpsd"
}

# -----------------------------------------------------------------------------
# NAS MOUNT
# -----------------------------------------------------------------------------

function setup_nas_mount {
  section "NAS mount setup"

  if [ -z "${NAS_IP:-}" ] || [ -z "${NAS_SHARE:-}" ]; then
    info "No NAS configured — skipping."
    return
  fi

  local CREDS="/etc/samba/synology.creds"
  local MOUNT_POINT="/mnt/astro"

  sudo mkdir -p /etc/samba
  sudo mkdir -p "$MOUNT_POINT"

  sudo sh -c "umask 077 && cat > '$CREDS'" <<CREDSEOF
username=${NAS_USER}
password=${NAS_PASS}
CREDSEOF

  local FSTAB_ENTRY="//${NAS_IP}/${NAS_SHARE} ${MOUNT_POINT} cifs credentials=${CREDS},uid=$(id -u),gid=$(id -g),iocharset=utf8,_netdev 0 0"

  if grep -q "$MOUNT_POINT" /etc/fstab 2>/dev/null; then
    info "NAS mount already in fstab — skipping."
  else
    echo "$FSTAB_ENTRY" | sudo tee -a /etc/fstab > /dev/null
    info "NAS mount added to fstab: //${NAS_IP}/${NAS_SHARE} -> ${MOUNT_POINT}"
  fi

  sudo mount "$MOUNT_POINT" \
    && info "NAS mounted at ${MOUNT_POINT}" \
    || warn "NAS mount failed — check credentials and network. Entry is in fstab for next boot."
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
  read -rp "  NAS IP address (e.g. 192.168.178.3) : " NAS_IP
  read -rp "  NAS share name          [astro]      : " NAS_SHARE
  NAS_SHARE="${NAS_SHARE:-astro}"
  NAS_USER=""
  NAS_PASS=""
  if [ -n "$NAS_IP" ]; then
    read -rp "  NAS username                         : " NAS_USER
    read -rsp "  NAS password                         : " NAS_PASS
    echo
  fi

  [ -n "$AAVSO_CODE" ]   && toml_set "$TOML" "aavso.observer_code" "$AAVSO_CODE"
  [ -n "$AAVSO_WEBOBS" ] && toml_set "$TOML" "aavso.webobs_token" "$AAVSO_WEBOBS"
  [ -n "$AAVSO_TARGET" ] && toml_set "$TOML" "aavso.target_key" "$AAVSO_TARGET"

  toml_set "$TOML" "location.lat" "$LAT" float
  toml_set "$TOML" "location.lon" "$LON" float
  toml_set "$TOML" "location.elevation" "$ELEV" float
  toml_set "$TOML" "location.maidenhead" "$GRID"

  [ -n "$TG_TOKEN" ] && toml_set "$TOML" "notifications.telegram_bot_token" "$TG_TOKEN"
  [ -n "$TG_CHAT" ]  && toml_set "$TOML" "notifications.telegram_chat_id" "$TG_CHAT"

  if [ -n "$NAS_IP" ]; then
    toml_set "$TOML" "network.nas_ip" "$NAS_IP"
    toml_set "$TOML" "network.home_grid" "$GRID"
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

  toml_set "$TOML" "seestars.0.name" "$SCOPE_NAME"
  toml_set "$TOML" "seestars.0.model" "$SCOPE_MODEL"
  toml_set "$TOML" "seestars.0.ip" "$SCOPE_IP"

  info "Running fleet_mapper.py..."
  if "$VENV/bin/python3" "$SEEVAR_DIR/core/hardware/fleet_mapper.py"; then
    info "Fleet schema generated: data/fleet_schema.json"
  else
    warn "fleet_mapper.py returned an error. Edit [[seestars]] in config.toml and re-run:"
    warn "  cd ~/seevar && python3 core/hardware/fleet_mapper.py"
  fi

  info "Telescope: ${SCOPE_NAME} (${SCOPE_MODEL}) @ ${SCOPE_IP}"
}

# -----------------------------------------------------------------------------
# SYSTEMD SERVICES
# -----------------------------------------------------------------------------

function systemd_service_setup {
  section "Installing systemd user services"

  local SYSTEMD_DIR="$HOME/.config/systemd/user"
  mkdir -p "$SYSTEMD_DIR"
  local PYBIN="$VENV/bin/python3"

  cat > "$SYSTEMD_DIR/seevar-dashboard.service" <<SVCEOF
[Unit]
Description=SeeVar Dashboard
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
Environment=PYTHONPATH=${SEEVAR_DIR}
ExecStart=${PYBIN} core/dashboard/dashboard.py
Restart=always
RestartSec=10
StandardOutput=append:${SEEVAR_DIR}/logs/dashboard.log
StandardError=append:${SEEVAR_DIR}/logs/dashboard.err

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
ReadWritePaths=${SEEVAR_DIR}/data ${SEEVAR_DIR}/logs
TimeoutStartSec=30s
TimeoutStopSec=10s

[Install]
WantedBy=default.target
SVCEOF

  cat > "$SYSTEMD_DIR/seevar-planner.service" <<SVCEOF
[Unit]
Description=SeeVar Nightly Planner
After=network-online.target seevar-weather.service seevar-gps.service
Wants=network-online.target seevar-weather.service seevar-gps.service

[Service]
Type=oneshot
WorkingDirectory=${SEEVAR_DIR}
Environment=PYTHONPATH=${SEEVAR_DIR}
ExecStart=${PYBIN} core/preflight/nightly_planner.py
ExecStart=${PYBIN} core/preflight/schedule_compiler.py
StandardOutput=append:${SEEVAR_DIR}/logs/planner.log
StandardError=append:${SEEVAR_DIR}/logs/planner.log

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
ReadWritePaths=${SEEVAR_DIR}/data ${SEEVAR_DIR}/logs
TimeoutStartSec=180s
TimeoutStopSec=10s

[Install]
WantedBy=default.target
SVCEOF

  cat > "$SYSTEMD_DIR/seevar-planner.timer" <<SVCEOF
[Unit]
Description=Run SeeVar Nightly Planner Daily

[Timer]
OnBootSec=3min
OnCalendar=*-*-* 15:00:00
Persistent=true
Unit=seevar-planner.service

[Install]
WantedBy=timers.target
SVCEOF

  cat > "$SYSTEMD_DIR/seevar-orchestrator.service" <<SVCEOF
[Unit]
Description=SeeVar Science Orchestrator
After=network-online.target seevar-weather.service seevar-gps.service
Wants=network-online.target seevar-weather.service seevar-gps.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
Environment=PYTHONPATH=${SEEVAR_DIR}
ExecStart=${PYBIN} core/flight/orchestrator.py
Restart=always
RestartSec=15
StandardOutput=append:${SEEVAR_DIR}/logs/orchestrator.log
StandardError=append:${SEEVAR_DIR}/logs/orchestrator.log

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
ReadWritePaths=${SEEVAR_DIR}/data ${SEEVAR_DIR}/logs
TimeoutStartSec=30s
TimeoutStopSec=10s

[Install]
WantedBy=default.target
SVCEOF

  cat > "$SYSTEMD_DIR/seevar-weather.service" <<SVCEOF
[Unit]
Description=SeeVar Weather Sentinel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
Environment=PYTHONPATH=${SEEVAR_DIR}
ExecStart=${PYBIN} core/preflight/weather.py
Restart=always
RestartSec=30
StandardOutput=append:${SEEVAR_DIR}/logs/weather.log
StandardError=append:${SEEVAR_DIR}/logs/weather.err

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
ReadWritePaths=${SEEVAR_DIR}/data ${SEEVAR_DIR}/logs
TimeoutStartSec=30s
TimeoutStopSec=10s

[Install]
WantedBy=default.target
SVCEOF

  cat > "$SYSTEMD_DIR/seevar-gps.service" <<SVCEOF
[Unit]
Description=SeeVar Continuous GPS Monitor
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${SEEVAR_DIR}
Environment=PYTHONPATH=${SEEVAR_DIR}
ExecStart=${PYBIN} core/utils/gps_monitor.py
Restart=always
RestartSec=10
StandardOutput=append:${SEEVAR_DIR}/logs/gps.log
StandardError=append:${SEEVAR_DIR}/logs/gps.err

NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
ReadWritePaths=${SEEVAR_DIR}/data ${SEEVAR_DIR}/logs
TimeoutStartSec=30s
TimeoutStopSec=10s

[Install]
WantedBy=default.target
SVCEOF

  chmod 644 "$SYSTEMD_DIR"/*.service "$SYSTEMD_DIR"/*.timer

  sudo loginctl enable-linger "$(whoami)"
  systemctl --user daemon-reload

  for service in seevar-weather seevar-orchestrator seevar-dashboard seevar-gps; do
    systemctl --user enable "$service"
    info "Enabled ${service}"
  done
  systemctl --user enable seevar-planner.timer
  info "Enabled seevar-planner.timer"

  section "Starting services"
  for service in seevar-weather seevar-orchestrator seevar-dashboard seevar-gps; do
    systemctl --user start "$service" \
      && info "Started ${service}" \
      || warn "${service} did not start cleanly — check: systemctl --user status ${service}"
  done
  systemctl --user start seevar-planner.service \
    && info "Ran initial seevar-planner.service" \
    || warn "seevar-planner.service did not start cleanly — check: systemctl --user status seevar-planner.service"
  systemctl --user start seevar-planner.timer \
    && info "Started seevar-planner.timer" \
    || warn "seevar-planner.timer did not start cleanly — check: systemctl --user status seevar-planner.timer"

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
# INITIAL PREFLIGHT PIPELINE
# -----------------------------------------------------------------------------

function run_initial_preflight {
  section "Running initial preflight pipeline"

  local PYBIN="$VENV/bin/python3"
  cd "$SEEVAR_DIR"

  info "Step 1/4 — Librarian: building federation catalog..."
  "$PYBIN" core/preflight/librarian.py \
    && info "Federation catalog ready." \
    || warn "librarian.py returned an error — check logs/librarian.log"

  info "Step 2/4 — Cadence Auditor: cross-referencing ledger..."
  "$PYBIN" core/preflight/audit.py \
    && info "Cadence audit complete." \
    || warn "audit.py returned an error — check logs/audit.log"

  info "Step 3/4 — Nightly Planner: filtering by horizon/altitude/cadence..."
  "$PYBIN" core/preflight/nightly_planner.py \
    && info "tonights_plan.json ready." \
    || warn "nightly_planner.py returned an error — check logs/nightly_planner.log"

  info "Step 4/4 — Schedule Compiler: generating SSC payload..."
  "$PYBIN" core/preflight/schedule_compiler.py \
    && info "ssc_payload.json ready." \
    || warn "schedule_compiler.py returned an error — check logs/schedule_compiler.log"

  info "Initial preflight pipeline complete — observatory is ready."
}

# -----------------------------------------------------------------------------
# SANITY CHECK
# -----------------------------------------------------------------------------

function sanity_check {
  section "Sanity check"

  local PYBIN="$VENV/bin/python3"
  local ok=true

  info "Python: $("$PYBIN" --version)"

  "$PYBIN" -c "import astropy, photutils, numpy, flask, skyfield, toml, tomli_w, tomlkit, tomllib" \
    && info "Core science imports OK" \
    || { warn "One or more core imports failed — review pip output above."; ok=false; }

  command -v gpsd &>/dev/null \
    && info "gpsd: $(gpsd --version 2>&1 | head -1)" \
    || warn "gpsd not found — GPS location will not be available."

  command -v solve-field &>/dev/null \
    && info "astrometry.net solve-field: OK" \
    || warn "solve-field not found — plate solving will not work."

  grep -q "YOUR_CODE_HERE" "$SEEVAR_DIR/config.toml" 2>/dev/null \
    && warn "config.toml: AAVSO observer code not set — edit before starting." \
    || info "config.toml: AAVSO observer code populated."

  grep -q '"TBD"' "$SEEVAR_DIR/config.toml" 2>/dev/null \
    && warn "config.toml: telescope IP still TBD — update [[seestars]] ip when known." \
    || info "config.toml: telescope IP set."

  $ok && info "Sanity check passed." || warn "Sanity check completed with warnings."
}

# -----------------------------------------------------------------------------
# BANNER
# -----------------------------------------------------------------------------

function print_banner {
  local HOST
  HOST=$(hostname)

  local DASH_LINE
  DASH_LINE=$(printf "%-53.53s" "  Dashboard : http://${HOST}.local:5050")

  cat <<BANNEREOF

┌─────────────────────────────────────────────────────┐
│            SeeVar Installation Complete             │
│                                                     │
│  Services started — waiting for astronomical night. │
│  Tonight's flight plan is loaded and ready.         │
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

BANNEREOF
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
  setup_nas_mount
  telescope_questionnaire
  setup_gps
  systemd_service_setup
  fetch_targets
  run_initial_preflight
  sanity_check
  print_banner
}

(return 0 2>/dev/null) && sourced=1 || sourced=0
[ "${sourced}" = 0 ] && setup
