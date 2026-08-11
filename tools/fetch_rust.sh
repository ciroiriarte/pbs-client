#!/usr/bin/env bash
# Fetch the official standalone Rust toolchain tarballs used as offline Source
# inputs to the build (so the package does NOT depend on the distro's rust —
# the same idea as the rustup step other builds use, but offline, because OBS
# build workers have no network).
#
# Output: dist/rust-<ver>-{x86_64,aarch64,powerpc64le}-unknown-linux-gnu plus armv7-unknown-linux-gnueabihf.tar.xz
# These are large (~150-200 MB each), git-ignored, and committed to the OBS
# package inside Source0. Re-run only when RUST_VERSION changes.
set -euo pipefail

RUST_VERSION="${RUST_VERSION:-1.90.0}"
BASE="https://static.rust-lang.org/dist"
OUT="$(cd "$(dirname "$0")/.." && pwd)/dist"
mkdir -p "$OUT"

for triple in \
  x86_64-unknown-linux-gnu \
  aarch64-unknown-linux-gnu \
  armv7-unknown-linux-gnueabihf \
  powerpc64le-unknown-linux-gnu
do
  f="rust-${RUST_VERSION}-${triple}.tar.xz"
  if [ -f "$OUT/$f" ]; then echo "have $f"; continue; fi
  echo "downloading $f ..."
  curl -fSL "$BASE/$f" -o "$OUT/$f.tmp"
  mv "$OUT/$f.tmp" "$OUT/$f"
  if curl -fsSL "$BASE/$f.sha256" -o "$OUT/$f.sha256" 2>/dev/null && [ -s "$OUT/$f.sha256" ]; then
    (cd "$OUT" && sha256sum -c <(awk -v f="$f" '{print $1"  "f}' "$f.sha256")) \
      || { echo "checksum FAILED"; rm -f "$OUT/$f"; exit 1; }
  fi
  rm -f "$OUT/$f.sha256"
  echo "saved $OUT/$f"
done
echo "Rust ${RUST_VERSION} toolchains ready in $OUT"
