#!/usr/bin/env bash
# Driver: run pct-inttest.sh for every deployable amd64 distro in parallel on a
# Proxmox VE host, then print a per-distro PASS/FAIL summary.
#
# Run this ON the Proxmox VE host (needs pct + templates). Templates must be
# present (pveam download local <template>). Each distro uses a distinct CTID and
# a distinct backup-id, so parallel runs don't collide on the shared PBS.
#
# Required env (scoped PBS API token, never root):
#   PBS_REPOSITORY / PBS_PASSWORD / PBS_FINGERPRINT
# Optional env: PVE_STORAGE, PVE_BRIDGE, PVE_VLAN, OBS_PROJECT (see pct-inttest.sh).
#
# Note: Rocky 10 needs x86-64-v3; Tumbleweed/Slowroll have no LXC template; Debian
# packages are arm64-only — none are deployable as amd64 CTs here, so they are not
# in the matrix below. Adjust template volids to what `pveam list local` shows.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ctid : "template-volid family obs-repo label"
declare -A JOBS=(
  [700]="local:vztmpl/opensuse-16.0-default_20260116_amd64.tar.xz suse openSUSE_Leap_16.0 leap16"
  [701]="local:vztmpl/opensuse-15.6-default_20240910_amd64.tar.xz suse openSUSE_Leap_15.6 leap15.6"
  [702]="local:vztmpl/rockylinux-9-default_20240912_amd64.tar.xz el RockyLinux_9 rocky9"
  [704]="local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst deb Ubuntu_24.04 ubuntu24.04"
  [705]="local:vztmpl/ubuntu-26.04-standard_26.04-1_amd64.tar.zst deb Ubuntu_26.04 ubuntu26.04"
)
LOGDIR="$(mktemp -d)"; echo "logs: $LOGDIR"
for id in "${!JOBS[@]}"; do pct destroy "$id" --purge >/dev/null 2>&1; done
for id in "${!JOBS[@]}"; do
  read -r tmpl fam repo label <<<"${JOBS[$id]}"
  "$HERE/pct-inttest.sh" "$id" "$tmpl" "$fam" "$repo" "$label" >"$LOGDIR/$label.log" 2>&1 &
done
wait
echo "############ SUMMARY ############"
rc=0
for id in "${!JOBS[@]}"; do
  read -r _ _ _ label <<<"${JOBS[$id]}"
  line=$(grep -E 'OVERALL:' "$LOGDIR/$label.log" 2>/dev/null | tail -1)
  res=$(grep -E 'RESULT:' "$LOGDIR/$label.log" 2>/dev/null | tail -1)
  printf '%-14s %s | %s\n' "$label" "${line:-NO RESULT (see $LOGDIR/$label.log)}" "$res"
  echo "$line" | grep -q 'PASS' || rc=1
done
exit "$rc"
