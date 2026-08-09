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
| `proxmox-backup-file-restore` | `proxmox-file-restore` (file-level restore of host/container backups) |

Package names mirror upstream Proxmox (the binary is `proxmox-file-restore`; the
package is `proxmox-backup-file-restore`).

**Out of scope:** the VM/block-image restore path (`proxmox-restore-daemon` + a
prebuilt kernel/initramfs restore image) and the Windows client.

## Supported targets

Built from source on OBS. Status reflects the toolchains/base repos actually
available on build.opensuse.org.

The build **carries its own Rust toolchain** (see "How the build works"), so the
distro's rust version is irrelevant — the MSRV wall is gone. **All 16 build
targets are green.**

| Distro | x86_64 | aarch64 | Notes |
|--------|:------:|:-------:|-------|
| openSUSE Tumbleweed | ✅ | ✅ | |
| openSUSE Slowroll | ✅ | — | no aarch64 base on OBS |
| openSUSE Leap 16.0 | ✅ | ✅ | |
| openSUSE Leap 15.6 | ✅ | ✅ | |
| Rocky Linux 9 | ✅ | — | noflush guard (libfuse3 3.10); no aarch64 base on OBS |
| Rocky Linux 10 | ✅ | — | no aarch64 base on OBS |
| Ubuntu 24.04 | ✅ | ✅ | |
| Ubuntu 26.04 | ✅ | ✅ | |
| Debian 11 (Bullseye) | — | ✅ | aarch64-only (no overlap with upstream amd64) |
| Debian 12 (Bookworm) | — | ✅ | aarch64-only |
| Debian 13 (Trixie) | — | ✅ | aarch64-only |

Debian is **aarch64-only** by design: Proxmox's official Debian client repo already
covers x86_64, so we only fill the arm64 gap. The only "—" cells are aarch64 for
Slowroll / Rocky, for which OBS mirrors no aarch64 base (Oracle/Alma 9/10 users can
consume the Rocky EL RPMs directly).

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
| Ubuntu 24.04 | `Ubuntu_24.04` |
| Ubuntu 26.04 | `Ubuntu_26.04` |
| Debian 11 (arm64) | `Debian_11` |
| Debian 12 (arm64) | `Debian_12` |
| Debian 13 (arm64) | `Debian_13` |

### openSUSE (zypper)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo zypper addrepo -f -G "$BASE/home:ciriarte:pbs-client.repo"
sudo zypper --gpg-auto-import-keys refresh
sudo zypper install proxmox-backup-client proxmox-backup-file-restore
```

### Rocky Linux (dnf)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo "$BASE/home:ciriarte:pbs-client.repo"
sudo dnf install -y proxmox-backup-client proxmox-backup-file-restore
```

### Ubuntu (apt)

```sh
BASE=https://download.opensuse.org/repositories/home:/ciriarte:/pbs-client/<REPO>
sudo install -d /etc/apt/keyrings
curl -fsSL "$BASE/Release.key" | sudo gpg --dearmor -o /etc/apt/keyrings/pbs-client.gpg
echo "deb [signed-by=/etc/apt/keyrings/pbs-client.gpg] $BASE/ ./" \
  | sudo tee /etc/apt/sources.list.d/pbs-client.list
sudo apt-get update
sudo apt-get install -y proxmox-backup-client proxmox-backup-file-restore
```

## How the build works (important)

