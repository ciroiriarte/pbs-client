#!/usr/bin/env bash
# Fetch the official standalone Rust toolchain tarballs used as offline Source
# inputs to the build (so the package does NOT depend on the distro's rust —
# the same idea as the rustup step other builds use, but offline, because OBS
# build workers have no network).
#
# Output: dist/rust-<ver>-{x86_64,aarch64}-unknown-linux-gnu.tar.xz
# These are large (~150-200 MB each), git-ignored, and committed to the OBS
# package as Source1/Source2. Re-run only when RUST_VERSION changes.
set -euo pipefail

RUST_VERSION="${RUST_VERSION:-1.90.0}"
BASE="https://static.rust-lang.org/dist"
OUT="$(cd "$(dirname "$0")/.." && pwd)/dist"
mkdir -p "$OUT"

for arch in x86_64 aarch64; do
  f="rust-${RUST_VERSION}-${arch}-unknown-linux-gnu.tar.xz"
  if [ -f "$OUT/$f" ]; then echo "have $f"; continue; fi
  echo "downloading $f ..."
  curl -fSL "$BASE/$f" -o "$OUT/$f.tmp"
  curl -fsSL "$BASE/$f.sha256" -o "$OUT/$f.sha256" 2>/dev/null || true
  if [ -s "$OUT/$f.sha256" ]; then
    (cd "$OUT" && sha256sum -c <(awk -v f="$f" '{print $1"  "f}' "$f.sha256")) || { echo "checksum FAILED"; exit 1; }
  fi
  mv "$OUT/$f.tmp" "$OUT/$f"
  rm -f "$OUT/$f.sha256"
  echo "saved $OUT/$f"
done
echo "Rust ${RUST_VERSION} toolchains ready in $OUT"
