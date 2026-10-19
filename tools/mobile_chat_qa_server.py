"""Offline mobile-chat fixture; no real model or user saves/settings are accessed."""
import os,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
qa=root/"build/p16/qa"
for key,value in {"RPG_PACK":str(root/"packs/new-game"),"RPG_CONFIG_DIR":str(qa/"config"),"RPG_USER_PACKS":str(qa/"packs"),"RPG_LIBRARY":str(qa/"library.json"),"RPG_SAVES":str(qa/"saves"),"RPG_NO_RESUME":"1","RPG_AUTOSAVE":"0"}.items():os.environ[key]=value
sys.path.insert(0,str(root/"api"))
import main
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,Option,SkillSpec,ToolCall
from rpg_core.runtime import GameSession
from rpg_gateway import LlmResponse,LlmRouter
requests=[]
class QaProvider:
    name="mobile_fixture"
    def complete(self,request):
        requests.append({"phase":request.get("phase","narrator"),"action":request.get("action")})
        if request.get("phase")=="clothing":return LlmResponse(tool_calls=[ToolCall(id="none",name="update_clothing",args={"changes":[]})],model="offline-fixture")
        time.sleep(.65)
        text=(request.get("action") or {}).get("text","")
        if "测试失败" in text:raise RuntimeError("测试用结算失败")
        return LlmResponse(narrator=NarratorOutput(narrative='守夜人把灯放回窗边，说：“我听见了，请继续。”\n\n风从石拱之间掠过，远处的水声慢慢清晰。你面前的庭院仍留着一条安静的小径。',options=[Option(id="look",label="看看窗外",action_text="我走到窗边，看看外面的庭院。"),Option(id="speak",label="询问星图",action_text="我询问守夜人关于星图的事情。")]),model="offline-fixture")
provider=QaProvider();profile=LlmProfile(provider=provider.name)
pack=main.manager.session.pack
pack.skills.append(SkillSpec(id="test_step",name="专注步法",description="测试回合的步法。",cost={"focus":2},category="战斗"))
main.manager.session=GameSession(pack,LlmRouter(LlmRolesConfig(narrator=profile),{provider.name:provider}))
s=main.manager.session
s.debug_set_state({"upper":"hoodie","lower":"trousers"})
s._record(turn=0,kind="narrative.generated",role="narrator",payload={"opening":True,"narrative":"你来到石拱下，守夜人说：“请进，今晚的星图已经准备好了。”你望向远处的群山。","options":[]})
for turn in range(2,20):
    s._record(turn=turn,kind="turn.started",actor="player",payload={"action":{"kind":"text","text":f"历史输入 {turn}：我沿着回廊继续走，看看手边的星图。","modes":["action"]}})
    s._record(turn=turn,kind="narrative.generated",role="narrator",payload={"narrative":f"历史叙述 {turn}。"+"夜风经过庭院的石阶，灯影轻轻落在手记上。"*7+'守夜人说：“别急着赶路。”你停下脚步。',"options":[]})
    s._record(turn=turn,kind="turn.committed",payload={})
s._record(turn=20,kind="narrative.generated",role="narrator",payload={"narrative":"你在长廊尽头停下。守夜人说：“今晚想先去哪里？”你把手记合上，望向庭院。","options":[{"id":"look","label":"看看窗外","action_text":"我走到窗边，看看外面的庭院。"},{"id":"speak","label":"询问星图","action_text":"我询问守夜人关于星图的事情。"}]})
s._record(turn=20,kind="turn.committed",payload={})
@main.app.get("/__qa/requests")
def qa_requests():return requests
# Put the fixture-only route before the production static-file catch-all.
main.app.router.routes.insert(0,main.app.router.routes.pop())
if __name__=="__main__":
    import uvicorn
    uvicorn.run(main.app,host="127.0.0.1",port=18812)
