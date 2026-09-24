#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the miku-voicebank-pack1..packN .rpm chain for Fedora / RHEL / openSUSE.

Same joke as the Debian packages, in the distribution's own format:

    sudo dnf remove miku-voicebank-pack

removes the base package, which takes the whole `Requires` chain with it, and
every package's `%preun` runs `miku-show --tick --index N`: the first one hands
the show to a background conductor, the rest each wait for their own moment in
the song, so one package really is erased every few seconds and dnf's progress
climbs with the lyrics instead of sitting at 0% for four minutes.

How the packages are written
----------------------------

The metadata and the payload (the show script, the lyric timeline, the fake
voicebank memory images) are assembled here in Python and handed to `rpmbuild`,
which writes the header and the signature.  That is the reliable way to produce a
package rpm accepts: the header/region/signature layout has a series of
invariants (region trailer counts, entry alignment, which digest covers what)
that are very easy to get subtly wrong by hand - tools/_check_rpm.py documents
them and is used to inspect the result.

`rpmbuild` is part of rpm-build:  sudo dnf install rpm-build

    python3 tools/build_rpm.py                       # 51 packages into dist/
    python3 tools/build_rpm.py --count 100
    python3 tools/build_rpm.py --audio-url https://example.com/song.mp3
    python3 tools/build_rpm.py --audio 初音ミクの消失.flac
    python3 tools/build_rpm.py --fake-size 0         # honest disk usage
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_DIR = os.path.dirname(HERE)                        # miku-remove-rpm/
ROOT = PACK_DIR
sys.path.insert(0, HERE)

import common    # noqa: E402  (this project's own payload helpers)
import profiles  # noqa: E402  (this project's own vocabulary)

SRC = common.SRC
DIST = os.path.join(PACK_DIR, "dist")

PROFILE = "rpm"                        # dnf / rpm wording in the transcript

VERSION = common.show_version()
PKG_BASE = "miku-voicebank-pack"       # the base package (no number)
MAINTAINER = "cosMo@暴走P <cosmo@bousou-p.invalid>"
HOMEPAGE = "https://www.bilibili.com/video/BV1zb8E6cE2a/"
LICENSE_TAG = "CC-BY-SA-4.0"
VENDOR = "miku-voicebank"

# The player is a *weak* dependency on purpose: `dnf remove` takes the whole
# dependency tree of a package with it, so a hard `Requires: mpv` would delete
# mpv (and its hundreds of multimedia libraries) along with the voicebank.
PLAYER_RECOMMENDS = ["mpv", "ffmpeg-free", "mpg123", "vlc", "pipewire-utils"]

# 5.4 GiB spread over the chain, so dnf reports the same number as apt does
FAKE_TOTAL_KIB = int(5.4 * 1024 * 1024)

SPEC_TEMPLATE = """\
Name:           {name}
Version:        {version}
Release:        1
Summary:        {summary}
License:        {license}
URL:            {url}
Vendor:         {vendor}
Packager:       {packager}
BuildArch:      noarch
{requires}{recommends}
%description
{description}

%prep

%build

%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}
cd %{{buildroot}}
tar xzf {payload}

{extra}
%files
{filelist}

%changelog
"""


def rpmbuild_path():
    return shutil.which("rpmbuild")


# --------------------------------------------------------------------------
# the payload every package carries
# --------------------------------------------------------------------------

def base_payload(args, audio_bytes, audio_name):
    """The files of the base package, as [(path, data, mode)]."""
    files = [
        ("usr/share/miku-voicebank/bin/miku-show", common.show_script(), 0o755),
        ("usr/share/miku-voicebank/bin/profiles.py",
         common.read_text(os.path.join(HERE, "profiles.py")), 0o644),
        ("usr/share/miku-voicebank/timeline.tsv",
         common.timeline_bytes(args.offset, args.profile), 0o644),
        ("usr/bin/miku-voicebank-show", common.wrapper_script(), 0o755),
        ("etc/miku-voicebank/show.conf",
         common.conf_text(audio_name if audio_bytes else "", args.audio_url,
                          args.profile), 0o644),
        ("usr/share/miku-voicebank/packs/pack0.dat",
         common.voicebank_dat(0, args.count), 0o644),
        ("usr/share/doc/%s/README.md" % PKG_BASE,
         common.read_text(os.path.join(SRC, "doc", "README.md")), 0o644),
        ("usr/share/doc/%s/copyright" % PKG_BASE,
         common.read_text(os.path.join(SRC, "doc", "copyright")), 0o644),
        ("usr/share/doc/%s/LICENSE" % PKG_BASE,
         common.read_text(os.path.join(SRC, "doc", "LICENSE")), 0o644),
    ]
    if audio_bytes:
        files.append(("usr/share/miku-voicebank/audio/" + audio_name,
                      audio_bytes, 0o644))
    for path, size, mode in common.MEMORY_FILES:
        files.append((path.strip("/"), common.memory_blob(path, size), mode))
    return files


