#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-package-manager vocabulary for the removal transcript.

The removal show pretends to be the package manager deleting a voicebank, so the
system chatter has to sound like the machine it is running on: `yay` on an Arch
box, `dnf` on Fedora, `dpkg` on Debian.  Everything that differs between the
three lives here, so the same `timeline.tsv` and the same `miku-show` serve all
of them.

Two consumers:

  * the builders stamp a profile into the package (`PROFILE=dnf` in show.conf)
    and expand the placeholders in the timeline;
  * `miku-show` picks the matching words for its own scripted lines
    (the `[VOCALOID] 正在删除 …` chatter, the confirmation prompt, the bars).

Placeholders look like ``<PKGTOOL>`` and are only expanded when the name is one
of the known tokens, so a lyric that happens to contain angle brackets
(``------------<最高级别压缩的离别之歌>------------``) is never touched, and neither
is the `# key value` header of the timeline.

    python3 tools/profiles.py            # show what each profile says
    python3 tools/profiles.py --timeline src/data/timeline.tsv --for rpm
"""

from __future__ import annotations

import argparse
import re
import sys

# --------------------------------------------------------------------------
# the vocabularies
# --------------------------------------------------------------------------

PROFILES = {
    # ---------------------------------------------------------------- apt ---
    "deb": {
        "name": "deb",
        "family": "Debian / Ubuntu",
        "PKGTOOL": "dpkg",                  # the low-level engine
        "PKGMGR": "apt",                    # the front end the user typed
        "PKGEXT": ".deb",
        "PKGEXTS": ".deb",
        "REMOVECMD": "sudo apt remove miku-voicebank-pack",
        "DBDIR": "/var/lib/dpkg",
        "DBDIR2": "/var/lib/dpkg/info",
        "DBTYPE": "dpkg 数据库",
        "LOCKFILE": "/var/lib/dpkg/lock-frontend",
        "LOCKOWNER": "apt",
        "VERIFY": "dpkg: 正在校验文件校验和...",
        "STATUSLINE": "dpkg: 状态：已安装 (配置文件保留) -> 已删除",
        "PURGELINE": "dpkg: 警告: 忽略请求的删除操作，因为 miku-voicebank-pack 已不存在",
        # --- what the removal transcript says -----------------------------
        "STAGE": "正在删除 miku",
        "TRANSACTION": "正在解析事务",
        "CACHE": "正在解析 dpkg 数据库",
        "CHECK": "正在检查是否有文件需要被一同移除...",
        "MEMFILES": "将额外执行：删除 dpkg 所管理的记忆文件（--purge）",
        "CONFIRM": "确认执行这些操作？[Y/n] y",
        "TRANSACTION2": "正在执行事务...",
        "INTEGRITY": "正在检查包完整性",
        "COMPLETE": ":: 卸载操作完成！",
        "HOOK": "正在运行 dpkg 钩子 vocaloid_remove...",
        "DBUPDATE": "-> 正在更新 dpkg 状态数据库...",
        "MEMDEL": "记忆文件（--purge）已删除：{size}",
        "IMGPERM": "权限有误（只读）",
    },
    # ---------------------------------------------------------------- dnf ---
    "rpm": {
        "name": "rpm",
        "family": "Fedora / RHEL",
        "PKGTOOL": "rpm",
        "PKGMGR": "dnf",
        "PKGEXT": ".rpm",
        "PKGEXTS": ".rpm",
        "REMOVECMD": "sudo dnf remove miku-voicebank-pack",
        "DBDIR": "/var/lib/rpm",
        "DBDIR2": "/usr/lib/sysimage/rpm",
        "DBTYPE": "rpmdb",
        "LOCKFILE": "/var/lib/rpm/.rpm.lock",
        "LOCKOWNER": "dnf",
        "VERIFY": "rpm: 正在校验软件包摘要...",
        "STATUSLINE": "rpm: 状态：removed",
        "PURGELINE": "rpm: 警告: package miku-voicebank-pack is not installed",
        "STAGE": "正在删除 miku",
        "TRANSACTION": "正在解析事务",
        "CACHE": "正在解析 rpmdb",
        "CHECK": "正在检查软件包依赖关系...",
        "MEMFILES": "将额外执行：删除 rpm 所管理的记忆文件（--nosave）",
        "CONFIRM": "确认执行这些操作？[Y/n] y",
        "TRANSACTION2": "正在执行事务...",
        "INTEGRITY": "正在检查包完整性",
        "COMPLETE": ":: 事务完成！",
        "HOOK": "正在运行 rpm 钩子 vocaloid_remove...",
        "DBUPDATE": "-> 正在更新 rpmdb 数据库...",
        "MEMDEL": "记忆文件（--nosave）已删除：{size}",
        "IMGPERM": "权限有误（只读）",
    },
    # ------------------------------------------------------------- pacman ---
    "pacman": {
        "name": "pacman",
        "family": "Arch / Manjaro",
        "PKGTOOL": "pacman",
        "PKGMGR": "pacman",
        "PKGEXT": ".pkg.tar.zst",
        "PKGEXTS": ".pkg.tar.*",
        "REMOVECMD": "sudo pacman -R miku-voicebank-pack",
        "DBDIR": "/var/lib/pacman",
        "DBDIR2": "/var/lib/pacman/local",
        "DBTYPE": "pacman 数据库",
        "LOCKFILE": "/var/lib/pacman/db.lck",
        "LOCKOWNER": "pacman",
        "VERIFY": "pacman: 正在校验 .MTREE...",
        "STATUSLINE": "pacman: 状态：removed",
        "PURGELINE": "pacman: 警告: miku-voicebank-pack 不在数据库中",
        "STAGE": "正在删除 miku",
        "TRANSACTION": "正在解析事务",
        "CACHE": "正在解析 pacman 数据库",
        "CHECK": "正在检查软件包依赖关系...",
        "MEMFILES": "将额外执行：删除 pacman 所管理的记忆文件（--nosave）",
        "CONFIRM": "确认执行这些操作？[Y/n] y",
        "TRANSACTION2": "正在执行事务...",
        "INTEGRITY": "正在检查包完整性",
        "COMPLETE": ":: 卸载操作完成！",
        "HOOK": "正在运行 pacman 钩子 vocaloid_remove...",
        "DBUPDATE": "-> 正在更新 pacman 本地数据库...",
        "MEMDEL": "记忆文件（--nosave）已删除：{size}",
        "IMGPERM": "权限有误（只读）",
    },
}

DEFAULT_PROFILE = "deb"

#: tokens that may appear as ``<TOKEN>``; anything else is left alone
TOKENS = tuple(sorted(k for k in PROFILES[DEFAULT_PROFILE] if k == k.upper()))

#: `[1]  25891 权限错误 (核心已转储)  yay` - the shell reporting which command
#: the kernel dumped, i.e. the package manager the user was running
PLACEHOLDER_KERNEL = re.compile(
    r"((?:权限错误 \(核心已转储\)|core dumped))\s+\S+")

_TOKEN_RE = re.compile(r"<(%s)>" % "|".join(TOKENS))

#: lines that were written by a *system* and therefore have to be re-worded per
#: package manager (kernel, package database, service manager, ...)
SYS_MARKERS = (
    "yay", "apt", "dnf", "rpm", "dpkg", "pacman", "systemd", "A stop job",
    "核心已转储", "core dumped",
)


def get(name):
    """Profile dict for `name`; unknown names fall back to the default one."""
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    return PROFILES.get(str(name).strip().lower(), PROFILES[DEFAULT_PROFILE])


def names():
    return sorted(PROFILES)


def expand(text, profile) -> str:
    """Replace the known ``<TOKEN>`` placeholders in `text`."""
    if "<" not in text:
        return text
    values = profile if isinstance(profile, dict) else get(profile)
    return _TOKEN_RE.sub(
        lambda m: str(values[m.group(1)]) if values.get(m.group(1)) is not None
        else m.group(0), text)


def expand_line(text, profile) -> str:
    """Expand the placeholders in one timeline line."""
    return expand(text, profile)


def stop_job_line(sec: int, unit: str = "miku", limit: str = "4min 0s") -> str:
    """The systemd `A stop job` line with a concrete counter (used by the demo)."""
    return "A stop job is running for %s (%ds/%s)" % (unit, sec, limit)


def expand_lines(items, profile):
    """`items` is [(t, kind, text)] -> a new list with tokens expanded."""
    if isinstance(profile, str):
        profile = get(profile)
    return [(t, kind, expand_line(text, profile)) for t, kind, text in items]


def expand_file(path, profile, out_path=None) -> int:
    """Expand the placeholders in a timeline file; `#` header lines are kept."""
    profile = get(profile) if isinstance(profile, str) else profile
    changed = 0
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        if line.startswith("#") or not line:
            out.append(line)
            continue
        new = expand_line(line, profile)
        if new != line:
            changed += 1
        out.append(new)
    with open(out_path or path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return changed


def _main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", help="only show this profile")
    ap.add_argument("--timeline", help="expand a timeline file to stdout")
    ap.add_argument("--for", dest="target", default=DEFAULT_PROFILE,
                    help="profile to use with --timeline")
    args = ap.parse_args()

    if args.timeline:
        profile = get(args.target)
        with open(args.timeline, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    print(line)
                else:
                    print(expand_line(line, profile))
        return 0

    for key in ([args.profile] if args.profile else names()):
        p = get(key)
        print("=== %s (%s) ===" % (p["name"], p["family"]))
        for field in ("PKGTOOL", "PKGMGR", "PKGEXT", "REMOVECMD", "DBDIR",
                      "LOCKFILE", "VERIFY", "STATUSLINE", "PURGELINE"):
            print("  %-12s %s" % (field, p[field]))
        print("  %-12s %s" % ("STOPJOB", stop_job_line(0)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
