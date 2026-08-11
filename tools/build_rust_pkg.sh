#!/usr/bin/env bash
# Build the source tarball for the pbs-client-rust OBS package: a single
# xz tarball whose top dir holds the per-arch official Rust toolchains. Committed
# once to the pbs-client-rust package (re-done only on a rust-version bump), so the
# per-release proxmox-backup-client bundle stays small. Run tools/fetch_rust.sh first.
set -euo pipefail

RUST_VERSION="${RUST_VERSION:-1.90.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
top="pbs-client-rust-${RUST_VERSION}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/$top"
for triple in \
  x86_64-unknown-linux-gnu \
  aarch64-unknown-linux-gnu \
  armv7-unknown-linux-gnueabihf \
  powerpc64le-unknown-linux-gnu
do
  f="rust-${RUST_VERSION}-${triple}.tar.xz"
  [ -f "$DIST/$f" ] || { echo "missing $DIST/$f — run tools/fetch_rust.sh"; exit 1; }
  cp "$DIST/$f" "$work/$top/"
done
out="$DIST/${top}.tar.gz"
# gzip (fast) over already-xz-compressed inner tarballs; debtransform accepts .tar.gz.
tar -C "$work" -czf "$out" "$top"
echo "wrote $out ($(du -m "$out" | cut -f1) MB)"
