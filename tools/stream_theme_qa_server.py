"""Isolated UI fixture using the actual HTTP streaming provider, never real models."""
from __future__ import annotations
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "build/p18/qa"
for key, value in {"RPG_PACK": str(ROOT/"packs/new-game"), "RPG_CONFIG_DIR": str(QA/"config"),
    "RPG_USER_PACKS": str(QA/"packs"), "RPG_LIBRARY": str(QA/"library.json"),
    "RPG_SAVES": str(QA/"saves"), "RPG_NO_RESUME": "1", "RPG_AUTOSAVE": "0"}.items():
    os.environ[key] = value
sys.path.insert(0, str(ROOT/"api"))
import main
from rpg_core.contracts import LlmProfile, LlmRolesConfig, SkillSpec
from rpg_core.runtime import GameSession
from rpg_gateway import LlmRouter, OpenAICompatibleProvider
REQUESTS = []
TEXT = '你沿着庭院的回廊放慢脚步。守夜人说：“别急，星图还在这里。”\n\n窗沿的微光映在合拢的手记上，风拂过衣角。远处传来钟声，石阶仍留着雨后的清凉。你停在门边，看见一封系着银线的信。'
class ModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        clothing = "衣物状态结算器" in body["messages"][0]["content"]
        REQUESTS.append({"stream": bool(body.get("stream")), "clothing": clothing})
        if clothing:
            time.sleep(.35)
            data = {"model": "offline-stream", "choices": [{"message": {"tool_calls": [{"id":"noop", "function":{"name":"update_clothing", "arguments":'{"changes":[]}'}}]}}]}
            encoded = json.dumps(data).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
            return
        failure = "测试失败" in body["messages"][-1]["content"]
        raw = json.dumps({"narrative": TEXT, "options": [{"id":"look","label":"查看来信","action_text":"我拿起银线系着的信。"},{"id":"ask","label":"询问星图","action_text":"我向守夜人询问星图。"}]}, ensure_ascii=False)
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        try:
            for i in range(0, len(raw), 4):
                delta = {"model":"offline-stream", "choices":[{"index":0,"delta":{"content":raw[i:i+4]},"finish_reason":None}]}
                self.wfile.write(("data: "+json.dumps(delta,ensure_ascii=False)+"\n\n").encode()); self.wfile.flush(); time.sleep(.035)
                if failure and i > 48: return
            self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
    def log_message(self, *args): pass

server = ThreadingHTTPServer(("127.0.0.1", 18816), ModelHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
p = OpenAICompatibleProvider(base_url="http://127.0.0.1:18816/v1", model="offline-stream", max_retries=0)
profile = LlmProfile(provider=p.name)
pack = main.manager.session.pack
pack.skills.append(SkillSpec(id="test_step", name="专注步法", description="稳定脚步。", cost={"focus":2}, category="探索"))
for field in pack.state.fields:
    if field.id == "upper": field.default = "hoodie"
    if field.id == "lower": field.default = "trousers"
main.manager.session = GameSession(pack, LlmRouter(LlmRolesConfig(narrator=profile), {p.name:p}))

@main.app.get("/__qa/requests")
def requests(): return REQUESTS
main.app.router.routes.insert(0, main.app.router.routes.pop())
@main.app.post("/__qa/history")
def history():
    with main.manager.lock:
        s=main.manager.session
        for turn in range(1,13):
            s._record(turn=turn,kind="turn.started",actor="player",payload={"action":{"kind":"text","text":f"历史输入 {turn}：我走过长廊。"}})
            s._record(turn=turn,kind="narrative.generated",role="narrator",payload={"narrative":f"历史叙述 {turn}。"+TEXT,"options":[]})
            s._record(turn=turn,kind="turn.committed",payload={})
    return {"ok":True}
main.app.router.routes.insert(0, main.app.router.routes.pop())
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main.app, host="127.0.0.1", port=18815)
