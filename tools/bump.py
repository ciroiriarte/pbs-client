#!/usr/bin/env python3
"""Track upstream Proxmox Backup releases and bump the OBS package.

Detects the newest upstream `v*` tag on the canonical git.proxmox.com repo and,
if it is newer than the version currently packaged, rewrites the package sources
(``_service`` revision, RPM ``.spec`` version, and both changelogs), re-vendors
via ``osc service``, and commits to OBS.

Upstream ships NO Cargo.lock, so ``obs-service-cargo`` resolves and vendors the
dependency graph itself; the committed ``vendor.tar.zst`` is the effective pin.

Designed to run under a systemd timer or CI. Requires: git, osc (configured),
and the openSUSE ``obs-service-cargo`` on the OBS source server. Stdlib only.

Usage:
    tools/bump.py [--package-dir proxmox-backup-client] [--dry-run] [--commit]

Exit codes: 0 = up to date or bump prepared; 2 = guardrail tripped; 1 = error.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_GIT = "https://git.proxmox.com/git/proxmox-backup.git"
MAINTAINER = "Ciro Iriarte <ciro.iriarte+software@gmail.com>"
# EL9's rust-toolset floor we are willing to rely on. If upstream MSRV exceeds
# this, EL9 needs EPEL/a newer toolchain — warn instead of silently shipping.
EL9_RUST_FLOOR = (1, 81)


def run(cmd: list[str], **kw) -> str:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def parse_ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s))


def latest_upstream_tag() -> str:
    out = run(["git", "ls-remote", "--tags", "--refs", UPSTREAM_GIT])
    tags = [
        line.split("/")[-1]
        for line in out.splitlines()
        if re.search(r"refs/tags/v\d", line)
    ]
    if not tags:
        raise RuntimeError("no upstream tags found")
    return max(tags, key=parse_ver)


def current_version(spec: Path) -> str:
    m = re.search(r"^Version:\s*(\S+)", spec.read_text(), re.M)
    if not m:
        raise RuntimeError(f"no Version: in {spec}")
    return m.group(1)


def upstream_msrv(tag: str) -> tuple[int, ...] | None:
    """Read rust-version from the tag's workspace Cargo.toml (shallow)."""
    try:
        blob = run(
            ["git", "archive", "--remote", UPSTREAM_GIT, tag, "Cargo.toml"],
        )
    except subprocess.CalledProcessError:
        return None  # some servers disallow archive; skip the check
    m = re.search(r'rust-version\s*=\s*"([\d.]+)"', blob)
    return parse_ver(m.group(1)) if m else None


def rewrite(pkg: Path, old: str, new: str) -> None:
    service = pkg / "_service"
    service.write_text(
        re.sub(
            r'(<param name="revision">)v?[\d.]+(</param>)',
            rf"\g<1>v{new}\g<2>",
            service.read_text(),
        )
    )

    spec = pkg / "proxmox-backup-client.spec"
    text = re.sub(r"^(Version:\s*)\S+", rf"\g<1>{new}", spec.read_text(), flags=re.M)
    text = re.sub(r"^(Release:\s*)\S+", r"\g<1>0", text, flags=re.M)
    spec.write_text(text)

    now = datetime.datetime.now(datetime.timezone.utc)
    rpm_stamp = now.strftime("%a %b %d %H:%M:%S UTC %Y")
    deb_stamp = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    entry = f"Update to upstream v{new}."

    changes = pkg / "proxmox-backup-client.changes"
    changes.write_text(
        f"-------------------------------------------------------------------\n"
        f"{rpm_stamp} - {MAINTAINER}\n\n- {entry}\n\n" + changes.read_text()
    )

    deb = pkg / "debian.changelog"
    deb.write_text(
        f"proxmox-backup-client ({new}-0) unstable; urgency=medium\n\n"
        f"  * {entry}\n\n"
        f" -- {MAINTAINER}  {deb_stamp}\n\n" + deb.read_text()
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-dir", default="proxmox-backup-client")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true", help="osc commit after vendoring")
    args = ap.parse_args()

    pkg = Path(args.package_dir).resolve()
    spec = pkg / "proxmox-backup-client.spec"
    if not spec.exists():
        print(f"error: {spec} not found", file=sys.stderr)
        return 1

    latest = latest_upstream_tag()            # e.g. "v4.2.1"
    new = latest.lstrip("v")
    cur = current_version(spec)
    print(f"current={cur} latest_upstream={latest}")

    if parse_ver(new) <= parse_ver(cur):
        print("up to date")
        return 0

    msrv = upstream_msrv(latest)
    if msrv and msrv > EL9_RUST_FLOOR:
        print(
            f"WARNING: upstream MSRV {'.'.join(map(str, msrv))} exceeds the EL9 "
            f"rust floor {'.'.join(map(str, EL9_RUST_FLOOR))}; verify Rocky 9 "
            f"has a new-enough rust-toolset (or add EPEL9) before publishing.",
            file=sys.stderr,
        )

    if args.dry_run:
        print(f"would bump {cur} -> {new}")
        return 0

    rewrite(pkg, cur, new)
    print(f"bumped {cur} -> {new}")

    # Re-vendor server-side (network) and stage the regenerated artifacts.
    subprocess.run(["osc", "service", "manualrun"], check=True, cwd=pkg)
    subprocess.run(["osc", "addremove"], check=True, cwd=pkg)

    if args.commit:
        subprocess.run(
            ["osc", "commit", "-m", f"Update to upstream v{new}"], check=True, cwd=pkg
        )
        print("committed to OBS")
    else:
        print("staged; re-run with --commit to publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
