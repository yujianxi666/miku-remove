#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test for the orchestrated removal (the part apt/dnf/pacman drive).

The bug this guards against:

    the base package's `--tick` returned after the *lyric timeline's* span
    (4:09, the length of the source video's edit) while the conductor was still
    singing the remaining seconds of the recording.  The package manager then
    finished the transaction and handed the terminal back mid-song, so the tail
    of the song was never heard.

So this test starts the real conductor (with a fake player, and SPEED cranked
up so it takes a second), lets the base package tick, and asserts that the
conductor's show really did run to the end of the recording.

    python3 tests/test_tick.py

It skips itself when there is no `/proc` (i.e. not Linux), because the
orchestration uses it to find stray processes.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOW = os.path.join(ROOT, "src", "bin", "miku-show")
TIMELINE = os.path.join(ROOT, "src", "data", "timeline.tsv")
SPEED = 400.0                      # 400x: the whole show in about a second

failures = []


def check(name, cond, detail=""):
    print("%-58s %s%s" % (name, "ok" if cond else "FAIL",
                          ("  " + detail) if detail else ""))
    if not cond:
        failures.append(name)


def load_module():
    loader = importlib.machinery.SourceFileLoader("miku_show_tick", SHOW)
    spec = importlib.util.spec_from_loader("miku_show_tick", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def make_mp3(path, frames=11000, bitrate=32):
    """~287 s of valid MPEG-1 Layer III, like the recording the show fetches."""
    header = bytes([0xFF, 0xFB, {32: 0x10, 128: 0x90}[bitrate], 0x00])
    flen = int(144 * bitrate * 1000 / 44100)
    with open(path, "wb") as f:
        f.write(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        for _ in range(frames):
            f.write(header + bytes(flen - 4))
    return frames * 1152 / 44100.0


def main() -> int:
    if not os.path.isdir("/proc") and not os.environ.get("MIKU_TEST_FORCE"):
        print("skipped: the orchestration needs /proc (run me on Linux)")
        return 0

    mod = load_module()
    tmp = tempfile.mkdtemp(prefix="miku-tick-test-")
    try:
        song = os.path.join(tmp, "long.mp3")
        media = make_mp3(song)
        state = {}

        # a fake player, so nothing is actually played
        class FakeAudio:
            def __init__(self, path, cfg, log):
                self.path = path
                self.actual_start = 0.0

            def start(self, start):
                self.actual_start = start
                state["start"] = time.monotonic()

            def alive(self):
                return True

            def stop(self, grace=1.5):
                state.setdefault("stop", time.monotonic())

            def kill(self):
                pass

        mod.Audio = FakeAudio
        mod.stray_players = lambda audio_path=None: []
        mod.stop_stray_players = lambda *a, **k: []
        mod.stray_conductors = lambda: []
        mod.kill_pids = lambda pids: None
        mod.release_conductor = lambda paths: None

        paths = {
            "progress": os.path.join(tmp, "progress"),
            "ping": os.path.join(tmp, "ping"),
            "done": os.path.join(tmp, "done"),
            "pid": os.path.join(tmp, "pid"),
            "lock": os.path.join(tmp, "show.lock"),
            "claim": os.path.join(tmp, "conductor.lock"),
            "log": os.path.join(tmp, "tick.log"),
        }
        mod.conductor_paths = lambda: paths

        # run the conductor in-process (a thread), like --conductor would
        import threading

        def start_conductor(cfg, args, timeline_path, audio_path, out_fd, p):
            def body():
                c2 = dict(cfg)
                c2["STATUS_STYLE"] = mod._conductor_style(cfg)
                paint = mod.Paint(False)
                screen = mod.Screen(io.StringIO(), paint, "off")
                a2 = argparse.Namespace(
                    calibrate=False, no_audio=False, fast=False, audio=None,
                    conf=None, speed=None, offset=None, start=None, status=None,
                    no_color=False)
                show = mod.Show(c2, a2, io.StringIO(), False, paint, screen)
                show.progress_path = p["progress"]
                show.ping_path = p["ping"]
                show.done_path = p["done"]
                show.pid_path = p["pid"]
                show.claim_path = p["claim"]
                mod.write_number(p["progress"], 0.0)
                mod.touch(p["ping"])
                show.t0 = time.monotonic()
                show.run(timeline_path, audio_path)
                state["conductor_end"] = time.monotonic()

            threading.Thread(target=body, daemon=True).start()
            with open(p["pid"], "w") as f:
                f.write("%d\n" % (os.getpid() + 1))
            return None

        mod.start_conductor = start_conductor

        cfg = dict(mod.DEFAULTS)
        cfg["SPEED"] = str(SPEED)
        cfg["COLOR"] = "0"
        cfg["STATUS_STYLE"] = "off"
        cfg["CONDUCTOR_STALE"] = "600"      # do not let staleness end the show

        out = io.StringIO()
        out.fileno = lambda: 1
        args = argparse.Namespace(
            index=0, count=1, tick=True, conductor=False, calibrate=False,
            no_audio=False, fast=False, audio=None, conf=None, speed=None,
            offset=None, start=None, status=None, no_color=False, quiet=True,
            timeline=None)

        meta, items = mod.load_timeline(TIMELINE)
        # the ticks count from the moment the music starts, so the show really
        # ends at `start + span` in the file
        wanted = mod.lyric_span(meta, items, media, 1.5)
        end_abs = wanted + meta["start"]
        check("the recording is longer than the video edit",
              media > meta["total"] + 6.0,
              "media %.1f, edit %.1f" % (media, meta["total"]))
        check("tick target covers the whole recording",
              end_abs >= media - 0.01,
              "end %.2f vs media %.2f" % (end_abs, media))

        t0 = time.monotonic()
        mod.cmd_tick(cfg, args, TIMELINE, song, out, False)
        returned = (time.monotonic() - t0) * SPEED     # in show seconds
        check("base package waited for the whole show",
              returned >= wanted - 2.0,
              "returned at %.1f s, show is %.1f s" % (returned, wanted))

        # let the conductor finish its epilogue
        deadline = time.monotonic() + 10.0
        while "conductor_end" not in state and time.monotonic() < deadline:
            time.sleep(0.05)
        check("conductor ran to the end of the recording",
              state.get("conductor_end") is not None
              and (state["conductor_end"] - t0) * SPEED >= end_abs - 1.0,
              "%.1f s of %.1f s" % ((state.get("conductor_end", t0) - t0) * SPEED,
                                    end_abs))
        check("conductor really started the player", "start" in state)
        check("progress marker reached the show length",
              (mod.read_number(paths["progress"]) or 0) >= wanted,
              str(mod.read_number(paths["progress"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
