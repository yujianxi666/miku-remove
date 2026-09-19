# miku-voicebank —— 卸载 miku 的时候，把《初音ミクの消失》唱完

一组 Debian 包：`miku-voicebank-pack1` … `miku-voicebank-pack51`。
装上去只是 51 块"声库数据"；但只要卸掉其中任何一个（一般是 `pack51`），整条依赖链会一起被拆掉，
而 `pack1` 的 `prerm` 会**把歌下载下来、播放，并逐句打印歌词** —— 一个声库被删除时的最后一场演出。

```
$ sudo apt remove miku-voicebank-pack51
[VOCALOID] 准备删除已安装的声库
[VOCALOID] 正在准备事务...
正在从网络获取声库波形：https://fms.uiero.com/downloads/mkrm.mp3
声库波形已就绪：/var/cache/miku-voicebank/mkrm.mp3（6.6 MiB）
[VOCALOID] 正在检查是否有文件需要被一同移除...
[VOCALOID] 以下声库将被移除：
  miku 4.0  [已安装]
  vocaloid-editor 4.0  [不再被其他包需要]
[VOCALOID] 将额外执行：删除所管理的记忆文件（--nosave）
[VOCALOID] 总计移除大小：5.4 GiB
[VOCALOID] 确认执行这些操作？[Y/n] y
[VOCALOID] 正在执行事务...
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
(2/2) 正在删除 vocaloid-editor  [##########] 100%
正在运行 vocaloid_remove 钩子...
-> 正在更新桌面数据库...
-> 正在更新图标缓存...
:: 卸载操作完成！
[VOCALOID] 声库 miku 4.0 (3.9.0) 已从本机移除。
[VOCALOID] 记忆文件（--nosave）已删除：5.4 GiB
[VOCALOID] 谢谢你… 以及… 晚安…
```

## 这个仓库里没有音乐文件

歌曲**不随仓库分发**，也不打进包里。第一次需要它的时候（安装时后台预取，或者卸载前现场获取）
脚本会用 Python 标准库把音频下载到缓存：

* 默认地址：`https://fms.uiero.com/downloads/mkrm.mp3`
* 缓存位置：`/var/cache/miku-voicebank/`（普通用户跑时退到 `~/.cache/miku-voicebank/`）
* 换地址：改 `/etc/miku-voicebank/show.conf` 里的 `AUDIO_URL`，或者打包时 `--audio-url`

下载失败不影响演出，只是没有声音，歌词照常打印。
想完全离线，也可以把任意音频放进 `/usr/share/miku-voicebank/audio/` 或写成 `AUDIO=/path/to/song.mp3`。

## 快速开始

```sh
# 1) 打包（只要有 python3，不需要 dpkg / 不需要音频文件）
make debs
#    等价于：
#    python3 tools/build_deb.py --count 51 --audio-url https://fms.uiero.com/downloads/mkrm.mp3
#    产物：miku-voicebank-pack（本体）+ pack1..pack51，一共 52 个包、约 0.4 MiB

# 2) 拷到 Linux 上装
mkdir -p ~/test && cp dist/*.deb ~/test/
sudo apt install ~/test/*.deb

# 3) 卸载 = 演出（约 4 分 45 秒）
sudo apt remove miku-voicebank-pack
```

`miku-voicebank-pack` 是声库本体（演出脚本、时间轴、配置都在它里面），
所有编号包都（间接）依赖它，所以卸它会一次拆掉 52 个包。
**apt 的进度条不会一直卡在 0%**：演出在后台 conductor 里跑，每个包的 prerm 只等到
"歌曲里属于自己的那一刻"就返回，于是每 5 秒左右真的删掉一个包，apt 的百分比跟着歌词涨到 100%
（实测 52 个包里有 49 个是在歌声中卸掉的）。想让 apt 干脆卡住不动：
`ORCHESTRATE=0 sudo apt remove miku-voicebank-pack`。

只想拆编号包、把本体留着以后单独唱：

```sh
sudo apt remove miku-voicebank-pack51
```

不想真卸载也能先看效果：

