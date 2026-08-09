#!/usr/bin/env python3
"""Assemble a self-contained, offline-buildable source bundle for the Proxmox
Backup client suite.

The `proxmox-backup` workspace pins Proxmox's own crates at versions that are
NOT on crates.io, and upstream ships no Cargo.lock. So we cannot `cargo vendor`
the workspace directly. Instead we assemble five repos side by side, enable the
`[patch.crates-io]` path overrides that upstream ships (commented out), and only
then vendor the remaining third-party crates:

    proxmox-backup-client-<ver>/
      proxmox-backup/        (release tag; patched Cargo.toml + .cargo/config.toml)
      proxmox/  pathpatterns/  pxar/  proxmox-fuse/   (coordinated commits)
      vendor/                (third-party crates only)

The sibling repos are UNTAGGED; their commits are pinned in tools/sources.json
(or auto-resolved by date-match with --auto and then verified to satisfy the
required crate majors). The bundle builds fully offline:

    cd proxmox-backup && cargo build --release --offline -p proxmox-backup-client ...

Usage:
    tools/build_source.py --version 4.2.0 [--auto] [--out DIST_DIR] [--keep-work]

Requires: git, cargo, tar, zstd. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "sources.json"


def run(cmd, cwd=None, env=None):
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def out(cmd, cwd=None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


def load_sources() -> dict:
    return json.loads(SOURCES.read_text())


def clone_at(url: str, ref: str, dest: Path) -> None:
    """Clone `url` and check out `ref` (a tag or full commit hash)."""
    run(["git", "clone", "--quiet", url, str(dest)])
    run(["git", "checkout", "--quiet", ref], cwd=dest)
    shutil.rmtree(dest / ".git")


def crate_version(repo: Path, crate: str) -> str | None:
    ct = repo / crate / "Cargo.toml"
    if not ct.exists():
        return None
    m = re.search(r'^version\s*=\s*"([^"]+)"', ct.read_text(), re.M)
    return m.group(1) if m else None


def required_majors(pbs: Path) -> dict[str, str]:
    """Parse proxmox-backup workspace deps -> {crate: required_major} for the
    Proxmox-owned crates we patch to paths (best-effort, for verification)."""
    text = (pbs / "Cargo.toml").read_text()
    reqs: dict[str, str] = {}
    for name in ("pathpatterns", "pxar", "proxmox-schema", "proxmox-router",
                 "proxmox-sys", "proxmox-fuse", "proxmox-s3-client"):
        m = re.search(rf'^{re.escape(name)}\s*=\s*(?:\{{[^}}]*version\s*=\s*)?"[\^~]?([0-9]+)',
                      text, re.M)
        if m:
            reqs[name] = m.group(1)
    return reqs


def auto_pin(refs: dict, work: Path) -> dict:
    """Resolve sibling commits by date-match to the proxmox-backup tag and keep
    the values already pinned in sources.json. Returns a refs dict."""
    src = load_sources()["upstream"]
    tag = refs["proxmox-backup"]
    tmp = work / "_probe-pbs"
    run(["git", "clone", "--quiet", "--depth", "1", "--branch", tag, src["proxmox-backup"], str(tmp)])
    date = out(["git", "log", "-1", "--format=%cI", "HEAD"], cwd=tmp)
    print(f"  {tag} date {date}")
    for name in ("proxmox", "pathpatterns", "pxar", "proxmox-fuse"):
        if refs.get(name):
            continue
        probe = work / f"_probe-{name}"
        run(["git", "clone", "--quiet", src[name], str(probe)])
        commit = out(["git", "rev-list", "-1", f"--before={date}", "HEAD"], cwd=probe)
        refs[name] = commit
        print(f"  auto-pinned {name} -> {commit}")
        shutil.rmtree(probe)
    shutil.rmtree(tmp)
    return refs


def enable_patches(pbs: Path) -> int:
    """Uncomment the [patch.crates-io] `path = "../..."` lines upstream ships."""
    ct = pbs / "Cargo.toml"
    lines = ct.read_text().splitlines()
    n = 0
    for i, l in enumerate(lines):
        if re.match(r'\s*#\s*\S+\s*=\s*\{\s*path\s*=\s*"\.\./', l):
            lines[i] = re.sub(r'^(\s*)#\s*', r"\1", l)
            n += 1
    ct.write_text("\n".join(lines) + "\n")
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="release version, e.g. 4.2.0")
    ap.add_argument("--auto", action="store_true",
                    help="auto-resolve any unpinned sibling commits by date-match")
    ap.add_argument("--out", default=str(HERE.parent / "dist"))
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    data = load_sources()
    upstream = data["upstream"]
    refs = dict(data["releases"].get(args.version, {}))
    refs.setdefault("proxmox-backup", f"v{args.version}")

    work = Path(tempfile.mkdtemp(prefix="pbs-bundle-"))
    try:
        missing = [k for k in ("proxmox", "pathpatterns", "pxar", "proxmox-fuse") if not refs.get(k)]
        if missing:
            if not args.auto:
                print(f"error: unpinned siblings {missing}; add to sources.json or use --auto",
                      file=sys.stderr)
                return 2
            refs = auto_pin(refs, work)

        bundle = work / f"proxmox-backup-client-{args.version}"
        bundle.mkdir()
        print("Cloning repos:")
        clone_at(upstream["proxmox-backup"], refs["proxmox-backup"], bundle / "proxmox-backup")
        for name in ("proxmox", "pathpatterns", "pxar", "proxmox-fuse"):
            print(f"  {name} @ {refs[name][:12]}")
            clone_at(upstream[name], refs[name], bundle / name)

        pbs = bundle / "proxmox-backup"

        # Verify the sibling crate majors satisfy proxmox-backup's requirements.
        reqs = required_majors(pbs)
        loc = {"pathpatterns": ("pathpatterns", "."), "pxar": ("pxar", "."),
               "proxmox-fuse": ("proxmox-fuse", "."), "proxmox-schema": ("proxmox", "proxmox-schema"),
               "proxmox-router": ("proxmox", "proxmox-router"), "proxmox-sys": ("proxmox", "proxmox-sys"),
               "proxmox-s3-client": ("proxmox", "proxmox-s3-client")}
        bad = []
        for crate, want_major in reqs.items():
            repo, sub = loc[crate]
            base = bundle / repo
            have = crate_version(base, sub) if sub != "." else crate_version(bundle, repo)
            if have and have.split(".")[0] != want_major:
                bad.append(f"{crate}: want ^{want_major}, sibling has {have}")
        if bad:
            print("error: sibling crate version mismatch:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 2
        print("Sibling crate versions satisfy requirements.")

        # EL9 compat: libfuse3 < 3.16 lacks fuse_file_info.noflush, which
        # proxmox-fuse's glue.c accesses unconditionally. Guard it so the C
        # symbols still exist (Rust links against them) but become no-ops on old
        # libfuse. Version-guarded, so newer distros keep full functionality.
        glue = bundle / "proxmox-fuse" / "src" / "glue.c"
        if glue.exists():
            g = glue.read_text()
            if "MAKE_ACCESSORS(noflush)" in g and "FUSE_VERSION >= 316" not in g:
                g = g.replace(
                    "MAKE_ACCESSORS(noflush)",
                    "#if FUSE_VERSION >= 316\n"
                    "MAKE_ACCESSORS(noflush)\n"
                    "#else\n"
                    "extern void glue_set_ffi_noflush(struct fuse_file_info *ffi, unsigned int value) { (void)ffi; (void)value; }\n"
                    "extern unsigned int glue_get_ffi_noflush(struct fuse_file_info *ffi) { (void)ffi; return 0; }\n"
                    "#endif")
                glue.write_text(g)
                print("Patched proxmox-fuse glue.c: guard noflush for libfuse < 3.16 (EL9).")

        # Enable path patches; drop upstream's registry-replacement cargo config.
        n = enable_patches(pbs)
        print(f"Enabled {n} [patch.crates-io] path overrides.")
        up_cfg = pbs / ".cargo" / "config.toml"
        if up_cfg.exists():
            up_cfg.unlink()

        # Vendor third-party crates (network) and write the offline cargo config.
        print("Vendoring third-party crates...")
        (pbs / ".cargo").mkdir(exist_ok=True)
        cfg = subprocess.run(["cargo", "vendor", "--locked", str(bundle / "vendor")],
                             cwd=pbs, check=False, text=True, capture_output=True)
        if cfg.returncode != 0:  # --locked fails if no lockfile yet; generate then retry
            run(["cargo", "generate-lockfile"], cwd=pbs)
            cfg = subprocess.run(["cargo", "vendor", str(bundle / "vendor")],
                                 cwd=pbs, check=True, text=True, capture_output=True)
        # cargo prints the config to add; rewrite its absolute path to a relative one.
        conf = cfg.stdout
        conf = re.sub(r'directory\s*=\s*".*/vendor"', 'directory = "../vendor"', conf)
        (pbs / ".cargo" / "config.toml").write_text(conf)
        count = len(list((bundle / "vendor").iterdir()))
        print(f"Vendored {count} crates.")

        # Note: Rust is NOT bundled here — it comes from the sibling pbs-client-rust
        # package (built once from tools/build_rust_pkg.sh), which the client
        # BuildRequires. This keeps the per-release bundle small.

        # Pack the bundle. Use xz, not zst: OBS's Debian debtransform only
        # unpacks .tar.gz/.bz2/.xz orig tarballs, and rpm handles .xz fine too,
        # so one .tar.xz Source0 serves both RPM and DEB targets.
        dist = Path(args.out)
        dist.mkdir(parents=True, exist_ok=True)
        tarball = dist / f"proxmox-backup-client-{args.version}.tar.xz"
        print(f"Packing {tarball} ...")
        run(["tar", "-cJf", str(tarball), "-C", str(work), bundle.name])
        size = tarball.stat().st_size // (1024 * 1024)
        print(f"Done: {tarball} ({size} MiB)")

        # Persist the resolved pins back into sources.json.
        data["releases"][args.version] = {k: refs[k] for k in
                                          ("proxmox-backup", "proxmox", "pathpatterns", "pxar", "proxmox-fuse")}
        SOURCES.write_text(json.dumps(data, indent=2) + "\n")
        return 0
    finally:
        if args.keep_work:
            print(f"work dir kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
