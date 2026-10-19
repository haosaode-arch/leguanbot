import os, sys, asyncio
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
os.environ["DATA_DIR"] = os.path.join(BASE, ".test_tmp")
sys.path.insert(0, os.path.join(BASE, "源代码"))

import database as db
db.init_db()

import economy
for raw, exp in [
    ("100金币", (100, "")),
    ("100金币+定制T恤", (100, "定制T恤")),
    ("定制T恤+100金币", (100, "定制T恤")),
    ("100 金币 + 一杯奶茶", (100, "一杯奶茶")),
    ("一箱可乐", (None, "一箱可乐")),
    ("", (None, "")),
]:
    got = economy.parse_reward(raw)
    print("parse_reward", repr(raw), "->", got, "OK" if got == exp else "FAIL")

import quiz
g, c = quiz.parse_reward("50金币", "100金币")
print("quiz.parse_reward ->", (g, c), "OK" if g == 50 else "FAIL")

import redpacket as rp
sent = {}
class FakeMsg:
    message_id = 0
    async def reply_text(self, text, **kw):
        sent["out"] = text
        return self
class FakeChat: type = "group"; id = -100999
class FakeUser:
    id = 42; first_name = "测试君"; username = "test"
class FakeUpdate: effective_chat = FakeChat(); effective_user = FakeUser(); message = FakeMsg()

db.add_points(42, 500)
asyncio.run(rp.cmd_redpacket(FakeUpdate(), FakeCtx := type("C", (), {"args": ["一箱可乐", "3"]})()))
print("纯自定义红包:", sent["out"].replace("\n", " | "))

token = list(rp.REDPACKETS.keys())[0]
class FakeQ:
    data = f"grab:{token}"
    from_user = FakeUser()
    async def answer(self, text, **kw): sent["grab"] = text
    async def edit_message_text(self, text, **kw): sent["edit"] = text
    message = FakeMsg()
asyncio.run(rp.cb_grab(type("U", (), {"callback_query": FakeQ()})(), type("C", (), {"bot": None})()))
print("grab 回执:", sent["grab"])

asyncio.run(rp.cmd_redpacket(FakeUpdate(), type("C", (), {"args": ["100金币+电影票", "5"]})()))
state = rp.REDPACKETS[list(rp.REDPACKETS.keys())[-1]]
print("组合红包: gold_total=%s custom=%r 拆分和校验=%s" % (
    state["gold_total"], state["custom"], sum(s for s in state["shares"] if s) == state["gold_total"]))

import lottery
print("lottery '100金币+定制T恤':", lottery._parse_prize("100金币+定制T恤"))
print("lottery '一等奖玩具':", lottery._parse_prize("一等奖玩具"))

import shutil; shutil.rmtree(".test_tmp", ignore_errors=True)
