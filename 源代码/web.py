# -*- coding: utf-8 -*-
"""Web 控制台：登录、运行状态、全局统计、排行榜、代理设置。
由 bot.py 在后台线程启动，端口由 WEB_PORT 环境变量控制（0=关闭）。

默认管理员：leguan / leguan123（可在数据库 settings 表中修改）
"""

import functools
import json
import os
import secrets
import sys
import time
import urllib.parse

import httpx
from flask import Flask, jsonify, redirect, request, session

import database as db

START_TS = time.time()
PORT = int(os.environ.get("WEB_PORT", "8080"))

PROXY_TYPES = ["socks5", "socks5h", "socks4", "http"]

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.jinja_env.autoescape = True  # noqa：模板为纯字符串，防意外注入


def _display_name(row):
    if row.get("first_name"):
        return row["first_name"]
    if row.get("username"):
        return "@" + row["username"]
    return f"用户{row['user_id']}"


# ---------------- 初始化 ----------------

def init():
    """在 db.init_db() 之后调用：生成会话密钥。"""
    if not db.get_setting("web_secret"):
        db.set_setting("web_secret", secrets.token_hex(32))
    app.secret_key = db.get_setting("web_secret")


# ---------------- 鉴权 ----------------

PUBLIC_PATHS = ("/login", "/api/login", "/healthz")


@app.before_request
def gate():
    if request.path in PUBLIC_PATHS:
        return None
    if not session.get("admin"):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="未登录"), 401
        return redirect("/login")
    return None


