# Embedded Deployment Guide — GAI_MEDashBoard

Target: Yocto-based embedded system with Docker, **no docker-compose**.  
Destination path on device: `/root/GAI_MEDASHBOARD/` (root's home is `/root`, not `/home`)

---

## Files in this folder

| File | Purpose |
|---|---|
| `Dockerfile` | Container image definition |
| `dashboard.py` | Streamlit app entry point |
| `data_fetcher.py` | Data fetching module |
| `macro_index.py` | Macro index computation module |
| `requirements.txt` | Python dependencies |
| `run_docker.sh` | Build + run script (no docker-compose required) |

---

## Step 1 — Check device architecture

SSH into the device and confirm the CPU architecture:

```sh
uname -m
```

Expected values and the corresponding Docker platform:

| `uname -m` | Platform tag |
|---|---|
| `aarch64` | `linux/arm64` |
| `armv7l` | `linux/arm/v7` |
| `x86_64` | `linux/amd64` |

The base image `python:3.11-slim` supports all three architectures — Docker will select the right variant automatically when you build on the device.

---

## Step 2 — Create destination directory on the device

SSH into the device first, then:

```sh
mkdir -p /root/GAI_MEDASHBOARD
```

---

## Step 3 — SCP files from this machine to the device

Run the following from your **Windows machine** (replace `<USER>` and `<DEVICE_IP>`):

```sh
# Copy the entire embedded_deployment folder contents
scp -r "embedded_deployment/." <USER>@<DEVICE_IP>:/root/GAI_MEDASHBOARD/
```

Example with a concrete IP:

```sh
scp -r "embedded_deployment/." root@192.168.1.100:/root/GAI_MEDASHBOARD/
```

If you are on Windows and using PowerShell / Command Prompt, `scp` is available via OpenSSH (built into Windows 10/11).  
If your device uses a non-standard SSH port (e.g. 2222), add `-P 2222`:

```sh
scp -P 2222 -r "embedded_deployment/." root@192.168.1.100:/root/GAI_MEDASHBOARD/
```

---

## Step 4 — SSH into the device and make the script executable

```sh
ssh <USER>@<DEVICE_IP>
chmod +x /root/GAI_MEDASHBOARD/run_docker.sh
```

---

## Step 5 — Build and run the container

```sh
cd /root/GAI_MEDASHBOARD
./run_docker.sh
```

The script will:
1. Remove any existing container with the same name.
2. Build the Docker image from the local `Dockerfile`.
3. Start the container with `--restart unless-stopped` so it survives reboots.

Access the dashboard at `http://<DEVICE_IP>:8501`.

---

## Useful commands on the device

```sh
# Follow live logs
docker logs -f macro-dashboard

# Stop the container
docker stop macro-dashboard

# Remove the container (image is kept)
docker rm macro-dashboard

# Remove image and container completely
docker stop macro-dashboard && docker rm macro-dashboard && docker rmi macro-dashboard

# Check container status
docker ps -a
```

---

## Auto-start on boot (no docker-compose)

The container already uses `--restart unless-stopped`, so Docker will restart it automatically after a reboot as long as the Docker daemon itself starts on boot.

Verify the Docker daemon is enabled in Yocto:

```sh
# systemd-based Yocto
systemctl enable docker
systemctl start docker
```

If Yocto uses SysVinit instead of systemd, check `/etc/init.d/docker` exists and is enabled.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `exec format error` | Architecture mismatch — build the image **on the device**, not cross-compiled |
| Port 8501 unreachable | `iptables -L` — firewall may be blocking the port |
| Out of storage | `df -h /home` — eMMC may be full; remove unused images with `docker image prune` |
| Container exits immediately | `docker logs macro-dashboard` — check Python import errors |
