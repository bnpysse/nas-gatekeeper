#!/bin/bash
# ==========================================
# Omni Radar V6.0
# N100 (Debian LXC) Podman/Docker Deploy Script
# ==========================================
set -e

APP_DIR="/opt/omni"
IMAGE="omni-app:latest"

echo "=========================================="
echo "  Omni Radar System - Local Deployment"
echo "  Target: N100 (Debian LXC)"
echo "=========================================="

# ── 1. Check Docker / Podman ──
if command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo ">>> ERROR: No compose utility found (podman-compose or docker compose)."
    exit 1
fi

echo ">>> Using compose command: ${COMPOSE_CMD}"

# ── 2. Build Image Online ──
echo ">>> Building application image..."
if [[ "$COMPOSE_CMD" == *"podman"* ]]; then
    podman build -t ${IMAGE} .
else
    docker build -t ${IMAGE} .
fi

# ── 3. Start Streamlit Container ──
echo ">>> Starting services..."
${COMPOSE_CMD} up -d --build

echo ""
echo ">>> Container status:"
${COMPOSE_CMD} ps

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "  Omni Streamlit is now running on 127.0.0.1:8501."
echo "  Ensure your N100 Gatekeeper reverse proxy routes /omni to this port."
echo "=========================================="

