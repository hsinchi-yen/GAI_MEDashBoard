# ============================================================
# build_arm64.ps1
# 本地 Windows 交叉編譯 ARM64 Docker 映像，並 SCP 部署至 Yocto
# 用法：
#   .\build_arm64.ps1                    # 只 build + 存 tar
#   .\build_arm64.ps1 -Deploy            # build + 存 tar + SCP + 遠端部署
#   .\build_arm64.ps1 -Deploy -YoctoIP 192.168.1.100
# ============================================================
param(
    [switch]$Deploy,
    [string]$YoctoIP   = "10.1.1.230",
    [string]$YoctoUser = "root",
    [string]$YoctoPath = "/root",
    [string]$SshKey    = ""          # 可選：-SshKey "C:\path\to\key.pem"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$IMAGE    = "macro-dashboard"
$TAG      = "arm64"
$FULL_TAG = "${IMAGE}:${TAG}"
$TAR_FILE = "macro-dashboard-arm64.tar"
$BUILDER  = "arm64-builder"
$DOCKERFILE = "embedded_deployment\Dockerfile"

Write-Host ""
Write-Host "======================================================"
Write-Host "  GAI MEDashBoard — ARM64 Cross Build"
Write-Host "======================================================"
Write-Host "  Image     : $FULL_TAG"
Write-Host "  Dockerfile: $DOCKERFILE"
Write-Host "  Output    : $TAR_FILE"
if ($Deploy) {
    Write-Host "  Deploy to : ${YoctoUser}@${YoctoIP}:${YoctoPath}"
}
Write-Host "======================================================"
Write-Host ""

# ── Step 1: 確保 arm64-builder 運行中 ───────────────────────
Write-Host "[1/4] 啟動 arm64-builder..."
docker buildx inspect $BUILDER --bootstrap | Out-Null
Write-Host "      Builder ready."

# ── Step 2: Cross-build ARM64 映像 ──────────────────────────
Write-Host ""
Write-Host "[2/4] Cross-building linux/arm64 image..."
Write-Host "      (首次建置需下載 base image，約 5-15 分鐘)"
$buildStart = Get-Date
docker buildx build `
    --builder $BUILDER `
    --platform linux/arm64 `
    --load `
    --tag $FULL_TAG `
    --file $DOCKERFILE `
    .
$buildSec = [int]((Get-Date) - $buildStart).TotalSeconds
Write-Host "      Build completed in ${buildSec}s."

# ── Step 3: 匯出為 tar ──────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Saving image to ${TAR_FILE}..."
$saveStart = Get-Date
docker save $FULL_TAG -o $TAR_FILE
$tarSizeMB = [math]::Round((Get-Item $TAR_FILE).Length / 1MB, 1)
$saveSec   = [int]((Get-Date) - $saveStart).TotalSeconds
Write-Host "      Saved: $TAR_FILE ($tarSizeMB MB, ${saveSec}s)"

# ── Step 4: SCP + 遠端部署（僅 -Deploy 時執行）──────────────
if (-not $Deploy) {
    Write-Host ""
    Write-Host "[4/4] Skipped (no -Deploy flag)."
    Write-Host ""
    Write-Host "手動部署指令："
    Write-Host "  scp $TAR_FILE ${YoctoUser}@${YoctoIP}:${YoctoPath}/"
    Write-Host "  ssh ${YoctoUser}@${YoctoIP} 'sh ${YoctoPath}/deploy.sh'"
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "[4/4] Deploying to Yocto (${YoctoUser}@${YoctoIP})..."

$sshOpts = @("-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10")
if ($SshKey -ne "") { $sshOpts += @("-i", $SshKey) }

# 上傳 tar
Write-Host "      Uploading $TAR_FILE..."
& scp @sshOpts $TAR_FILE "${YoctoUser}@${YoctoIP}:${YoctoPath}/"
if ($LASTEXITCODE -ne 0) { Write-Error "SCP failed"; exit 1 }

# 上傳 deploy.sh
Write-Host "      Uploading deploy.sh..."
& scp @sshOpts "embedded_deployment\deploy.sh" "${YoctoUser}@${YoctoIP}:${YoctoPath}/"
if ($LASTEXITCODE -ne 0) { Write-Error "SCP deploy.sh failed"; exit 1 }

# 遠端執行 deploy.sh
Write-Host "      Running deploy.sh on Yocto..."
& ssh @sshOpts "${YoctoUser}@${YoctoIP}" "chmod +x ${YoctoPath}/deploy.sh && sh ${YoctoPath}/deploy.sh ${YoctoPath}/${TAR_FILE}"
if ($LASTEXITCODE -ne 0) { Write-Error "Remote deploy failed"; exit 1 }

Write-Host ""
Write-Host "======================================================"
Write-Host "  Deploy complete!"
Write-Host "  Dashboard: http://${YoctoIP}:8501"
Write-Host "======================================================"
