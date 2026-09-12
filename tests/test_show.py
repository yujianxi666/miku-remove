#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sanity tests for src/bin/miku-show (no packages, no audio device needed).

    python3 tests/test_show.py

Checks the bits that are easy to get wrong: AUDIO_START handling for players
that cannot seek, the once-per-removal lock, timeline parsing and the bar.
"""
import argparse
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOW = os.path.join(ROOT, "src", "bin", "miku-show")
TIMELINE = os.path.join(ROOT, "src", "data", "timeline.tsv")

failures = []


def check(name, cond, detail=""):
    print("%-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
    if not cond:
        failures.append(name)


def load_module():
    loader = importlib.machinery.SourceFileLoader("miku_show", SHOW)
    spec = importlib.util.spec_from_loader("miku_show", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def make_show(mod, **cfg):
    conf = dict(mod.DEFAULTS)
    conf.update({k: str(v) for k, v in cfg.items()})
    args = argparse.Namespace(calibrate=False, no_audio=False, fast=False)
    paint = mod.Paint(False)
    screen = mod.Screen(open(os.devnull, "w"), paint, "off")
    return mod.Show(conf, args, open(os.devnull, "w"), False, paint, screen)


def fake_player(dirname, name):
    path = os.path.join(dirname, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nsleep 300\n")
    os.chmod(path, 0o755)
    return path


def make_mp3(path, frames=200):
    """A tiny but valid MPEG-1 Layer III file (128 kbps, 44.1 kHz, CBR)."""
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    flen = int(144 * 128000 / 44100)
    with open(path, "wb") as f:
        f.write(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        for _ in range(frames):
            f.write(header + bytes(flen - 4))
    return frames * 1152 / 44100.0


def test_process_control(mod, tmp):
    """The player must live in our process group and die with us."""
    class FakeAudio:
        def __init__(self):
            self.stopped = 0
            self.killed = 0

        def stop(self, grace=1.5):
            self.stopped += 1

        def kill(self):
            self.killed += 1

    show = make_show(mod)
    show.audio = FakeAudio()
    try:
        show.request_stop()
        check("interrupt: 1st press stops politely", False)
    except KeyboardInterrupt:
        check("interrupt: 1st press stops politely",
              show.audio.stopped == 1 and show.audio.killed == 0)
    try:
        show.request_stop()
        check("interrupt: 2nd press hard-kills", False)
    except KeyboardInterrupt:
        check("interrupt: 2nd press hard-kills",
              show.audio.stopped == 1 and show.audio.killed == 1)
    real_exit = os._exit
    codes = []
    os._exit = lambda code: codes.append(code)
    try:
        show.request_stop()
    except KeyboardInterrupt:
        pass
    finally:
        os._exit = real_exit
    check("interrupt: 3rd press exits at once", codes == [130] and show.audio.killed == 2,
          str(codes))

    # a real child: same process group, and it must not outlive us
    prog = (
        "import importlib.machinery, importlib.util, os, sys, argparse\n"
        "loader = importlib.machinery.SourceFileLoader('m', %r)\n"
        "spec = importlib.util.spec_from_loader('m', loader)\n"
        "m = importlib.util.module_from_spec(spec); loader.exec_module(m)\n"
        "cfg = dict(m.DEFAULTS); cfg['PLAYER'] = 'mpv'; cfg['KILL_STRAY'] = '0'\n"
        "args = argparse.Namespace(calibrate=False, no_audio=False, fast=False)\n"
        "p = m.Paint(False)\n"
        "s = m.Show(cfg, args, open(os.devnull, 'w'), False, p,\n"
        "           m.Screen(open(os.devnull, 'w'), p, 'off'))\n"
        "s.attach_audio(%r, 0.0)\n"
        "print(s.audio.proc.pid, os.getpid(), os.getpgrp(), flush=True)\n"
        "os._exit(0)\n"
    ) % (SHOW, os.path.join(tmp, "song.flac"))
    env = dict(os.environ)
    env["PATH"] = tmp + os.pathsep + env["PATH"]
    res = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=env)
    try:
        pid, parent, pgrp = (int(x) for x in res.stdout.split())
    except ValueError:
        check("player: spawned by attach_audio", False, res.stdout + res.stderr)
        return
    check("player: spawned by attach_audio", True, "pid %d" % pid)
    check("player: stays in our process group", pgrp == os.getpgrp(), str(pgrp))
    time.sleep(0.6)
    gone = not os.path.exists("/proc/%d" % pid)
    check("player: dies with the show (PDEATHSIG)", gone, "" if gone else "still running")
    if not gone:
        os.kill(pid, 9)


def main():
    mod = load_module()
    tmp = tempfile.mkdtemp(prefix="miku-test-")
    old_path = os.environ["PATH"]
    try:
        fake_player(tmp, "aplay")          # cannot seek
        fake_player(tmp, "mpv")            # can seek
        os.environ["PATH"] = tmp + os.pathsep + old_path
        audio = os.path.join(tmp, "song.flac")
        with open(audio, "wb") as f:
            f.write(b"fLaC" + bytes(4) + bytes(34))   # no real duration
        wav = os.path.join(tmp, "song.wav")
        with open(wav, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt ")  # only used for its extension

        # --- a seekable player: lyrics stay where the timeline says ---------
        show = make_show(mod, PLAYER="mpv", AUDIO_START="25.6", SPEED="1")
        show.attach_audio(audio, 25.6)
        check("mpv: playback starts at AUDIO_START", show.a_start == 25.6, str(show.a_start))
        check("mpv: lyric shift is -25.6s", abs(show.shift + 25.6) < 1e-9, str(show.shift))

        # --- a player that cannot seek: fall back to 0 *and* move the lyrics -
        show = make_show(mod, PLAYER="aplay", AUDIO_START="25.6", SPEED="1")
        show.attach_audio(wav, 25.6)
        check("aplay: fell back to the file start", show.a_start == 0.0, str(show.a_start))
        check("aplay: lyric shift follows the fallback", show.shift == 0.0, str(show.shift))
        if show.audio:
            show.audio.stop()

        # --- mp3 duration without a decoder ---------------------------------
        mp3 = os.path.join(tmp, "mkrm.mp3")
        expected = make_mp3(mp3, 200)
        got = mod.mp3_duration(mp3)
        check("mp3: duration from frames", abs(got - expected) < 0.05,
              "expected %.3f, got %s" % (expected, got))
        check("mp3: media_duration dispatches", abs(mod.media_duration(mp3) - expected) < 0.05)

        # --- timeline -------------------------------------------------------
        meta, items = mod.load_timeline(TIMELINE)
        check("timeline: %d lines" % len(items), len(items) > 150)
        check("timeline: start parsed", abs(meta["start"] - 25.6) < 0.01, str(meta["start"]))
        check("timeline: total parsed", abs(meta["total"] - 249.233) < 0.01, str(meta["total"]))
        check("timeline: sorted", all(items[i][0] <= items[i + 1][0] for i in range(len(items) - 1)))
        first = items[0][0]
        check("timeline: first lyric lands 0.8s after the downbeat",
              abs(first - 26.4) < 0.01, str(first))

        # --- bar rendering --------------------------------------------------
        paint = mod.Paint(False)
        show = make_show(mod)
        show.total = 249.233
        bar = show.bar("(1/2) 正在删除 miku", 0.5, show.stamp(124.6))
        check("bar: half full", "[#####-----]  50%" in bar, bar)
        check("bar: clock", "02:04 / 04:09" in bar, bar)
        gag = show.gag_bar(5, 100)
        check("bar: 再一次就好 gag", "[再一次就好-----]" in gag and "100%" in gag, gag)

        # --- the once-per-transaction lock ---------------------------------
        mod.LOCK_DIRS = [tmp]
        stamp = mod.lock_path()
        check("lock: path is writable", bool(stamp), str(stamp))
        check("lock: first removal may sing", mod.once_allowed(249.0) is True)
        check("lock: second removal stays quiet", mod.once_allowed(249.0) is False)
        os.utime(stamp, (time.time() - 400, time.time() - 400))
        check("lock: goes stale, sings again", mod.once_allowed(249.0) is True)

        # --- player choice --------------------------------------------------
        fake_player(tmp, "pw-play")
        fake_player(tmp, "paplay")
        picked = mod.pick_player({"PLAYER": "auto"}, 0.0, lambda m: None)
        wslg = os.path.exists("/mnt/wslg/PulseServer") and not mod.native_pipewire()
        if wslg:
            check("player: WSLg skips native-PipeWire pw-play", picked[0] != "pw-play",
                  picked[0])
        check("player: honours PLAYER=", mod.pick_player({"PLAYER": "pw-play"}, 0.0,
                                                         lambda m: None)[0] == "pw-play")
        check("player: PLAYER=none is silent", mod.pick_player({"PLAYER": "none"}, 0.0,
                                                               lambda m: None) is None)
        check("player: mp3 never picks a wav-only player",
              mod.pick_player({"PLAYER": "auto"}, 0.0, lambda m: None, mp3) is not None
              and mod.pick_player({"PLAYER": "auto"}, 0.0, lambda m: None,
                                  mp3)[0] not in ("aplay", "paplay", "pw-play"),
              str(mod.pick_player({"PLAYER": "auto"}, 0.0, lambda m: None, mp3)))
        check("player: wav-only player is refused for mp3",
              mod.pick_player({"PLAYER": "aplay"}, 0.0, lambda m: None, mp3) is None)

        # --- fetching the song from a URL ------------------------------------
        cache = os.path.join(tmp, "cache")
        url = "file://" + mp3.replace(os.sep, "/")
        cfg = {"AUDIO": "", "AUDIO_URL": url, "AUDIO_CACHE": cache}
        got = mod.resolve_audio(cfg, None, lambda t, s="msg": None)
        check("fetch: downloads into the cache", got == os.path.join(cache, "mkrm.mp3"), str(got))
        check("fetch: cached file is the whole song",
              os.path.isfile(got) and os.path.getsize(got) == os.path.getsize(mp3))
        first = mod.resolve_audio(cfg, None, lambda t, s="msg": None)   # second run: cache hit
        check("fetch: second run uses the cache", first == got)
        bad = {"AUDIO": "", "AUDIO_URL": "file:///nonexistent/nope.mp3",
               "AUDIO_CACHE": cache}
        check("fetch: failure is not fatal",
              mod.resolve_audio(bad, None, lambda t, s="msg": None) is None)
        check("fetch: --check never downloads",
              mod.resolve_audio({"AUDIO_URL": url, "AUDIO_CACHE": os.path.join(tmp, "c2")},
                                None, lambda t, s="msg": None, allow_download=False) is None)

        # --- stray players --------------------------------------------------
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                   "miku-voicebank/audio/x.flac"])
        time.sleep(0.3)
        found = mod.stray_players(os.path.join(tmp, "song.flac"))
        check("stray: finds an orphaned player", victim.pid in found, str(found))
        check("stray: never lists itself", os.getpid() not in found)
        mod.stop_stray_players(audio, lambda m: None, quiet=True)
        time.sleep(0.2)
        check("stray: SIGTERM is enough", victim.poll() is not None)

        # --- interrupts / process lifetime ----------------------------------
        test_process_control(mod, tmp)

        # --- dead terminal --------------------------------------------------
        class DeadStream:
            def write(self, s):
                raise OSError(5, "Input/output error")

            def flush(self):
                pass

        dead = mod.Screen(DeadStream(), mod.Paint(False), "inline")
        dead.line("hello")                      # must not raise
        dead.status("bar")
        check("screen: survives a dead terminal", dead.broken is True)
        show = make_show(mod)
        show.s = dead
        show.t0 = time.monotonic()
        try:
            show.wait_for(30.0)
            check("show: stops early when the terminal is gone", False)
        except KeyboardInterrupt:
            check("show: stops early when the terminal is gone", True)

        # --- config ---------------------------------------------------------
        conf = os.path.join(tmp, "show.conf")
        with open(conf, "w") as f:
            f.write('# comment\nAUDIO_OFFSET = "+1.50"\nNO_AUDIO=1\n')
        cfg, used = mod.load_config(conf)
        check("config: parsed", cfg["AUDIO_OFFSET"] == "+1.50" and cfg["NO_AUDIO"] == "1")
        os.environ["MIKU_SPEED"] = "40"
        cfg, _ = mod.load_config(conf)
        check("config: MIKU_ env override", cfg["SPEED"] == "40", cfg["SPEED"])
        del os.environ["MIKU_SPEED"]
    finally:
        os.environ["PATH"] = old_path
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
