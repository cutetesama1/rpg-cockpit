"""Isolated HTTP model fixture for ZIP skill libraries, world selection and learning."""
from __future__ import annotations
import json,os,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'build/p19'/('qa-'+str(time.time_ns()))
for key,value in {'RPG_CONFIG_DIR':str(QA/'config'),'RPG_USER_PACKS':str(QA/'packs'),'RPG_LIBRARY':str(QA/'library.json'),'RPG_SKILL_LIBRARIES':str(QA/'skill-libraries'),'RPG_SAVES':str(QA/'saves'),'RPG_NO_RESUME':'1'}.items():os.environ[key]=value
sys.path.insert(0,str(ROOT/'api'))
import main
from rpg_gateway import build_router,merge_update
REQUESTS=[]
class ModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        system=body['messages'][0]['content'];user=body['messages'][1]['content']
        phase='narrator';content=None;calls=None
        if '世界技能配置器' in system:
            phase='skill_selection';data=json.loads(user);strong='强大' in data['world'] or '大法师' in data['world']
            refs=[e['ref'] for e in data['candidates'] if e['kind']=='magic' and e['school']!='空间']
            initial=[] if data['preserve_initial'] else refs if strong else [r for r in refs if r.endswith('magic_light_low_01')]
            content=json.dumps({'world_tags':['magic'],'skill_refs':refs,'initial_refs':initial,'reason':'依照资深大法师背景掌握多个体系。' if strong else '依照学徒背景，仅把点灯术列为初始法术。'},ensure_ascii=False)
        elif '后置技能学习结算器' in system:
            phase='skill_learning';data=json.loads(user);text=data['narrative'];learning=[]
            if '你终于学会了火弹' in text:
                entry=next(e for e in data['catalog_candidates'] if e['skill']['name']=='火弹')
                learning=[{'ref':entry['ref'],'evidence':text}]
            calls=[{'id':'learn_fixed','type':'function','function':{'name':'learn_catalog_skills','arguments':json.dumps({'skills':learning},ensure_ascii=False)}}]
        elif '衣物状态结算器' in system:
            phase='clothing';calls=[{'id':'wardrobe_noop','type':'function','function':{'name':'update_clothing','arguments':'{"changes":[]}'}}]
        else:
            action={}
            if '# 玩家本回合行动\n' in user:
                raw=user.split('# 玩家本回合行动\n',1)[1]
                action=json.JSONDecoder().raw_decode(raw.lstrip())[0]
            text=action.get('text','')
            if '想学' in text:narrative='你想要学会火弹。导师示意你先阅读法杖旁的练习手记，尚未教授完整咒语。'
            elif '学习火弹' in text:narrative='你终于学会了火弹，掌心的暖光在反复练习后稳定下来。'
            elif action.get('skills'):narrative='你依照熟悉的咒语挥动法杖，火光沿着你指向的方向掠去。'
            else:narrative='你站在学院的练习室里，导师把一页写着咒语的手记放在桌上。'
            content=json.dumps({'narrative':narrative,'options':[{'id':'learn','label':'学习火弹','action_text':'我向导师学习火弹。'}]},ensure_ascii=False)
        REQUESTS.append({'phase':phase,'stream':bool(body.get('stream')),'tool_names':[t['function']['name'] for t in body.get('tools',[])],
            'fixed_instruction_present':'本次已选技能的固定执行说明' in user})
        if body.get('stream') and content is not None:
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for i in range(0,len(content),5):
                packet={'model':'offline-skills','choices':[{'index':0,'delta':{'content':content[i:i+5]},'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(packet,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.015)
            self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
        else:
            data=json.dumps({'model':'offline-skills','choices':[{'message':{'content':content,'tool_calls':calls or []}}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}},ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',18820),ModelHandler)
threading.Thread(target=server.serve_forever,daemon=True).start()
main.manager.settings=merge_update(main.manager.settings,{'roles':{'narrator':{'provider':'openai'},'settler':{'provider':'openai'}},'providers':{'openai':{'preset':'custom','base_url':'http://127.0.0.1:18820/v1','model':'offline-skills','max_retries':0}}})
# Build one editable apprentice world with no installed library. Browser tests install ZIPs.
if not (main.manager.user_dir/'skills-qa').exists():
    main.manager.create('技能测试世界','skills-qa')
else:main.manager.select('skills-qa')
main.manager.update_prompts({'pre':'你是一名魔法学院的初学者。魔法通过咒语和法杖施放，学习后才会掌握技能。'})
main.manager.session=main.GameSession(main.load_pack(main.manager.pack_dir),build_router(main.manager.settings))
@main.app.get('/__qa/requests')
def requests():return REQUESTS
main.app.router.routes.insert(0,main.app.router.routes.pop())
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=18819)
