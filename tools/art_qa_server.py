"""Offline art-theme preview fixture; writes only ignored build/p15 test directories."""
import os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
qa=root/"build/p15/qa"
for key,value in {"RPG_PACK":str(root/"packs/new-game"),"RPG_CONFIG_DIR":str(qa/"config"),"RPG_USER_PACKS":str(qa/"packs"),"RPG_LIBRARY":str(qa/"library.json"),"RPG_SAVES":str(qa/"saves"),"RPG_NO_RESUME":"1","RPG_AUTOSAVE":"0"}.items():os.environ[key]=value
sys.path.insert(0,str(root/"api"))
import main
session=main.manager.session
session.debug_set_state({"upper":"hoodie","lower":"trousers"})
text='你推开庭院尽头的铜门，夜风带着松木与雨水的气息掠过袖口。高处的穹顶缓缓展开，星光沿着石阶，落在一本尚未合拢的旅途手记上。\n\n守夜人把灯放在桌边，轻声说：“欢迎回来。今晚的星图，已经替你准备好了。”你停在门前，望向廊柱之间的远山。\n\n“先休息一会儿吧。”他指了指窗下的空椅，随后安静地退到一旁。窗外传来细微的水声，下一段旅程仍在等待你的选择。'
session._record(turn=0,kind="narrative.generated",role="narrator",payload={"opening":True,"narrative":text,"options":[{"id":"courtyard","label":"走进庭院","action_text":"我走进庭院，看看廊柱外的夜景。"},{"id":"atlas","label":"翻阅星图","action_text":"我走到桌边，翻阅那本星图。"},{"id":"keeper","label":"与守夜人交谈","action_text":"我向守夜人询问今晚的旅程。"}]})
if __name__=="__main__":
    import uvicorn
    uvicorn.run(main.app,host="127.0.0.1",port=18812)
