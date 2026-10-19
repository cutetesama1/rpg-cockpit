"""Isolated HTTP model fixture for the stateless 0.7 wire protocol and UI acceptance."""
from __future__ import annotations
import json,os,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'build/p21'/('qa-'+str(time.time_ns()))
for key,path in {'RPG_CONFIG_DIR':'config','RPG_USER_PACKS':'packs','RPG_LIBRARY':'library.json','RPG_SKILL_LIBRARIES':'skill-libraries','RPG_SAVES':'saves'}.items():os.environ[key]=str(QA/path)
os.environ['RPG_NO_RESUME']='1'
sys.path.insert(0,str(ROOT/'api'))
import main
from rpg_gateway import build_router,merge_update
from rpg_core.settlement import DOMAINS
REQUESTS=[]
class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        system=body['messages'][0]['content'];user=body['messages'][1]['content'];calls=None;phase='narration';content=''
        if '世界技能配置器' in system:
            phase='skill_selection';data=json.loads(user)
            refs=[e['ref'] for e in data['candidates'] if e['kind']=='magic' and e['school']!='空间']
            content=json.dumps({'world_tags':['magic'],'skill_refs':refs,'initial_refs':[],'reason':'故意返回空初始列表，验收强者背景补齐。'},ensure_ascii=False)
        elif '独立回合结算器' in system:
            phase='settlement';data=json.loads(user);text=data['narrative'];ops=[]
            def op(name,args,evidence):ops.append({'name':name,'args':args,'evidence':evidence})
            if '木桩擦伤了你的手臂' in text:op('damage',{'target':data['resource_bindings'].get('health','hp'),'amount':3,'reason':'擦伤'},'木桩擦伤了你的手臂')
            if '你换上了卫衣' in text:op('update_clothing',{'changes':[{'slot':'upper','garment':'hoodie','evidence':'你换上了卫衣'}]},'你换上了卫衣')
            if '你终于学会了火弹' in text:
                candidate=next((e for e in data['candidates'] if e['name']=='火弹'),None)
                if candidate:op('learn_catalog_skills',{'skills':[{'ref':candidate['ref'],'evidence':'你终于学会了火弹，掌心的暖光稳定下来。'}]},'你终于学会了火弹，掌心的暖光稳定下来。')
            if '你认识了米拉' in text:op('set_flag',{'flag':'met_mira','value':True,'reason':'认识米拉'},'你认识了米拉')
            calls=[{'id':'settlement','type':'function','function':{'name':'settle_turn','arguments':json.dumps({'checked':list(DOMAINS),'operations':ops},ensure_ascii=False)}}]
            REQUESTS.append({'phase':phase,'roles':[m['role'] for m in body['messages']],'tool_names':[t['function']['name'] for t in body.get('tools',[])],'keys':sorted(data),'hp':data['state'].get('hp'),'candidate_count':len(data['candidates']),'history_absent':not bool({'recent','events','action','tool_results','tool_exchanges'}&data.keys())})
        else:
            action={}
            if '# 玩家本回合行动\n' in user:action=json.JSONDecoder().raw_decode(user.split('# 玩家本回合行动\n',1)[1].lstrip())[0]
            text=action.get('text','')
            if '受伤' in text:narr='木桩擦伤了你的手臂。你换上了卫衣，把袖口理平。你认识了米拉，她递来干净的绷带。'
            elif '学习火弹' in text:narr='你终于学会了火弹，掌心的暖光稳定下来。'
            elif action.get('skills'):narr='你依照熟悉的咒语挥动法杖，火光掠过练习室。'
            else:narr='你站在学院的练习室里，导师把一页手记放在桌上。“先让杖头亮起来吧。”'
            content=json.dumps({'narrative':narr,'options':[{'id':'learn','label':'学习火弹','action_text':'我向导师学习火弹。'}]},ensure_ascii=False)
            REQUESTS.append({'phase':phase,'tool_names':[t['function']['name'] for t in body.get('tools',[])]})
        if body.get('stream') and calls is None:
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for i in range(0,len(content),6):
                data={'model':'fixture','choices':[{'index':0,'delta':{'content':content[i:i+6]},'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(data,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.006)
            self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
        else:
            data=json.dumps({'model':'fixture','choices':[{'message':{'content':content,'tool_calls':calls or []}}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}},ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',18832),Model);threading.Thread(target=server.serve_forever,daemon=True).start()
main.manager.settings=merge_update(main.manager.settings,{'roles':{'narrator':{'provider':'openai'},'settler':{'provider':'openai'}},'providers':{'openai':{'preset':'custom','base_url':'http://127.0.0.1:18832/v1','model':'fixture','max_retries':0}}})
main.manager.builder_apply({'title':'结算与数值测试','prompts':{'pre':'你是魔法学院的初学者。'}},pack_id='stateless-qa')
@main.app.get('/__qa/requests')
def requests():return REQUESTS
main.app.router.routes.insert(0,main.app.router.routes.pop())
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=18831)
