#!/usr/bin/env bash
# Shared helpers for the pbs-client OBS package test matrix.
# Sourced by run-matrix.sh. Bash 4+.

set -euo pipefail

: "${HYPERVISOR:=root@bigiron.lan}"     # libvirt host that runs throwaway client VMs
: "${PBS_HOST:=pbs-01.lan}"             # live Proxmox Backup Server under test
: "${OBS_PROJECT:=home:ciriarte:pbs-client}"
: "${SSH_OPTS:=-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10}"

# OBS download base; project ':' become '/' and ':' is doubled as ':/'
obs_repo_base() {  # $1 = OBS repository name (e.g. openSUSE_Tumbleweed)
  local proj_path="${OBS_PROJECT//://}"
  proj_path="${proj_path//\//:/}"       # home:/ciriarte:/pbs-client
  echo "https://download.opensuse.org/repositories/${proj_path}/$1"
}

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf 'not ok - %s\n' "$*"; return 1; }
pass() { printf 'ok - %s\n' "$*"; }

vssh() { ssh $SSH_OPTS "$1" "$2"; }      # $1=target $2=cmd

# --- VM lifecycle on the hypervisor (libvirt + golden cloud-image templates) ---
# Templates are named "<distro>-<arch>-gold" and must exist on $HYPERVISOR.
vm_clone_boot() {  # $1=distro $2=arch -> prints VM IP on stdout
  local distro="$1" arch="$2" name="pbs-test-${1}-${2}"
  vssh "$HYPERVISOR" "virt-clone --original ${distro}-${arch}-gold --name ${name} --auto-clone >/dev/null"
  vssh "$HYPERVISOR" "virsh start ${name} >/dev/null"
  # Wait for a lease; requires the default libvirt network / guest agent.
  local ip=""
  for _ in $(seq 1 60); do
    ip=$(vssh "$HYPERVISOR" "virsh -q domifaddr ${name} --source agent 2>/dev/null | awk '/ipv4/{print \$4}' | cut -d/ -f1 | head -1" || true)
    [ -n "$ip" ] && break
    sleep 5
  done
  [ -n "$ip" ] || { fail "no IP for ${name}"; return 1; }
  # Wait for sshd.
  for _ in $(seq 1 30); do vssh "root@${ip}" true 2>/dev/null && break; sleep 5; done
  echo "$ip"
}

vm_destroy() {  # $1=distro $2=arch
  local name="pbs-test-${1}-${2}"
  vssh "$HYPERVISOR" "virsh destroy ${name} >/dev/null 2>&1 || true"
  vssh "$HYPERVISOR" "virsh undefine --remove-all-storage ${name} >/dev/null 2>&1 || true"
}

# --- repo add + install per distro family ---
add_repo_install() {  # $1=vm_ip $2=family $3=obs_repo_name
  local ip="$1" family="$2" repo; repo="$(obs_repo_base "$3")"
  case "$family" in
    suse)
      vssh "root@${ip}" "zypper --non-interactive ar -f -G ${repo}/${3}.repo pbs-client || zypper --non-interactive ar -f ${repo}/ pbs-client; \
        zypper --non-interactive --gpg-auto-import-keys refresh; \
        zypper --non-interactive install proxmox-backup-client proxmox-file-restore" ;;
    el)
      vssh "root@${ip}" "dnf -y install dnf-plugins-core; \
        dnf config-manager --add-repo ${repo}/${3}.repo; \
        dnf -y install proxmox-backup-client proxmox-file-restore" ;;
    deb)
      vssh "root@${ip}" "install -d /etc/apt/keyrings; \
        curl -fsSL ${repo}/Release.key | gpg --dearmor -o /etc/apt/keyrings/pbs-client.gpg; \
        echo 'deb [signed-by=/etc/apt/keyrings/pbs-client.gpg] ${repo}/ ./' > /etc/apt/sources.list.d/pbs-client.list; \
        apt-get update; apt-get -y install proxmox-backup-client proxmox-file-restore" ;;
    *) fail "unknown family ${family}"; return 1 ;;
  esac
}

smoke() {  # $1=vm_ip -- runs on all arches
  vssh "root@${1}" "proxmox-backup-client version && pxar --version && proxmox-file-restore --version"
}

# --- full backup + restore, x86_64 only ---
# Requires env: PBS_REPOSITORY (token@host:datastore), PBS_PASSWORD (secret),
# PBS_FINGERPRINT. Uses a per-distro namespace so parallel runs never collide.
backup_restore() {  # $1=vm_ip $2=namespace
  local ip="$1" ns="$2"
  vssh "root@${ip}" "set -e; \
    export PBS_REPOSITORY='${PBS_REPOSITORY}' PBS_PASSWORD='${PBS_PASSWORD}' PBS_FINGERPRINT='${PBS_FINGERPRINT}'; \
    dd if=/dev/urandom of=/root/payload bs=1M count=64 status=none; \
    proxmox-backup-client backup root.pxar:/root --ns '${ns}' --backup-id pbs-client-test; \
    snap=\$(proxmox-backup-client snapshot list --ns '${ns}' --output-format json | python3 -c 'import sys,json;a=json.load(sys.stdin);print(sorted(a,key=lambda x:x[\"backup-time\"])[-1][\"backup-time\"])'); \
    rm -rf /root/restore && mkdir /root/restore; \
    proxmox-backup-client restore --ns '${ns}' host/pbs-client-test/\$snap root.pxar /root/restore; \
    diff /root/payload /root/restore/payload"
}
