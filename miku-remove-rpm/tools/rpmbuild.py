#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A minimal, dependency-free RPM writer — development reference only.

Production packages are written by **rpmbuild** (see tools/build_rpm.py): the
header/region/signature invariants below are subtle enough that rpm is the only
trustworthy judge of the result.  This module keeps a readable description of
the format (and can emit a package for inspection with `python3
tools/rpmbuild.py`), which is useful when reading a hex dump, but its output is
*not* accepted by rpm 6 - do not ship it.

What the format actually requires (learned the hard way from rpm 6.0.2):

  * the header magic is the four bytes `8e ad e8 01`; rpm compares all four, so a
    header written with version 0 fails as "hdr magic: BAD";
  * the signature header must be wrapped in a region: the first index entry is
    RPMTAG_HEADERSIGNATURES (62), type BIN, count 16 (REGION_TAG_COUNT), and the
    region trailer sits at `dl - 16` with count 16 and a negative offset of
    `-16 * entries` (rpm derives the region's index length from it);
  * every entry's offset must be a multiple of its type's alignment (4 for
    INT32), and the index has to stay sorted by tag after the region entry is
    prepended - rpm pairs entries with offsets by position;
  * the SHA1/SHA256 entries in the signature header are hex *strings* of the
    **main header** (magic + il + dl + index + store), not of the payload;
  * FILERDEVS is INT16, not INT32;
  * the region's data is walked with "length to the next offset" semantics, so
    there must be no stray padding between entries or before the trailer.

    rpm = Rpm(name="hello", version="1.0", release="1", summary="...",
              description="...", files=[RpmFile("/usr/bin/hello", data, 0o755)],
              requires=["/bin/sh"], scriptlets={"preun": "..."})
    open("hello-1.0-1.noarch.rpm", "wb").write(rpm.build())
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import struct
import time

LEAD_MAGIC = b"\xed\xab\xee\xdb"
HEADER_MAGIC = b"\x8e\xad\xe8"

# --- tag numbers (rpm 4.x) --------------------------------------------------
T_SIGNATURES = 62
T_HEADERIMMUTABLE = 63
T_HEADERI18NTABLE = 100

T_NAME = 1000
T_VERSION = 1001
T_RELEASE = 1002
T_SUMMARY = 1004
T_DESCRIPTION = 1005
T_SIZE = 1009
T_GROUP = 1016
T_OS = 1021
T_ARCH = 1022
T_FILESIZES = 1028
T_FILEMODES = 1030
T_FILERDEVS = 1033
T_FILEMTIMES = 1034
T_FILEDIGESTS = 1035
T_FILELINKTOS = 1036
T_FILEFLAGS = 1037
T_FILEUSERNAME = 1039
T_FILEGROUPNAME = 1040
T_SOURCERPM = 1044
T_FILEVERIFYFLAGS = 1045
T_ARCHIVESIZE = 1046
T_PROVIDENAME = 1047
T_PROVIDEVERSION = 1048
T_REQUIRENAME = 1049
T_REQUIREVERSION = 1050
T_RPMVERSION = 1064
T_HEADERSIGNATURES = 62        # region tag of the signature header
T_HEADERIMMUTABLE = 63         # region tag of the main header
T_LICENSE = 1014
T_VENDOR = 1011
T_PACKAGER = 1015
T_URL = 1020
T_RECOMMENDSNAME = 5046
T_RECOMMENDSVERSION = 5047
T_PAYLOADFORMAT = 1124
T_PAYLOADCOMPRESSOR = 1125
T_PAYLOADFLAGS = 1126
T_FILEDEVICES = 1095
T_FILEINODES = 1096
T_FILELANGS = 1097
T_DIRINDEXES = 1116
T_BASENAMES = 1117
T_DIRNAMES = 1118
T_PAYLOADDIGEST = 5092

# signature-area tags
S_SIZE = 1000
S_MD5 = 1004
S_PAYLOADSIZE = 1007
S_SHA1 = 269
S_SHA256 = 273

T_PREUN = 1026
T_POSTUN = 1027
T_PREUNPROG = 1085
T_POSTUNPROG = 1088
T_POSTIN = 1024
T_POSTINPROG = 1086
T_PREIN = 1023
T_PREINPROG = 1084

# entry types
T_NULL, T_CHAR, T_INT8, T_INT16, T_INT32, T_INT64 = 0, 1, 2, 3, 4, 5
T_STRING, T_BIN, T_STRING_ARRAY, T_I18NSTRING = 6, 7, 8, 9

DEFAULT_MTIME = 1234567890

#: how each rpm type has to be aligned inside the header store
#: (rpm's `typeAlign`: 1 for strings, 4 for INT32, 8 for INT64, ...)
_TYPE_ALIGN = {
    T_NULL: 1, T_CHAR: 1, 2: 1, T_INT16: 2, T_INT32: 4, 5: 8,
    T_STRING: 1, T_BIN: 1, T_STRING_ARRAY: 1, T_I18NSTRING: 1,
}


class RpmFile:
    """One file in the payload."""

    def __init__(self, path, data, mode=0o644, mtime=DEFAULT_MTIME,
                 user="root", group="root"):
        self.path = "/" + path.strip("/")
        self.data = data if isinstance(data, bytes) else data.encode("utf-8")
        self.mode = mode
        self.mtime = mtime
        self.user = user
        self.group = group


def _align8(n):
    return (n + 7) & ~7


class _Header:
    """Collects tags and serialises them as an rpm header structure.

    `region` wraps the header in an immutable region: the signature header *has*
    to be wrapped (rpm rejects a package whose signature has no region), and the
    main header is wrapped too, the way every real package is.
    """

    def __init__(self, region=False, signature=True):
        self.entries = {}
        self.region = region
        #: which region tag to use: 62 for the signature header, 63 for the
        #: main header's immutable region
        self.signature = signature
        self.region_tag = (T_HEADERSIGNATURES if signature
                           else T_HEADERIMMUTABLE)

    def add(self, tag, etype, values):
        if etype in (T_STRING, T_I18NSTRING, T_STRING_ARRAY):
            values = [v.decode("utf-8") if isinstance(v, bytes) else str(v)
                      for v in values]
        self.entries[tag] = (etype, list(values))
        return self

    def string(self, tag, value):
        return self.add(tag, T_STRING, [value])

    def i18n(self, tag, value):
        return self.add(tag, T_I18NSTRING, [value])

    def int32(self, tag, values):
        if not isinstance(values, (list, tuple)):
            values = [values]
        return self.add(tag, T_INT32, values)

    def int16(self, tag, values):
        if not isinstance(values, (list, tuple)):
            values = [values]
        return self.add(tag, T_INT16, values)

    def binary(self, tag, data):
        return self.add(tag, T_BIN, [data])

    def strings(self, tag, values):
        return self.add(tag, T_STRING_ARRAY, list(values))

    def align8(self):
        """Grow the store so the whole header is a multiple of 8 bytes.

        rpm wants the signature header to end on an 8-byte boundary.  The padding
        goes *inside* the store - bytes between the two headers would be read as
        the start of the next one - and with a region it goes in front of the
        trailer, which has to stay the last thing in the store.
        """
        pad = (-self.total_size()) % 8
        if pad:
            self._tail = getattr(self, "_tail", b"") + b"\0" * pad
        return self

    def total_size(self) -> int:
        """Bytes this header will occupy once serialised."""
        index_len = 16 * len(self.entries)
        if self.region:
            index_len += 16                     # the region entry itself
        fixed = 16 + index_len + (16 if self.region else 0)   # + the trailer
        return fixed + len(self._store_bytes())

    def compute_pad(self, want: int):
        """Grow the store so the serialised header is exactly `want` bytes."""
        pad = want - self.total_size()
        if pad < 0 or pad % 8:
            raise ValueError("header of %d bytes cannot reach %d"
                             % (self.total_size(), want))
        if pad:
            self._tail = getattr(self, "_tail", b"") + b"\0" * pad
        return self

    def _store_bytes(self):
        """The tag store, without the region trailer."""
        store = bytearray()
        for tag in sorted(self.entries):
            etype, values = self.entries[tag]
            if etype != T_NULL:
                store += self._store(etype, values)
        return bytes(store) + getattr(self, "_tail", b"")

    # -- serialisation ---------------------------------------------------
    # rpm header integers are big-endian ("network order"): `struct '!i'` in
    # rpm's own readers.  Getting this wrong yields a file that looks fine in a
    # hex dump but that no rpm tool will open.
    ENDIAN = ">"

    def _store(self, etype, values):
        if etype in (T_STRING, T_I18NSTRING):
            return ("".join(v + "\0" for v in values)).encode("utf-8")
        if etype == T_STRING_ARRAY:
            return ("".join(v + "\0" for v in values)).encode("utf-8")
        if etype == T_BIN:
            return b"".join(values)
        if etype == T_INT32:
            return b"".join(struct.pack(self.ENDIAN + "I", v & 0xFFFFFFFF)
                            for v in values)
        if etype == T_INT16:
            return b"".join(struct.pack(self.ENDIAN + "H", v & 0xFFFF)
                            for v in values)
        if etype == T_CHAR:
            return bytes(v & 0xFF for v in values)
        raise ValueError("entry type %d not supported" % etype)

    def _region_trailer(self, offset, nindex: int, store_size: int) -> bytes:
        """The 16-byte "region trailer" entry that closes the store.

        Both headers keep count == REGION_TAG_COUNT (16) and a negative offset of
        -16 * entries; the *region entry* is what differs between them (see
        `build`): rpm's verify pass wants 16 there, its import pass takes the
        region's data length from it.
        """
        del offset, store_size
        tag = self.region_tag
        return struct.pack(self.ENDIAN + "IiiI", tag, T_BIN,
                           -16 * nindex, 16)

    def build(self) -> bytes:
        """Serialise the header.

        The store is written in *tag order* and each entry's offset is the byte
        just written, so the offsets increase together with the tags and the data
        is contiguous.  rpm requires exactly that inside a region; a "packed"
        layout (data appended in whatever order, offsets pointing into the
        middle of other entries) fails its per-tag sanity check with

            tag[6]: BAD, tag 1009 type 4 offset 426 count 1 len 357
        """
        tags = sorted(self.entries)
        store = bytearray()
        index = []
        for tag in tags:
            etype, values = self.entries[tag]
            if etype != T_NULL:
                # rpm validates the offset of every entry against the type's
                # alignment (`hdrchkAlign`: offset must be a multiple of 4 for
                # an INT32, 2 for an INT16, ...).  A misaligned INT32 is
                # reported as "signature tag[2]: BAD, tag 1000 type 4 offset
                # 106 count 1 len 65", so pad up to the type's size.
                align = _TYPE_ALIGN.get(etype, 1)
                while len(store) % align:
                    store += b"\0"
            offset = len(store)
            if etype != T_NULL:
                chunk = self._store(etype, values)
                store += chunk
                # for binary tags rpm records the number of *bytes*, not the
                # number of items: a payload digest declared as count 1 gets
                # silently truncated to a single byte by every rpm reader
                count = len(chunk) if etype == T_BIN else len(values)
            else:
                count = len(values)
            index.append((tag, etype, offset, count))

        if self.region:
            # Wrap the header in an immutable region: the store is
            #     [tag data][region trailer]
            # with a region entry in front of the index.  rpm needs this on the
            # signature header, and its main-header bookkeeping assumes it too.
            #
            # The store is laid out so that every entry's data is followed
            # *immediately* by the next entry (and the last one by the trailer).
            # rpm walks the region in "fast" mode, where a string entry's length
            # is `next offset - this offset`, and it then demands
            #     sum(lengths) + 16 == header data length.
            # A stray padding byte between two entries, or between the last entry
            # and the trailer, breaks that sum and rpm reports either
            # "tag[N]: BAD ... len X" or "hdr load: BAD".  So the alignment
            # padding is written in front of the entry that needs it, and the
            # final block is padded by extending the last string's data.
            tag = self.region_tag
            tail = getattr(self, "_tail", b"")
            store += tail
            data_end = len(store) + 16               # the trailer goes last
            if data_end % 16:
                data_end += 16 - (data_end % 16)
            gap = data_end - 16 - len(store)
            if gap and index:
                store += b"\0" * gap
                last = index[-1]
                if last[1] in (T_STRING, T_STRING_ARRAY, T_I18NSTRING, T_BIN):
                    # the extra NULs are simply more string terminators, so the
                    # entry (and therefore the region total) still matches
                    index[-1] = (last[0], last[1], last[2], last[3] + gap)
            elif gap:
                store += b"\0" * gap
            trailer_at = data_end - 16
            store += self._region_trailer(trailer_at, len(index) + 1,
                                          trailer_at + 16)
            index.insert(0, (tag, T_BIN, trailer_at, 16))
            # rpm pairs index entries with store offsets *by position*, so after
            # prepending the region the rest has to go back into ascending tag
            # order - otherwise every tag gets the wrong offset and rpm reports
            # "signature tag[2]: BAD, tag 1000 type 4 offset 106 count 1 len 65".
            index[1:] = sorted(index[1:], key=lambda e: e[0])
        else:
            store += getattr(self, "_tail", b"")

        body = b"".join(struct.pack(self.ENDIAN + "IIII", *e) for e in index)
        # magic(3) + version(1) + reserved(4) + nindex(4) + storesize(4) = 16
        #
        # The version byte must be 1 in *both* headers: rpm's magic constant is
        # the four bytes 8e ad e8 01, and rpmReadHeader() compares four of them,
        # so a header written with version 0 is reported as
        #     "hdr magic: BAD"  /  "signature hdr magic: BAD"
        # even though the first three bytes look perfect in a hex dump.
        hdr = (HEADER_MAGIC + b"\x01" + b"\x00" * 4
               + struct.pack(self.ENDIAN + "II", len(index), len(store)))
        out = hdr + body + bytes(store)
        assert len(out) == 16 + 16 * len(index) + len(store), (len(out), len(store))
        return out


def cpio_newc(entries, align=4):
    """`entries` = [(name, data, mode, mtime, inode, is_dir, nlink)].

    newc has one 110-byte header: the 6-byte magic ``070701`` followed by
    thirteen 8-digit hex fields - ino, mode, uid, gid, nlink, mtime, filesize,
    devmajor, devminor, rdevmajor, rdevminor, namesize, check.  One extra field
    (or a missing one) makes the whole archive unreadable, so the field count is
    not a detail to get creative with.
    """

    def field(value, width=8):
        return ("%0*x" % (width, value)).encode("ascii")

    out = bytearray()
    for name, data, mode, mtime, inode, is_dir, nlink in entries:
        path = name.encode("utf-8") + (b"/" if is_dir else b"")
        body = b"" if is_dir else data
        out += (b"070701" + field(inode) + field(mode) + field(0) + field(0)
                + field(nlink) + field(mtime) + field(len(body)) + field(0)
                + field(0) + field(0) + field(0) + field(len(path) + 1)
                + field(0))
        out += path + b"\0"
        while len(out) % align:
            out += b"\0"
        if body:
            out += body
            while len(out) % align:
                out += b"\0"
    # trailer: same shape as a real member - magic + thirteen zero fields, then
    # the name.  Using twelve fields here would put "TRAILER!!!" eight bytes too
    # early and desynchronise every reader.
    out += (b"070701" + field(0) * 13) + b"TRAILER!!!\0"
    while len(out) % 512:
        out += b"\0"
    return bytes(out)


def _gzip(data, level=9, mtime=DEFAULT_MTIME):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level, mtime=mtime) as gz:
        gz.write(data)
    return buf.getvalue()


