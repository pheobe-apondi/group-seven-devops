# Setup — macOS (Multipass + Ubuntu 24.04 LTS)

Goal: by the end of this guide you have an Ubuntu 24.04 LTS VM on your Mac and this repository running inside it.

> This project assumes **Ubuntu Server 24.04 LTS**. Other distros mostly work but are not the supported target.

## 1. Host requirements

| Resource | Minimum |
|---|---|
| CPU | 2 cores free |
| RAM | 4 GB free |
| Disk | 20 GB free |
| macOS | 13 Ventura or newer |

## 2. Install Multipass

```bash
brew install --cask multipass
multipass version   # verify
```

If you don't have Homebrew: https://brew.sh

## 3. Create the dedicated host folder

The VM mounts **only** `~/group-seven-devops/` — not your entire home directory.

```bash
mkdir -p ~/group-seven-devops
cd ~/group-seven-devops
git clone https://github.com/pheobe-apondi/group-seven-devops.git
```

## 4. Start the VM

```bash
multipass launch 24.04 \
  --name group-seven \
  --cpus 1 \
  --memory 1G \
  --disk 8G \
  --mount "$HOME/group-seven-devops:/home/ubuntu/group-seven-devops"
```

### VM profile

| Resource | Value |
|---|---|
| CPU | 1 |
| RAM | 1 GB |
| Disk | 8 GB |
| Host mount | `~/group-seven-devops` → `/home/ubuntu/group-seven-devops` |

## 5. Get into the VM

```bash
multipass shell group-seven
```

Your prompt should look like `ubuntu@group-seven:~$`. All commands below run **inside the VM**.

## 6. Enter the repository

```bash
cd ~/group-seven-devops/group-seven-devops
ls
```

## 7. Verify you're on Ubuntu 24.04

```bash
lsb_release -a   # Description should say Ubuntu 24.04 LTS
```

## 8. Run the installer

```bash
chmod +x install.sh reset.sh health-check.sh
sudo ./install.sh
```

Validate:

```bash
curl http://localhost/service-a/health
curl http://127.0.0.1:3002/health
curl http://127.0.0.1:3003/health
curl http://localhost/service-a/greet-service-b
```

To hit the API from your Mac (outside the VM):

```bash
multipass info group-seven   # look at the "IPv4" line
curl http://<that-ip>/service-a/health
```

## 9. Multipass cheat sheet

```bash
multipass list                        # list VMs
multipass shell group-seven           # open shell
multipass stop group-seven            # power off, keep state
multipass start group-seven           # power on
multipass delete group-seven          # mark for deletion
multipass purge                       # free disk after delete
multipass info group-seven            # IP, status, mounts
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `multipass launch` hangs at "Retrieving image" | First-run image download | Wait — first boot can take 3–5 min |
| `Could not resolve host: service-b.internal` | `/etc/hosts` entry missing | `sudo ./install.sh` |
| Nginx 502 on `/service-a/health` | Service A down | `systemctl status service-a && journalctl -u service-a -n 30` |
| "Permission denied" on `install.sh` | Forgot `chmod +x` | `chmod +x install.sh reset.sh health-check.sh` |
| `lsb_release` shows 22.04 | Wrong image | `multipass delete group-seven && multipass purge && multipass launch 24.04 ...` |
