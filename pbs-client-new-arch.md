# pbs-client new architecture support session summary

Date: 2026-08-11

## Original goal

Add support for ARM32 and PowerPC where available, meaning only where both are true:

- upstream Rust publishes a usable native host toolchain; and
- OBS has compatible workers/base repositories for the target distro.

The user later emphasized that this is a backup client, so data consistency and large-file safety must take priority over merely making builds pass.

## High-level result

PowerPC support is effectively enabled and verified on active OBS targets.

ARM32 support is partially enabled and made significant progress through many compile barriers, but it is not yet complete. The ARM32 work exposed repeated upstream assumptions that Linux libc fields are 64-bit. The fixes applied or prepared keep internal backup/client semantics wide and only convert at libc/FFI boundaries.

## OBS/project changes

Used `osc` to inspect and operate `build.opensuse.org` as requested.

### Live OBS metadata findings

Live OBS project metadata initially already had Debian `armv7l` enabled, but local `project/_meta.xml` was stale.

Queried OBS upstream repository arch metadata and found available base/workers including:

- Tumbleweed standard: `armv7l`, `ppc64le`
- Leap 16.0 standard: `ppc64le`
- Leap 15.6 standard: `ppc64le`
- Ubuntu 24.04/26.04 universe: `armv7l`, `ppc64le`
- Debian 11/12/13 standard: `armv7l`, `ppc64le`
- Rocky 9/10: secondary arches exist upstream in some repos, but this project kept Rocky x86_64-only for now.

### Local `project/_meta.xml`

Updated local metadata to enable:

- `openSUSE_Tumbleweed`: `x86_64`, `aarch64`, `armv7l`, `ppc64le`
- `openSUSE_Leap_16.0`: `x86_64`, `aarch64`, `ppc64le`
- `openSUSE_Leap_15.6`: `x86_64`, `aarch64`, `ppc64le`
- `Ubuntu_24.04`: `x86_64`, `aarch64`, `armv7l`, `ppc64le`
- `Ubuntu_26.04`: `x86_64`, `aarch64`, `armv7l`, `ppc64le`
- `Debian_11/12/13`: `aarch64`, `armv7l`, `ppc64le`

Also switched local Tumbleweed path from `openSUSE:Factory/snapshot` to `openSUSE:Tumbleweed/standard` so armv7l/ppc64le ports are available.

Applied OBS project metadata with:

```sh
osc meta prj home:ciriarte:pbs-client -F project/_meta.xml
```

## Rust toolchain package changes (`pbs-client-rust`)

### Added Rust host toolchains

Updated scripts to fetch/package these Rust 1.90.0 host toolchains:

- `x86_64-unknown-linux-gnu`
- `aarch64-unknown-linux-gnu`
- `armv7-unknown-linux-gnueabihf`
- `powerpc64le-unknown-linux-gnu`

Downloaded and checksum-verified:

- `dist/rust-1.90.0-armv7-unknown-linux-gnueabihf.tar.xz`
- `dist/rust-1.90.0-powerpc64le-unknown-linux-gnu.tar.xz`

Rebuilt:

- `dist/pbs-client-rust-1.90.0.tar.gz`

New bundle size observed: about `846 MB`.

### Packaging updates

Updated:

- `tools/fetch_rust.sh`
- `tools/build_rust_pkg.sh`
- `pbs-client-rust/pbs-client-rust.spec`
- `pbs-client-rust/debian.rules`
- `pbs-client-rust/debian.control`
- `pbs-client-rust/pbs-client-rust.changes`
- `pbs-client-rust/debian.changelog`

Key mappings:

- RPM/OBS ARM32: `armv7l`/`armv7hl` -> `armv7-unknown-linux-gnueabihf`
- Debian ARM32: `armhf` -> `armv7-unknown-linux-gnueabihf`
- RPM/OBS PowerPC: `ppc64le` -> `powerpc64le-unknown-linux-gnu`
- Debian PowerPC: `ppc64el` -> `powerpc64le-unknown-linux-gnu`

Updated RPM `ExclusiveArch` to include:

```spec
ExclusiveArch: x86_64 aarch64 armv7hl ppc64le
```

Updated Debian package architecture list to include:

```debcontrol
Architecture: amd64 arm64 armhf ppc64el
```

### OBS upload/result

Direct `osc commit` for the 846 MB Rust tarball stalled, so individual files were uploaded through `osc api -X PUT -T`.

Remote OBS evidence after upload:

- `pbs-client-rust-1.90.0.tar.gz` remote size became `886720729` bytes.
- New `pbs-client-rust` builds showed success for ppc64le and most armv7l targets.
- Ubuntu armv7l helper builds were at times still queued/building due to worker availability.

## Client package architecture changes (`proxmox-backup-client`)

Updated:

- `proxmox-backup-client/debian.control`
- `proxmox-backup-client/debian.rules`
- `proxmox-backup-client/proxmox-backup-client.spec`
- `proxmox-backup-client/debian.changelog`
- `proxmox-backup-client/proxmox-backup-client.changes`
- `tools/build_source.py`

