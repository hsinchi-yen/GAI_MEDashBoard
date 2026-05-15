#!/bin/sh
set -e

IMAGE=macro-dashboard
CONTAINER=macro-dashboard
PORT=8501

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Remove existing container if present
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Stopping and removing existing container: ${CONTAINER}"
    docker stop "${CONTAINER}" >/dev/null 2>&1 || true
    docker rm   "${CONTAINER}" >/dev/null 2>&1 || true
fi

echo "Building image: ${IMAGE}"
docker build -t "${IMAGE}" "${SCRIPT_DIR}"

ETH0_IP=$(ip -4 addr show eth0 2>/dev/null | awk '/inet / {split($2,a,"/"); print a[1]}')
if [ -z "${ETH0_IP}" ]; then
    echo "ERROR: could not resolve an IPv4 address for eth0. Is the interface up?"
    exit 1
fi
echo "eth0 address: ${ETH0_IP}"

echo "Starting container: ${CONTAINER}"
# --network host avoids iptables NAT port-mapping (iptable_raw kernel module
# is absent on this board). STREAMLIT_SERVER_ADDRESS pins Streamlit to eth0
# only, overriding the address = "0.0.0.0" in config.toml.
docker run -d \
    --name "${CONTAINER}" \
    --restart unless-stopped \
    --network host \
    -e STREAMLIT_SERVER_ADDRESS="${ETH0_IP}" \
    "${IMAGE}"

echo ""
echo "Dashboard running at http://${ETH0_IP}:${PORT}"
echo "  Logs  : docker logs -f ${CONTAINER}"
echo "  Stop  : docker stop ${CONTAINER}"
echo "  Remove: docker rm ${CONTAINER}"
