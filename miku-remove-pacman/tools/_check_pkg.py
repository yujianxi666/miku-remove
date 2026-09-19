#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent checker for the generated Arch packages.

Decompresses the .pkg.tar.zst with the zstd binary and asserts the structure
pacman needs: .PKGINFO first, .INSTALL present, .MTREE entries matching the
payload, and payload paths relative to the filesystem root.

    python3 tools/_check_pkg.py dist/miku-voicebank-pack-3.9.1-1-any.pkg.tar.zst
    python3 tools/_check_pkg.py dist/*.pkg.tar.zst      # all of them
"""
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile

failures = []


def check(name, cond, detail=""):
    print("  %-46s %s%s" % (name, "ok" if cond else "FAIL",
                            ("  " + str(detail)) if detail else ""))
    if not cond:
        failures.append(name)


def main(path):
    blob = open(path, "rb").read()
    print("file: %s (%d bytes)" % (path, len(blob)))
    exe = shutil.which("zstd")
    raw = subprocess.run([exe, "-d", "-c", "-q"], input=blob,
                         stdout=subprocess.PIPE).stdout
    check("decompresses with zstd", len(raw) > 0, len(raw))
    tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    names = tar.getnames()
    check("first member is .PKGINFO", names and names[0] == "./.PKGINFO", names[:3])
    check("has .INSTALL", "./.INSTALL" in names)
    check("has .MTREE", "./.MTREE" in names)
    info = tar.extractfile("./.PKGINFO").read().decode("utf-8")
    print("--- .PKGINFO ---")
    for line in info.splitlines():
        print("  " + line)
    install = tar.extractfile("./.INSTALL").read().decode("utf-8")
    check(".INSTALL defines pre_remove", "pre_remove()" in install)
    check(".INSTALL defines post_install", "post_install()" in install)
    check(".INSTALL stamps the index", "__INDEX__" not in install)
    check(".INSTALL stamps the count", "__COUNT__" not in install)
    check(".INSTALL ticks miku-show", "--tick --index" in install)
    check(".INSTALL skips upgrades", '"remove" ] || return 0' in install)
    # mtree vs payload
    tree = gzip.decompress(tar.extractfile("./.MTREE").read()).decode("utf-8")
    tree_entries = {}
    for line in tree.splitlines():
        if line.startswith("./"):
            rel = line.split()[0][2:]
            fields = dict(kv.split("=", 1) for kv in line.split()[1:])
            tree_entries[rel] = fields
    payload = {}
    for member in tar.getmembers():
        if member.name in ("./.PKGINFO", "./.INSTALL", "./.MTREE"):
            continue
        if not member.isfile():
            continue
        rel = member.name[2:]
        data = tar.extractfile(member).read()
        payload[rel] = (data, member.mode)
    check(".MTREE covers every payload file",
          set(tree_entries) == set(payload),
          "tree=%d payload=%d" % (len(tree_entries), len(payload)))
    bad = []
    for rel, (data, mode) in payload.items():
        fields = tree_entries.get(rel)
        if not fields:
            bad.append((rel, "missing"))
            continue
        if fields.get("md5digest") != hashlib.md5(data).hexdigest():
            bad.append((rel, "md5"))
        if int(fields.get("size", -1)) != len(data):
            bad.append((rel, "size"))
        if int(fields.get("mode", "0"), 8) != mode:
            bad.append((rel, "mode"))
    check(".MTREE digests/sizes/modes match", not bad, bad[:4])
    check("no absolute paths in payload",
          all(not n.startswith("/") for n in payload))
    print("--- payload (%d files) ---" % len(payload))
    for rel in sorted(payload)[:8]:
        data, mode = payload[rel]
        print("   %-52s %7d  mode=%s" % (rel, len(data), oct(mode)))
    if len(payload) > 8:
        print("   ... and %d more" % (len(payload) - 8))
    print("--- result ---")
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("all pacman checks passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__ or "usage: _check_pkg.py <package.pkg.tar.zst> ...")
    code = 0
    for path in sys.argv[1:]:
        code |= main(path)
        print()
    if len(sys.argv) > 2:
        print("checked %d packages" % (len(sys.argv) - 1))
    sys.exit(code)