Debian binary packages now declare:

```debcontrol
Architecture: amd64 arm64 armhf ppc64el
```

## Source-bundle compatibility patches

The client source bundle is produced by `tools/build_source.py`. Rather than hand-editing generated bundle contents, compatibility changes were added to the generator so future bundles are reproducible.

### Data-safety policy used

For ARM32 libc differences:

- Do **not** change internal backup/client model types to 32-bit.
- Keep logical sizes, offsets, inodes, and timestamps as `i64`/`u64` where upstream expects wide semantics.
- When reading narrower libc fields on ARM32, widen at the boundary, e.g. `as i64` / `as u64`.
- When writing into libc fields that may be narrower on ARM32, use checked conversions (`try_into`) or fail loudly.
- Do not truncate file sizes/offsets/timestamps silently.
- For FUSE C glue, enable Large File Support with `_FILE_OFFSET_BITS=64`; do not bypass FUSE's assertion and do not force 32-bit offsets.

This preserves data consistency for backup workloads.

### Patches added in `tools/build_source.py`

#### `proxmox-time`

Patched `proxmox/proxmox-time/src/posix.rs` for ARM32 `time_t`:

- `mktime`/`timegm` results are widened to `i64`.
- `localtime_r`/`gmtime_r` input epochs are checked-converted to `libc::time_t`.

#### `pbs-buildcfg`

Patched `proxmox-backup/pbs-buildcfg/build.rs` for missing multiarch mappings:

- Rust target arch `arm` -> `arm-linux-gnueabihf`
- Rust target arch `powerpc64` -> `powerpc64le-linux-gnu`

This fixed the ppc64le panic:

```text
Unsupported architecture: powerpc64
```

#### `proxmox-sys`

Patched 32-bit libc type assumptions:

- `crypt.rs`: checked conversion for `crypt_gensalt_rn` `count` argument.
- `fs/mod.rs`: widen `stat.f_type` into internal `i64`.
- `linux/timer.rs`: write `timespec` fields as `libc::time_t` / `libc::c_long`.
- `process_locker.rs`: widen `libc::time` result into internal `i64`.

#### `proxmox-shared-memory`

Patched `ftruncate` length conversion to use checked conversion to platform `off_t`.

#### `proxmox-fuse`

Patched several ARM32 libc field-width assumptions:

- widen `stat.st_ino` to `u64`
- widen `st_*time_nsec` values to `i64`
- widen FUSE readdir offsets to `i64`

Also kept the existing EL9 `noflush` compatibility guard.

Most importantly, added Large File Support to C glue build:

```rust
.flag("-D_FILE_OFFSET_BITS=64")
```

This is the correct fix for the FUSE error:

```text
static assertion failed: "fuse: off_t must be 64bit"
```

It avoids 2 GiB offset limits and preserves FUSE large-file safety.

#### `pbs-config`

Patched stat timestamp cache comparisons/storage:

- widen `stat.st_mtime` and `stat.st_mtime_nsec` to `i64` before comparing/storing.

#### `pbs-datastore` / `pbs-pxar-fuse`

Patched more ARM32 file offset/stat field assumptions:

- `pbs-datastore/src/chunk_store.rs`: widen `stat.st_atime` to `i64`.
- `pbs-datastore/src/fixed_index.rs`: checked conversions for mmap/ftruncate offsets.
- `pbs-pxar-fuse/src/lib.rs`: widen inode reads, checked-convert inode/size/time values written into `libc::stat`.

#### `pbs-fuse-loop`

Latest local generator patch added:

- widen `stat.st_ino` when passed to `EntryParam::simple`
- checked conversion for `stat.st_size` writes

However, because repeated large Source0 uploads started stalling, the latest `pbs-fuse-loop` fix was also applied as small recipe-side `sed` patches in:

- `proxmox-backup-client/debian.rules`
- `proxmox-backup-client/proxmox-backup-client.spec`

The first version used `?` in a non-`Result` function (`minimal_stat`) and failed. It was corrected to use `.expect("size does not fit into st_size field")`, which fails loudly instead of truncating.

## OBS client build evidence

### PowerPC

After source patches, ppc64le builds succeeded on active targets including:

- `openSUSE_Tumbleweed/ppc64le`
- `openSUSE_Leap_16.0/ppc64le`
- `Ubuntu_24.04/ppc64le`
- `Debian_13/ppc64le`
- `Debian_12/ppc64le`

Some ppc64le targets were still building or blocked on OBS infrastructure at different points:

- `Debian_11/ppc64le`: blocked/downloading DoD packages.
- Some Ubuntu/Leap ppc64le jobs were still building during later polls, but prior evidence showed ppc64le path was compiling successfully after `pbs-buildcfg` mapping.

### ARM32

ARM32 progressed through many earlier blockers:

