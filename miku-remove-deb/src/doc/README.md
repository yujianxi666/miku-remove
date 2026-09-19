# miku-voicebank-pack

`miku 4.0` 声库**本体**（不带编号）—— 这整条依赖链的根，也是唯一带**卸载演出**的那一块。
演出脚本、歌词时间轴、配置、假记忆文件都在这里；`miku-voicebank-pack1` … `pack51`
只是数据块，它们（间接）依赖本体。

```sh
# 安装（52 个本地 deb，apt 会自己按依赖链排好）
sudo cp dist/*.deb ~/test/          # 或任意目录
sudo apt install ~/test/*.deb

# 卸载：拆掉整条链，演出开始
sudo apt remove miku-voicebank-pack
```

卸载时 apt 的进度条**不会一直卡在 0%**：演出在后台 conductor 进程里跑，
每个包的 prerm 只等到"歌曲里属于自己的那一刻"就返回，于是每 5 秒左右真的删掉一个包，
apt 的百分比跟着歌词从 0% 涨到 100%。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/usr/share/miku-voicebank/bin/miku-show` | 演出脚本（Python 3，只用标准库） |
| `/usr/share/miku-voicebank/timeline.tsv` | 歌词时间轴（由字幕生成） |
| `/etc/miku-voicebank/show.conf` | 配置（conffile）：歌曲来源、播放器、偏移、编排 |
| `/usr/bin/miku-voicebank-show` | 手动运行整场演出，不用真的卸载 |
| `/usr/share/vocaloid/models/memory/*.img` | 声库的"记忆文件"，卸载时会逐个报错 |

歌曲**不一定在这个包里**：配置里的 `AUDIO` 指向本地文件（随包附带时），
`AUDIO_URL` 则是下载地址；缓存放在 `/var/cache/miku-voicebank/`，
本体的 postinst 会在后台先抓一次。`miku-voicebank-show --check` 会告诉你当前用的是哪一种。

## 手动试听

```sh
miku-voicebank-show --check        # 报告歌曲来源、缓存、播放器、时间轴
miku-voicebank-show --fetch-audio  # 只下载歌曲
miku-voicebank-show --no-audio     # 只听歌词，不播放
miku-voicebank-show --calibrate    # 边听边用 [ ] { } 微调歌词偏移，s 保存
miku-voicebank-show --speed 40     # 40 倍速预览
miku-voicebank-show --stop-audio   # 有残留播放进程时把它停掉
```

中途想停：Ctrl+C 连按（1 下停音乐，2 下强杀播放器，3 下立刻返回）；关掉终端窗口也会一起结束。
排查演出编排：`cat /run/miku-voicebank/tick.log`。

## 依赖链

`pack1 → pack2 → … → packN → miku-voicebank-pack`，所以：

* `apt install ~/test/*.deb` 会一次性装齐；
* `apt remove miku-voicebank-pack` 会把整条链一起拆掉（N+1 个包）；
* `apt remove miku-voicebank-packN` 只拆编号包，本体留着（以后单独卸本体还能再唱一遍）；
* 演出只唱一遍：后台 conductor 用 `/run/miku-voicebank/conductor.lock` 认领，
  先跑完的 tick 会给后面的 tick 留下 `progress`/`done` 标记。

---

歌词与歌曲版权属于 cosMo@暴走P / Crypton Future Media。
这个包只是个玩笑，不要拿去干正经事。