The client **cannot** be vendored from crates.io. The `proxmox-backup` workspace
pins Proxmox's *own* crates at versions that aren't published (e.g. `pathpatterns 1`,
`pxar 1.0.1`, `proxmox-schema 5`), and upstream ships no `Cargo.lock`. So we
**assemble five repos** (`proxmox-backup` + `proxmox` + `pathpatterns` + `pxar` +
`proxmox-fuse`) at coordinated commits, enable the `[patch.crates-io]` path
overrides upstream ships commented-out, and vendor only the third-party crates.
`tools/build_source.py` produces a self-contained bundle that builds fully offline
— there is **no OBS source service** (OBS can't do multi-repo assembly).

The bundle also **carries an offline Rust toolchain** (`rust-<ver>-<arch>.tar.xz`
for x86_64 + aarch64, fetched by `tools/fetch_rust.sh`). The build installs it and
uses *its* `cargo`/`rustc` instead of the distro's — the same idea as the rustup
step used by network-enabled builders (e.g. the Fedora COPR), but **offline**,
because OBS build workers have no network. This removes the distro-rust MSRV
constraint entirely: builds need only base `gcc`/`clang`/`pkgconf`/`fuse3-devel`,
so every listed distro (including old ones like Leap 15.6 and Debian 11) builds
uniformly with no per-distro toolchain gymnastics.

## Repository layout

```
proxmox-backup-client/        # the osc package (one source → RPM + DEB)
  proxmox-backup-client.spec  # RPM recipe (openSUSE + Rocky); Source0 = the bundle
  proxmox-backup-client.changes
  debian.control|rules|compat|changelog|*.install   # Ubuntu recipe
  _constraints                # extra disk/mem for the vendored build
project/
  _meta.xml                   # distro/arch matrix   (osc meta prj -F)
  _config                     # prjconf (rust preference, deb support)
tools/
  sources.json                # pinned sibling commits per release
  build_source.py             # assemble the offline bundle (clone+patch+vendor+tar)
  bump.py                     # upstream version tracker (systemd timer / CI)
tests/run-matrix.sh, lib.sh   # VM provisioning + backup/restore verification
```

## Maintainer workflow

```sh
# One-time project setup
osc meta prj     home:ciriarte:pbs-client -F project/_meta.xml
osc meta prjconf home:ciriarte:pbs-client -F project/_config

# Build the source bundle for the current version (clone + patch + vendor + tar)
tools/build_source.py --version 4.2.0        # -> dist/proxmox-backup-client-4.2.0.tar.xz

# Package: check out, add the bundle + recipe, commit
osc co home:ciriarte:pbs-client proxmox-backup-client
cd <checkout>
cp ../../dist/proxmox-backup-client-4.2.0.tar.xz .
cp -a <repo>/proxmox-backup-client/* .
osc addremove && osc commit -m "Initial import (v4.2.0)"

# Later: automatic bumps (assembles a fresh bundle, updates changelogs, commits)
tools/bump.py --checkout <checkout> --commit
```

## Notes / known risks

- **Sibling repos are untagged.** `proxmox` / `pathpatterns` / `pxar` /
  `proxmox-fuse` carry no release tags, so `tools/build_source.py` pins commits by
  **date-match** to the release tag and verifies the crate majors satisfy the
  workspace requirements before building. `sources.json` records the exact pins.
  (Upstream proposal: ask Proxmox to publish per-release sibling commit hashes so
  this is deterministic instead of heuristic.)
- **Rust toolchain is bundled, not from the distro.** The workspace's effective
  MSRV is ~1.87 (`proxmox-time` uses a 1.86 feature, `proxmox-fixed-string` declares
  1.87), which many distros' packaged rust doesn't meet. Rather than chase each
  distro's rust (versioned toolchains, backports, gcc-runtime `Substitute`
  gymnastics — all removed now), the build ships and uses its own Rust
  `RUST_VERSION` (pinned in `tools/fetch_rust.sh` / `build_source.py` / the
  recipes). Bump rust by changing those pins and re-running `fetch_rust.sh` +
  `build_source.py`. Note: this inflates the bundle by ~350 MB (both arch
  toolchains); a future optimization is a separate in-project rust package so the
  per-release source stays small.
- **pkgconf** is required (`proxmox-fuse`'s build.rs execs `pkgconf`, not
  `pkg-config`). On openSUSE Leap 15.6 and Debian Bullseye the old freedesktop
  `pkg-config` lacks that binary; on Bullseye `pkgconf` even conflicts with the
  `pkg-config` package, so the Debian recipe build-depends on `pkgconf` only and
  sets `PKG_CONFIG=pkgconf`.
- **EL9 fuse**: RHEL/Rocky 9 ships libfuse3 3.10, which lacks `fuse_file_info.noflush`
  (added in libfuse 3.16). `build_source.py` guards that field in `proxmox-fuse`'s
  `glue.c` (no-op on old libfuse, full functionality on ≥3.16) so EL9 builds the
  full suite without shipping a replacement fuse3.
- **Bundle size.** The assembled tarball carries five repos + ~456 vendored crates;
  it is large but self-contained and builds with no network.
- **aarch64** is only available where OBS mirrors that distro's aarch64 base repos
  (Tumbleweed, Leap 16.0, Ubuntu 26.04). Slowroll and RockyLinux 9/10 have no
  aarch64 base on OBS, so those stay x86_64-only.
