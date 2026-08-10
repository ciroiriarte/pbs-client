#!/usr/bin/env bash
# Integration test for the pbs-client OBS packages, run ON a Proxmox VE host.
# Deploys a disposable unprivileged CT for one distro, installs the packages from
# the OBS repo, and runs the full client operation battery against a live PBS.
# Prints TAP-ish lines + a final PASS/FAIL, then destroys the CT.
#
# This is the Proxmox-VE (pct/LXC) counterpart to run-matrix.sh (libvirt). It is
# what was actually used to validate the published packages end-to-end.
#
# Usage: pct-inttest.sh <ctid> <template-volid> <family> <obsrepo> <label>
#   family: suse | el | deb
#
# Required env (use a SCOPED PBS API token, never root):
#   PBS_REPOSITORY  e.g. 'user@realm!token@pbs-host:datastore'
#   PBS_PASSWORD    the API token secret
#   PBS_FINGERPRINT the PBS server TLS sha256 fingerprint
# Optional env: PVE_BRIDGE (vmbr0), PVE_VLAN (unset), PVE_STORAGE (local-lvm),
#   PBS_HOST (pbs host to ping; derived from PBS_REPOSITORY if unset),
#   OBS_PROJECT (home:ciriarte:pbs-client).
set -uo pipefail

CTID="$1"; TEMPLATE="$2"; FAMILY="$3"; OBSREPO="$4"; LABEL="$5"
: "${PBS_REPOSITORY:?set PBS_REPOSITORY (user@realm!token@host:datastore)}"
: "${PBS_PASSWORD:?set PBS_PASSWORD (API token secret)}"
: "${PBS_FINGERPRINT:?set PBS_FINGERPRINT (PBS TLS sha256 fingerprint)}"
BRIDGE="${PVE_BRIDGE:-vmbr0}"; VLAN="${PVE_VLAN:-}"; STORAGE="${PVE_STORAGE:-local-lvm}"
OBS_PROJECT="${OBS_PROJECT:-home:ciriarte:pbs-client}"
# OBS download path puts ':/' between project components: home:/ciriarte:/pbs-client
OBS_DL_PROJ="$(echo "$OBS_PROJECT" | sed 's|:|:/|g')"
OBSBASE="https://download.opensuse.org/repositories/${OBS_DL_PROJ}/${OBSREPO}"
PBS_HOST="${PBS_HOST:-$(echo "$PBS_REPOSITORY" | sed -E 's/.*@([^:@]+):[^:]+$/\1/')}"
BID="inttest-${LABEL}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pass=0; fail=0
ok(){ echo "ok   - [$LABEL] $*"; pass=$((pass+1)); }
no(){ echo "FAIL - [$LABEL] $*"; fail=$((fail+1)); }
retry(){ local n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 4 ] && return 1; echo "   (retry $n)"; sleep 15; done; }
cx(){ pct exec "$CTID" -- bash -lc "$1"; }
cxe(){ pct exec "$CTID" -- bash -lc "export PBS_REPOSITORY='$PBS_REPOSITORY' PBS_PASSWORD='$PBS_PASSWORD' PBS_FINGERPRINT='$PBS_FINGERPRINT'; $1"; }
snap_time(){ cxe "proxmox-backup-client snapshot list --output-format json | bash /root/snaptime.sh $1"; }

cleanup(){ pct stop "$CTID" >/dev/null 2>&1; pct destroy "$CTID" --purge >/dev/null 2>&1; }
trap cleanup EXIT

echo "=== [$LABEL] deploy CT $CTID from $TEMPLATE ==="
netcfg="name=eth0,bridge=$BRIDGE,ip=dhcp"; [ -n "$VLAN" ] && netcfg="$netcfg,tag=$VLAN"
pct create "$CTID" "$TEMPLATE" --hostname "pbstest-$LABEL" --cores 2 --memory 2048 --swap 512 \
  --rootfs "$STORAGE:8" --net0 "$netcfg" --unprivileged 1 --features nesting=1 --start 1 \
  >/dev/null 2>&1 || { echo "CT create failed"; exit 1; }
for i in $(seq 1 30); do cx 'ping -c1 -W2 download.opensuse.org >/dev/null 2>&1' && break; sleep 3; done
cx "ping -c1 -W2 $PBS_HOST >/dev/null 2>&1" && ok "network up" || { no "no network"; exit 1; }
pct push "$CTID" "$HERE/snaptime.sh" /root/snaptime.sh

