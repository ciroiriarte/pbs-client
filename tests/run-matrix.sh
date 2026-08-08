#!/usr/bin/env bash
# Provision throwaway per-distro VMs on the hypervisor, install the pbs-client
# packages from OBS, and verify them against the live PBS.
#
#   x86_64  -> install + smoke + real backup/restore against $PBS_HOST
#   aarch64 -> install + smoke only
#
# Emits TAP so CI can consume the results. Each (distro,arch) is independent;
# a failure records "not ok" and continues so one bad target does not mask others.
#
# Required env for the x86_64 backup/restore leg (use a scoped PBS API token,
# NOT root): PBS_REPOSITORY, PBS_PASSWORD, PBS_FINGERPRINT
#
# Usage: tests/run-matrix.sh [distro:arch ...]   (default: full matrix)

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib.sh
source "${here}/lib.sh"

# distro-key : family : OBS repository name
declare -A FAMILY=(
  [tumbleweed]=suse   [slowroll]=suse   [leap15.6]=suse   [leap16.0]=suse
  [rocky9]=el         [rocky10]=el
  [ubuntu24.04]=deb   [ubuntu26.04]=deb
)
declare -A OBSREPO=(
  [tumbleweed]=openSUSE_Tumbleweed  [slowroll]=openSUSE_Slowroll
  [leap15.6]=openSUSE_Leap_15.6     [leap16.0]=openSUSE_Leap_16.0
  [rocky9]=RockyLinux_9             [rocky10]=RockyLinux_10
  [ubuntu24.04]=xUbuntu_24.04       [ubuntu26.04]=xUbuntu_26.04
)

ARCHES=(x86_64 aarch64)
TARGETS=("$@")
if [ ${#TARGETS[@]} -eq 0 ]; then
  for d in "${!FAMILY[@]}"; do for a in "${ARCHES[@]}"; do TARGETS+=("${d}:${a}"); done; done
fi

planned=${#TARGETS[@]}
echo "TAP version 13"
echo "1..${planned}"

n=0
for t in "${TARGETS[@]}"; do
  n=$((n+1))
  distro="${t%%:*}"; arch="${t##*:}"
  fam="${FAMILY[$distro]:-}"; repo="${OBSREPO[$distro]:-}"
  desc="${distro}/${arch}"

  if [ -z "$fam" ] || [ -z "$repo" ]; then
    echo "not ok ${n} - ${desc} # unknown target"; continue
  fi

  ip=""
  {
    log "provisioning ${desc}"
    ip="$(vm_clone_boot "$distro" "$arch")"
    add_repo_install "$ip" "$fam" "$repo"
    smoke "$ip"
    if [ "$arch" = x86_64 ]; then
      : "${PBS_REPOSITORY:?set PBS_REPOSITORY for backup/restore}"
      backup_restore "$ip" "test-${distro}"
    fi
  } && echo "ok ${n} - ${desc}" || echo "not ok ${n} - ${desc}"

  [ -n "$ip" ] && vm_destroy "$distro" "$arch" || true
done