class Rpm:
    """One noarch rpm."""

    def __init__(self, name, version, release="1", summary="", description="",
                 license="CC-BY-SA-4.0", group="Applications/System", url="",
                 files=None, requires=None, provides=None, recommends=None,
                 scriptlets=None, arch="noarch", mtime=DEFAULT_MTIME,
                 vendor="", packager="", package_size=None):
        self.name = name
        self.version = version
        self.release = release
        self.summary = summary
        self.description = description
        self.license = license
        self.group = group
        self.url = url
        self.files = list(files or [])
        self.requires = list(requires or [])
        self.provides = list(provides or [])
        self.recommends = list(recommends or [])
        # scriptlet tag -> (interpreter, body); e.g. {"preun": ("/bin/sh", "...")}
        self.scriptlets = dict(scriptlets or {})
        self.arch = arch
        self.mtime = mtime
        self.vendor = vendor
        self.packager = packager
        # rpm has no Installed-Size field: `Size` is what dnf reports, normally
        # the sum of the payload.  The voicebank pretends to weigh gigabytes, so
        # the builder can override it.
        self.package_size = package_size

    # -- payload ---------------------------------------------------------
    def payload(self):
        """-> (cpio bytes, gzipped bytes, [(name, RpmFile or None)]).

        The third element is the payload order: directories (as None) first,
        then the files.  The header's file arrays must follow exactly this
        order, so it is returned rather than recomputed.
        """
        dirs, seen = [], set()
        for f in self.files:
            parent = os.path.dirname(f.path)
            while parent and parent != "/" and parent not in seen:
                seen.add(parent)
                dirs.append(parent)
                parent = os.path.dirname(parent)
        members = [("." + d, None) for d in dirs] + \
                  [("." + f.path, f) for f in self.files]
        entries = []
        for inode, (name, f) in enumerate(members, 1):
            if f is None:
                entries.append((name, b"", 0o40755, self.mtime, inode, True, 2))
            else:
                entries.append((name, f.data, 0o100000 | f.mode,
                                f.mtime, inode, False, 1))
        raw = cpio_newc(entries)
        return raw, _gzip(raw), members

    def build(self) -> bytes:
        raw_cpio, compressed, members = self.payload()

        # --- file metadata, in the same order as the payload ---------------
        # One entry per cpio member (directories included): every array below
        # must line up index-for-index with `members`, or rpm loses track of
        # which size/mode/digest belongs to which path.
        basenames, dirindexes = [], []
        sizes, modes, mtimes, digests, flags = [], [], [], [], []
        rdevs, inodes, devices, langs = [], [], [], []
        dirnames = ["."]
        for name, _f in members:
            d = os.path.dirname(name)
            if d not in dirnames:
                dirnames.append(d)
        for i, (name, f) in enumerate(members):
            basenames.append(os.path.basename(name))
            dirindexes.append(dirnames.index(os.path.dirname(name)))
            sizes.append(0 if f is None else len(f.data))
            modes.append(0o40755 if f is None else 0o100000 | f.mode)
            mtimes.append(self.mtime if f is None else f.mtime)
            digests.append("" if f is None else hashlib.md5(f.data).hexdigest())
            flags.append(0)
            rdevs.append(0)
            inodes.append(i + 1)
            devices.append(1)
            langs.append("")

        h = _Header(region=True, signature=False)
        h.i18n(T_HEADERI18NTABLE, "C")
        h.string(T_NAME, self.name)
        h.string(T_VERSION, self.version)
        h.string(T_RELEASE, self.release)
        h.i18n(T_SUMMARY, self.summary)
        h.i18n(T_DESCRIPTION, self.description)
        real_size = sum(len(f.data) for f in self.files)
        h.int32(T_SIZE, self.package_size or real_size)
        h.i18n(T_GROUP, self.group)
        h.string(T_LICENSE, self.license)
        h.string(T_URL, self.url)
        h.string(T_OS, "linux")
        h.string(T_ARCH, self.arch)
        h.string(T_VENDOR, self.vendor)
        h.string(T_PACKAGER, self.packager)
        h.string(T_RPMVERSION, "4.19.0")
        h.string(T_SOURCERPM, "%s-%s-%s.src.rpm" % (self.name, self.version, self.release))
        h.int32(T_ARCHIVESIZE, len(raw_cpio))
        h.string(T_PAYLOADFORMAT, "cpio")
        h.string(T_PAYLOADCOMPRESSOR, "gzip")
        h.string(T_PAYLOADFLAGS, "9")
        # (no RPMTAG_PAYLOADDIGEST here: rpm's own region walker flags the last
        # blob entry of an immutable region as "tag[40]: BAD ... len 2", and the
        # payload MD5 in the signature header already covers integrity.)

        names_all = [n for n, _ in members]
        h.strings(T_BASENAMES, basenames)
        h.strings(T_DIRNAMES, dirnames or ["/"])
        h.int32(T_DIRINDEXES, dirindexes)
        h.int32(T_FILESIZES, sizes)
        h.int16(T_FILEMODES, modes)
        h.int32(T_FILEMTIMES, mtimes)
        h.strings(T_FILEDIGESTS, digests)
        h.int32(T_FILEFLAGS, flags)
        h.strings(T_FILEUSERNAME, ["root"] * len(names_all))
        h.strings(T_FILEGROUPNAME, ["root"] * len(names_all))
        # FILERDEVS is an INT16 array (rpm's rpmtag.h), and the main header is
        # inside an immutable region, so the type is actually checked: writing it
        # as INT32 gets "tag[18]: BAD, tag 1033 type 4 offset ... count 5 len 10"
        h.int16(T_FILERDEVS, rdevs)
        h.int32(T_FILEINODES, inodes)
        h.int32(T_FILEDEVICES, devices)
        h.strings(T_FILELANGS, langs)

        if self.provides:
            h.strings(T_PROVIDENAME, self.provides)
            h.strings(T_PROVIDEVERSION, [self.version] * len(self.provides))
        if self.requires:
            h.strings(T_REQUIRENAME, self.requires)
            h.strings(T_REQUIREVERSION, [""] * len(self.requires))
        if self.recommends:
            h.strings(T_RECOMMENDSNAME, self.recommends)
            h.strings(T_RECOMMENDSVERSION, [""] * len(self.recommends))

        for key, (interp, body) in self.scriptlets.items():
            body = body.encode("utf-8") if not isinstance(body, bytes) else body
            if key == "preun":
                h.add(T_PREUN, T_STRING, [body])
                h.string(T_PREUNPROG, interp)
            elif key == "postun":
                h.add(T_POSTUN, T_STRING, [body])
                h.string(T_POSTUNPROG, interp)
            elif key == "post":
                h.add(T_POSTIN, T_STRING, [body])
                h.string(T_POSTINPROG, interp)
            elif key == "pre":
                h.add(T_PREIN, T_STRING, [body])
                h.string(T_PREINPROG, interp)
            else:
                raise ValueError("scriptlet %r not supported" % key)

        main = h.build()

        # --- signature header ---------------------------------------------
        # rpm's signature reader insists on the region wrapper: the header must
        # start with an RPMTAG_HEADERSIGNATURES entry whose negative-count
        # trailer closes the store.  Without it rpm says
        #     "signature hdr magic: BAD"  (or "region trailer: BAD")
        # and refuses the package, even though nm, file(1) and every
        # independent parser are perfectly happy with it.
        sig = _Header(region=True)
        # The SHA1/SHA256 entries in the signature header are digests of the
        # *main header*, not of the payload: rpm calls
        # `rpmvsInitRange(vs, RPMSIG_HEADER)` right after reading the signature
        # and then `hdrblobDigestUpdate(blob)` for the main header, and that
        # function hashes
        #     magic + il + dl + index + store
        # A wrong value here is reported as
        #     "Header SHA256 digest: BAD (package tag 273: invalid type 7)"
        # (type 7 = the binary blob this used to write instead of a hex string).
        sig.int32(S_SIZE, len(compressed))
        sig.binary(S_MD5, hashlib.md5(compressed).digest())
        sig.string(S_SHA1, hashlib.sha1(main).hexdigest())
        sig.string(S_SHA256, hashlib.sha256(main).hexdigest())
        sig.int32(S_PAYLOADSIZE, len(raw_cpio))
        sig.align8()
        lead = self._lead()
        sig_blob = sig.build()
        # The 96-byte lead sits in front of the signature header, so the header
        # itself may need one more whole 8-byte block to put `lead + signature`
        # on a multiple of 8.  That padding goes in front of the trailer, inside
        # the store.
        want = ((len(lead) + len(sig_blob) + 7) // 8 * 8) - len(lead)
        if want > len(sig_blob):
            sig.compute_pad(want)
            sig_blob = sig.build()
        assert (len(lead) + len(sig_blob)) % 8 == 0, "signature misaligned"
        return lead + sig_blob + main + compressed

    def _lead(self) -> bytes:
        # the lead is read with "!4sBBhh66shh16s" in rpm's own readers
        name = self.name.encode("ascii", "replace")[:65]
        parts = [
            LEAD_MAGIC,
            bytes([3, 0]),                     # rpm 3.0
            struct.pack(">H", 0),              # binary package
            struct.pack(">H", 255 if self.arch == "noarch" else 1),
            name + b"\0" * (66 - len(name)),
            struct.pack(">H", 1),              # linux
            struct.pack(">h", 5),              # signature type
            b"\0" * 16,
        ]
        return b"".join(parts)


def selftest():
    """Parse our own output back with the rpm reader if one is available."""
    import shutil
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp(prefix="rpm-selftest-")
    rpm = Rpm(name="miku-test", version="1.0", release="1", summary="test",
              description="a test package", files=[
                  RpmFile("/usr/share/miku-test/data.txt", b"hello\n", 0o644),
                  RpmFile("/usr/bin/miku-test", b"#!/bin/sh\necho hi\n", 0o755),
              ], requires=["/bin/sh"], scriptlets={"preun": ("/bin/sh", "exit 0\n")})
    path = os.path.join(tmp, "miku-test-1.0-1.noarch.rpm")
    with open(path, "wb") as f:
        f.write(rpm.build())
    print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))
    if shutil.which("rpm"):
        for args in (["-qpi", path], ["-qpl", path], ["-qp", "--scripts", path],
                     ["-qp", "--requires", path]):
            out = subprocess.run(["rpm"] + args, capture_output=True, text=True)
            print("$ rpm %s\n%s%s" % (" ".join(args), out.stdout, out.stderr))
    else:
        import struct as _s
        blob = open(path, "rb").read()
        print("lead magic ok:", blob[:4] == LEAD_MAGIC)
        hdr = blob[96:96 + 8 + 4 + 4 + 4 + 4 + 4 + 4]
        print("signature magic ok:", hdr[:3] == HEADER_MAGIC)
    import json
    print(json.dumps({"payload_raw": len(rpm.payload()[0]),
                      "payload_gz": len(rpm.payload()[1]),
                      "entries": len(rpm.payload()[2])}))


if __name__ == "__main__":
    selftest()
