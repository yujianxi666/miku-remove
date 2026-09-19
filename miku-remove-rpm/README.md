# miku-voicebank (Fedora / RHEL) —— 卸载时唱完《初音ミクの消失》

一组 RPM 包：**`miku-voicebank-pack`**（声库本体，不带编号）+ `miku-voicebank-pack1` … `pack51`
（51 块声库数据）。装上去只是数据包；但只要卸掉**本体包**，RPM 的依赖关系会把整条链一起带走，
而每个包的 `%preun` 都会调用一次 `miku-show`，一边删包一边把"声库被删除"的过程逐句打印出来：

```sh
sudo dnf remove miku-voicebank-pack      # 52 个包一起卸，演出开始
```

**而且 dnf 的进度条不会一直卡在 0%**：演出在后台 conductor 进程里跑，
每个包的 `%preun` 只等到"歌曲里属于自己的那一刻"就返回，于是每 5 秒左右真的擦掉一个包，
dnf 的事务百分比跟着歌词一格格涨上去。

```sh
(2/2) 正在检查包完整性 [再一次就好-----] 100%
(1/2) 正在删除 miku              [----------]   0%   <- 音乐从这一拍开始
  我诞生在这世上 然后发觉到自己
  自己只是 模仿着人类而已
  ...
  删除失败：かっ.wav 文件正在使用
  #坏:/usr/share/vocaloid/models/memory/r.1.-3.img
  kill：正在尝试杀死进程（PID:39）
  ...
  晚安…
(1/2) 正在删除 miku             [##########] 100%
:: 事务完成！
[VOCALOID] 声库 miku 4.0 (3.9.1) 已从本机移除。
[VOCALOID] 谢谢你… 以及… 晚安…
```

歌是**完整播完**的：演出时钟按音频文件的真实时长走（`miku-show` 自己解析 mp3/flac/wav 的时长），
而不是按字幕里那段剪辑的 4 分 09 秒 —— 录音比那个剪辑长十几秒，
本体的 `%preun` 会一直等到最后一个音符结束才返回，
所以 dnf 不会在歌还没唱完的时候就把终端还给你。

**转写用的是 Fedora 的说法**：字幕里的系统输出会按包管理器替换 ——
内核那行 `[1] 25891 权限有误 (核心已转储) yay`（源视频是在 Arch 上录的）在这里显示成 `dnf`，
事务、钩子、rpmdb 更新的措辞也都是 rpm/dnf 的样子。

**歌曲不随包分发**：默认从 `https://fms.uiero.com/downloads/mkrm.mp3` 下载并缓存，
所以 `dist/` 一共只有 0.4 MiB。想离线/自带音频就 `--audio 初音ミクの消失.flac`。

---

## 1. 快速开始

打包只要 Python 3 —— **不需要 `rpmbuild`、不需要 `rpm`、也不需要 Linux**：
`tools/rpmbuild.py` 自己写 RPM 的 lead / signature header / header / cpio 载荷。

```sh
# 默认：歌曲在安装时后台预取、卸载前按需下载
python3 tools/build_rpm.py
# 等价于
python3 tools/build_rpm.py --count 51 --audio-url https://fms.uiero.com/downloads/mkrm.mp3

python3 tools/build_rpm.py --count 100                    # 复刻 1→…→100 的横幅
python3 tools/build_rpm.py --audio 初音ミクの消失.flac      # 改成自带音频（约 38 MB）
python3 tools/build_rpm.py --fake-size 0                  # 让 dnf 报真实的磁盘占用
python3 tools/build_rpm.py --profile deb                  # 换成 apt/dpkg 的说法（对照用）
```

拷到 Fedora 上装：

```sh
sudo dnf install ./dist/*.rpm      # 52 个包一次装完，本体的 %post 会后台把歌抓下来
```

卸载（拆掉整条链，演出开始）：

```sh
sudo dnf remove miku-voicebank-pack      # 全部 52 个（推荐；进度条会一路涨到 100%）
sudo dnf remove miku-voicebank-pack51    # 只拆 51 个编号包，本体留着
```

不想真卸载也能看一遍：

```sh
miku-voicebank-show                # 完整演出（需要的话先下载歌曲）
miku-voicebank-show --check        # 只报告：歌曲地址/缓存、播放器、时间轴
miku-voicebank-show --fetch-audio  # 只把歌抓下来
miku-voicebank-show --speed 40     # 40 倍速预览
miku-voicebank-show --no-audio     # 只听歌词，不播放
miku-voicebank-show --calibrate    # 边听边用 [ ] { } 微调歌词偏移，s 保存
```

## 2. 打包器（tools/rpmbuild.py）

RPM 的文件格式是自己写的，所以这台机器上不需要任何 rpm 工具链：

* **lead**（96 字节）+ **signature header**（8 字节对齐，含 payload 的 md5/sha1/sha256）
  + **header**（所有 tag，大端整数）+ **gzip 压缩的 cpio newc 载荷**；
* 文件元数据（`basenames`/`dirnames`/`dirindexes`/`filesizes`/`filemodes`/`filedigests`…）
  与 cpio 成员一一对应，校验和逐字节自洽；
* `tools/_check_rpm.py` 会**独立**把这些再解析一遍核对：

```sh
python3 tools/_check_rpm.py dist/*.rpm      # 52 个包全部结构自检
```

## 3. 需要什么

