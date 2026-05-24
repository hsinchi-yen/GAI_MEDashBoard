#!/bin/sh
set -e

IMAGE=macro-dashboard
CONTAINER=macro-dashboard
PORT=8501

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 確保 Docker daemon 開機自動啟動（僅需設定一次，冪等操作）
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker >/dev/null 2>&1 || true
fi

# Remove existing container if present
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Stopping and removing existing container: ${CONTAINER}"
    docker stop "${CONTAINER}" >/dev/null 2>&1 || true
    docker rm   "${CONTAINER}" >/dev/null 2>&1 || true
fi

echo "Building image: ${IMAGE}"
docker build -t "${IMAGE}" "${SCRIPT_DIR}"

DATA_DIR="/root/macro_dashboard_data"
ENV_FILE="/root/.env"
mkdir -p "${DATA_DIR}/db"

ENV_ARG=""
if [ -f "$ENV_FILE" ]; then
    ENV_ARG="--env-file $ENV_FILE"
fi

echo "Starting container: ${CONTAINER}"
# --network host: 繞過 iptables NAT port-mapping（此板無 iptable_raw 模組）
# -v: 持久化 SQLite DB，避免容器重建後資料遺失
docker run -d \
    --name "${CONTAINER}" \
    --restart unless-stopped \
    --network host \
    -v "${DATA_DIR}:/app/app_data" \
    ${ENV_ARG} \
    "${IMAGE}"

# 僅用於顯示，不影響 Streamlit 綁定行為
CURRENT_IP=$(ip -4 addr show eth0 2>/dev/null | awk '/inet / {split($2,a,"/"); print a[1]}')
echo ""
if [ -n "${CURRENT_IP}" ]; then
    echo "Dashboard running at http://${CURRENT_IP}:${PORT}"
else
    echo "Dashboard running at http://<device-ip>:${PORT}"
fi
echo "  Logs  : docker logs -f ${CONTAINER}"
echo "  Stop  : docker stop ${CONTAINER}"
echo "  Remove: docker rm ${CONTAINER}"
