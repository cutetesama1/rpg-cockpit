import os,sys,json,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'build/multiplayer-qa'/str(time.time_ns())
for key,path in {'RPG_CONFIG_DIR':'config','RPG_USER_PACKS':'packs','RPG_LIBRARY':'library.json','RPG_SAVES':'saves','RPG_SKILL_LIBRARIES':'skill-libraries'}.items():os.environ[key]=str(QA/path)
os.environ['RPG_PARTY_PORT']='18897';os.environ['RPG_NO_RESUME']='1';os.environ['RPG_PACK']=str(ROOT/'packs/new-game')
sys.path.insert(0,str(ROOT/'api'));import main
from rpg_gateway import merge_update
from rpg_core.contracts import SkillSpec
REQUESTS=[]
class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        try:data=json.loads(body['messages'][1]['content'])
        except ValueError:data={}
        if 'players' not in data:
            tools=[t['function']['name'] for t in body.get('tools',[])];calls=[]
            if 'settle_turn' in tools:
                from rpg_core.settlement import DOMAINS
                calls=[{'id':'single_settle','type':'function','function':{'name':'settle_turn','arguments':json.dumps({'checked':list(DOMAINS),'operations':[]})}}]
            REQUESTS.append({'phase':'single_settlement' if calls else 'single_narration','tools':tools})
            packet=json.dumps({'choices':[{'message':{'content':json.dumps({'narrative':'你站在旧路标前，山风带来森林的气息。','options':[]},ensure_ascii=False),'tool_calls':calls}}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(packet)));self.end_headers();self.wfile.write(packet);return
        settle=any(t['function']['name']=='settle_party_round' for t in body.get('tools',[]));calls=[]
        players=data['players'];a,b=players[:2];text=f"{a['name']}的手臂被树枝擦伤。{b['name']}换上了卫衣，朝队友挥手。队伍沿着林间小径走到旧路标前，停下来观察下一条道路。"
        if data.get('opening'):text=f"{a['name']}和{b['name']}在旧路标前会合，山风带来森林的气息。前方的旅途等待各自的选择。"
        if settle:text=data['narrative']
        REQUESTS.append({'phase':'settlement' if settle else 'narration','roles':[m['role'] for m in body['messages']],'tools':[t['function']['name'] for t in body.get('tools',[])],'history_absent':not bool({'recent','events','inputs'}&data.keys()),'actors':len(players)})
        if settle:
            ops=[{'actor_id':a['actor_id'],'name':'damage','args':{'target':'hp','amount':3},'evidence':a['name']+'的手臂被树枝擦伤'},
                {'actor_id':b['actor_id'],'name':'update_clothing','args':{'changes':[{'slot':'upper','garment':'hoodie','evidence':b['name']+'换上了卫衣'}]},'evidence':b['name']+'换上了卫衣'},
                {'actor_id':b['actor_id'],'name':'update_portrait','args':{'changes':{'pose':'cheer'}},'evidence':b['name']+'换上了卫衣，朝队友挥手'},
                {'actor_id':'world','name':'set_flag','args':{'flag':'unknown_demo_flag','value':True},'evidence':'队伍沿着林间小径走到旧路标前'}]
            if '手臂被树枝擦伤' not in text:ops=[]
            calls=[{'id':'settle','type':'function','function':{'name':'settle_party_round','arguments':json.dumps({'operations':ops},ensure_ascii=False)}}];content=''
        else:content=json.dumps({'narrative':text,'options':[{'actor_id':p['actor_id'],'label':'检查旧路标','action_text':'走近检查旧路标上的文字'} for p in players]},ensure_ascii=False)
        if body.get('stream') and not settle:
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for i in range(0,len(content),4):
                packet={'choices':[{'index':0,'delta':{'content':content[i:i+4]},'finish_reason':None}]};self.wfile.write(('data: '+json.dumps(packet,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.035)
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        else:
            result=json.dumps({'choices':[{'message':{'content':content,'tool_calls':calls}}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}},ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
    def log_message(self,*args):pass
model=ThreadingHTTPServer(('127.0.0.1',18895),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
main.manager.session.pack.skills=[SkillSpec(id='party_guard',name='防护术',description='为自己架起一道防护',cost={'focus':2},cooldown=2,targets=['self'],action_text='施展防护术')]
main.manager.settings=merge_update(main.manager.settings,{'roles':{'separated':True,'narrator':{'provider':'openai'},'settler':{'provider':'openai'}},'providers':{'openai':{'preset':'custom','base_url':'http://127.0.0.1:18895/v1','model':'local-party-fixture','max_retries':0}}})
@main.app.get('/__qa/party')
def report():return {'requests':REQUESTS}
main.app.router.routes.insert(0,main.app.router.routes.pop())
if __name__=='__main__':
    import uvicorn
    alternate=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=18896,log_level='warning',access_log=False))
    threading.Thread(target=alternate.run,daemon=True).start()
    uvicorn.run(main.app,host='127.0.0.1',port=18894,log_level='warning')
