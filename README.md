# pbs-client — Proxmox Backup client for non-Debian distros

Community/**unofficial** packaging of the Proxmox Backup **client** suite, built
**from upstream Rust source** on the [openSUSE Build Service](https://build.opensuse.org)
for distros where Proxmox ships no native packages.

> "Proxmox" is a trademark of Proxmox Server Solutions GmbH. This project is
> community-maintained and **not endorsed by Proxmox**. Licensed AGPL-3.0.

- **OBS project:** `home:ciriarte:pbs-client`
- **Source/automation:** https://github.com/ciroiriarte/pbs-client
- **Upstream:** https://git.proxmox.com/git/proxmox-backup.git (canonical; the
  GitHub mirror lags a major version and is *not* used)

## What's included

| Package | Binaries |
|---------|----------|
| `proxmox-backup-client` | `proxmox-backup-client`, `pxar` |
| `proxmox-file-restore` | `proxmox-file-restore` (file-level restore of host/container backups) |

**Out of scope:** the VM/block-image restore path (`proxmox-restore-daemon` + a
prebuilt kernel/initramfs restore image) and the Windows client.

## Supported targets

openSUSE **Leap 16.0 / 15.6**, **Tumbleweed**, **Slowroll**; **Rocky Linux 9 / 10**;
**Ubuntu 24.04 / 26.04** — on **x86_64** and **aarch64**.

> Note: Proxmox's official Debian `bookworm` client repo already works on Ubuntu
> x86_64. This repo exists to add **aarch64** and a single unified repo across all
> the distros above.

## Install

Replace `<REPO>` with your distro's repository name from the table, and see the
live index at
`https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/`.

| Distro | `<REPO>` |
|--------|----------|
| Tumbleweed | `openSUSE_Tumbleweed` |
| Slowroll | `openSUSE_Slowroll` |
| Leap 16.0 | `openSUSE_Leap_16.0` |
| Leap 15.6 | `openSUSE_Leap_15.6` |
| Rocky 9 | `RockyLinux_9` |
| Rocky 10 | `RockyLinux_10` |
| Ubuntu 24.04 | `xUbuntu_24.04` |
| Ubuntu 26.04 | `xUbuntu_26.04` |

### openSUSE (zypper)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo zypper addrepo -f -G "$BASE/home:ciriarte:pbs-client.repo"
sudo zypper --gpg-auto-import-keys refresh
sudo zypper install proxmox-backup-client proxmox-file-restore
```

### Rocky Linux (dnf)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo "$BASE/home:ciriarte:pbs-client.repo"
sudo dnf install -y proxmox-backup-client proxmox-file-restore
```

### Ubuntu (apt)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo install -d /etc/apt/keyrings
curl -fsSL "$BASE/Release.key" | sudo gpg --dearmor -o /etc/apt/keyrings/pbs-client.gpg
echo "deb [signed-by=/etc/apt/keyrings/pbs-client.gpg] $BASE/ ./" \
  | sudo tee /etc/apt/sources.list.d/pbs-client.list
sudo apt-get update
sudo apt-get install -y proxmox-backup-client proxmox-file-restore
```

## Repository layout

```
proxmox-backup-client/        # the osc package (one source → RPM + DEB)
  _service                    # obs_scm fetch (git.proxmox.com tag) + cargo_vendor
  proxmox-backup-client.spec  # RPM recipe (openSUSE + Rocky)
  proxmox-backup-client.changes
  debian.control|rules|compat|changelog|*.install   # Ubuntu recipe
  _constraints                # extra disk/mem for the vendored build
project/
  _meta.xml                   # distro/arch matrix   (osc meta prj -F)
  _config                     # prjconf (rust preference, deb support)
tools/bump.py                 # upstream version tracker (systemd timer / CI)
tests/run-matrix.sh, lib.sh   # VM provisioning + backup/restore verification
```

## Maintainer workflow

```sh
# One-time project setup
osc meta prj     home:ciriarte:pbs-client -F project/_meta.xml
osc meta prjconf home:ciriarte:pbs-client -F project/_config

# Package: check out, vendor, commit
osc co home:ciriarte:pbs-client proxmox-backup-client
cp -a proxmox-backup-client/* <checkout>/    # or work in the checkout directly
cd <checkout>
osc service manualrun        # runs obs_scm + cargo_vendor -> vendor.tar.zst
osc addremove && osc commit -m "Initial import (v4.2.0)"

# Later: automatic bumps
tools/bump.py --commit       # detects a newer upstream tag, re-vendors, commits
```

## Notes / known risks

- **No upstream `Cargo.lock`.** `obs-service-cargo` resolves and vendors deps
  itself (`update=true`); the committed `vendor.tar.zst` is the pin. Each bump
  re-resolves — test before publishing.
- **MSRV = rust 1.81** (edition 2021). Leap pulls a current toolchain from
  `devel:languages:rust`; EL9 relies on `rust-toolset` ≥ 1.81 (add EPEL9 if a
  future MSRV bump outruns it — `bump.py` warns).
- `Rocky:10` / `Ubuntu:26.04` availability on build.opensuse.org should be
  confirmed; stage them last if not yet published.