1. `proxmox-time` 32-bit `time_t` mismatch
2. `proxmox-sys` libc type mismatches
3. `proxmox-shared-memory` `off_t` mismatch
4. `proxmox-fuse` Rust field-width mismatches
5. libfuse C static assert for 64-bit `off_t`, fixed by `_FILE_OFFSET_BITS=64`
6. `pbs-config` stat timestamp mismatches
7. `pbs-datastore`/`pbs-pxar-fuse` offset/stat mismatches
8. `pbs-fuse-loop` stat inode/size mismatch

At the end of the session, ARM32 builds were still not fully green. The latest uploaded OBS recipe fix corrected the invalid `?` usage in `minimal_stat` by using `.expect(...)`, and builds were re-triggered.

Need to continue by polling:

```sh
osc results home:ciriarte:pbs-client proxmox-backup-client --csv | grep -E 'armv7l|ppc64le'
```

If ARM32 fails again, fetch the latest log, e.g.:

```sh
osc buildlog home:ciriarte:pbs-client proxmox-backup-client Debian_13 armv7l | tail -260
```

## Upload issue encountered

Large OBS Source0 uploads for `dist/proxmox-backup-client-4.2.0.tar.xz` began stalling after revision 36.

Tried:

- `osc api -X PUT -T ...`
- clean checkout `osc commit`
- `curl --upload-file` using osc credentials
- `curl --http1.1 -H 'Expect:' --upload-file`

All stalled on the 53 MiB tarball. Remote source remained at rev 36 with md5:

```text
f459b9adc57a466a5f01aae7ff038bf4  proxmox-backup-client-4.2.0.tar.xz
```

Local rebuilt tarball with the latest generator-side `pbs-fuse-loop` patch had md5:

```text
e821e7ff1313d262883f4d5a367f6869  dist/proxmox-backup-client-4.2.0.tar.xz
```

Workaround used: apply latest small fix via recipe-side `sed` patches instead of replacing Source0 again.

## Documentation updates

Updated `README.md` to describe:

- new supported architecture matrix with ARM32 and ppc64le/ppc64el columns;
- Debian as non-amd64 by design: `arm64`, `armhf`, `ppc64el`;
- expanded Rust toolchain bundle including `x86_64`, `aarch64`, `armv7`, and `ppc64le`;
- Rust helper tarball size now about 846 MB;
- secondary-arch policy: only where OBS mirrors compatible bases and Rust publishes host tools.

## Important safety conclusion

For the FUSE failure shown in the screenshot, the recommendation to enable Large File Support is correct. The safe fix is:

```rust
.flag("-D_FILE_OFFSET_BITS=64")
```

or equivalent CFLAGS for the C glue compile.

Do **not** change FUSE offsets to 32-bit or bypass the assertion. That would create a 2 GiB file/offset ceiling and is unsafe for backup workloads.

For the other Rust compile failures, the safe pattern is boundary conversion:

- widen 32-bit libc reads into 64-bit internal types;
- checked-convert 64-bit internal values when writing to libc fields;
- fail loudly on overflow rather than truncate.

## Current local modified files

Observed modified files include:

- `README.md`
- `project/_meta.xml`
- `tools/fetch_rust.sh`
- `tools/build_rust_pkg.sh`
- `tools/build_source.py`
- `pbs-client-rust/debian.control`
- `pbs-client-rust/debian.rules`
- `pbs-client-rust/pbs-client-rust.spec`
- `pbs-client-rust/debian.changelog`
- `pbs-client-rust/pbs-client-rust.changes`
- `proxmox-backup-client/debian.control`
- `proxmox-backup-client/debian.rules`
- `proxmox-backup-client/proxmox-backup-client.spec`
- `proxmox-backup-client/debian.changelog`
- `proxmox-backup-client/proxmox-backup-client.changes`

Also generated/updated large files under `dist/`:

- `rust-1.90.0-armv7-unknown-linux-gnueabihf.tar.xz`
- `rust-1.90.0-powerpc64le-unknown-linux-gnu.tar.xz`
- `pbs-client-rust-1.90.0.tar.gz`
- `proxmox-backup-client-4.2.0.tar.xz`

## Suggested next steps

1. Poll OBS build state after the latest recipe-only fix:

   ```sh
   osc results home:ciriarte:pbs-client proxmox-backup-client --csv | grep -E 'armv7l|ppc64le'
   ```

2. If ARM32 still fails, fetch latest log and continue boundary-conversion fixes. Avoid data-truncating changes.

3. Once ARM32 is green, try to resolve the large Source0 upload issue so `tools/build_source.py` and OBS Source0 are fully aligned, instead of relying on recipe-side sed patches.

4. Run/obtain final OBS evidence for:

   - all newly enabled ppc64le targets;
   - all newly enabled armv7l targets where workers are available;
   - note any OBS-infrastructure-only blockers separately.

5. Consider upstreaming the clean, minimal Rust source patches to Proxmox-owned crates if ARM32 support is intended long-term.
