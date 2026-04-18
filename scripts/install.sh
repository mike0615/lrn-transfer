#!/usr/bin/env bash
# =============================================================================
# install.sh — lrn-transfer post-RPM setup script
# =============================================================================
# Run as root after installing the RPM. Creates the Python venv and
# installs paramiko from bundled wheels (air-gapped) or from PyPI (online).
#
# Usage:
#   sudo bash /opt/lrn-transfer/install.sh
# =============================================================================
set -euo pipefail

APP_HOME="/opt/lrn-transfer"
APP_CONF="/etc/lrn-transfer"
APP_LOG="/var/log/lrn-transfer"
APP_LIB="/var/lib/lrn-transfer"
APP_USER="lrn-transfer"
VENV="${APP_HOME}/venv"
WHEELS_DIR="${APP_HOME}/wheels"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()     { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${YELLOW}=== $* ===${NC}"; }

[[ "$(id -u)" -eq 0 ]] || die "Must run as root"

section "Creating system user"
getent group  "$APP_USER" >/dev/null || groupadd -r "$APP_USER"
getent passwd "$APP_USER" >/dev/null || \
    useradd -r -g "$APP_USER" -d "$APP_LIB" -s /sbin/nologin \
        -c "lrn-transfer service account" "$APP_USER"
log "User: $APP_USER"

section "Creating directories"
mkdir -p "$APP_LOG" "$APP_LIB" "$APP_CONF/keys"
chown "$APP_USER:$APP_USER" "$APP_LOG" "$APP_LIB"
chmod 750 "$APP_LOG" "$APP_LIB"
chmod 700 "$APP_CONF/keys"
log "Directories ready"

section "Building Python virtual environment"
command -v python3 &>/dev/null || die "python3 is required (dnf install python3)"

if [[ -d "$VENV" ]]; then
    warn "Existing venv found at $VENV — removing and rebuilding"
    rm -rf "$VENV"
fi

python3 -m venv "$VENV"
log "Venv created: $VENV"

section "Installing paramiko"
if [[ -d "$WHEELS_DIR" ]] && ls "$WHEELS_DIR"/*.whl &>/dev/null 2>&1; then
    log "Installing from bundled wheels (air-gapped): $WHEELS_DIR"
    "$VENV/bin/pip" install --no-index --find-links="$WHEELS_DIR" paramiko
else
    warn "No bundled wheels found — installing from PyPI (requires internet)"
    "$VENV/bin/pip" install paramiko
fi

# Verify
"$VENV/bin/python3" -c "import paramiko; print(f'paramiko {paramiko.__version__} OK')" \
    || die "paramiko import failed"
log "paramiko installed successfully"

section "Setting ownership"
chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod 755 "$APP_HOME/lrn-transferd.py"
log "Ownership set to $APP_USER"

section "Configuring systemd"
systemctl daemon-reload

if [[ ! -f "$APP_CONF/lrn-transfer.conf" ]]; then
    section "Creating default config"
    cp "$APP_CONF/lrn-transfer.conf.example" "$APP_CONF/lrn-transfer.conf"
    chown root:"$APP_USER" "$APP_CONF/lrn-transfer.conf"
    chmod 640 "$APP_CONF/lrn-transfer.conf"
    warn "Default config installed at $APP_CONF/lrn-transfer.conf"
    warn "Edit it before starting the service!"
else
    log "Config already exists: $APP_CONF/lrn-transfer.conf"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  lrn-transfer setup complete"
echo ""
echo "  Next steps:"
echo "    1. Edit config:"
echo "         nano $APP_CONF/lrn-transfer.conf"
echo ""
echo "    2. Generate SSH key for SFTP auth:"
echo "         ssh-keygen -t ed25519 -f $APP_CONF/keys/id_ed25519_transfer"
echo "         # Copy public key to transfer PC's authorized_keys"
echo ""
echo "    3. Enable and start:"
echo "         systemctl enable --now lrn-transfer"
echo ""
echo "    4. Check status:"
echo "         systemctl status lrn-transfer"
echo "         journalctl -u lrn-transfer -f"
echo ""
echo "    5. View transfer history:"
echo "         $VENV/bin/python3 $APP_HOME/lrn-transferd.py \\"
echo "             --config $APP_CONF/lrn-transfer.conf --status"
echo "═══════════════════════════════════════════════════════════════"
