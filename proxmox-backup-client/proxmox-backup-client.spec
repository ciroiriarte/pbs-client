#
# spec file for package proxmox-backup-client (community/unofficial)
#
# Builds the Proxmox Backup CLIENT suite from source for openSUSE and
# RHEL-compatible distros. Unofficial: "Proxmox" is a trademark of Proxmox
# Server Solutions GmbH; this repository is community-maintained and not
# endorsed by Proxmox.
#
# Source0 is a self-contained bundle produced by tools/build_source.py:
#   proxmox-backup-client-<ver>/
#     proxmox-backup/   (patched; .cargo/config.toml -> ../vendor)
#     proxmox/ pathpatterns/ pxar/ proxmox-fuse/   (path-patched crates)
#     vendor/           (third-party crates)
# It builds fully offline; no source services or network at build time.
#

Name:           proxmox-backup-client
Version:        4.2.0
Release:        0
Summary:        Proxmox Backup client (proxmox-backup-client, pxar)
License:        AGPL-3.0-or-later
URL:            https://pbs.proxmox.com
Source0:        proxmox-backup-client-%{version}.tar.xz

BuildRequires:  zstd
BuildRequires:  cargo
BuildRequires:  rust >= 1.81
BuildRequires:  clang
BuildRequires:  llvm-devel
BuildRequires:  pkgconfig
BuildRequires:  pkgconfig(fuse3)
BuildRequires:  pkgconfig(openssl)
BuildRequires:  pkgconfig(libzstd)
BuildRequires:  pkgconfig(libacl)
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(uuid)
Requires:       fuse3

%description
Command-line client for Proxmox Backup Server. Provides proxmox-backup-client
for creating and restoring deduplicated, encrypted backups, and the pxar
archive tool.

This is a community/unofficial build from upstream Rust sources.

%package -n proxmox-file-restore
Summary:        Single-file restore for Proxmox Backup
Requires:       %{name} = %{version}-%{release}
Requires:       fuse3

%description -n proxmox-file-restore
proxmox-file-restore performs file-level restore from Proxmox Backup Server
snapshots (host and container backups). The VM/block-image restore path
(proxmox-restore-daemon + a prebuilt restore image) is NOT included.

%prep
%autosetup -n proxmox-backup-client-%{version}

%build
export CARGO_HOME=%{_builddir}/cargo-home
export ZSTD_SYS_USE_PKG_CONFIG=1
export OPENSSL_NO_VENDOR=1
# pbs-buildcfg/build.rs embeds REPOID; without it, it shells out to `git` (absent
# in the build root, and the bundle carries no .git). Provide the version instead.
export REPOID=%{version}
cd proxmox-backup
# Offline build against the bundled vendor/ (see proxmox-backup/.cargo/config.toml).
cargo build --release --offline \
  -p proxmox-backup-client --bin proxmox-backup-client \
  -p pxar-bin              --bin pxar \
  -p proxmox-file-restore  --bin proxmox-file-restore

%install
cd proxmox-backup
install -D -m 0755 target/release/proxmox-backup-client %{buildroot}%{_bindir}/proxmox-backup-client
install -D -m 0755 target/release/pxar                  %{buildroot}%{_bindir}/pxar
install -D -m 0755 target/release/proxmox-file-restore  %{buildroot}%{_bindir}/proxmox-file-restore
# Upstream ships static zsh completions (man pages need the heavy sphinx docs
# build, intentionally skipped for a lean offline client build).
install -D -m 0644 zsh-completions/_proxmox-backup-client %{buildroot}%{_datadir}/zsh/site-functions/_proxmox-backup-client
install -D -m 0644 zsh-completions/_pxar                  %{buildroot}%{_datadir}/zsh/site-functions/_pxar
install -D -m 0644 zsh-completions/_proxmox-file-restore  %{buildroot}%{_datadir}/zsh/site-functions/_proxmox-file-restore

%files
%license proxmox-backup/debian/copyright
%doc proxmox-backup/README.rst
%{_bindir}/proxmox-backup-client
%{_bindir}/pxar
# Co-own the zsh dirs (openSUSE QA rejects unowned dirs; co-ownership is fine).
%dir %{_datadir}/zsh
%dir %{_datadir}/zsh/site-functions
%{_datadir}/zsh/site-functions/_proxmox-backup-client
%{_datadir}/zsh/site-functions/_pxar

%files -n proxmox-file-restore
%{_bindir}/proxmox-file-restore
%dir %{_datadir}/zsh
%dir %{_datadir}/zsh/site-functions
%{_datadir}/zsh/site-functions/_proxmox-file-restore

%changelog
