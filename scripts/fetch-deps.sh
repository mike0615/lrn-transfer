#!/usr/bin/env bash
# =============================================================================
# fetch-deps.sh — Download all Python wheels for air-gapped lrn-transfer install.
# Run on an INTERNET-CONNECTED Rocky Linux 9 machine.
# Output: SOURCES/wheels/ populated with paramiko and all dependencies.
#
# Usage:
#   ./scripts/fetch-deps.sh
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHEELS_DIR="${ROOT}/SOURCES/wheels"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

command -v pip3 &>/dev/null || die "pip3 is required"
command -v python3 &>/dev/null || die "python3 is required"

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')")
PLATFORM="manylinux_2_28_x86_64"

mkdir -p "$WHEELS_DIR"
log "Downloading Python wheels to: $WHEELS_DIR"
log "Target: Python ${PYTHON_VER} / ${PLATFORM}"

# Download paramiko and all its transitive dependencies as binary wheels.
# Try platform-constrained first (for cross-arch builds), fall back to native.
pip3 download \
    "paramiko>=3.4.0" \
    --only-binary=:all: \
    --platform="${PLATFORM}" \
    --python-version="${PYTHON_VER}" \
    --no-deps \
    -d "$WHEELS_DIR" 2>/dev/null && \
pip3 download \
    "paramiko>=3.4.0" \
    --only-binary=:all: \
    --platform="${PLATFORM}" \
    --python-version="${PYTHON_VER}" \
    --no-deps \
    --no-index --find-links="$WHEELS_DIR" \
    -d "$WHEELS_DIR" 2>/dev/null || true

# Full resolve without platform constraints (works natively, most reliable)
pip3 download \
    "paramiko>=3.4.0" \
    -d "$WHEELS_DIR" || die "Failed to download paramiko wheels"

WHEEL_COUNT=$(ls "$WHEELS_DIR"/*.whl "$WHEELS_DIR"/*.tar.gz 2>/dev/null | wc -l)
log "Downloaded ${WHEEL_COUNT} packages to $WHEELS_DIR"
log "Packages:"
ls "$WHEELS_DIR" | sed 's/^/  /'

log "Done. Next step: make rpm"
