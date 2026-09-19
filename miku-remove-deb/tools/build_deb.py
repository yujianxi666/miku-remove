#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the miku-voicebank-pack1..packN .deb chain.

Pure stdlib: no dpkg, no ar, no tar binary - it writes the ar archive and the
control/data tarballs itself, so the packages can be built on Windows too.

    python3 tools/build_deb.py                       # 51 packages into dist/
    python3 tools/build_deb.py --count 100           # the "1→2→…→100" variant
    python3 tools/build_deb.py --fake-size 0         # honest disk usage
    python3 tools/build_deb.py --audio path/to.flac  # ship another recording

The chain is:  pack1 Depends pack2 Depends ... Depends packN
so `apt install ~/test/*.deb` installs all of them in one go, and
`apt remove miku-voicebank-packN` takes the whole chain down with it -
at which point pack1's prerm plays the song and prints the lyrics.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import random
import re
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import common  # noqa: E402  (this project's own payload helpers)

SHOW_SCRIPT = os.path.join(SRC, "bin", "miku-show")


def show_version(default="3.9.0") -> str:
    """The version miku-show reports, so the packages and the show agree."""
    try:
        with open(SHOW_SCRIPT, "r", encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else default
    except OSError:
        return default


VERSION = show_version()
PKG_BASE = "miku-voicebank-pack"
MAINTAINER = "cosMo@暴走P <cosmo@bousou-p.invalid>"
HOMEPAGE = "https://www.bilibili.com/video/BV1zb8E6cE2a/"
MTIME = 1234567890            # fixed, so builds are reproducible
SHARE = "/usr/share/miku-voicebank"
SONG_NAME = "初音ミクの消失.flac"

# Where the shipped package should fetch the song from when no local audio file
# is bundled.  tools/make_github_release.py rewrites DEFAULT_URL for releases.
DEFAULT_URL = "https://fms.uiero.com/downloads/mkrm.mp3"
DEFAULT_AUDIO_URL = os.environ.get("MIKU_AUDIO_URL", DEFAULT_URL)

# 5.4 GiB, exactly what the video's apt reports.  Spread over the chain so the
# dependency list looks like a real voicebank instead of 51 empty packages.
FAKE_TOTAL_KIB = int(5.4 * 1024 * 1024)

KANA = ("あ い う え お か き く け こ さ し す せ そ た ち つ て と な に ぬ ね の "
        "は ひ ふ へ ほ ま み む め も や ゆ よ ら り る れ ろ わ を ん "
        "が ぎ ぐ げ ご ざ じ ず ぜ ぞ だ ぢ づ で ど ば び ぶ べ ぼ ぱ ぴ ぷ ぺ ぽ "
        "きゃ きゅ きょ しゃ しゅ しょ ちゃ ちゅ ちょ にゃ にゅ にょ りゃ りゅ りょ "
        "ヴ ファ フィ フェ フォ ティ ディ ツィ").split()


# --------------------------------------------------------------------------
# archive writing
# --------------------------------------------------------------------------

def ar(members) -> bytes:
    """Classic Unix ar archive, the way dpkg-deb writes .deb files."""
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = ("%-16s%-12d%-6d%-6d%-8o%-10d`\n"
                  % (name[:16], MTIME, 0, 0, 0o100644, len(data))).encode("ascii")
        assert len(header) == 60, len(header)
        out += header
        out += data
        if len(data) % 2:
            out += b"\n"
    return bytes(out)


def tar_gz(files, dirs, level=9) -> bytes:
    """tar.gz with ./ prefixed names, root ownership and even padding."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for d in sorted(dirs):
            info = tarfile.TarInfo("./" + d.strip("/") + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = MTIME
            tar.addfile(info)
        for path, data, mode in files:
            info = tarfile.TarInfo("./" + path.strip("/"))
            info.size = len(data)
            info.mode = mode
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = MTIME
            tar.addfile(info, io.BytesIO(data))
    body = raw.getvalue()
    packed = io.BytesIO()
    with gzip.GzipFile(fileobj=packed, mode="wb", compresslevel=level, mtime=MTIME) as gz:
        gz.write(body)
    return packed.getvalue()


def add_parents(paths, dirs):
    for p in paths:
        parts = p.strip("/").split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))


def md5sums(files) -> bytes:
    lines = []
    for path, data, _mode in sorted(files):
        lines.append("%s  %s" % (hashlib.md5(data).hexdigest(), path.strip("/")))
    return ("\n".join(lines) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# package payloads
# --------------------------------------------------------------------------

def voicebank_dat(index: int, count: int) -> bytes:
    """A plausible-looking slab of voicebank sample data."""
    rnd = random.Random(0xC05 + index)
    out = []
    out.append("# miku-voicebank-pack%d  (%d/%d)" % (index, index, count))
    out.append("# bank    : miku 4.0 (CV)")
    out.append("# format  : 44.1 kHz / 16 bit / mono / RAW+FRQ")
    out.append("# samples : %d" % (110 + index * 7))
    out.append("#")
    for i in range(110 + index * 7):
        syl = rnd.choice(KANA)
        dur = rnd.uniform(0.08, 0.62)
        size = int(dur * 88200)
        freq = rnd.choice((440.0, 466.2, 493.9, 523.3, 554.4, 587.3, 622.3, 659.3))
        out.append("%s_%03d.wav\t%.3f s\t%7d B\t%.1f Hz\t%s"
                   % (syl, i, dur, size, freq, rnd.choice(("frq", "raw", "raw+frq"))))
    return ("\n".join(out) + "\n").encode("utf-8")


def memory_blob(name: str, size: int, seed: int) -> bytes:
    rnd = random.Random(seed)
    head = ("MIKU-MEMORY-IMAGE\t%s\tmiku 4.0\t--nosave\n" % name).encode("utf-8")
    body = bytes(rnd.getrandbits(8) for _ in range(max(0, size - len(head))))
    return head + body


def render(text: str, index: int, count: int) -> bytes:
    return (text.replace("__INDEX__", str(index))
                .replace("__COUNT__", str(count))
                .replace("__BASE__", "1" if index == 0 else "0")
                .encode("utf-8"))


# --------------------------------------------------------------------------
# one package
# --------------------------------------------------------------------------

def control_text(index: int, count: int, installed_kb: int, description: str) -> bytes:
    """index 0 = the base package (`miku-voicebank-pack`), 1..count = the chain."""
    if index:
        name = "%s%d" % (PKG_BASE, index)
    else:
        name = PKG_BASE.rstrip("-")            # -> miku-voicebank-pack
    fields = [
        "Package: %s" % name,
        "Version: %s" % VERSION,
        "Architecture: all",
        "Maintainer: %s" % MAINTAINER,
        "Installed-Size: %d" % installed_kb,
        "Section: sound",
        "Priority: optional",
        "Homepage: %s" % HOMEPAGE,
    ]
    if index == 0:
        # the base holds the show itself; everything else depends on it
        fields.append("Depends: python3")
        fields.append("Recommends: mpv | ffmpeg | mpg123 | vlc-bin | "
                      "pipewire-bin | pulseaudio-utils | alsa-utils | sox")
        fields.append("Suggests: mpv")
    elif index < count:
        fields.append("Depends: %s%d (>= %s)" % (PKG_BASE, index + 1, VERSION))
    else:
        fields.append("Depends: %s (>= %s)" % (PKG_BASE.rstrip("-"), VERSION))
    if index == 0:
        fields.append("Description: miku 4.0 voicebank (base package)")
    else:
        fields.append("Description: miku 4.0 voicebank data pack (%d/%d)" % (index, count))
    for line in description.strip("\n").split("\n"):
        fields.append((" " + line) if line else " .")
    return ("\n".join(fields) + "\n").encode("utf-8")


DESC_TAIL = """
Hatsune Miku voicebank sample data, split over a dependency chain so that the
engine can stream it while it is being registered.
.
Everything depends on the base package `miku-voicebank-pack`, so removing that
one package takes the whole voicebank down with it.  Doing so invokes the
VOCALOID uninstaller, which is known to be a little dramatic about it.
"""

DESC_VOICE = """
The voicebank itself: the singer, the removal sequence and the last song.
.
Removing this package removes every miku-voicebank-pack* data pack as well,
then plays 初音ミクの消失 while the files are deleted.
"""


def build_package(index: int, count: int, audio_path, payload: dict,
                  fake_kib: int, real_kb: int) -> bytes:
    """index 0 = base package (payload), 1..count = numbered data packs."""
    files = []
    dirs = set()

    # --- data.tar ------------------------------------------------------
    if index == 0:
        files.append(("usr/share/miku-voicebank/bin/miku-show",
                      payload["show"], 0o755))
        files.append(("usr/share/miku-voicebank/bin/profiles.py",
                      payload["profiles"], 0o644))
        files.append(("usr/share/miku-voicebank/timeline.tsv",
                      payload["timeline"], 0o644))
        if payload.get("audio"):
            files.append(("usr/share/miku-voicebank/audio/" + payload["audio_name"],
                          payload["audio"], 0o644))
        files.append(("usr/bin/miku-voicebank-show", payload["wrapper"], 0o755))
        files.append(("etc/miku-voicebank/show.conf", payload["conf"], 0o644))
        for name, size, mode in (
                ("/usr/share/vocaloid/models/memory/r.-1.2.img", 5120, 0o644),
                ("/usr/share/vocaloid/models/memory/r.0.-1.img", 6144, 0o644),
                ("/usr/share/vocaloid/models/memory/r.0.0.img", 7168, 0o644),
                ("/usr/share/vocaloid/models/memory/r.0.1.img", 4096, 0o644),
                ("/usr/share/vocaloid/models/memory/r.1.-2.img", 5632, 0o644),
                ("/usr/share/vocaloid/models/memory/r.1.-3.img", 4608, 0o644),
                ("/usr/share/vocaloid/models/memory/user.img", 2048, 0o444),
                ("/usr/share/vocaloid/models/blobs/r.-1.2.img", 8192, 0o644),
        ):
            # a stable seed: hash() is randomised per process, which would make
            # two builds of the same package differ byte for byte
            seed = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
            files.append((name.strip("/"), memory_blob(os.path.basename(name), size,
                                                       seed), mode))
        files.append(("usr/share/doc/%s/README.md" % PKG_BASE.rstrip("-"),
                      payload["readme"], 0o644))
        files.append(("usr/share/doc/%s/copyright" % PKG_BASE.rstrip("-"),
                      payload["copyright"], 0o644))
    else:
        files.append(("usr/share/miku-voicebank/packs/pack%d.dat" % index,
                      voicebank_dat(index, count), 0o644))

    add_parents([f[0] for f in files], dirs)

    # --- control.tar ---------------------------------------------------
    scripts = payload["scripts"](index, count)
    desc = DESC_VOICE if index == 0 else DESC_TAIL
    ctrl = [("control", control_text(index, count, real_kb + fake_kib, desc), 0o644),
            ("md5sums", md5sums(files), 0o644)]
    for name, data in scripts.items():
        ctrl.append((name, data, 0o755))
    if index == 0:
        ctrl.append(("conffiles", b"/etc/miku-voicebank/show.conf\n", 0o644))

    cd = set()
    add_parents([c[0] for c in ctrl], cd)

    return ar([("debian-binary", b"2.0\n"),
               ("control.tar.gz", tar_gz(ctrl, cd, level=9)),
               ("data.tar.gz", tar_gz(files, dirs, level=1))])


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str) -> bytes:
    """Read a file that ends up in the .deb as text, and force LF.

    Maintainer scripts and the show script are executed by dpkg on Linux; a
    stray CR (Windows checkout without .gitattributes, editor set to CRLF)
    turns them into "bad interpreter: /bin/sh^M".  Normalising here means the
    packages are correct no matter how the source tree was checked out.
    """
    return read(path).replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def main() -> int:
    global VERSION
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=51, help="packages in the chain")
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--out", default=DIST)
    ap.add_argument("--audio", default="",
                    help="local song file to ship inside pack1 (optional)")
    ap.add_argument("--audio-url", default=DEFAULT_AUDIO_URL,
                    help="...or fetch the song from this URL at install/removal time")
    ap.add_argument("--timeline", default=os.path.join(SRC, "data", "timeline.tsv"))
    ap.add_argument("--srt", default=os.path.join(ROOT, "miku-remove.srt"),
                    help="regenerate the timeline from this subtitle file if it exists")
    ap.add_argument("--offset", type=float, default=25.6,
                    help="lyric alignment offset for the shipped recording")
    ap.add_argument("--fake-size", type=float, default=5.4,
                    help="GiB apt should *claim* it frees (0 = be honest)")
    ap.add_argument("--profile", default="deb",
                    help="package-manager vocabulary for the transcript "
                         "(deb | rpm | pacman)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    VERSION = args.version

    if not args.audio and not args.audio_url:
        default_song = os.path.join(ROOT, SONG_NAME)
        if os.path.isfile(default_song):
            args.audio = default_song
        else:
            sys.stderr.write("build_deb: neither --audio nor --audio-url given\n")
            return 2

    audio_bytes = b""
    audio_name = ""
    if args.audio:
        if not os.path.isfile(args.audio):
            sys.stderr.write("build_deb: song not found: %s\n" % args.audio)
            return 2
        audio_bytes = read(args.audio)
        audio_name = os.path.basename(args.audio)

    # the timeline either comes from the SRT or is taken as it is (a source
    # checkout of the GitHub release ships the generated file, not the SRT)
    timeline = b""
    if os.path.isfile(args.srt):
        timeline = common.timeline_bytes(args.offset, args.profile)
    elif os.path.isfile(args.timeline):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import profiles  # noqa: E402
        prof = profiles.get(args.profile)
        raw = read(args.timeline).decode("utf-8")
        out = []
        for line in raw.splitlines():
            if not line or line.startswith("#"):
                out.append(line)
            else:
                out.append(profiles.expand_line(line, prof))
        timeline = ("\n".join(out) + "\n").encode("utf-8")
    else:
        sys.stderr.write("build_deb: no timeline (need --srt or --timeline)\n")
        return 2

    conf = read_text(os.path.join(SRC, "etc", "show.conf")).decode("utf-8")
    conf = conf.replace("__AUDIO__",
                        ("/usr/share/miku-voicebank/audio/" + audio_name) if audio_bytes else "")
    conf = conf.replace("__AUDIO_URL__", args.audio_url or "")
    conf = conf.replace("__PROFILE__", args.profile)

    prerm = read_text(os.path.join(SRC, "maintainer", "prerm")).decode("utf-8")
    postrm = read_text(os.path.join(SRC, "maintainer", "postrm"))
    postinst_src = read_text(os.path.join(SRC, "maintainer", "postinst")).decode("utf-8")

    payload = {
        "show": read_text(os.path.join(SRC, "bin", "miku-show")),
        "profiles": read_text(os.path.join(ROOT, "tools", "profiles.py")),
        "wrapper": read_text(os.path.join(SRC, "bin", "miku-voicebank-show")),
        "conf": conf.encode("utf-8"),
        "timeline": timeline,
        "audio": audio_bytes,
        "audio_name": audio_name,
        "readme": read_text(os.path.join(SRC, "doc", "README.md")) if
        os.path.isfile(os.path.join(SRC, "doc", "README.md")) else b"",
        "copyright": read_text(os.path.join(SRC, "doc", "copyright")),
        "scripts": lambda i, c: {
            "prerm": render(prerm, i, c),
            "postrm": postrm,
            "postinst": render(postinst_src, i, c),
        },
    }

    os.makedirs(args.out, exist_ok=True)
    fake_total = int(args.fake_size * 1024 * 1024)
    per_fake = fake_total // (args.count + 1)

    base_real_kb = (len(payload["show"]) + len(payload["timeline"]) +
                    len(payload["conf"]) + len(audio_bytes) + 4096) // 1024
    plan = [(0, base_real_kb)]
    plan += [(i, (len(voicebank_dat(i, args.count)) + 1023) // 1024)
             for i in range(1, args.count + 1)]

    total_bytes = 0
    for n, (index, real_kb) in enumerate(plan, 1):
        data = build_package(index, args.count, args.audio, payload,
                             per_fake, real_kb)
        name = ("%s_%s_all.deb" % (PKG_BASE.rstrip("-"), VERSION) if index == 0
                else "%s%d_%s_all.deb" % (PKG_BASE, index, VERSION))
        with open(os.path.join(args.out, name), "wb") as f:
            f.write(data)
        total_bytes += len(data)
        if not args.quiet:
            sys.stdout.write("\r  built %3d/%d  %-46s %8.1f KiB"
                             % (n, len(plan), name, len(data) / 1024))
            sys.stdout.flush()
    if not args.quiet:
        print("\n  %d packages (%s + pack1..pack%d), %.1f MiB total"
              % (len(plan), PKG_BASE.rstrip("-"), args.count, total_bytes / 1048576))
        print("  chain: pack1 → … → pack%d → %s" % (args.count, PKG_BASE.rstrip("-")))
        print("  fake Installed-Size: %.2f GiB" % (fake_total / 1024 / 1024))
        print("  uninstall everything: sudo apt remove %s" % PKG_BASE.rstrip("-"))
        print("  -> copy dist/*.deb to a Linux box and: sudo apt install ~/test/*.deb")
    return 0


if __name__ == "__main__":
    sys.exit(main())