echo "=== [$LABEL] install packages ($FAMILY) ==="
case "$FAMILY" in
  suse) cx "zypper --non-interactive --no-gpg-checks ar -fG '$OBSBASE/' pbs 2>/dev/null; true"
        retry cx "zypper --non-interactive --gpg-auto-import-keys --no-gpg-checks refresh pbs"
        cx "zypper --non-interactive --no-gpg-checks install -y proxmox-backup-client proxmox-backup-file-restore" ;;
  el)   cx "dnf -y install dnf-plugins-core >/dev/null 2>&1; (dnf -y config-manager --add-repo '$OBSBASE/${OBS_PROJECT//:/_}.repo' || dnf config-manager --add-repo '$OBSBASE/${OBS_PROJECT//:/_}.repo') 2>/dev/null; true"
        retry cx "dnf -y --nogpgcheck makecache --repo ${OBS_PROJECT//:/_}"
        cx "dnf -y --nogpgcheck install proxmox-backup-client proxmox-backup-file-restore" ;;
  deb)  cx "apt-get update >/dev/null 2>&1; apt-get -y install curl gpg ca-certificates >/dev/null 2>&1; install -d /etc/apt/keyrings; curl -fsSL '$OBSBASE/Release.key' | gpg --dearmor -o /etc/apt/keyrings/pbs.gpg; echo \"deb [signed-by=/etc/apt/keyrings/pbs.gpg] $OBSBASE/ ./\" > /etc/apt/sources.list.d/pbs.list"
        retry cx "apt-get update -o Dir::Etc::sourcelist=sources.list.d/pbs.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0"
        cx "apt-get -y install proxmox-backup-client proxmox-backup-file-restore" ;;
esac
cx 'command -v proxmox-backup-client >/dev/null' && ok "packages installed" || { no "install failed"; exit 1; }

echo "=== [$LABEL] client battery ==="
cx 'proxmox-backup-client version | head -1' && ok "version" || no "version"
cx 'command -v pxar >/dev/null' && ok "pxar present" || no "pxar present"
cx 'command -v proxmox-file-restore >/dev/null' && ok "file-restore present" || no "file-restore present"

cx 'rm -rf /root/src /root/out && mkdir -p /root/src/sub && head -c 20000000 /dev/urandom >/root/src/big.bin && echo hello > /root/src/sub/a.txt && dd if=/dev/zero of=/root/src/zero bs=1M count=5 status=none; sha256sum /root/src/big.bin /root/src/sub/a.txt > /root/src.sums'

# 1) plain backup
cxe "cd /root && proxmox-backup-client backup root.pxar:/root/src --backup-id '$BID' --backup-type host" && ok "backup (plain)" || no "backup (plain)"
# 2) snapshot list
cxe "proxmox-backup-client snapshot list --output-format json | grep -q '$BID'" && ok "snapshot list" || no "snapshot list"
T=$(snap_time "$BID")
# 3) restore + verify (PBS wants the snapshot time in RFC3339, e.g. host/id/2026-..Z)
cxe "rm -rf /root/out && mkdir /root/out && proxmox-backup-client restore host/$BID/$T root.pxar /root/out && cd /root/out && sha256sum -c /root/src.sums >/dev/null" && ok "restore + checksum verify" || no "restore + verify"
# 4) file-restore list + extract (the archive is addressed as root.pxar.didx)
cxe "proxmox-file-restore list host/$BID/$T /root.pxar.didx >/dev/null" && ok "file-restore list" || no "file-restore list"
cxe "rm -rf /root/fr && mkdir /root/fr && proxmox-file-restore extract host/$BID/$T /root.pxar.didx/sub/a.txt /root/fr && grep -q hello /root/fr/a.txt" && ok "file-restore extract single file" || no "file-restore extract"
# 5) encrypted backup + restore
cxe "proxmox-backup-client key create /root/enc.key --kdf none >/dev/null 2>&1; cd /root && proxmox-backup-client backup enc.pxar:/root/src --backup-id '${BID}-enc' --backup-type host --keyfile /root/enc.key" && ok "backup (encrypted)" || no "backup (encrypted)"
TE=$(snap_time "${BID}-enc")
cxe "rm -rf /root/oute && mkdir /root/oute && proxmox-backup-client restore host/${BID}-enc/$TE enc.pxar /root/oute --keyfile /root/enc.key && cd /root/oute && sha256sum -c /root/src.sums >/dev/null" && ok "restore (encrypted) + verify" || no "restore (encrypted)"
# 6) local pxar roundtrip
cx 'cd /root && pxar create /root/local.pxar /root/src >/dev/null 2>&1 && rm -rf /root/px && mkdir /root/px && pxar extract /root/local.pxar --target /root/px >/dev/null 2>&1 && cd /root/px && sha256sum -c /root/src.sums >/dev/null' && ok "pxar create/extract roundtrip" || no "pxar roundtrip"
# 7) cleanup our test snapshots
cxe "proxmox-backup-client snapshot forget host/$BID/$T >/dev/null 2>&1; proxmox-backup-client snapshot forget host/${BID}-enc/$TE >/dev/null 2>&1; true" && ok "snapshot forget (cleanup)" || no "snapshot forget"

echo "=== [$LABEL] RESULT: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ] && echo "[$LABEL] OVERALL: PASS" || echo "[$LABEL] OVERALL: FAIL"
exit "$fail"
