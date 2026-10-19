"""Replay recorded live-model wardrobe responses through the actual API/UI, offline."""
import os,sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
qa=root/"build/p14/qa"
for key,value in {"RPG_PACK":str(root/"packs/new-game"),"RPG_CONFIG_DIR":str(qa/"config"),"RPG_USER_PACKS":str(qa/"packs"),"RPG_LIBRARY":str(qa/"library.json"),"RPG_SAVES":str(qa/"saves"),"RPG_NO_RESUME":"1","RPG_AUTOSAVE":"0"}.items():os.environ[key]=value
sys.path.insert(0,str(root/"api"))
import main
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall
from rpg_core.runtime import GameSession
from rpg_gateway import LlmResponse,LlmRouter
records=json.loads((root/"docs/previews/p14-live-clothing-verification.json").read_text(encoding="utf-8"))["scenarios"][:6]
class Recorded:
    name="recorded_live_output"
    index=0
    def complete(self,request):
        row=records[self.index]
        if request.get("phase")=="clothing":
            self.index+=1
            args=row["applied_clothing"][0]["args"] if row["applied_clothing"] else {"changes":[]}
            return LlmResponse(tool_calls=[ToolCall(id=f"clothing_{self.index}",name="update_clothing",args=args)],model="recorded-output-replay")
        return LlmResponse(narrator=NarratorOutput(narrative=row["narrative"]),model="recorded-output-replay")
provider=Recorded()
profile=LlmProfile(provider=provider.name)
main.manager.session=GameSession(main.manager.session.pack,LlmRouter(LlmRolesConfig(narrator=profile),{provider.name:provider}))
main.manager.session._record(turn=0,kind="narrative.generated",role="narrator",payload={"opening":True,"narrative":"你站在训练室的更衣柜旁。","options":[]})
if __name__=="__main__":
    import uvicorn
    uvicorn.run(main.app,host="127.0.0.1",port=18812)
