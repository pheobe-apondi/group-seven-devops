# Setup — Windows (Multipass + Ubuntu 24.04 LTS)

Goal: by the end of this guide you have an Ubuntu 24.04 LTS VM on your Windows machine and this repository running inside it.

> This project assumes **Ubuntu Server 24.04 LTS**. Other distros mostly work but are not the supported target.

## 1. Host requirements

| Resource | Minimum |
|---|---|
| CPU | 2 cores free, virtualization enabled in BIOS/UEFI |
| RAM | 4 GB free |
| Disk | 20 GB free |
| Windows | 10 (build 19041+) or 11 — Home or Pro |

Confirm virtualization is on: Task Manager → Performance → CPU → "Virtualization: Enabled". If Disabled, reboot into BIOS/UEFI and enable VT-x (Intel) or AMD-V (AMD).

## 2. Install Multipass

> Run this from an **Administrator PowerShell** — one time only. After install, all `multipass` commands run as your normal user.

```powershell
winget install Canonical.Multipass
```

Close the elevated window. Open a normal PowerShell and verify:

```powershell
multipass version
```

## 3. Create the dedicated host folder

```powershell
New-Item -ItemType Directory -Force -Path $HOME\group-seven-devops
cd $HOME\group-seven-devops
git clone https://github.com/pheobe-apondi/group-seven-devops.git
```

## 4. Start the VM

```powershell
multipass launch 24.04 `
  --name group-seven `
  --cpus 1 `
  --memory 1G `
  --disk 8G `
  --mount "${HOME}\group-seven-devops:/home/ubuntu/group-seven-devops"
```

### VM profile

| Resource | Value |
|---|---|
| CPU | 1 |
| RAM | 1 GB |
| Disk | 8 GB |
| Host mount | `%USERPROFILE%\group-seven-devops` → `/home/ubuntu/group-seven-devops` |

## 5. Get into the VM

```powershell
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

To hit the API from Windows (outside the VM):

```powershell
multipass info group-seven   # look at the "IPv4" line
curl http://<that-ip>/service-a/health
```

## 9. Multipass cheat sheet

```powershell
multipass list                        # list VMs
multipass shell group-seven           # open shell
multipass stop group-seven            # power off, keep state
multipass start group-seven           # power on
multipass delete group-seven          # mark for deletion
multipass purge                       # free disk after delete
multipass info group-seven            # IP, status, mounts
```

## Alternatives (if Multipass won't run)

| Option | When to use | Trade-off |
|---|---|---|
| **WSL2 (Ubuntu 24.04)** | Can't install a hypervisor | Not a real VM — `systemd` needs `[boot] systemd=true` in `/etc/wsl.conf` |
| **VirtualBox + Ubuntu Server ISO** | Multipass won't start | Heavier setup, well documented |
| **Hyper-V + Ubuntu Server ISO** | Windows Pro only | Full VM, more manual setup |

### WSL2 quickstart (fallback)

```powershell
wsl --install -d Ubuntu-24.04
wsl -d Ubuntu-24.04
```

Inside WSL, create `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Then `exit`, run `wsl --shutdown` from PowerShell, reopen the distro. Verify:

```bash
ps -p 1 -o comm=   # should print: systemd
```

After that, `sudo ./install.sh` and the rest of the workflow are identical.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `multipass launch` hangs at "Retrieving image" | First-run image download | Wait — first boot can take 3–5 min |
| `launch failed: CPU does not support KVM extensions` | Virtualization disabled in BIOS | Enable VT-x or AMD-V in BIOS/UEFI |
| `Hyper-V is not available` on Home edition | Multipass needs a hypervisor | Install VirtualBox first, then `multipass set local.driver=virtualbox` |
| `Could not resolve host: service-b.internal` | `/etc/hosts` entry missing | `sudo ./install.sh` |
| Nginx 502 on `/service-a/health` | Service A down | `systemctl status service-a && journalctl -u service-a -n 30` |
| "Permission denied" on `install.sh` | Forgot `chmod +x` | `chmod +x install.sh reset.sh health-check.sh` |
| WSL2: `systemctl` says "not booted with systemd" | `systemd=true` not set | Edit `/etc/wsl.conf`, run `wsl --shutdown`, reopen |
