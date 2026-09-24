# miku-remove —— 卸载一个假声库，听它唱完《初音ミクの消失》

装一个假的 `miku 4.0` 声库；卸掉它的时候，包里的那首歌会一边播，
一边把"声库正在被删除"的过程逐句打印出来，而包管理器的进度条跟着歌词一格格涨 ——
因为演出被拆给了依赖链上每个包的卸载钩子。

同一个玩笑做了三种包格式，各自放在**独立的文件夹**里，互不依赖：

| 文件夹 | 发行版 | 包 | 安装 | 卸载 |
| --- | --- | --- | --- | --- |
| [`miku-remove-deb/`](miku-remove-deb/) | Debian / Ubuntu | `.deb`（52 个） | `sudo apt install ./dist/*.deb` | `sudo apt remove miku-voicebank-pack` |
| [`miku-remove-rpm/`](miku-remove-rpm/) | Fedora / RHEL | `.rpm`（52 个） | `sudo dnf install ./dist/*.rpm` | `sudo dnf remove miku-voicebank-pack` |
| [`miku-remove-pacman/`](miku-remove-pacman/) | Arch / Manjaro | `.pkg.tar.zst`（52 个） | `sudo pacman -U ./dist/*.pkg.tar.zst` | `sudo pacman -R miku-voicebank-pack` |

每个文件夹都是**自包含**的：自己的演出脚本、歌词时间轴、打包器、自检、README 和字幕源文件，
可以单独下载、单独改、单独打包（只要 Python 3；Debian 版连 dpkg 都不需要，
RPM 版不需要 rpmbuild，Arch 版不需要 makepkg）：

```sh
cd miku-remove-deb    && make debs     # 或 make all：自检 + 打包
cd miku-remove-rpm    && make rpms     # make check 会把生成的 rpm 再解析一遍
cd miku-remove-pacman && make pkgs     # make check 会解压 .pkg.tar.zst 核对
```

用法、原理、配置项、依赖链细节、以及"哪些系统输出按包管理器换词"的说明，
都在各自文件夹的 `README.md` 里。

## 这个仓库里没有音频

歌曲不随包分发：运行时从 `AUDIO_URL`（默认 `https://fms.uiero.com/downloads/mkrm.mp3`）
下载并缓存，所以每个版本的 52 个包加起来也只有 0.4 MiB 左右。
仓库里不含 `.mp3`/`.flac`/`.wav` 等音频，也不含打包产物（`.deb`/`.rpm`/`.pkg.tar.zst`）。

## 许可

本仓库以 **CC BY-SA 4.0**（署名—相同方式共享）授权，全文见 [`LICENSE`](LICENSE)：
可以自由使用、修改、再分发，包括商用，条件是按同样方式共享并保留署名。

**歌曲与歌词不在这个许可范围内**：《初音ミクの消失》版权属于 cosMo@暴走P，
声音属于 Crypton Future Media。本仓库不含音频，只在运行时从可配置的地址获取。
