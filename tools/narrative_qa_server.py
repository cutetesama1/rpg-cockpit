"""Seeded local UI fixture; never uses the real model or saves."""
import os, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
qa=root/"build/p13/qa"
for key,value in {"RPG_PACK":str(root/"packs/new-game"),"RPG_CONFIG_DIR":str(qa/"config"),"RPG_USER_PACKS":str(qa/"packs"),"RPG_LIBRARY":str(qa/"library.json"),"RPG_SAVES":str(qa/"saves"),"RPG_NO_RESUME":"1","RPG_AUTOSAVE":"0"}.items(): os.environ[key]=value
sys.path.insert(0,str(root/"api"))
import main
narrative='教练说：“先深呼吸。”你点了点头。\n\n门边传来声音：「准备好了吗？」风吹过窗台。\n'+('普通冒险游戏里的长叙述会依照手机屏幕宽度自然折行。'*12)+'\n'+('LongWord'*60)
main.manager.session.debug_set_state({"upper":"hoodie"})
main.manager.session._record(turn=0,kind="narrative.generated",role="narrator",payload={"opening":True,"narrative":narrative,"options":[]})
if __name__=="__main__":
    import uvicorn
    uvicorn.run(main.app,host="127.0.0.1",port=18812)