| 需要 | 说明 |
| --- | --- |
| Fedora / RHEL / CentOS Stream / openSUSE（rpm + dnf/zypper） | 包是 `noarch` 的，任何架构都能装 |
| Python 3 | 本体包 `Requires: python3`；演出脚本和下载都只用标准库 |
| 一个能解码 mp3 的播放器 | `mpv` / `ffplay` / `cvlc` / `mpg123` 自动检测。本体包 `Requires: mpv`，`Recommends: ffmpeg-free, mpg123, vlc` |
| 网络（可选） | 只在需要下载歌曲时用到；把音频放进包里就能完全离线 |

`miku-voicebank-show --check` 会告诉你当前会用到哪个播放器，以及歌曲是本地文件还是待下载。

## 4. 依赖链是怎么拆掉的

`pack1 → pack2 → … → pack51 → miku-voicebank-pack`：每个编号包都 `Requires` 链条上的下一个，
最后一个 `Requires` 本体。所以：

* 装的时候 dnf 会按依赖把 52 个包一次配好，最后配置的 `pack1` 打印链条横幅；
* `dnf remove miku-voicebank-pack` 时，dnf 会把所有依赖它的包一起列入事务，一次拆掉 52 个；
* 拆的顺序是 pack1、pack2、…、pack51、本体。

`%preun` 里的 `--tick --index N` 就是"我是链条里第几个"：第一个 tick 在后台拉起 conductor
开始演出，之后每个 tick 只等到自己的时刻就返回，所以包是一个一个真正被删掉的。
`/run/miku-voicebank/` 里的状态保证一场卸载只唱一遍。

## 5. 配置与微调

配置文件 `/etc/miku-voicebank/show.conf`（rpm 标记为 `%config(noreplace)`，升级不会被覆盖），
个人覆盖放 `~/.config/miku-voicebank/show.conf`，命令行参数优先级最高，
所有键都能用 `MIKU_` 前缀的环境变量覆盖（例如 `MIKU_SPEED=40`）：

| 键 | 作用 |
| --- | --- |
| `PROFILE` | 转写用哪个包管理器的说法：`rpm`（本包默认）/ `deb` / `pacman` |
| `AUDIO` / `AUDIO_URL` | 歌曲本地路径 / 下载地址 |
| `PLAYER` | `auto` 或指定播放器名，`none` 表示静音 |
| `AUDIO_START` | 从歌曲第几秒开始播（>0 需要能跳播的播放器） |
| `AUDIO_OFFSET` | 歌词整体平移秒数，用来微调对齐 |
| `AUDIO_TAIL` | 最后一个音符之后再放几秒（默认 1.5，保证尾音不被切掉） |
| `NO_AUDIO` / `STATUS_STYLE` / `COLOR` / `SPEED` / `FORCE` | 静音 / 进度条样式 / 颜色 / 倍速 / 无终端也演满全场 |
| `KILL_STRAY` | 演出前是否清理残留的旧播放进程（默认 1） |
| `ORCHESTRATE` / `CONDUCTOR_STALE` | 编排模式开关 / conductor 判定为失联的秒数 |

## 6. 歌词时间轴与包管理器用词

`src/data/timeline.tsv` 由 `miku-remove.srt` 生成，里面**只把真正和设备有关的那一行**
留成了占位符：

```
51.450  lyric  [1]    25891 权限错误 (核心已转储) <PKGMGR>
```

`tools/profiles.py` 保存三套词表（`deb` = apt/dpkg、`rpm` = dnf/rpm、`pacman` = pacman），
打包时按 `--profile` 展开写进包里；`miku-show` 里那些脚本台词
（`正在执行事务`、`正在运行 … 钩子`、进度条标签）也走同一套词表，
所以同一份字幕在每个系统上都像是本机自己在删包。

重新生成时间轴 / 换一份录音：

```sh
python3 tools/make_timeline.py miku-remove.srt src/data/timeline.tsv --offset 25.6
python3 tools/audio_profile.py 你的音频.flac     # 电平曲线、落拍点 -> 建议偏移
python3 tools/build_rpm.py                       # 重新打包
```

## 7. 目录结构

```
miku-remove-rpm/
├── README.md                       本文件
├── LICENSE                         MIT
├── Makefile                        make rpms / make check / make test / make clean
├── src/
│   ├── bin/miku-show               演出脚本（Python 3，只用标准库）
│   ├── bin/miku-voicebank-show     手动跑一遍的入口（装到 /usr/bin）
│   ├── bin/profiles.py             占位符词表（随包安装，show 会读它）
│   ├── data/timeline.tsv           歌词时间轴（由 SRT 生成，已含 +25.6s 偏移）
│   ├── doc/{README.md,copyright}   装到 /usr/share/doc/miku-voicebank-pack/
│   ├── etc/show.conf               装到 /etc/miku-voicebank/show.conf
│   └── maintainer/postrm           （钩子脚本在 tools/build_rpm.py 里生成）
├── tools/
│   ├── build_rpm.py                打包器：52 个 .rpm 进 dist/
│   ├── rpmbuild.py                 纯 Python 的 RPM 写入器
│   ├── _check_rpm.py               独立解析生成的 rpm，核对结构与摘要
│   ├── profiles.py                 包管理器词表
│   ├── common.py                   载荷（脚本/时间轴/配置/假记忆文件）
│   ├── make_timeline.py            SRT -> timeline.tsv
│   └── audio_profile.py            电平曲线 / 落拍点 -> 建议偏移
├── tests/test_show.py              演出脚本自检（对齐 / 时长 / 下载 / 播放器 / 中断 / 锁）
├── tests/test_tick.py              编排自检（本体是否等到整首歌唱完）
├── dist/                           52 个 .rpm（本体 + pack1..pack51，共 0.4 MiB）
├── miku-remove.srt                 原始字幕（时间轴的唯一来源）
└── mkrm.mp3                        默认下载的那首歌的本地副本（可选，方便离线/测试）
```