def data_payload(index, count):
    return [("usr/share/miku-voicebank/packs/pack%d.dat" % index,
             common.voicebank_dat(index, count), 0o644)]


def payload_tarball(files, path):
    """A tar (not a package) that %install simply unpacks into the buildroot."""
    with tarfile.open(path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = common.MTIME
            tar.addfile(info, __import__("io").BytesIO(data))


# --------------------------------------------------------------------------
# scriptlets
# --------------------------------------------------------------------------

def scriptlet_preun(index, count):
    return """#!/bin/sh
# miku-voicebank - %preun
#
# 卸载时让声库唱完最后一首歌。每个包的 %preun 都会调用一次 miku-show：
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


def scriptlet_post(index, count):
    if index == 0:
        return """#!/bin/sh
# miku-voicebank-pack - %post
set -e
echo "[VOCALOID] 声库本体 miku-voicebank-pack (4.0) 已注册"
if [ -x /usr/share/miku-voicebank/bin/miku-show ]; then
    nohup /usr/share/miku-voicebank/bin/miku-show --fetch-audio --quiet \\
        >/dev/null 2>&1 &
fi
exit 0
"""
    if index == 1:
        return """#!/bin/sh
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
echo "[VOCALOID] 声库数据 pack{index} 已注册（{index}/{count}）"
exit 0
""".format(index=index, count=count)


# --------------------------------------------------------------------------
# one spec
# --------------------------------------------------------------------------

def spec_for(index, count, payload_tar, workdir, args):
    name = common.pkg_name(index)
    if index == 0:
        summary = "miku 4.0 voicebank (base package)"
        description = (
            "The voicebank itself: the singer, the removal sequence and the last "
            "song.\n\nRemoving this package removes every miku-voicebank-pack* "
            "data pack as well, then plays 初音ミクの消失 while the files are "
            "deleted.")
        requires = ["/bin/sh", "python3"]
        recommends = PLAYER_RECOMMENDS
        files = base_payload(args, args._audio_bytes, args._audio_name)
    else:
        summary = "miku 4.0 voicebank data pack (%d/%d)" % (index, count)
        description = common.DESC_TAIL.strip()
        requires = ["/bin/sh"]
        if index < count:
            requires.append("%s%d >= %s" % (PKG_BASE, index + 1, args.version))
        else:
            requires.append("%s >= %s" % (PKG_BASE, args.version))
        recommends = []
        files = data_payload(index, count)

    payload_tarball(files, payload_tar)

    # File list.  Only the directories this package actually creates are listed
    # (as %dir): owning /usr or /usr/bin makes the transaction fail with
    # "conflicts with file from package filesystem".
    paths = sorted(p for p, _d, _m in files)
    ours = set()
    for p in paths:
        parts = p.split("/")
        for i in range(2, len(parts)):          # skip the leading /usr, /etc, ...
            ours.add("/" + "/".join(parts[:i]))
    # ...but only those that are not shared with the base system
    shared = {"/usr", "/usr/bin", "/usr/share", "/usr/share/doc", "/etc"}
    lines = ["%dir " + d for d in sorted(ours - shared)]
    for p, _d, m in sorted(files):
        lines.append("%%attr(%04o, root, root) /%s" % (m, p) if m != 0o644
                     else "/" + p)
    filelist = "\n".join(lines)

    req = "".join("Requires:       %s\n" % r for r in dict.fromkeys(requires))
    rec = "".join("Recommends:     %s\n" % r for r in dict.fromkeys(recommends))
    spec = SPEC_TEMPLATE.format(
        name=name, version=args.version, summary=summary, license=LICENSE_TAG,
        url=HOMEPAGE, vendor=VENDOR, packager=MAINTAINER,
        requires=req, recommends=rec, description=description,
        payload=payload_tar, extra="", filelist=filelist)
    preun = scriptlet_preun(index, count)
    post = scriptlet_post(index, count)
    with open(os.path.join(workdir, "preun.sh"), "w") as f:
        f.write(preun)
    with open(os.path.join(workdir, "post.sh"), "w") as f:
        f.write(post)
    spec += "\n%preun -p /bin/sh\n" + preun + "\n%post -p /bin/sh\n" + post
    spec_path = os.path.join(workdir, "%s.spec" % name)
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec)
    return spec_path, name


def build_with_rpmbuild(args, count, out):
    topdir = tempfile.mkdtemp(prefix="miku-rpm-")
    for sub in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        os.makedirs(os.path.join(topdir, sub), exist_ok=True)
    total = 0
    try:
        for index in range(0, count + 1):
            workdir = tempfile.mkdtemp(prefix="miku-spec-", dir=topdir)
            payload_tar = os.path.join(workdir, "payload.tar.gz")
            spec_path, name = spec_for(index, count, payload_tar, workdir, args)
            res = subprocess.run(
                ["rpmbuild", "--define", "_topdir %s" % topdir,
                 "--define", "_rpmdir %s/RPMS" % topdir,
                 "--define", "_build_id_links none",
                 "--define", "buildroot %s/BUILDROOT/%s" % (topdir, name),
                 "-bb", spec_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if res.returncode != 0:
                sys.stderr.write(res.stdout.decode("utf-8", "replace"))
                return None
            moved = 0
            for root, _dirs, names in os.walk(os.path.join(topdir, "RPMS")):
                for n in names:
                    if n.startswith(name + "-") and n.endswith(".rpm"):
                        shutil.move(os.path.join(root, n),
                                    os.path.join(out, n))
                        moved += 1
            if not moved:
                sys.stderr.write("build_rpm: rpmbuild produced nothing for %s\n"
                                 % name)
                return None
            total += moved
            if not args.quiet:
                sys.stdout.write("\r  built %3d/%d  %s" %
                                 (index + 1, count + 1, name))
                sys.stdout.flush()
            shutil.rmtree(workdir, ignore_errors=True)
    finally:
        shutil.rmtree(topdir, ignore_errors=True)
    if not args.quiet:
        print()
    return total


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
    ap.add_argument("--profile", default=PROFILE,
                    help="package-manager vocabulary for the transcript")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.audio and not args.audio_url:
        default_song = os.path.join(ROOT, common.SONG_NAME)
        if os.path.isfile(default_song):
            args.audio = default_song
        else:
            sys.stderr.write("build_rpm: neither --audio nor --audio-url given\n")
            return 2

    args._audio_bytes = b""
    args._audio_name = ""
    if args.audio:
        if not os.path.isfile(args.audio):
            sys.stderr.write("build_rpm: song not found: %s\n" % args.audio)
            return 2
        args._audio_bytes = common.read(args.audio)
        args._audio_name = os.path.basename(args.audio)

    os.makedirs(args.out, exist_ok=True)
    builder = rpmbuild_path()
    if not builder:
        sys.stderr.write(
            "build_rpm: rpmbuild is required to write the packages.\n"
            "  Fedora/RHEL:  sudo dnf install rpm-build\n"
            "  openSUSE:     sudo zypper install rpm-build\n"
            "  Debian/Ubuntu (for cross-building):  sudo apt install rpm\n")
        return 2
    if not args.quiet:
        print("  rpmbuild: %s" % builder)

    total = build_with_rpmbuild(args, args.count, args.out)
    if total is None:
        return 1

    if not args.quiet:
        print("  %d packages (%s + pack1..pack%d), %.1f MiB total"
              % (total, PKG_BASE, args.count,
                 sum(os.path.getsize(os.path.join(args.out, f))
                     for f in os.listdir(args.out)) / 1048576))
        print("  chain: pack1 → … → pack%d → %s" % (args.count, PKG_BASE))
        print("  remove everything: sudo dnf remove %s" % PKG_BASE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