# ---------------- 页面 ----------------

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录 · 娱乐机器人控制台</title>
<style>
  :root { color-scheme: dark; }
  body { font-family:"Segoe UI","Microsoft YaHei",sans-serif; min-height:100vh; margin:0;
         display:flex; align-items:center; justify-content:center;
         background:linear-gradient(135deg,#0f1023 0%,#1a1033 55%,#0f1f2e 100%); color:#e8e8f2; }
  .box { background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1);
         border-radius:16px; padding:36px; width:320px; }
  h1 { font-size:19px; text-align:center; margin:0 0 6px; }
  .sub { color:#9799b3; font-size:12px; text-align:center; margin-bottom:22px; }
  label { display:block; font-size:12px; color:#9799b3; margin:12px 0 4px; }
  input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(255,255,255,.14);
          background:rgba(255,255,255,.06); color:#e8e8f2; font-size:14px; box-sizing:border-box; }
  button { width:100%; margin-top:22px; padding:11px; border:none; border-radius:10px;
           background:#6d5bd0; color:#fff; font-size:15px; cursor:pointer; }
  button:hover { background:#7d6be0; }
  .err { color:#ff6b6b; font-size:12px; text-align:center; height:16px; margin-top:10px; }
</style>
</head>
<body>
<div class="box">
  <h1>🎰 娱乐机器人控制台</h1>
  <div class="sub">请使用管理员账号登录</div>
  <label>账号</label><input id="u" autocomplete="username">
  <label>密码</label><input id="p" type="password" autocomplete="current-password">
  <button onclick="doLogin()">登 录</button>
  <div class="err" id="err"></div>
</div>
<script>
async function doLogin(){
  const r = await fetch("/api/login", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username: document.getElementById("u").value,
                          password: document.getElementById("p").value})
  });
  if(r.ok){ location.href = "/"; }
  else { document.getElementById("err").textContent = "账号或密码错误"; }
}
document.getElementById("p").addEventListener("keydown", e=>{ if(e.key==="Enter") doLogin(); });
</script>
</body>
</html>"""


_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎰 娱乐机器人 · 控制台</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    min-height: 100vh; padding: 32px 16px;
    background: linear-gradient(135deg,#0f1023 0%,#1a1033 55%,#0f1f2e 100%);
    color: #e8e8f2;
  }
  .wrap { max-width: 860px; margin: 0 auto; }
  .topbar { display:flex; justify-content:space-between; align-items:flex-start; }
  h1 { font-size: 26px; letter-spacing: 1px; margin-bottom: 6px; }
  .sub { color: #9799b3; font-size: 13px; margin-bottom: 26px; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%;
         background:#31d158; margin-right:6px; box-shadow:0 0 8px #31d158; }
  .logout { background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12);
            color:#c8c9de; border-radius:10px; padding:8px 16px; font-size:13px; cursor:pointer; }
  .logout:hover { background:rgba(255,255,255,.14); }
  .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 14px; }
  .card, .panel {
    background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.09);
    border-radius: 14px; padding: 18px;
  }
  .card .k { color:#9799b3; font-size:12px; margin-bottom:8px; }
  .card .v { font-size: 26px; font-weight: 700; }
  .panel { padding: 20px; margin-top: 18px; }
  .panel h2 { font-size: 15px; color: #b9a7ff; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; color:#9799b3; font-weight: 500; padding: 6px 8px; font-size:12px;}
  td { padding: 8px; border-top: 1px solid rgba(255,255,255,.07); }
  .num { font-variant-numeric: tabular-nums; }
  .medal { font-size: 15px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; }
  .chip { background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.1);
          border-radius:20px; padding:4px 12px; font-size:12px; color:#c8c9de; }
  .chip.ctl { cursor:pointer; user-select:none; padding:8px 16px; font-size:13px; }
  .chip.ctl:hover { background:rgba(255,255,255,.15); }
  .chip.on  { border-color: rgba(73,209,141,.55); color:#8ef0b4; }
  .chip.off { opacity:.5; border-color: rgba(255,107,107,.45); color:#ff9a9a; }
  .muted { color:#9799b3; font-size:13px; }
  footer { margin-top: 26px; color:#6f7188; font-size:12px; }
  /* 代理表单 */
  .row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px; align-items:center; }
  .field { display:flex; flex-direction:column; gap:4px; }
  .field span { font-size:12px; color:#9799b3; }
  input, select { padding:8px 10px; border-radius:10px; border:1px solid rgba(255,255,255,.14);
          background:rgba(255,255,255,.06); color:#e8e8f2; font-size:13px; min-width:110px; }
  .btn { border:none; border-radius:10px; cursor:pointer; font-size:13px; padding:9px 16px; color:#fff; }
  .btn.primary { background:#6d5bd0; } .btn.primary:hover { background:#7d6be0; }
  .btn.warn { background:#b06d2c; } .btn.warn:hover { background:#c47b36; }
  .btn.ghost { background:rgba(255,255,255,.09); } .btn.ghost:hover { background:rgba(255,255,255,.16); }
  .msg { font-size:13px; margin-top:8px; min-height:18px; }
  .ok { color:#31d158; } .no { color:#ff6b6b; }
  input[type=checkbox]{ width:auto; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <h1>🎰 娱乐机器人 · 控制台</h1>
      <div class="sub"><span class="dot"></span>Bot 运行中 · 数据每 10 秒自动刷新</div>
    </div>
    <button class="logout" onclick="fetch('/api/logout',{method:'POST'}).then(()=>location='/login')">退出登录</button>
  </div>

  <div class="cards">
    <div class="card"><div class="k">运行时长</div><div class="v" id="uptime">–</div></div>
    <div class="card"><div class="k">注册用户</div><div class="v num" id="users">–</div></div>
    <div class="card"><div class="k">金币总量</div><div class="v num" id="coins">–</div></div>
    <div class="card"><div class="k">累计签到</div><div class="v num" id="signins">–</div></div>
    <div class="card"><div class="k">猜拳场次</div><div class="v num" id="rps">–</div></div>
  </div>

  <div class="panel">
    <h2>💰 金币排行榜 Top 10</h2>
    <table>
      <thead><tr><th style="width:46px">名次</th><th>成员</th><th>金币</th>
                   <th>战绩(胜/负)</th><th style="width:80px">连签</th></tr></thead>
      <tbody id="top"><tr><td colspan="5" class="muted">加载中……</td></tr></tbody>
    </table>
  </div>

  <div class="panel" id="proxyPanel">
    <h2>🌐 代理设置（机器人访问 Telegram 用）</h2>
    <div class="row">
      <label class="field" style="flex-direction:row; gap:8px; align-items:center;">
        <input type="checkbox" id="p_enable"> <span style="font-size:13px;color:#c8c9de;">启用代理</span>
      </label>
      <label class="field"><span>类型</span>
        <select id="p_type"></select>
      </label>
      <label class="field"><span>服务器</span><input id="p_host" placeholder="127.0.0.1"></label>
      <label class="field"><span>端口</span><input id="p_port" placeholder="1080" width="6"></label>
      <label class="field"><span>用户名(可选)</span><input id="p_user"></label>
      <label class="field"><span>密码(可选)</span><input id="p_pass" type="password" placeholder="留空保持不变"></label>
    </div>
    <div class="row">
      <button class="btn primary" onclick="saveProxy()">💾 保存</button>
      <button class="btn ghost" onclick="testProxy()">🔍 测试连接</button>
      <button class="btn warn" onclick="restartBot()">♻️ 保存并重启机器人生效</button>
      <span class="msg" id="p_msg"></span>
    </div>
    <div class="muted">当前生效：<span id="p_current">…</span></div>
  </div>

  <div class="panel">
    <h2>🎛 游戏开关（点击即时生效，无需重启）</h2>
    <div class="chips" id="games"><span class="muted">加载中……</span></div>
    <div class="muted" style="margin-top:10px;">关闭后群里对应命令立即停用；进行中的抽奖/轮盘/红包不受影响。答题游戏：</div>
    <div class="muted">群内 <code>/发题</code> 发题 · 私聊 <code>/出题 题目｜答案｜奖励</code> 创建 · <code>/答题奖励</code> 设默认奖励</div>
  </div>

  <div class="panel">
    <h2>🎮 群里可用的功能</h2>
    <div class="chips">
      <span class="chip">/签到 每日领金币</span><span class="chip">/抽奖 定时开奖</span>
      <span class="chip">/轮盘 俄罗斯轮盘</span><span class="chip">/红包 手气红包</span>
      <span class="chip">/点人 随机点名</span><span class="chip">/骰子 掷骰子</span>
      <span class="chip">/硬币 抛硬币</span><span class="chip">/猜拳 石头剪刀布</span>
      <span class="chip">/接龙 词语接龙</span><span class="chip">/排行 金币榜</span>
    </div>
  </div>

  <footer>娱乐机器人 · 数据存于 /app/data · 接口：<code>/api/stats</code> · 健康：<code>/healthz</code></footer>
</div>

<script>
function fmtUptime(s){
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600),
        m=Math.floor(s%3600/60), sec=s%60;
  return (d? d+"天 ":"")+h+"时 "+m+"分 "+sec+"秒";
}
const nf=new Intl.NumberFormat("zh-CN");

async function load(){
  const r=await fetch("/api/stats");
  if(r.status===401){ location="/login"; return; }
  const s=await r.json();
  document.getElementById("uptime").textContent=fmtUptime(s.uptime);
  document.getElementById("users").textContent=nf.format(s.users);
  document.getElementById("coins").textContent=nf.format(s.coins);
  document.getElementById("signins").textContent=nf.format(s.signins);
  document.getElementById("rps").textContent=nf.format(s.rps_games);
  const medals=["🥇","🥈","🥉"];
  document.getElementById("top").innerHTML = s.top.length===0
    ? '<tr><td colspan="5" class="muted">还没有用户，去群里发 /签到 吧～</td></tr>'
    : s.top.map((t,i)=>`<tr>
        <td class="medal">${medals[i]||i+1}</td>
        <td>${t.name}</td>
        <td class="num"><b>${nf.format(t.points)}</b></td>
        <td class="num">${t.wins} / ${t.losses}</td>
        <td class="num">${t.streak? t.streak+"🔥":"–"}</td></tr>`).join("");
}

function proxyMsg(text, ok){
  const el=document.getElementById("p_msg");
  el.textContent=text; el.className="msg "+(ok?"ok":"no");
  setTimeout(()=>{ el.textContent=""; }, 6000);
}

async function loadSettings(){
  const sel=document.getElementById("p_type");
  ["socks5","socks5h","socks4","http"].forEach(t=>{ const o=document.createElement("option"); o.value=o.textContent=t; sel.appendChild(o); });
  const s=await (await fetch("/api/proxy_settings")).json();
  document.getElementById("p_enable").checked=!!s.enabled;
  sel.value=s.type||"socks5";
  document.getElementById("p_host").value=s.host||"";
  document.getElementById("p_port").value=s.port||"";
  document.getElementById("p_user").value=s.user||"";
  document.getElementById("p_current").textContent=s.active||"未启用（直连）";
}

function collectProxy(){
  return {
    enabled: document.getElementById("p_enable").checked ? 1 : 0,
    type: document.getElementById("p_type").value,
    host: document.getElementById("p_host").value.trim(),
    port: document.getElementById("p_port").value.trim(),
    user: document.getElementById("p_user").value.trim(),
    pass: document.getElementById("p_pass").value,
  };
}

async function saveProxy(){
  const r=await fetch("/api/proxy_settings", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(collectProxy())});
  proxyMsg(r.ok ? "已保存（新配置需重启后生效）" : "保存失败", r.ok);
  if(r.ok) loadSettings();
}

async function testProxy(){
  proxyMsg("测试中…", true);
  const r=await fetch("/api/proxy_test", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(collectProxy())});
  const s=await r.json();
  proxyMsg(s.ok ? `✅ 连接成功！延迟 ${s.ms} ms` : `❌ 失败：${s.error}`, s.ok);
}

async function restartBot(){
  if(!confirm("确定重启机器人？新代理配置将生效。重启约需几秒。")) return;
  proxyMsg("重启中…", true);
  try{ await fetch("/api/restart", {method:"POST"}); }catch(e){}
  location.reload();
}

load(); setInterval(load, 10000); loadSettings(); loadGames();

function gameMsg(text, ok){
  // 复用代理提示区域显示反馈可能离开关太远，单独用 console + 按钮 self-state 提示
  console.log(text);
}

async function loadGames(){
  const r=await fetch("/api/games");
  if(r.status===401){ location="/login"; return; }
  const games=await r.json();
  const box=document.getElementById("games");
  box.innerHTML="";
  for(const [k,v] of Object.entries(games)){
    const btn=document.createElement("button");
    btn.className="chip ctl "+(v.enabled?"on":"off");
    btn.textContent=(v.enabled?"✅ ":"⛔ ")+v.name+"("+k+")";
    btn.title="点击" + (v.enabled?"关闭":"开启") + v.name;
    btn.onclick=async()=>{
      const resp=await fetch("/api/games",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({key:k, enabled:!v.enabled})});
      if(resp.ok){ loadGames(); }
    };
    box.appendChild(btn);
  }
}
</script>
</body>
</html>"""


@app.get("/login")
def login_page():
    return _LOGIN_PAGE


@app.get("/")
def index():
    return _PAGE


# ---------------- 接口 ----------------

@app.post("/api/login")
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    if db.verify_admin(data.get("username") or "", data.get("password") or ""):
        session["admin"] = True
        return jsonify(ok=True)
    return jsonify(ok=False), 401


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/stats")
def stats():
    g = db.global_stats()
    top = db.top_rich(10)
    return jsonify(
        uptime=int(time.time() - START_TS),
        users=g["users"],
        coins=g["coins"],
        signins=g["signins"],
        rps_games=g["rps_games"],
        top=[
            {
                "name": _display_name(r),
                "points": r["points"],
                "wins": r["wins"],
                "losses": r["losses"],
                "streak": r["streak"],
            }
            for r in top
        ],
    )


# ---------------- 代理设置 ----------------

def _proxy_url(prefix: str = "proxy_") -> str:
    """根据数据库设置拼出代理 URL，未启用返回 None。"""
    if db.get_setting(prefix + "enabled") != "1":
        return None
    ptype = db.get_setting(prefix + "type") or "socks5"
    host = db.get_setting(prefix + "host") or ""
    port = db.get_setting(prefix + "port") or ""
    user = urllib.parse.quote(db.get_setting(prefix + "user") or "")
    pw = urllib.parse.quote(db.get_setting(prefix + "pass") or "")
    if not (host and port):
        return None
    auth = f"{user}:{pw}@" if user else ""
    return f"{ptype}://{auth}{host}:{port}"


@app.get("/api/proxy_settings")
def get_proxy_settings():
    return jsonify(
        enabled=db.get_setting("proxy_enabled") == "1",
        type=db.get_setting("proxy_type") or "socks5",
        host=db.get_setting("proxy_host") or "",
        port=db.get_setting("proxy_port") or "",
        user=db.get_setting("proxy_user") or "",
        has_pass=bool(db.get_setting("proxy_pass")),
        active=_proxy_url() or "未启用（直连）",
    )


@app.post("/api/proxy_settings")
def set_proxy_settings():
    d = request.get_json(force=True, silent=True) or {}
    db.set_setting("proxy_enabled", "1" if d.get("enabled") else "0")
    db.set_setting("proxy_type", d.get("type") if d.get("type") in PROXY_TYPES else "socks5")
    db.set_setting("proxy_host", str(d.get("host") or "").strip())
    db.set_setting("proxy_port", str(d.get("port") or "").strip())
    db.set_setting("proxy_user", str(d.get("user") or "").strip())
    # 密码留空 = 不修改旧密码
    pw = d.get("pass")
    if pw:
        db.set_setting("proxy_pass", str(pw))
    return jsonify(ok=True)


@app.post("/api/proxy_test")
def proxy_test():
    """用提交的表单（而非已保存值）测试连接，直接测到 api.telegram.org。"""
    d = request.get_json(force=True, silent=True) or {}
    host = str(d.get("host") or "").strip()
    port = str(d.get("port") or "").strip()
    if not host or not port:
        return jsonify(ok=False, error="请填写服务器地址和端口")
    ptype = d.get("type") if d.get("type") in PROXY_TYPES else "socks5"
    user = urllib.parse.quote(str(d.get("user") or ""))
    pw = urllib.parse.quote(str(d.get("pass") or ""))
    auth = f"{user}:{pw}@" if user else ""
    url = f"{ptype}://{auth}{host}:{port}"
    t0 = time.perf_counter()
    try:
        r = httpx.get("https://api.telegram.org/", proxy=url, timeout=8)
        ms = int((time.perf_counter() - t0) * 1000)
        return jsonify(ok=r.status_code == 200,
                       ms=ms,
                       error=None if r.status_code == 200 else f"HTTP {r.status_code}")
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200], ms=int((time.perf_counter() - t0) * 1000))


@app.post("/api/restart")
def api_restart():
    """以新配置重启 bot 进程（Docker 环境 exec 后容器继续运行）。"""
    def _do():
        time.sleep(0.3)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
        os.execv(sys.executable, [sys.executable, script])
    import threading
    threading.Thread(target=_do, daemon=True).start()
    return jsonify(ok=True, message="正在重启……")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


# ---------------- 游戏独立开关 ----------------

@app.get("/api/games")
def api_games_list():
    return jsonify(
        {k: {"name": v, "enabled": db.is_game_enabled(k)} for k, v in db.GAME_NAMES.items()}
    )


@app.post("/api/games")
def api_games_toggle():
    d = request.get_json(force=True, silent=True) or {}
    key = d.get("key")
    if key not in db.GAME_NAMES:
        return jsonify(ok=False, error="未知游戏"), 400
    db.set_game_enabled(key, bool(d.get("enabled")))
    return jsonify(ok=True, key=key, enabled=db.is_game_enabled(key))


def start(port: int = None):
    """在调用方线程里阻塞运行（bot.py 放在后台线程调用）。"""
    p = port or PORT
    if p <= 0:
        return
    app.run(host="0.0.0.0", port=p, use_reloader=False, threaded=True)
