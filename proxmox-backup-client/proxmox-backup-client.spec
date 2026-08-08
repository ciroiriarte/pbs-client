#
# spec file for package proxmox-backup-client (community/unofficial)
#
# Builds the Proxmox Backup CLIENT suite from source for openSUSE and
# RHEL-compatible distros. Unofficial: "Proxmox" is a trademark of Proxmox
# Server Solutions GmbH; this repository is community-maintained and not
# endorsed by Proxmox.
#

Name:           proxmox-backup-client
Version:        4.2.0
Release:        0
Summary:        Proxmox Backup client (proxmox-backup-client, pxar)
License:        AGPL-3.0-or-later
URL:            https://pbs.proxmox.com
Source0:        proxmox-backup-%{version}.tar.zst
Source1:        vendor.tar.zst
Source2:        cargo_config

BuildRequires:  zstd
BuildRequires:  cargo
BuildRequires:  rust >= 1.81
BuildRequires:  clang
BuildRequires:  pkgconfig
BuildRequires:  pkgconfig(fuse3)
BuildRequires:  pkgconfig(openssl)
BuildRequires:  pkgconfig(libzstd)
BuildRequires:  pkgconfig(libacl)
BuildRequires:  pkgconfig(libsystemd)
BuildRequires:  pkgconfig(uuid)
%if 0%{?rhel}
BuildRequires:  llvm-devel
%else
BuildRequires:  llvm-devel
BuildRequires:  libopenssl-devel
%endif
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
%autosetup -n proxmox-backup-%{version}
# Vendored crates + offline cargo config produced by obs-service-cargo.
tar -xf %{SOURCE1}
install -D -m 0644 %{SOURCE2} .cargo/config.toml

%build
export CARGO_HOME="%{_builddir}/proxmox-backup-%{version}/.cargo"
export ZSTD_SYS_USE_PKG_CONFIG=1
export OPENSSL_NO_VENDOR=1
# PXAR/FUSE bindgen needs libclang at runtime of the build.
cargo build --release --offline \
  -p proxmox-backup-client --bin proxmox-backup-client \
  -p pxar-bin              --bin pxar \
  -p proxmox-file-restore  --bin proxmox-file-restore

%install
install -D -m 0755 target/release/proxmox-backup-client %{buildroot}%{_bindir}/proxmox-backup-client
install -D -m 0755 target/release/pxar                  %{buildroot}%{_bindir}/pxar
install -D -m 0755 target/release/proxmox-file-restore  %{buildroot}%{_bindir}/proxmox-file-restore

# Upstream ships static zsh completions (man pages require the heavy sphinx docs
# build, which we intentionally skip for a lean offline client build).
install -D -m 0644 zsh-completions/_proxmox-backup-client %{buildroot}%{_datadir}/zsh/site-functions/_proxmox-backup-client
install -D -m 0644 zsh-completions/_pxar                  %{buildroot}%{_datadir}/zsh/site-functions/_pxar
install -D -m 0644 zsh-completions/_proxmox-file-restore  %{buildroot}%{_datadir}/zsh/site-functions/_proxmox-file-restore

%files
%license debian/copyright
%doc README.rst
%{_bindir}/proxmox-backup-client
%{_bindir}/pxar
%{_datadir}/zsh/site-functions/_proxmox-backup-client
%{_datadir}/zsh/site-functions/_pxar

%files -n proxmox-file-restore
%{_bindir}/proxmox-file-restore
%{_datadir}/zsh/site-functions/_proxmox-file-restore

%changelog
