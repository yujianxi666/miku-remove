#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-derive the lyric alignment offset for a recording.

If you swap in another audio file, the lyrics have to be shifted so that the
SRT's song timeline lands on the recording's own timeline.  This finds the
moment the music drops in (the SRT's song starts where the deletion starts,
i.e. where the accompaniment kicks in) and reports the offset to hand to
tools/make_timeline.py --offset.

    python3 tools/audio_profile.py 初音ミクの消失.flac
    python3 tools/audio_profile.py song.wav --res 5

A .flac input is decoded with `flac -d` or `ffmpeg` if either is installed;
anything else is read with the stdlib wave module.  Stdlib only otherwise.
"""

from __future__ import annotations

import argparse
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

# the SRT's own numbers (see tools/make_timeline.py)
SONG_SPAN = 279.816 - 30.583      # how long the removal lasts in the source video


def decode(path: str) -> str:
    """Return a WAV path for `path`, decoding it first if needed."""
    if path.lower().endswith(".wav"):
        return path
    tmp = os.path.join(tempfile.gettempdir(), "miku-align.wav")
    if shutil.which("flac"):
        cmd = ["flac", "-d", "-s", "-f", "-o", tmp, path]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, tmp]
    else:
        sys.exit("需要 flac 或 ffmpeg 来解码 %s（或先自己转成 wav）" % os.path.basename(path))
    print("decoding with %s ..." % cmd[0])
    subprocess.run(cmd, check=True)
    return tmp


def profile(path: str, hop_s: float = 0.1):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    a = array.array("h")
    a.frombytes(raw)
    if ch == 2:
        mono = [(a[2 * i] + a[2 * i + 1]) * 0.5 for i in range(n)]
    else:
        mono = list(a)
    hop = int(sr * hop_s)
    rms = []
    for i in range(0, len(mono) - hop, hop):
        seg = mono[i:i + hop]
        rms.append((sum(v * v for v in seg) / len(seg)) ** 0.5)
    return rms, hop_s, n / sr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("--res", type=float, default=5.0, help="profile resolution (seconds)")
    ap.add_argument("--drop-search", type=float, default=60.0,
                    help="only look for the drop in the first N seconds")
    args = ap.parse_args()

    wav = decode(args.audio)
    rms, hop, dur = profile(wav)
    peak = max(rms) or 1.0
    db = [20 * math.log10(max(v, 1e-9) / peak) for v in rms]

    per = max(1, int(round(args.res / hop)))
    print("file: %s  (%.1f s)" % (args.audio, dur))
    print("\n=== level profile (%.0f s bins) ===" % args.res)
    for i in range(0, len(db) - per, per):
        seg = db[i:i + per]
        mean = sum(seg) / len(seg)
        t = i * hop
        print("%3d:%02d %7.1f dB %s" % (int(t // 60), int(t % 60), mean,
                                        "#" * int(max(0.0, (mean + 60) / 60 * 40))))

    # the drop: the largest single-step jump out of a quiet passage
    limit = int(args.drop_search / hop)
    best, best_i = 0.0, None
    for i in range(1, min(limit, len(db))):
        jump = db[i] - min(db[max(0, i - 20):i])
        if jump > best:
            best, best_i = jump, i
    drop = best_i * hop if best_i else 0.0
    print("\n=== landmarks ===")
    print("  beat drop            : %.2f s  (+%.1f dB)" % (drop, best))
    last = None
    for i in range(len(db) - 1, -1, -1):
        if db[i] > -35:
            last = i * hop
            break
    print("  music ends           : %.2f s" % (last or 0.0))
    if last:
        print("  music span           : %.2f s   (the source video's removal is %.2f s)"
              % (last - drop, SONG_SPAN))
        print("  -> suggested offset  : %.2f s" % drop)
        print("     python3 tools/make_timeline.py miku-remove.srt src/data/timeline.tsv"
              " --offset %.2f" % drop)
        if abs((last - drop) - SONG_SPAN) > 4.0:
            print("  !! the span differs by %.1f s from the video's edit - the recording"
                  " may be a different arrangement, so expect to fine-tune with"
                  " `miku-voicebank-show --calibrate`." % ((last - drop) - SONG_SPAN))
    return 0


if __name__ == "__main__":
    sys.exit(main())
