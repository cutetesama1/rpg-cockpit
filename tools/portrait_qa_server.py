"""Isolated ordinary portrait fixture for browser acceptance, no network model."""
import os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'build/portrait-qa'/str(time.time_ns())
for key,value in {'RPG_PACK':str(ROOT/'packs/new-game'),'RPG_CONFIG_DIR':str(QA/'config'),'RPG_USER_PACKS':str(QA/'packs'),'RPG_LIBRARY':str(QA/'library.json'),'RPG_SAVES':str(QA/'saves'),'RPG_SKILL_LIBRARIES':str(QA/'skills'),'RPG_NO_RESUME':'1','RPG_AUTOSAVE':'0'}.items():os.environ[key]=value
sys.path.insert(0,str(ROOT/'api'))
import main
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall
from rpg_core.runtime import GameSession
from rpg_core.settlement import DOMAINS
from rpg_gateway import LlmResponse,LlmRouter

class Provider:
    name='portrait-offline-fixture'
    index=0
    rows=[
      ('你戴上巫师帽，微笑着向左看去。',{'expression':'smile','gaze':'left'},[{'slot':'headwear','garment':'witch'}]),
      ('你戴上眼镜，握住雨伞，站在原地。',{'pose':'hold'},[{'slot':'facewear','garment':'glasses'},{'slot':'handheld','garment':'umbrella'}]),
      ('你收起雨伞，双手护住身体，眼中含着泪水。',{'pose':'guard','expression':'sad','tears':2},[{'slot':'handheld','garment':'none'},{'slot':'facewear','garment':'none'}]),
      ('你放下双手，闭眼站定。',{'pose':'stand','eye_state':'closed','tears':0},[]),
      ('你睁开眼睛，右手施法，周围浮起金色星光。',{'pose':'cast','eye_state':'open','expression':'default','decoration_foreground':'foreground1-39'},[]),
      ('你握住剑杖，在原地站定。',{'pose':'hold'},[{'slot':'handheld','garment':'sword cane'}]),
      ('你换上浅色云朵包，别上高位苹果发夹，戴好爱心图案耳环。',{'pose':'hold','accessory_tone':'light','hairpin_position':'high','earring_graphic':'heart'},[{'slot':'handheld','garment':'cloud purse'},{'slot':'headwear','garment':'apple hairpin'},{'slot':'earrings','garment':'graphic'}]),
      ('你将苹果发夹移到低位，换用深色云朵包。',{'accessory_tone':'dark','hairpin_position':'low'},[]),
    ]
    def complete(self,request):
        text,portrait,clothes=self.rows[min(self.index,len(self.rows)-1)]
        if request.get('phase')=='settlement':
            operations=[{'name':'update_portrait','args':{'changes':portrait},'evidence':text}]
            if clothes:operations.append({'name':'update_clothing','args':{'changes':[{**item,'evidence':text} for item in clothes]},'evidence':text})
            self.index+=1
            return LlmResponse(tool_calls=[ToolCall(id='portrait',name='settle_turn',args={'checked':list(DOMAINS),'operations':operations})])
        return LlmResponse(narrator=NarratorOutput(narrative=text))

p=Provider();profile=LlmProfile(provider=p.name)
main.manager.session=GameSession(main.manager.session.pack,LlmRouter(LlmRolesConfig(narrator=profile),{p.name:p}))
main.manager.session._record(turn=0,kind='narrative.generated',role='narrator',payload={'opening':True,'narrative':'你站在训练场的衣架旁。','options':[]})
if __name__=='__main__':
 import uvicorn
 uvicorn.run(main.app,host='127.0.0.1',port=18871)
