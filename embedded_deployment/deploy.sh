#!/bin/sh
# ============================================================
# deploy.sh  —  Yocto 端部署腳本
# 從預先建置的 ARM64 tar 載入 Docker 映像並啟動容器
#
# 用法：
#   sh deploy.sh /tmp/macro-dashboard-arm64.tar
# ============================================================
set -e

TAR_FILE="${1:-/tmp/macro-dashboard-arm64.tar}"
IMAGE="macro-dashboard"
TAG="arm64"
FULL_TAG="${IMAGE}:${TAG}"
CONTAINER="macro-dashboard"
PORT=8501
DATA_DIR="/root/macro_dashboard_data"
ENV_FILE="/root/.env"

echo ""
echo "======================================================"
echo "  GAI MEDashBoard — Yocto Deploy"
echo "======================================================"
echo "  Image tar : $TAR_FILE"
echo "  Container : $CONTAINER"
echo "  Port      : $PORT"
echo "  Data dir  : $DATA_DIR"
echo "======================================================"
echo ""

# ── Step 1: 建立資料目錄（SQLite DB 持久化）──────────────────
mkdir -p "${DATA_DIR}/db"
echo "[1/5] Data directory ready: $DATA_DIR"

# ── Step 2: 載入新映像 ──────────────────────────────────────
if [ ! -f "$TAR_FILE" ]; then
    echo "ERROR: tar not found: $TAR_FILE"
    exit 1
fi

echo ""
echo "[2/5] Loading Docker image from $TAR_FILE..."
# docker load outputs the loaded image info; old tag becomes <none>:<none>
docker load -i "$TAR_FILE"
echo "      Image loaded: $FULL_TAG"

# ── Step 3: 停止並移除舊容器 ────────────────────────────────
echo ""
echo "[3/5] Stopping old container (if any)..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    docker stop  "${CONTAINER}" >/dev/null 2>&1 || true
    docker rm    "${CONTAINER}" >/dev/null 2>&1 || true
    echo "      Old container removed."
else
    echo "      No existing container found."
fi

# ── Step 4: 啟動新容器 ──────────────────────────────────────
echo ""
echo "[4/5] Starting container: $CONTAINER"

ENV_ARG=""
if [ -f "$ENV_FILE" ]; then
    ENV_ARG="--env-file $ENV_FILE"
    echo "      Using env file: $ENV_FILE"
fi

docker run -d \
    --name "${CONTAINER}" \
    --restart unless-stopped \
    --network host \
    -v "${DATA_DIR}:/app/app_data" \
    ${ENV_ARG} \
    "${FULL_TAG}"

echo "      Container started."

# ── Step 5: 清除懸空映像（舊版 <none>:<none>）────────────────
echo ""
echo "[5/5] Pruning dangling images..."
PRUNED=$(docker image prune -f 2>&1)
echo "      $PRUNED"

# ── 驗證 ────────────────────────────────────────────────────
echo ""
echo "Waiting 5s for container health check..."
sleep 5
STATUS=$(docker inspect --format='{{.State.Status}}' "${CONTAINER}" 2>/dev/null || echo "unknown")
echo "Container status: $STATUS"

echo ""
CURRENT_IP=$(ip -4 addr show eth0 2>/dev/null | awk '/inet / {split($2,a,"/"); print a[1]}' || \
             ip -4 addr 2>/dev/null | awk '/inet / && !/127\./ {split($2,a,"/"); print a[1]; exit}' || echo "")
echo "======================================================"
echo "  Deploy complete!"
if [ -n "$CURRENT_IP" ]; then
    echo "  Dashboard: http://${CURRENT_IP}:${PORT}"
else
    echo "  Dashboard: http://<device-ip>:${PORT}"
fi
echo "  Logs  : docker logs -f ${CONTAINER}"
echo "  DB    : ${DATA_DIR}/db/indicator_cache.sqlite3"
echo "  Stop  : docker stop ${CONTAINER}"
echo ""
echo "  Initial data load (15yr history, run once):"
echo "  docker exec ${CONTAINER} python scheduler.py --run-now"
echo "======================================================"
