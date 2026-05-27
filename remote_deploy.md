# Remote Yocto Deploy — Operating Rules

> Version: 2026-05-28  
> Target: `root@10.1.1.230` — Yocto aarch64 (pico-imx8mm), Docker only (no docker-compose)  
> Applies to: any Python/Streamlit project cross-compiled for ARM64

---

## Prerequisites (local machine)

| Requirement | Check |
|---|---|
| Docker Desktop with buildx | `docker buildx version` |
| `arm64-builder` buildx builder | `docker buildx inspect arm64-builder` |
| SSH key or password for `root@10.1.1.230` | `ssh root@10.1.1.230 echo ok` |
| `build_arm64.ps1` in project root | see scaffold below |
| `embedded_deployment/Dockerfile` | ARM64-compatible, no x86 assumptions |
| `embedded_deployment/deploy.sh` | see scaffold below |

Create the arm64 builder once:
```powershell
docker buildx create --name arm64-builder --use
docker buildx inspect arm64-builder --bootstrap
```

---

## Step 1 — Code is committed

Never build from a dirty working tree. Verify before building:
```powershell
git status --short    # should be empty or only untracked docs
git log --oneline -3
```

---

## Step 2 — Cross-compile + Deploy (one command)

```powershell
.\build_arm64.ps1 -Deploy
```

What this does:
1. `docker buildx build --platform linux/arm64 --load` → image `macro-dashboard:arm64`
2. `docker save` → `macro-dashboard-arm64.tar` (~1 GB)
3. `scp` tar + `deploy.sh` to `/root/` on remote
4. SSH → `sh /root/deploy.sh /root/macro-dashboard-arm64.tar`

`deploy.sh` on the remote:
1. `docker load` the tar (old image becomes `<none>:<none>`)
2. `docker stop` + `docker rm` the old container
3. `docker run -d --restart unless-stopped --network host -v /root/macro_dashboard_data:/app/app_data --env-file /root/.env <image>`
4. `docker image prune -f` (removes the `<none>` dangling image automatically)

Optional params:
```powershell
.\build_arm64.ps1 -Deploy -YoctoIP 192.168.1.5 -SshKey C:\keys\id_rsa
```

---

## Step 3 — Verify container health

```powershell
ssh root@10.1.1.230 "docker inspect --format 'Status: {{.State.Status}}  Health: {{.State.Health.Status}}' macro-dashboard"
ssh root@10.1.1.230 "curl -sf http://localhost:8501/_stcore/health && echo OK"
```

Expected: `Status: running  Health: healthy` and `okOK`.

---

## Step 4 — Initial data load (first deploy or after DB wipe)

The DB is persisted in the host volume `/root/macro_dashboard_data/db/`. On a **fresh deploy** (empty DB), run the scheduler once to populate 15 years of history:

```bash
docker exec macro-dashboard python scheduler.py --run-now
```

This takes ~10–15 minutes. Run it in the background and tail logs:
```bash
docker exec -d macro-dashboard python scheduler.py --run-now
docker logs -f macro-dashboard
```

Skip on re-deploy if the volume already has data (the volume survives container restarts).

---

## Step 5 — Cleanup (after each deploy)

The `deploy.sh` prunes dangling images automatically. After SCP you should also remove the tar:

```bash
# Already handled by deploy.sh but confirm manually if needed:
ssh root@10.1.1.230 "rm -f /root/macro-dashboard-arm64.tar && echo removed"
```

For unused images from other projects — **check containers first**, then remove only if no container uses them:
```bash
ssh root@10.1.1.230 "docker ps -a --format '{{.Image}}'"   # see what's in use
ssh root@10.1.1.230 "docker rmi <image:tag>"               # only for confirmed orphans
```

---

## Step 6 — Acceptance tests

### 6a. Fetcher live test (new/modified fetchers)
```bash
# SCP the test script into container and run
scp tests/acceptance_fetchers.py root@10.1.1.230:/tmp/
ssh root@10.1.1.230 "docker cp /tmp/acceptance_fetchers.py macro-dashboard:/app/tests/ && docker exec macro-dashboard python /app/tests/acceptance_fetchers.py"
```
Each fetcher should show `[PASS]` with a non-empty row count and sensible latest value.

### 6b. GMI regime check (after DB is populated)
```bash
scp tests/acceptance_gmi.py root@10.1.1.230:/tmp/
ssh root@10.1.1.230 "docker cp /tmp/acceptance_gmi.py macro-dashboard:/app/tests/ && docker exec macro-dashboard python /app/tests/acceptance_gmi.py"
```
Expect `valid_count ≥ 15` and `regime ≠ unknown`.

### 6c. Dashboard HTTP
```
http://10.1.1.230:8501
```

---

## Rollback

The old image is retained as `<none>:<none>` only until `docker image prune` runs. To rollback, you must re-deploy the previous tar from the local machine.

**Mitigation**: tag the previous image before deploying:
```bash
ssh root@10.1.1.230 "docker tag macro-dashboard:arm64 macro-dashboard:prev"
# deploy new image
# if rollback needed:
ssh root@10.1.1.230 "docker stop macro-dashboard && docker rm macro-dashboard && docker run -d --name macro-dashboard --restart unless-stopped --network host -v /root/macro_dashboard_data:/app/app_data --env-file /root/.env macro-dashboard:prev"
```

---

## Key paths on remote

| Path | Purpose |
|---|---|
| `/root/macro_dashboard_data/db/indicator_cache.sqlite3` | Persistent SQLite DB (15-yr history) |
| `/root/.env` | API keys (FRED_API_KEY, FINMIND_TOKEN, …) |
| `/root/deploy.sh` | Deployment script (updated on each deploy) |
| Container `/app/` | Application code (ephemeral — lost on image change) |

---

## Scaffold files

### `build_arm64.ps1` (local, project root)
```powershell
param(
    [switch]$Deploy,
    [string]$YoctoIP   = "10.1.1.230",
    [string]$YoctoUser = "root",
    [string]$YoctoPath = "/root",
    [string]$SshKey    = ""
)
$IMAGE = "macro-dashboard"; $TAG = "arm64"; $FULL_TAG = "${IMAGE}:${TAG}"
$TAR   = "macro-dashboard-arm64.tar"; $BUILDER = "arm64-builder"
docker buildx build --builder $BUILDER --platform linux/arm64 --load --tag $FULL_TAG --file embedded_deployment\Dockerfile .
docker save $FULL_TAG -o $TAR
if (-not $Deploy) { exit 0 }
$sshOpts = @("-o","StrictHostKeyChecking=no","-o","ConnectTimeout=10")
if ($SshKey) { $sshOpts += @("-i",$SshKey) }
& scp @sshOpts $TAR embedded_deployment\deploy.sh "${YoctoUser}@${YoctoIP}:${YoctoPath}/"
& ssh @sshOpts "${YoctoUser}@${YoctoIP}" "chmod +x ${YoctoPath}/deploy.sh && sh ${YoctoPath}/deploy.sh ${YoctoPath}/${TAR}"
```

### `embedded_deployment/deploy.sh` (deployed to remote on each run)
Core logic (see full version in repo):
```sh
docker load -i "$TAR_FILE"
docker stop  "$CONTAINER" && docker rm "$CONTAINER"
docker run -d --name "$CONTAINER" --restart unless-stopped --network host \
    -v "${DATA_DIR}:/app/app_data" ${ENV_ARG} "${FULL_TAG}"
docker image prune -f
rm -f "$TAR_FILE"   # clean tar after load
```
