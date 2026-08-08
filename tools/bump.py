#!/usr/bin/env python3
"""Track upstream Proxmox Backup releases and publish a new client bundle to OBS.

Detects the newest upstream `v*` tag on the canonical git.proxmox.com repo and,
if it is newer than the version currently packaged, assembles a fresh offline
source bundle (tools/build_source.py --auto: clone + date-match sibling commits +
[patch.crates-io] + vendor), updates the recipe version/changelogs, copies the
bundle into the osc checkout, and commits.

Because the client cannot vendor from crates.io alone (Proxmox's own crates are
unpublished at the pinned versions), there is no OBS source service — the bundle
is produced here and committed as Source0. See tools/build_source.py.

Run from an osc checkout of the package (or pass --checkout). Requires: git,
cargo, tar, zstd, osc. Stdlib only.

Usage:
    tools/bump.py [--checkout DIR] [--dry-run] [--commit]

Exit codes: 0 = up to date or bump prepared; 2 = guardrail tripped; 1 = error.
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PKGDIR = REPO / "proxmox-backup-client"
UPSTREAM_GIT = "https://git.proxmox.com/git/proxmox-backup.git"
MAINTAINER = "Ciro Iriarte <ciro.iriarte+software@gmail.com>"
EL9_RUST_FLOOR = (1, 81)


def run(cmd, cwd=None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout


def parse_ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s))


def latest_upstream_tag() -> str:
    out = run(["git", "ls-remote", "--tags", "--refs", UPSTREAM_GIT])
    tags = [l.split("/")[-1] for l in out.splitlines() if re.search(r"refs/tags/v\d", l)]
    if not tags:
        raise RuntimeError("no upstream tags found")
    return max(tags, key=parse_ver)


def current_version() -> str:
    m = re.search(r"^Version:\s*(\S+)", (PKGDIR / "proxmox-backup-client.spec").read_text(), re.M)
    if not m:
        raise RuntimeError("no Version: in spec")
    return m.group(1)


def rewrite_recipe(new: str) -> None:
    spec = PKGDIR / "proxmox-backup-client.spec"
    text = re.sub(r"^(Version:\s*)\S+", rf"\g<1>{new}", spec.read_text(), flags=re.M)
    text = re.sub(r"^(Release:\s*)\S+", r"\g<1>0", text, flags=re.M)
    spec.write_text(text)

    now = datetime.datetime.now(datetime.timezone.utc)
    entry = f"Update to upstream v{new}."
    changes = PKGDIR / "proxmox-backup-client.changes"
    changes.write_text(
        "-------------------------------------------------------------------\n"
        f"{now:%a %b %d %H:%M:%S UTC %Y} - {MAINTAINER}\n\n- {entry}\n\n" + changes.read_text())
    deb = PKGDIR / "debian.changelog"
    deb.write_text(
        f"proxmox-backup-client ({new}-0) unstable; urgency=medium\n\n"
        f"  * {entry}\n\n -- {MAINTAINER}  {now:%a, %d %b %Y %H:%M:%S +0000}\n\n" + deb.read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", help="osc checkout dir of the package (to copy bundle + commit)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    latest = latest_upstream_tag()
    new = latest.lstrip("v")
    cur = current_version()
    print(f"current={cur} latest_upstream={latest}")
    if parse_ver(new) <= parse_ver(cur):
        print("up to date")
        return 0
    if args.dry_run:
        print(f"would bump {cur} -> {new}")
        return 0

    # Assemble the offline bundle (auto-resolves + verifies sibling commits).
    dist = REPO / "dist"
    print(f"assembling bundle for {new} ...")
    run([sys.executable, str(HERE / "build_source.py"), "--version", new, "--auto",
         "--out", str(dist)])
    tarball = dist / f"proxmox-backup-client-{new}.tar.zst"
    if not tarball.exists():
        print("error: bundle not produced", file=sys.stderr)
        return 1

    rewrite_recipe(new)
    print(f"bumped {cur} -> {new}; bundle at {tarball}")

    if not args.checkout:
        print("no --checkout given; recipe + bundle updated locally. "
              "Copy the bundle + recipe into your osc checkout and commit.")
        return 0

    co = Path(args.checkout)
    old = list(co.glob("proxmox-backup-client-*.tar.zst"))
    for f in old:
        run(["osc", "rm", "--force", f.name], cwd=co)
    run(["cp", str(tarball), str(co)])
    for f in PKGDIR.glob("*"):
        run(["cp", str(f), str(co)])
    run(["osc", "addremove"], cwd=co)
    if args.commit:
        run(["osc", "commit", "-m", f"Update to upstream v{new}"], cwd=co)
        print("committed to OBS")
    else:
        print("staged in checkout; re-run with --commit to publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