```sh
miku-voicebank-show                # 完整演出（会先下载歌曲）
miku-voicebank-show --check        # 只报告：歌曲地址/缓存/播放器/时间轴
miku-voicebank-show --fetch-audio  # 只把歌抓下来
miku-voicebank-show --no-audio     # 只听歌词
miku-voicebank-show --speed 40     # 40 倍速预览
miku-voicebank-show --calibrate    # 边听边用 [ ] { } 调歌词偏移，s 保存
```

## 需要什么

| 需要 | 说明 |
| --- | --- |
| Debian / Ubuntu（dpkg + apt） | `apt install ./test/*.deb` 需要 apt 1.1+ |
| Python 3 | 演出脚本只用标准库；下载也用它 |
| 一个能解码 mp3 的播放器 | `mpv` / `ffplay` / `vlc` / `mpg123` 自动检测；一个都没有就只打印歌词 |
| 网络（可选） | 只在需要下载歌曲时用到；离线可以用本地文件代替 |

`miku-voicebank-pack` 带 `Recommends: mpv | ffmpeg | ...`，默认 `apt install` 会顺手装一个能出声的播放器。

## 配置

`/etc/miku-voicebank/show.conf`（conffile，升级不覆盖），个人覆盖放
`~/.config/miku-voicebank/show.conf`，命令行参数优先，所有键都能用 `MIKU_` 前缀的环境变量覆盖
（例如 `MIKU_SPEED=40`）：

| 键 | 作用 |
| --- | --- |
| `PROFILE` | 转写用哪套包管理器的说法：`deb`（默认）/ `rpm` / `pacman` |
| `AUDIO` | 本地歌曲路径（留空 = 不用本地文件） |
| `AUDIO_URL` | 歌曲下载地址（留空 = 不下载） |
| `AUDIO_CACHE` | 下载缓存放哪 |
| `AUDIO_FETCH_TIMEOUT` / `AUDIO_FETCH_RETRIES` | 下载超时 / 重试 |
| `PLAYER` | `auto` 或指定播放器；`auto` 会按格式挑（mp3 不会选 `aplay`） |
| `AUDIO_START` | 从第几秒开始播（>0 需要能跳播的播放器：mpv/ffplay/vlc） |
| `AUDIO_OFFSET` | 歌词整体平移秒数 |
| `AUDIO_TAIL` | 最后一个音符之后再放几秒（默认 1.5，保证尾音不被切掉） |
| `NO_AUDIO` / `STATUS_STYLE` / `COLOR` / `SPEED` / `FORCE` / `KILL_STRAY` | 静音 / 进度条样式 / 颜色 / 倍速 / 无终端也演满全场 / 演出前清理残留播放进程 |
| `ORCHESTRATE` / `CONDUCTOR_STALE` | 编排模式开关（0 = 让 apt 卡在 0%）/ conductor 失联判定秒数 |

### 想中途停下 / 善后

* **Ctrl+C 连按**：第 1 下停掉音乐并退出，第 2 下 SIGKILL 播放器，第 3 下立刻返回。
* **直接关掉终端窗口**：播放器、conductor 和脚本同进程组，且子进程带 `PR_SET_PDEATHSIG`，歌会跟着停。
* 音乐还在响：`miku-voicebank-show --stop-audio`。
* Ctrl+C 把 `apt` 也打断了：`sudo apt --fix-broken install` 修一下再来。
* 彻底清理：`sudo apt purge 'miku-voicebank-pack*'`、`rm -rf /var/cache/miku-voicebank`。
* 排查编排：`cat /run/miku-voicebank/tick.log`。

## 歌词对齐

歌词时间轴（`src/data/timeline.tsv`）来自一段粉丝做的"假终端"字幕，它对着**约 4 分 09 秒**的剪辑配时间。
仓库里默认下载的那份音频长 **286.8 秒**：前 25.6 秒是安静的前奏，25.6 秒处一个 +20 dB 的落拍进正歌，
约 275 秒开始收尾；而删除过程本身是 `279.816 − 30.583 = 249.23` 秒，正好等于 `275 − 25.6`。
所以默认偏移取 **+25.60 秒**。

时间轴里只有真正和设备有关的那一行留成了占位符（源视频是在 Arch 上录的）：

```
51.450  lyric  [1]    25891 权限错误 (核心已转储) <PKGMGR>
```

