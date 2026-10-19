# 🎰 TG 娱乐机器人

一个带**经济系统**的 Telegram 群娱乐机器人：签到攒金币 → 用金币玩抽奖、轮盘、红包、猜拳。

## 功能一览

| 分类 | 命令（中文 / 英文） | 说明 |
|------|--------------------|------|
| 💰 经济 | `/签到` `/signin` | 每日签到，连续签到每天有加成 |
|  | `/余额` `/balance` | 钱包、签到天数、猜拳战绩 |
|  | `/排行` `/top` | 金币排行榜（前 10） |
| 🎁 互动 | `/抽奖 奖品 [分钟]` `/lottery` | 按钮报名，倒计时自动开奖；奖品写"100金币"自动入账 |
|  | `/轮盘 奖品 [人数]` `/roulette` | 俄罗斯轮盘：人满后每轮随机淘汰 1 人，幸存者独吞奖池 |
|  | `/红包 总额 [份数]` `/redpacket` | 手气红包，随机拆分，开抢后展示战况 |
|  | `/点人 问题` `/pick` | 随机 @ 一个最近 10 分钟发过言的群友 |
| 🎲 小游戏 | `/骰子 [数量]` `/dice` | 掷 1–10 个骰子并求和 |
|  | `/硬币` `/coin` | 抛硬币 |
|  | `/猜拳 石头\|剪刀\|布` `/rps` | 与机器人猜拳，赢 +80 输 -50 金币 |
| 🧩 接龙 | `/接龙 词语` `/chain` | 词语首尾相接，不许重复；`/接龙` 看进度，`/接龙 结束` 收尾 |
|  | `/帮助` `/help` | 功能菜单 |

## 部署步骤（Windows 裸跑）

1. **拿 token**：TG 里找 [@BotFather](https://t.me/BotFather) → `/newbot` → 复制 `123456:ABC-xxx` 格式的 token。
2. 把 token 粘贴保存为本目录下的 `token.txt`（一行即可）。
3. 双击 **启动.bat**（自动装依赖并启动）；或手动：
   ```
   pip install -r requirements.txt
   python bot.py
   ```
4. 在 BotFather 发 `/setprivacy` → 选你的 bot → **Disable**（否则机器人看不到群消息，"点人"功能失效）。也可以直接把机器人设为**群管理员**。
5. 把机器人拉进群，发 `/帮助` 试试！

## Web 控制台

`http://服务器IP:8080`（端口在 compose/环境变量 `WEB_PORT` 里改）

- **登录**：默认管理员 `leguan` / `leguan123`，登录后才能看到面板
- **仪表盘**：运行时长、用户/金币总量、Top10 排行榜，10 秒自动刷新
- **代理设置**：本地直连不了 Telegram 时，在这里填 SOCKS 代理（服务器/端口/可选账号密码），支持保存、测试连接、一键重启生效

代理优先级：**Web 控制台配置 > 容器环境变量 `PROXY_URL` > 直连**。
禁止容器访问外网时也可在 `docker-compose.yml` 里直接写 `PROXY_URL=socks5://user:pass@127.0.0.1:1080`。

## 部署步骤（Docker）

前提：目标机器装好 Docker + Docker Compose 插件。

```bash
# 1. 配置 token（二选一）
cp .env.example .env        # 然后编辑 .env 填入 BOT_TOKEN
# 或者：把 token 存进同目录 token.txt，并在 docker-compose.yml 里解开挂载那一行

# 2. 构建并启动
docker compose up -d --build

# 3. 查看日志 / 停止
docker compose logs -f
docker compose down
```

- **Web 控制台**：`http://服务器IP:8080` —— 运行状态、用户/金币总量、Top10 排行榜，10 秒自动刷新；端口在 `docker-compose.yml` 左边改。
- 数据持久化在 `./data/bot_data.db`，重建容器不丢数据。
- Token 也可以用容器环境变量 `BOT_TOKEN` 传，两种方式都支持。
- `/setprivacy → Disable` 或把 bot 设为群管理员，这一步与部署方式无关，必做。

## 数据与运维

- 所有金币、签到记录存在同目录 `bot_data.db`（SQLite），删掉即重置。
- 抽奖/轮盘/接龙的局内状态在内存中，重启会丢失进行中的局（金币不丢）。
- 跑在 Emby 服务器上时，占用约 60–120MB 内存、CPU 几乎为 0，互不干扰。
- 长期挂机建议用任务计划程序开机自启：`pythonw.exe bot.py`（无窗口运行）。

## 文件结构

```
bot.py        主入口：注册命令、中文命令分发、帮助菜单、启动 Web
database.py   SQLite 数据层（建表/读写积分/排行榜/全局统计）
economy.py    签到、余额、排行
fun.py        骰子、硬币、猜拳、随机点人
lottery.py    抽奖、俄罗斯轮盘
redpacket.py  手气红包
jielong.py    词语接龙
web.py        Web 控制台（Flask，端口 8080）
Dockerfile / docker-compose.yml / .env.example   Docker 部署
启动.bat       Windows 一键启动
```
