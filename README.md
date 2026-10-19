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

服务器上运行时，用 `docker-compose.server.yml` 直接拉取镜像（推荐，无需在服务器构建）；或用 `docker-compose.yml` 在本机 build。

```bash
# 1. 配置 token（二选一）
cp .env.example .env        # 然后编辑 .env 填入 BOT_TOKEN
# 或者：把 token 存进同目录 token.txt，并在 docker-compose.yml 里解开挂载那一行

# 2. 首次拉取并启动（镜像名改成你自己的，见下文「发布到 GitHub」）
docker compose -f docker-compose.server.yml pull
docker compose -f docker-compose.server.yml up -d

# 3. 查看日志 / 停止
docker compose -f docker-compose.server.yml logs -f
docker compose -f docker-compose.server.yml down
```

- **Web 控制台**：`http://服务器IP:8080` —— 运行状态、用户/金币总量、Top10 排行榜，10 秒自动刷新；端口在 `docker-compose.yml` 左边改。
- 数据持久化在 `./data/bot_data.db`，重建容器不丢数据。
- `/setprivacy → Disable` 或把 bot 设为群管理员，这一步与部署方式无关，必做。

## 发布到 GitHub（自动打包镜像）

每次更新代码后，GitHub Actions 会**自动构建 Docker 镜像**并发布，服务器一条命令拉取最新版。只需配置一次：

1. **建仓库**：注册/登录 [github.com](https://github.com) → 右上角 ➕ → **New repository** → 名称如 `tg-funbot` → 选 **Public** → 不要勾选自动生成 README → **Create**。
2. **关联远程**（Windows 上已装 git）：
   ```bash
   cd "C:\Users\Administrator\Desktop\TG机器人"
   git remote add origin https://github.com/你的用户名/tg-funbot.git
   ```
3. **首次推送**：双击 **推送更新.bat**（首次会弹出浏览器让你登录 GitHub 授权）。
4. 推送后稍等 2–5 分钟，GitHub 仓库 **Actions** 标签页会自动完成构建并发布镜像：
   `ghcr.io/你的用户名/tg-funbot:latest`
5. **服务器拉取**：把这行镜像地址填进 `docker-compose.server.yml` 的 `image:` 字段，然后按上面「部署步骤（Docker）」执行即可。

> 免密：GitHub 内置的 GITHUB_TOKEN 会自动授权推送 GHCR，不需要配置任何 token。

## 以后每次更新（3 步）

```bash
1. 双击「推送更新.bat」                # 自动 add/commit/push
2. 等 Actions 构建完成（约 2–5 分钟）   # 仓库 Actions 页面看进度的绿勾
3. 服务器上执行：
   docker compose -f docker-compose.server.yml pull
   docker compose -f docker-compose.server.yml up -d
```

金币数据在服务器 `./data/bot_data.db`，更新镜像不会丢失。

## 镜像版本

- `latest` —— 最新构建
- `v<提交号>` 格式（如 `va9942c7`）—— 每次构建的历史版本，可随时回滚：
  `docker run ghcr.io/你的用户名/tg-funbot:va9942c7`

如果服务器网络拉 GHCR 慢/被墙：给 Docker daemon 配代理（`/etc/docker/daemon.json` 或 systemd 环境变量 `HTTP_PROXY/HTTPS_PROXY`），或改用国内镜像站加速。

## 数据与运维

- 所有金币、签到记录存在同目录 `bot_data.db`（SQLite），删掉即重置。
- 抽奖/轮盘/接龙的局内状态在内存中，重启会丢失进行中的局（金币不丢）。
- 跑在 Emby 服务器上时，占用约 60–120MB 内存、CPU 几乎为 0，互不干扰。
- 长期挂机建议用任务计划程序开机自启：`pythonw.exe bot.py`（无窗口运行）。

## 文件结构

```
bot.py        主入口：注册命令、中文命令分发、帮助菜单、启动 Web
database.py   SQLite 数据层（建表/读写积分/设置/排行榜/全局统计）
economy.py    签到、余额、排行
fun.py        骰子、硬币、猜拳、随机点人
lottery.py    抽奖、俄罗斯轮盘
redpacket.py  手气红包
jielong.py    词语接龙
web.py        Web 控制台（登录/仪表盘/代理设置/重启）
Dockerfile / docker-compose.yml        本机构建部署
docker-compose.server.yml             服务器拉取镜像部署
.github/workflows/build.yml           GitHub Actions 自动打包
推送更新.bat        每次更新的推送一键脚本
启动.bat           Windows 直跑一键脚本
.env.example       token 模板
```
