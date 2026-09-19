#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the miku-voicebank-pack1..packN .rpm chain for Fedora / RHEL / openSUSE.

Same joke as the Debian packages, in the distribution's own format:

    sudo dnf remove miku-voicebank-pack

removes the base package, which takes the whole `Requires` chain with it, and
every package's `%preun` runs `miku-show --tick --index N`: the first one hands
the show to a background conductor, the rest each wait for their own moment in
the song.  One package really is erased every few seconds, so dnf's transaction
progress climbs with the lyrics instead of sitting at 0% for four minutes.

Pure stdlib: it writes the rpm itself (lead + signature header + header +
gzip'd cpio payload), so it builds on any machine with Python 3 - no rpmbuild,
no rpm, no Linux.

    python3 tools/build_rpm.py                       # 51 packages into dist/
    python3 tools/build_rpm.py --count 100
    python3 tools/build_rpm.py --audio-url https://example.com/song.mp3
    python3 tools/build_rpm.py --audio 初音ミクの消失.flac
    python3 tools/build_rpm.py --fake-size 0         # honest disk usage
"""

from __future__ import annotations

import argparse
import io
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_DIR = os.path.dirname(HERE)                        # miku-remove-rpm/
ROOT = PACK_DIR
sys.path.insert(0, HERE)

from rpmbuild import Rpm, RpmFile, DEFAULT_MTIME  # noqa: E402

import common    # noqa: E402  (this project's own payload helpers)
import profiles  # noqa: E402  (this project's own vocabulary)


SRC = common.SRC
DIST = os.path.join(PACK_DIR, "dist")

PROFILE = "rpm"                        # dnf / rpm wording in the transcript

VERSION = common.show_version()
PKG_BASE = "miku-voicebank-pack"       # the base package (no number)
PKG_DATA = "miku-voicebank-pack"       # packN = PKG_DATA + N
MAINTAINER = "cosMo@暴走P <cosmo@bousou-p.invalid>"
HOMEPAGE = "https://www.bilibili.com/video/BV1zb8E6cE2a/"
LICENSE_TAG = "MIT and see /usr/share/doc/%s/copyright" % PKG_BASE

# what the player needs to exist at runtime
PLAYER_REQUIRES = ["mpv"]
PLAYER_RECOMMENDS = ["ffmpeg-free", "mpg123", "vlc"]

# 5.4 GiB spread over the chain, so dnf reports the same number as apt does
FAKE_TOTAL_KIB = int(5.4 * 1024 * 1024)


def nvr(index: int) -> str:
    return "%s-%s-1" % (common.pkg_name(index), VERSION)


def scriptlet_preun(index: int, count: int) -> str:
    """The removal ritual, as a %preun scriptlet."""
    return """#!/bin/sh
# miku-voicebank-pack - %preun
#
# 卸载时让声库唱完最后一首歌。每个包的 %preun 都会调用一次 miku-show：
#
#   第一个包把演出丢到后台（conductor）开始放歌；
#   之后每个包只负责"等到歌曲里属于自己的那一刻"再返回 ——
#   于是 rpm 每隔几秒真的擦掉一个包，dnf 的进度条跟着歌词一点点涨，
#   而不是卡在 0% 四分钟再跳到 100%。
#
# {index} 是本包在链条里的名次（0 = 本体，一直等到整首歌唱完）。
set -e

if [ "$1" = "0" ] || [ "$1" = "remove" ]; then
    SHOW=/usr/share/miku-voicebank/bin/miku-show
    if [ -x "$SHOW" ]; then
        if command -v timeout >/dev/null 2>&1; then
            timeout 900 "$SHOW" --tick --index {index} --count {count} || true
        else
            "$SHOW" --tick --index {index} --count {count} || true
        fi
    fi
fi

exit 0
""".format(index=index, count=count)


def scriptlet_post(index: int, count: int) -> str:
    if index == 0:
        return """#!/bin/sh
# miku-voicebank-pack - %post
set -e

echo "[VOCALOID] 声库本体 miku-voicebank-pack (4.0) 已注册"
# 歌曲如果是从网络获取的，就在后台先抓下来，卸载时不用等网络
if [ -x /usr/share/miku-voicebank/bin/miku-show ]; then
    nohup /usr/share/miku-voicebank/bin/miku-show --fetch-audio --quiet \\
        >/dev/null 2>&1 &
fi
exit 0
"""
    if index == 1:
        return """#!/bin/sh
# miku-voicebank-pack1 - %post
cat <<'BANNER'

====================================
Top-level package installed (miku-voicebank-pack1)
Dependency chain: 1→2→3→…→{count}→miku-voicebank-pack
Removing miku-voicebank-pack removes the whole voicebank.
====================================
BANNER
exit 0
""".format(count=count)
    return """#!/bin/sh
# miku-voicebank-pack{index} - %post
echo "[VOCALOID] 声库数据 pack{index} 已注册（{index}/{count}）"
exit 0
""".format(index=index, count=count)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=common.PACK_COUNT)
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--out", default=DIST)
    ap.add_argument("--audio", default="",
                    help="local song file to ship inside the base package")
    ap.add_argument("--audio-url", default=common.DEFAULT_AUDIO_URL,
                    help="...or fetch the song from this URL at removal time")
    ap.add_argument("--offset", type=float, default=common.AUDIO_OFFSET)
    ap.add_argument("--fake-size", type=float, default=5.4,
                    help="GiB dnf should *claim* it frees (0 = be honest)")
    ap.add_argument("--vendor", default="miku-voicebank")
    ap.add_argument("--profile", default=PROFILE,
                    help="package-manager vocabulary for the transcript "
                         "(deb | rpm | pacman)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.audio and not args.audio_url:
        default_song = os.path.join(ROOT, common.SONG_NAME)
        if os.path.isfile(default_song):
            args.audio = default_song
        else:
            sys.stderr.write("build_rpm: neither --audio nor --audio-url given\n")
            return 2

    audio_bytes = b""
    audio_name = ""
    if args.audio:
        if not os.path.isfile(args.audio):
            sys.stderr.write("build_rpm: song not found: %s\n" % args.audio)
            return 2
        audio_bytes = common.read(args.audio)
        audio_name = os.path.basename(args.audio)

    timeline = common.timeline_bytes(args.offset, args.profile)
    conf = common.conf_text(audio_name if audio_bytes else "", args.audio_url,
                            args.profile)
    postrm = common.read_text(os.path.join(SRC, "maintainer", "postrm"))
    readme = common.read_text(os.path.join(SRC, "doc", "README.md"))
    copyright_text = common.read_text(os.path.join(SRC, "doc", "copyright"))
    vocab = common.read_text(os.path.join(HERE, "profiles.py"))

    bases = [common.show_script(), common.wrapper_script()]

    os.makedirs(args.out, exist_ok=True)
    fake_total = int(args.fake_size * 1024 * 1024)
    per_fake = fake_total // (args.count + 1)
    total_bytes = 0

    for index in range(0, args.count + 1):
        files = []
        if index == 0:
            files.append(RpmFile("/usr/share/miku-voicebank/bin/miku-show",
                                 bases[0], 0o755))
            files.append(RpmFile("/usr/share/miku-voicebank/bin/profiles.py",
                                 vocab, 0o644))
            files.append(RpmFile("/usr/share/miku-voicebank/timeline.tsv",
                                 timeline, 0o644))
            if audio_bytes:
                files.append(RpmFile(
                    "/usr/share/miku-voicebank/audio/" + audio_name,
                    audio_bytes, 0o644))
            files.append(RpmFile("/usr/bin/miku-voicebank-show",
                                 bases[1], 0o755))
            files.append(RpmFile("/etc/miku-voicebank/show.conf", conf, 0o644))
            files.append(RpmFile(
                "/usr/share/miku-voicebank/packs/pack0.dat",
                common.voicebank_dat(0, args.count), 0o644))
            for name, size, mode in common.MEMORY_FILES:
                files.append(RpmFile(name, common.memory_blob(name, size), mode))
            files.append(RpmFile("/usr/share/doc/%s/README.md" % PKG_BASE,
                                 readme, 0o644))
            files.append(RpmFile("/usr/share/doc/%s/copyright" % PKG_BASE,
                                 copyright_text, 0o644))
            requires = ["python3", "/bin/sh"]
            recommends = PLAYER_REQUIRES + PLAYER_RECOMMENDS
            summary = "miku 4.0 voicebank (base package)"
            description = (
                "The voicebank itself: the singer, the removal sequence and the "
                "last song.\n\n"
                "Removing this package removes every miku-voicebank-pack* data "
                "pack as well, then plays 初音ミクの消失 while the files are "
                "deleted.")
        else:
            files.append(RpmFile(
                "/usr/share/miku-voicebank/packs/pack%d.dat" % index,
                common.voicebank_dat(index, args.count), 0o644))
            requires = ["/bin/sh"]
            if index < args.count:
                requires.append("%s%d >= %s" % (PKG_DATA, index + 1, VERSION))
            else:
                requires.append("%s >= %s" % (PKG_BASE, VERSION))
            recommends = []
            summary = "miku 4.0 voicebank data pack (%d/%d)" % (index, args.count)
            description = common.DESC_TAIL

        size_kib = per_fake + sum(len(f.data) for f in files) // 1024 + 4

        rpm = Rpm(
            name=common.pkg_name(index),
            version=args.version,
            release="1",
            summary=summary,
            description=description,
            license=LICENSE_TAG,
            url=HOMEPAGE,
            files=files,
            requires=requires,
            recommends=recommends,
            scriptlets={
                "preun": ("/bin/sh", scriptlet_preun(index, args.count)),
                "post": ("/bin/sh", scriptlet_post(index, args.count)),
            },
            vendor=args.vendor,
            packager=MAINTAINER,
            mtime=DEFAULT_MTIME,
            package_size=size_kib * 1024,
        )
        data = rpm.build()

        name = "%s-%s-1.noarch.rpm" % (common.pkg_name(index), args.version)
        with open(os.path.join(args.out, name), "wb") as f:
            f.write(data)
        total_bytes += len(data)
        if not args.quiet:
            sys.stdout.write("\r  built %3d/%d  %-46s %8.1f KiB"
                             % (index + 1, args.count + 1, name, len(data) / 1024))
            sys.stdout.flush()

    if not args.quiet:
        print("\n  %d packages (%s + pack1..pack%d), %.1f MiB total"
              % (args.count + 1, PKG_BASE, args.count, total_bytes / 1048576))
        print("  chain: pack1 → … → pack%d → %s" % (args.count, PKG_BASE))
        print("  remove everything: sudo dnf remove %s" % PKG_BASE)
        print("  -> install with:   sudo dnf install ./dist/*.rpm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
