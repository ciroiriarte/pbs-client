#
# pbs-client-rust — a private, prebuilt Rust toolchain used ONLY as a build
# dependency of proxmox-backup-client. It installs the official static Rust
# release into /opt/pbs-client-rust so the client build does not depend on the
# distro's rust (whose version is often too old). Not intended for end users.
#
# Source0 is a tarball (built by tools/build_rust_pkg.sh) whose top dir holds the
# per-arch official toolchains: pbs-client-rust-<ver>/rust-<ver>-<triple>.tar.xz
#

%global rust_version 1.90.0
# It's a prebuilt binary drop; skip the RPM machinery that assumes we compiled it.
%global debug_package %{nil}
%define __strip /bin/true
%global __brp_check_rpaths %{nil}
%global __brp_strip %{nil}
%global __brp_strip_static_archive %{nil}
%global __brp_strip_comment_note %{nil}
%global _build_id_links none
%global prefix_dir /opt/pbs-client-rust

Name:           pbs-client-rust
Version:        %{rust_version}
Release:        0
Summary:        Private prebuilt Rust toolchain for building proxmox-backup-client
License:        (MIT OR Apache-2.0)
URL:            https://www.rust-lang.org
Source0:        pbs-client-rust-%{version}.tar.gz
ExclusiveArch:  x86_64 aarch64
BuildRequires:  tar
BuildRequires:  xz

%description
Prebuilt upstream Rust toolchain (rustc, cargo, rust-std) installed under
%{prefix_dir}, used exclusively as a build dependency of proxmox-backup-client so
its build is independent of the distribution's Rust version. Community/unofficial.

%prep
%autosetup -n pbs-client-rust-%{version}

%build

%install
case "$(uname -m)" in
  x86_64)  triple=x86_64-unknown-linux-gnu ;;
  aarch64) triple=aarch64-unknown-linux-gnu ;;
  *) echo "unsupported arch $(uname -m)"; exit 1 ;;
esac
tar -xf rust-%{rust_version}-$triple.tar.xz
rust-%{rust_version}-$triple/install.sh --prefix=%{buildroot}%{prefix_dir} \
  --disable-ldconfig --components=rustc,cargo,rust-std-$triple
# Drop install.sh's bookkeeping (uninstall script + manifest); not needed in an rpm.
rm -f %{buildroot}%{prefix_dir}/lib/rustlib/{uninstall.sh,install.log,components,rust-installer-version,manifest-*}

%files
%{prefix_dir}

%changelog