`tools/profiles.py` 存了三套词表（`deb` = apt/dpkg、`rpm` = dnf/rpm、`pacman` = pacman），
打包时按 `--profile` 展开写进包里；`miku-show` 的脚本台词（事务、钩子、进度条标签）也走同一套词表。

换别的音频时重新算：

```sh
python3 tools/audio_profile.py 你的音频.flac     # 打印电平曲线、落拍点、建议偏移
python3 tools/make_timeline.py your.srt src/data/timeline.tsv --offset <新偏移>
make debs
```

编曲对不上时偏移只能近似，用 `miku-voicebank-show --calibrate` 手动微调最省事。

## 目录结构

```
├── src/
│   ├── bin/miku-show              演出脚本（Python 3，标准库）
│   ├── bin/miku-voicebank-show    手动跑一遍的入口（装到 /usr/bin）
│   ├── data/timeline.tsv          歌词时间轴（已含 +25.6s 偏移）
│   ├── doc/{README.md,copyright}  装到 /usr/share/doc/miku-voicebank-pack1/
│   ├── etc/show.conf              装到 /etc/miku-voicebank/show.conf（conffile）
│   └── maintainer/{prerm,postinst,postrm}
├── tools/
│   ├── build_deb.py               纯 Python 打包器（ar + tar.gz，不需要 dpkg-deb）
│   ├── profiles.py                包管理器词表（deb / rpm / pacman）
│   ├── common.py                  载荷（脚本/时间轴/配置/假记忆文件）
│   ├── make_timeline.py           从你自己的 SRT 生成时间轴
│   └── audio_profile.py           电平曲线 / 落拍点 -> 建议偏移
├── tests/test_show.py             自检（对齐、时长、下载、播放器选择、中断、锁）
├── tests/test_tick.py             自检（编排：本体是否等到整首歌唱完）
└── .github/workflows/build-deb.yml  CI 里打包并上传 artifacts
```

## 打包原理

* **依赖链**：`pack1 → pack2 → … → pack51`。dpkg 按依赖倒序配置，所以最后配置的是 `pack1`，
  由它打印 `Top-level package installed` 横幅；卸载 `pack51` 时 apt 会把 50 个依赖它的包一起拆掉。
* **演出触发**：每个包的 `prerm` 都会尝试调用 `miku-show --once`，
  `/run/miku-voicebank/show.lock` 保证整场只唱一遍，不管 apt 从哪一端开始拆。
* **磁盘占用**：control 里的 `Installed-Size` 是按 `5.4 GiB` 编的（纯装饰，让 apt 认真地说
  "After this operation, 5799 MB ... will be used"）。磁盘紧张就 `--fake-size 0.3`。
* **假记忆文件**：真的会装出 `/usr/share/vocaloid/models/memory/*.img`，其中 `user.img` 是 0444，
  所以歌词里那句"删除失败：user.img 权限有误（只读）"名副其实（虽然只是演出）。

## 上传到 GitHub

```sh
cd github                      # 本目录
git init -b main
git add .
git commit -m "miku-voicebank: sing 初音ミクの消失 when the voicebank is removed"
git remote add origin git@github.com:<你的用户名>/miku-remove.git
git push -u origin main
```

没有配 SSH key 就用 HTTPS：`git remote add origin https://github.com/<你的用户名>/miku-remove.git`
（会要求输入用户名 + Personal Access Token 作为密码）。

也可以不装 git：在 GitHub 上新建仓库 → "uploading an existing file" → 把本目录里的文件拖进去。

> 行尾已经在 `.gitattributes` 里钉死为 LF：这些 shell 脚本会被 dpkg 在 Linux 上直接执行，
> 混进一个 CR 就会变成 `bad interpreter: /bin/sh^M`。`tools/build_deb.py` 打包时也会再归一一次。

## 版权 / 免责

代码 MIT（见 `LICENSE`）。**歌曲和歌词不属于这个玩笑**：
《初音ミクの消失》版权属于 cosMo@暴走P，声音属于 Crypton Future Media。
本仓库不含任何音频，只在运行时从可配置的地址获取；歌词文本来自粉丝字幕，仅用于这个玩梗项目。
请自己买碟、别传播音频。这是一个给同好录视频用的玩具，别拿去干正经事。
