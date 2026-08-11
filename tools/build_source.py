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

        # Architecture compat: upstream assumes libc::time_t is i64 in
        # proxmox-time. On 32-bit armhf, libc::time_t is i32, so explicitly
        # cast mktime/timegm results to i64 and cast checked input epochs back
        # to libc::time_t for localtime_r/gmtime_r.
        posix = bundle / "proxmox" / "proxmox-time" / "src" / "posix.rs"
        if posix.exists():
            t = posix.read_text()
            changed = False
            if "Ok(epoch as i64)" not in t:
                t = t.replace("    Ok(epoch)\n", "    Ok(epoch as i64)\n", 2)
                changed = True
            if "let epoch: libc::time_t = epoch" not in t:
                t = t.replace(
                    "pub fn localtime(epoch: i64) -> Result<libc::tm, Error> {\n    let mut result = new_libc_tm();\n\n    unsafe {",
                    "pub fn localtime(epoch: i64) -> Result<libc::tm, Error> {\n    let mut result = new_libc_tm();\n    let epoch: libc::time_t = epoch\n        .try_into()\n        .map_err(|_| format_err!(\"epoch out of range for libc::time_t: '{epoch}'\"))?;\n\n    unsafe {",
                )
                t = t.replace(
                    "pub fn gmtime(epoch: i64) -> Result<libc::tm, Error> {\n    let mut result = new_libc_tm();\n\n    unsafe {",
                    "pub fn gmtime(epoch: i64) -> Result<libc::tm, Error> {\n    let mut result = new_libc_tm();\n    let epoch: libc::time_t = epoch\n        .try_into()\n        .map_err(|_| format_err!(\"epoch out of range for libc::time_t: '{epoch}'\"))?;\n\n    unsafe {",
                )
                changed = True
            if changed:
                posix.write_text(t)
                print("Patched proxmox-time posix.rs: support 32-bit libc::time_t.")

        # Architecture compat: pbs-buildcfg only knows Debian multiarch tuples
        # for the upstream server/client arches. Add native armhf and ppc64le
        # mappings used by the OBS builds enabled here.
        buildcfg = pbs / "pbs-buildcfg" / "build.rs"
        if buildcfg.exists():
            b = buildcfg.read_text()
            if 'Ok("arm") => "arm-linux-gnueabihf"' not in b:
                b = b.replace(
                    '        Ok("aarch64") => "aarch64-linux-gnu",\n        Ok("riscv64") => "riscv64-linux-gnu",',
                    '        Ok("aarch64") => "aarch64-linux-gnu",\n        Ok("arm") => "arm-linux-gnueabihf",\n        Ok("powerpc64") => "powerpc64le-linux-gnu",\n        Ok("riscv64") => "riscv64-linux-gnu",',
                )
                buildcfg.write_text(b)
                print("Patched pbs-buildcfg build.rs: add armhf/ppc64le multiarch mappings.")

        # Architecture compat: proxmox-sys has several Linux libc type
        # assumptions that are true on 64-bit targets but not armhf. Keep the
        # public Rust API types unchanged and cast at the libc boundary.
        proxmox_sys = bundle / "proxmox" / "proxmox-sys" / "src"
        if proxmox_sys.exists():
            patched_sys = False
            crypt = proxmox_sys / "crypt.rs"
            c = crypt.read_text()
            if "count.try_into()?" not in c:
                c = c.replace("            count,\n", "            count.try_into()?,\n", 1)
                crypt.write_text(c)
                patched_sys = True
            fs_mod = proxmox_sys / "fs" / "mod.rs"
            f = fs_mod.read_text()
            if "fs_type: stat.f_type as i64" not in f:
                f = f.replace("        fs_type: stat.f_type,\n", "        fs_type: stat.f_type as i64,\n", 1)
                fs_mod.write_text(f)
                patched_sys = True
            timer = proxmox_sys / "linux" / "timer.rs"
            tm = timer.read_text()
            if "tv_sec: value.as_secs() as libc::time_t" not in tm:
                tm = tm.replace("            tv_sec: value.as_secs() as i64,\n", "            tv_sec: value.as_secs() as libc::time_t,\n", 1)
                tm = tm.replace("            tv_nsec: value.subsec_nanos() as i64,\n", "            tv_nsec: value.subsec_nanos() as libc::c_long,\n", 1)
                timer.write_text(tm)
                patched_sys = True
            locker = proxmox_sys / "process_locker.rs"
            l = locker.read_text()
            if "let now = unsafe { libc::time(std::ptr::null_mut()) } as i64;" not in l:
                l = l.replace(
                    "        let now = unsafe { libc::time(std::ptr::null_mut()) };\n",
                    "        let now = unsafe { libc::time(std::ptr::null_mut()) } as i64;\n",
                    1,
                )
                locker.write_text(l)
                patched_sys = True
            if patched_sys:
                print("Patched proxmox-sys: support 32-bit armhf libc types.")

        # Architecture compat: proxmox-shared-memory passes an i64 to
        # nix::unistd::ftruncate; on armhf nix::libc::off_t is i32.
        shared_memory = bundle / "proxmox" / "proxmox-shared-memory" / "src" / "lib.rs"
        if shared_memory.exists():
            m = shared_memory.read_text()
            if "nix::unistd::ftruncate(&file, size.try_into()?)" not in m:
                m = m.replace(
                    "        nix::unistd::ftruncate(&file, size as i64)?;\n",
                    "        nix::unistd::ftruncate(&file, size.try_into()?)?;\n",
                    1,
                )
                shared_memory.write_text(m)
                print("Patched proxmox-shared-memory: support 32-bit off_t.")

        # Architecture compat: proxmox-fuse receives several libc fields
        # whose widths differ on 32-bit armhf; widen them at the Rust API
        # boundary to match proxmox-fuse's internal u64/i64 types.
        fuse_src = bundle / "proxmox-fuse" / "src"
        if fuse_src.exists():
            patched_fuse = False
            requests = fuse_src / "requests.rs"
            r = requests.read_text()
            replacements = {
                "            inode: stat.st_ino,\n": "            inode: stat.st_ino as u64,\n",
                "            Some(SetTime::from_c(self.stat.st_atime, self.stat.st_atime_nsec))\n": "            Some(SetTime::from_c(self.stat.st_atime, self.stat.st_atime_nsec as i64))\n",
                "            Some(SetTime::from_c(self.stat.st_mtime, self.stat.st_mtime_nsec))\n": "            Some(SetTime::from_c(self.stat.st_mtime, self.stat.st_mtime_nsec as i64))\n",
                "            Some(c_duration(self.stat.st_ctime, self.stat.st_ctime_nsec))\n": "            Some(c_duration(self.stat.st_ctime, self.stat.st_ctime_nsec as i64))\n",
            }
            for old, new in replacements.items():
                if old in r and new not in r:
                    r = r.replace(old, new, 1)
                    patched_fuse = True
            if patched_fuse:
                requests.write_text(r)
            session = fuse_src / "session.rs"
            se = session.read_text()
            if "                offset as i64,\n" not in se:
                se = se.replace("                offset,\n", "                offset as i64,\n", 2)
                session.write_text(se)
                patched_fuse = True
            if patched_fuse:
                print("Patched proxmox-fuse: support 32-bit armhf libc field widths.")

        # Architecture compat: pbs-config caches libc stat timestamps in
        # i64 fields; widen stat values before comparing/storing on armhf.
        pbs_config = pbs / "pbs-config" / "src"
        if pbs_config.exists():
            patched_config = False
            for rel in ("acl.rs", "user.rs"):
                cfg = pbs_config / rel
                text = cfg.read_text()
                new = text.replace("stat.st_mtime == cache.last_mtime", "stat.st_mtime as i64 == cache.last_mtime")
                new = new.replace("stat.st_mtime_nsec == cache.last_mtime_nsec", "stat.st_mtime_nsec as i64 == cache.last_mtime_nsec")
                new = new.replace("cache.last_mtime = stat.st_mtime;", "cache.last_mtime = stat.st_mtime as i64;")
                new = new.replace("cache.last_mtime_nsec = stat.st_mtime_nsec;", "cache.last_mtime_nsec = stat.st_mtime_nsec as i64;")
                if new != text:
                    cfg.write_text(new)
                    patched_config = True
            if patched_config:
                print("Patched pbs-config: support 32-bit stat timestamp fields.")

        # Architecture compat: pbs-datastore and pbs-pxar-fuse use file
        # offsets and libc::stat fields whose widths narrow on armhf. Use
        # checked conversions where values flow into libc fields.
        datastore = pbs / "pbs-datastore" / "src"
        pxar_fuse = pbs / "pbs-pxar-fuse" / "src" / "lib.rs"
        patched_datastore_pxar = False
        if datastore.exists():
            chunk_store = datastore / "chunk_store.rs"
            cs = chunk_store.read_text()
            if "stat.st_atime as i64" not in cs:
                cs = cs.replace("                        stat.st_atime,\n", "                        stat.st_atime as i64,\n", 1)
                chunk_store.write_text(cs)
                patched_datastore_pxar = True
            fixed_index = datastore / "fixed_index.rs"
            fi = fixed_index.read_text()
            fixed_replacements = {
                "                header_size as i64,\n": "                header_size.try_into()?,\n",
                "        nix::unistd::ftruncate(&file, file_size)?;\n": "        nix::unistd::ftruncate(&file, file_size.try_into()?)?;\n",
                "        nix::unistd::ftruncate(&self.file, new_size)?;\n": "        nix::unistd::ftruncate(&self.file, new_size.try_into()?)?;\n",
                "            nix::unistd::ftruncate(&self.file, file_size)?;\n": "            nix::unistd::ftruncate(&self.file, file_size.try_into()?)?;\n",
            }
            for old, new in fixed_replacements.items():
                if old in fi and new not in fi:
                    fi = fi.replace(old, new)
                    patched_datastore_pxar = True
            if patched_datastore_pxar:
                fixed_index.write_text(fi)
        if pxar_fuse.exists():
            px = pxar_fuse.read_text()
            px_replacements = {
                "stat.st_ino, &file)?": "stat.st_ino as u64, &file)?",
                "    stat.st_ino = inode;\n": "    stat.st_ino = inode.try_into()\n        .map_err(|err| format_err!(\"inode does not fit into st_ino field: {err}\"))?;\n",
                '    stat.st_size = i64::try_from(entry.file_size().unwrap_or(0))\n        .map_err(|err| format_err!("size does not fit into st_size field: {}", err))?;\n': '    stat.st_size = entry.file_size().unwrap_or(0).try_into()\n        .map_err(|err| format_err!("size does not fit into st_size field: {}", err))?;\n',
                "    stat.st_atime = metadata.stat.mtime.secs;\n": "    stat.st_atime = metadata.stat.mtime.secs.try_into()\n        .map_err(|err| format_err!(\"mtime seconds do not fit into st_atime field: {err}\"))?;\n",
                "    stat.st_mtime = metadata.stat.mtime.secs;\n": "    stat.st_mtime = metadata.stat.mtime.secs.try_into()\n        .map_err(|err| format_err!(\"mtime seconds do not fit into st_mtime field: {err}\"))?;\n",
                "    stat.st_ctime = metadata.stat.mtime.secs;\n": "    stat.st_ctime = metadata.stat.mtime.secs.try_into()\n        .map_err(|err| format_err!(\"mtime seconds do not fit into st_ctime field: {err}\"))?;\n",
            }
            for old, new in px_replacements.items():
                if old in px and new not in px:
                    px = px.replace(old, new, 1)
                    patched_datastore_pxar = True
            if patched_datastore_pxar:
                pxar_fuse.write_text(px)
        if patched_datastore_pxar:
            print("Patched datastore/pxar-fuse: support 32-bit armhf file offsets and stat fields.")

        # Architecture compat: pbs-fuse-loop passes libc::stat fields to
        # proxmox-fuse's widened API and writes sizes back into stat fields.
        # Widen inode reads; use checked conversion for st_size writes.
        fuse_loop = pbs / "pbs-fuse-loop" / "src" / "fuse_loop.rs"
        if fuse_loop.exists():
            fl = fuse_loop.read_text()
            patched_fuse_loop = False
            if "EntryParam::simple(stat.st_ino as u64, stat)" not in fl:
                fl = fl.replace(
                    "EntryParam::simple(stat.st_ino, stat)",
                    "EntryParam::simple(stat.st_ino as u64, stat)",
                    1,
                )
                patched_fuse_loop = True
            if "stat.st_size = size.try_into()" not in fl:
                fl = fl.replace(
                    "    stat.st_size = size;\n",
                    "    stat.st_size = size.try_into()\n        .expect(\"size does not fit into st_size field\");\n",
                    1,
                )
                patched_fuse_loop = True
            if patched_fuse_loop:
                fuse_loop.write_text(fl)
                print("Patched pbs-fuse-loop: support 32-bit armhf stat fields.")

        # Architecture compat: pbs-client's pxar create/extract/metadata read
        # libc::stat fields and write file offsets/timestamps that narrow on
        # armhf (st_ino u32, st_mtime/f_type i32, off_t/time_t i32). Keep the
        # wide pxar semantics: widen libc reads; checked-convert values written
        # into libc off_t/time_t so oversized files/timestamps fail loudly
        # instead of truncating.
        pxar = pbs / "pbs-client" / "src" / "pxar"
        if pxar.exists():
            patched_pxar = False
            create = pxar / "create.rs"
            cr = create.read_text()
            create_replacements = {
                # widen fstatfs f_type read into pxar's i64 return
                "    Ok(fs_stat.f_type)\n": "    Ok(fs_stat.f_type as i64)\n",
                # widen st_ino read into HardLinkInfo's u64 field (2 sites)
                "                    st_ino: stat.st_ino,\n": "                    st_ino: stat.st_ino as u64,\n",
                # widen st_mtime read into catalog add_file's i64 mtime
                "                        .add_file(c_file_name, file_size, stat.st_mtime)?;\n": "                        .add_file(c_file_name, file_size, stat.st_mtime as i64)?;\n",
                # widen st_mtime read into StatxTimestamp::new's i64 secs
                "            mtime: pxar::format::StatxTimestamp::new(stat.st_mtime, stat.st_mtime_nsec as u32),\n": "            mtime: pxar::format::StatxTimestamp::new(stat.st_mtime as i64, stat.st_mtime_nsec as u32),\n",
            }
            for old, new in create_replacements.items():
                if old in cr and new not in cr:
                    cr = cr.replace(old, new)
                    patched_pxar = True
            if patched_pxar:
                create.write_text(cr)
            extract = pxar / "extract.rs"
            ex = extract.read_text()
            # checked conversion for ftruncate off_t (2 identical sites);
            # enclosing fns return Result<(), Error> so propagate on overflow
            if "nix::unistd::ftruncate(&file, size as i64)" in ex:
                ex = ex.replace(
                    "nix::unistd::ftruncate(&file, size as i64)",
                    "nix::unistd::ftruncate(&file, size.try_into().context(\"file size does not fit into off_t\")?)",
                )
                extract.write_text(ex)
                patched_pxar = True
            metadata = pxar / "metadata.rs"
            md = metadata.read_text()
            md_changed = False
            if "tv_nsec: UTIME_OMIT as libc::c_long,\n" not in md:
                md = md.replace(
                    "            tv_nsec: UTIME_OMIT,\n",
                    "            tv_nsec: UTIME_OMIT as libc::c_long,\n",
                    1,
                )
                md_changed = True
            # timestamp_to_update_timespec returns an array, not a Result, so
            # fail loudly on a time_t that cannot hold the mtime seconds
            if "tv_sec: mtime.secs.try_into()" not in md:
                md = md.replace(
                    "            tv_sec: mtime.secs,\n",
                    "            tv_sec: mtime.secs.try_into()\n                .expect(\"mtime seconds do not fit into libc::time_t\"),\n",
                    1,
                )
                md_changed = True
            if md_changed:
                metadata.write_text(md)
                patched_pxar = True
            if patched_pxar:
                print("Patched pbs-client pxar: support 32-bit armhf stat/offset fields.")

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
        fuse_build = bundle / "proxmox-fuse" / "build.rs"
        if fuse_build.exists():
            fb = fuse_build.read_text()
            if '-D_FILE_OFFSET_BITS=64' not in fb:
                fb = fb.replace(
                    '    cc.pic(true).opt_level(3).flag("-DFUSE_USE_VERSION=35");',
                    '    cc.pic(true).opt_level(3).flag("-DFUSE_USE_VERSION=35").flag("-D_FILE_OFFSET_BITS=64");',
                )
                fuse_build.write_text(fb)
                print("Patched proxmox-fuse build.rs: enable 64-bit off_t for libfuse on 32-bit targets.")

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
