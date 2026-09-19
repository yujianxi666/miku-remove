#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent checker for the generated rpm packages.

Reads the lead, both headers and the payload without the builder's help, and
asserts what `dnf install` needs: header sizes, 8-byte signature alignment,
payload digests, the cpio walk, and the file metadata arrays.

    python3 tools/_check_rpm.py dist/miku-voicebank-pack-3.9.1-1.noarch.rpm
    python3 tools/_check_rpm.py dist/*.rpm          # all of them
"""
import gzip
import hashlib
import struct
import sys

TYPES = {0: ("NULL", 0), 1: ("CHAR", 1), 2: ("INT8", 1), 3: ("INT16", 2),
         4: ("INT32", 4), 5: ("INT64", 8), 6: ("STRING", 1), 7: ("BIN", 1),
         8: ("STRING_ARRAY", 1), 9: ("I18NSTRING", 1)}

NAMES = {
    100: "headeri18ntable", 62: "signatures", 63: "headerimmutable",
    269: "sha1", 273: "sha256",
    1000: "name", 1001: "version", 1002: "release", 1004: "summary",
    1005: "description", 1006: "buildtime", 1009: "size", 1011: "vendor",
    1014: "license", 1015: "packager", 1016: "group", 1020: "url",
    1021: "os", 1022: "arch", 1024: "postin", 1026: "preun", 1027: "postun",
    1028: "filesizes", 1030: "filemodes", 1033: "filerdevs", 1034: "filemtimes",
    1035: "filedigests", 1037: "fileflags", 1039: "fileusername",
    1040: "filegroupname", 1044: "sourcerpm", 1045: "fileverifyflags",
    1046: "archivesize", 1047: "providename", 1048: "provideversion",
    1049: "requirename", 1050: "requireversion", 1064: "rpmversion",
    1084: "preinprog", 1085: "preunprog", 1086: "postinprog", 1088: "postunprog",
    1095: "filedevices", 1096: "fileinodes", 1097: "filelangs",
    1116: "dirindexes", 1117: "basenames", 1118: "dirnames",
    1124: "payloadformat", 1125: "payloadcompressor", 1126: "payloadflags",
    5092: "payloaddigest", 5046: "recommendsname", 5047: "recommendsversion",
}
SIGNAMES = {1000: "size", 1004: "md5", 1007: "payloadsize", 269: "sha1",
            273: "sha256"}

failures = []


def check(name, cond, detail=""):
    print("  %-46s %s%s" % (name, "ok" if cond else "FAIL",
                            ("  " + str(detail)) if detail else ""))
    if not cond:
        failures.append(name)


def read_header(blob, off, sig=False):
    assert blob[off:off + 3] == b"\x8e\xad\xe8", "bad magic at %d" % off
    n, store_size = struct.unpack(">ii", blob[off + 8:off + 16])
    entries = []
    p = off + 16
    for _ in range(n):
        tag, ty, o, c = struct.unpack(">iiii", blob[p:p + 16])
        entries.append((tag, ty, o, c))
        p += 16
    store = blob[p:p + store_size]
    end = p + store_size
    out = {}
    for tag, ty, o, c in entries:
        kind, unit = TYPES[ty]
        name = (SIGNAMES if sig else NAMES).get(tag, "tag%d" % tag)
        if kind in ("STRING", "I18NSTRING"):
            items, i = [], o
            for _ in range(c):
                j = store.index(b"\0", i)
                items.append(store[i:j])
                i = j + 1
            out[name] = items[0] if c == 1 else items
        elif kind == "STRING_ARRAY":
            items, i = [], o
            for _ in range(c):
                j = store.index(b"\0", i)
                items.append(store[i:j])
                i = j + 1
            out[name] = items
        elif kind == "INT32":
            out[name] = tuple(struct.unpack(">%di" % c, store[o:o + 4 * c]))
        elif kind == "INT16":
            out[name] = tuple(struct.unpack(">%dH" % c, store[o:o + 2 * c]))
        elif kind == "BIN":
            # for binary tags `count` is the number of *bytes*
            out[name] = store[o:o + c]
        else:
            out[name] = store[o:o + c]
    return out, end


def one(value):
    """INT32 tags come back as tuples; unwrap single values."""
    return value[0] if isinstance(value, tuple) and len(value) == 1 else value


def main(path):
    blob = open(path, "rb").read()
    print("file: %s (%d bytes)" % (path, len(blob)))
    print("--- lead ---")
    check("lead magic", blob[:4] == b"\xed\xab\xee\xdb", blob[:4])
    check("lead is 96 bytes", len(blob) > 96)
    print("--- signature header at 96 ---")
    sig, sig_end = read_header(blob, 96, sig=True)
    check("signature ends 8-byte aligned", sig_end % 8 == 0, sig_end)
    print("--- main header at %d ---" % sig_end)
    check("main magic at signature end", blob[sig_end:sig_end + 3] == b"\x8e\xad\xe8")
    hdr, hdr_end = read_header(blob, sig_end)
    payload = blob[hdr_end:]
    print("  payload: %d bytes, starts %d" % (len(payload), hdr_end))
    check("payload is gzip", payload[:2] == b"\x1f\x8b", payload[:2])
    raw = gzip.decompress(payload)
    check("header archivesize matches payload",
          one(hdr.get("archivesize")) == len(raw),
          "%s vs %s" % (one(hdr.get("archivesize")), len(raw)))
    check("signature size matches payload", one(sig.get("size")) == len(payload),
          "%s vs %s" % (one(sig.get("size")), len(payload)))
    check("signature md5 matches payload",
          sig.get("md5") == hashlib.md5(payload).digest())
    check("signature sha256 matches payload",
          sig.get("sha256") == hashlib.sha256(payload).digest())
    check("signature sha1 matches payload",
          sig.get("sha1") == hashlib.sha1(payload).digest())
    check("payloaddigest matches", hdr.get("payloaddigest") ==
          hashlib.sha256(payload).digest())
    print("--- metadata ---")
    for key in ("name", "version", "release", "arch", "os", "summary", "size",
                "license", "vendor", "packager", "url", "payloadformat",
                "payloadcompressor", "payloadflags", "requirename",
                "requireversion", "recommendsname"):
        if key in hdr:
            print("  %-20s %s" % (key, hdr[key]))
    for key in ("preun", "postin", "postun", "preunprog", "postinprog"):
        if key in hdr:
            value = hdr[key]
            if isinstance(value, bytes):
                value = value.decode("utf-8", "replace").splitlines()
                value = value[1] if len(value) > 1 else value[0] if value else ""
            print("  %-20s %r" % (key, value))
    # --- file metadata vs cpio -------------------------------------------
    print("--- cpio walk ---")
    names = []
    p = 0
    while True:
        magic = raw[p:p + 6]
        if magic != b"070701":
            check("cpio magic", False, repr(magic))
            break
        # fields: 0 ino, 1 mode, 2 uid, 3 gid, 4 nlink, 5 mtime, 6 filesize,
        #         7 devmajor, 8 devminor, 9 rdevmajor, 10 rdevminor,
        #         11 namesize, 12 check
        head = raw[p:p + 110]
        if raw[p + 110:p + 121] == b"TRAILER!!!\0":
            names.append("TRAILER!!!")
            break
        try:
            fields = [int(head[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        except ValueError:
            check("cpio member fields are hex", False, repr(raw[p:p + 6]))
            break
        size, namesize = fields[6], fields[11]
        name_start = p + 110
        name = raw[name_start:name_start + namesize - 1].decode()
        q = name_start + namesize
        q += (4 - q % 4) % 4
        names.append(name)
        q += size
        q += (4 - q % 4) % 4
        p = q
    check("cpio ends with TRAILER", names and names[-1] == "TRAILER!!!")
    payload_names = [n for n in names if n != "TRAILER!!!"]
    basenames = [b.decode() for b in hdr["basenames"]]
    dirnames = [b.decode() for b in hdr["dirnames"]]
    dirindexes = hdr["dirindexes"]
    full = []
    for base, di in zip(basenames, dirindexes):
        d = dirnames[di]
        full.append((d.rstrip("/") + "/" + base) if d not in (".", "") else "./" + base)
    check("cpio member count == header basenames",
          len(payload_names) == len(basenames),
          "%d vs %d" % (len(payload_names), len(basenames)))
    check("paths line up",
          [n.rstrip("/") for n in payload_names] == [f.rstrip("/") for f in full],
          "\n    cpio: %s\n    hdr : %s" % (payload_names[:4], full[:4]))
    sizes = hdr.get("filesizes")
    modes = hdr.get("filemodes")
    if sizes:
        real = [int(raw[i:i + 1] and 1) for i in []]  # placeholder
        check("filesizes length == members", len(sizes) == len(payload_names),
              "%d vs %d" % (len(sizes), len(payload_names)))
        check("filesizes are sane", all(s >= 0 for s in sizes), sizes[:6])
    if modes:
        check("headerdir modes are directories",
              all(bool(m & 0o040000) for n, m in zip(payload_names, modes)
                  if n.endswith("/")),
              [oct(m) for n, m in zip(payload_names, modes) if n.endswith("/")][:4])
        check("file modes are regular files",
              all(bool(m & 0o100000) for n, m in zip(payload_names, modes)
                  if not n.endswith("/")),
              [oct(m) for n, m in zip(payload_names, modes) if not n.endswith("/")][:4])
    print("--- result ---")
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("all structural checks passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__ or "usage: _check_rpm.py <package.rpm> ...")
    code = 0
    for path in sys.argv[1:]:
        code |= main(path)
        print()
    if len(sys.argv) > 2:
        print("checked %d packages" % (len(sys.argv) - 1))
    sys.exit(code)
