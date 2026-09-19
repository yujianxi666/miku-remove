#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check the built packages with the system's own rpm.

    python3 tools/_check_rpm.py dist/*.rpm

`rpm -qp` / `rpm -K` parse the header, the region and the signature with rpm's
own code, which is the only verdict that matters (`dnf install` uses the same
parser).  Without rpm installed the script falls back to reading the header
layout itself, which catches structural damage but not everything dnf checks.
"""

from __future__ import annotations

import argparse
import glob
import shutil
import struct
import subprocess
import sys

MAGIC = b"\x8e\xad\xe8"


def with_system_rpm(paths) -> int:
    """Verify every package with `rpm -K` and print name/version/arch."""
    failures = []
    for path in paths:
        check = subprocess.run(["rpm", "-K", path], capture_output=True, text=True)
        query = subprocess.run(
            ["rpm", "-qp", "--qf", "%{NAME} %{VERSION}-%{RELEASE} %{ARCH}", path],
            capture_output=True, text=True)
        ok = check.returncode == 0 and query.returncode == 0
        print("  %-46s %s" % (path.split("/")[-1],
                              query.stdout.strip() if ok else "FAIL"))
        if not ok:
            failures.append(path)
            sys.stderr.write(check.stdout + check.stderr + query.stderr)
    print()
    if failures:
        print("FAILED: %d package(s)" % len(failures))
        return 1
    print("all %d packages verified by rpm" % len(paths))
    return 0


def read_header(blob, off):
    """-> (entries, store, end).  Raises when the header is malformed."""
    if blob[off:off + 3] != MAGIC:
        raise ValueError("no header magic at %d" % off)
    if blob[off + 3] != 1:
        raise ValueError("header version is %d, rpm wants 1" % blob[off + 3])
    n, store_size = struct.unpack(">ii", blob[off + 8:off + 16])
    entries = []
    p = off + 16
    for _ in range(n):
        entries.append(struct.unpack(">iiii", blob[p:p + 16]))
        p += 16
    store = blob[p:p + store_size]
    return entries, store, p + store_size


def inspect(path) -> list:
    """Structural sanity check without rpm; returns a list of problems."""
    blob = open(path, "rb").read()
    problems = []
    if blob[:4] != b"\xed\xab\xee\xdb":
        problems.append("lead magic")
    sig_entries, sig_store, sig_end = read_header(blob, 96)
    # note: rpmbuild pads between the signature header and the main one, so
    # `sig_end` itself does not have to be 8-byte aligned; the main header is
    # looked up at the next 8-byte boundary.
    tag, ty, off, count = sig_entries[0]
    if (tag, ty, count) != (62, 7, 16):
        problems.append("signature region entry is %r, want tag 62 type 7 count 16"
                        % ((tag, ty, count),))
    trailer = struct.unpack(">IiiI", sig_store[off:off + 16])
    if trailer[0] != 62 or trailer[1] != 7 or trailer[3] != 16:
        problems.append("signature region trailer is %r" % (trailer,))
    elif -trailer[2] != 16 * len(sig_entries):
        problems.append("signature region entry count mismatch (%d vs %d)"
                        % (-trailer[2] // 16, len(sig_entries)))
    main_entries, main_store, main_end = read_header(blob, sig_end + (-sig_end) % 8)
    # the payload can be gzip (older rpm) or zstd (rpm 6 default)
    if blob[main_end:main_end + 2] not in (b"\x1f\x8b", b"\x28\xb5"):
        problems.append("payload is neither gzip nor zstd at %d" % main_end)
    if main_entries and main_entries[0][0] != 63:
        problems.append("main region entry has tag %d, want 63" % main_entries[0][0])
    align = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 1, 9: 1}
    for tag, ty, o, _c in main_entries:
        if ty not in align:
            problems.append("tag %d has unknown type %d" % (tag, ty))
            continue
        if o % align[ty]:
            problems.append("tag %d offset %d is not %d-aligned"
                            % (tag, o, align[ty]))
        if o >= len(main_store):
            problems.append("tag %d offset %d is outside the store" % (tag, o))
    return problems


def without_rpm(paths) -> int:
    print("(rpm not installed: falling back to a structural check)")
    bad = 0
    for path in paths:
        problems = inspect(path)
        print("  %-46s %s" % (path.split("/")[-1],
                              "ok" if not problems else "FAIL"))
        for p in problems:
            print("        %s" % p)
        bad += bool(problems)
    print()
    if bad:
        print("FAILED: %d package(s)" % bad)
        return 1
    print("all %d packages look structurally sound (install rpm for a real check)"
          % len(paths))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="+")
    args = ap.parse_args()
    paths = []
    for pattern in args.packages:
        found = sorted(glob.glob(pattern))
        paths.extend(found or [pattern])
    if not paths:
        sys.stderr.write("nothing to check\n")
        return 2
    if shutil.which("rpm"):
        return with_system_rpm(paths)
    return without_rpm(paths)


if __name__ == "__main__":
    sys.exit(main())
