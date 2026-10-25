import io,json,threading,urllib.error,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from rpg_gateway import default_settings,merge_update,build_router
from rpg_gateway.providers import OpenAICompatibleProvider
from rpg_gateway.model_list import list_endpoint_models,ModelListError
from rpg_gateway.http_identity import USER_AGENT,cloudflare_1010_hint

class Gateway(BaseHTTPRequestHandler):
    received=[];block=False;fallback=False
    def log_message(self,*args):pass
    def reply(self,status,data,content_type='application/json',extra=None):
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)))
        for key,value in (extra or {}).items():self.send_header(key,value)
        self.end_headers();self.wfile.write(data)
    def process(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
        self.received.append({'path':self.path,'ua':self.headers.get('User-Agent'),'authorization':self.headers.get('Authorization'),'accept':self.headers.get('Accept'),'body':data})
        if self.block or self.headers.get('User-Agent','').startswith('Python-urllib'):
            # The significant Cloudflare code occurs beyond the previous 300-byte truncation.
            body=('<!doctype html><html><head>'+(' '*3000)+'</head><body>Error code: 1010 Cloudflare '+self.headers.get('Authorization','')+'</body></html>').encode()
            self.reply(403,body,'text/html',{'Server':'cloudflare','CF-Ray':'fixture-ray-SJC'});return
        if self.path.endswith('/models'):
            self.reply(200,b'{"data":[{"id":"own-model","owned_by":"local"}]}');return
        if self.path.endswith('/audio/speech'):
            self.reply(200,b'ID3fixture-audio','audio/mpeg');return
        if data.get('stream'):
            if self.fallback:self.reply(400,b'{"error":"stream unsupported"}');return
            content=json.dumps({'narrative':'山风拂过你的衣角。','options':[]},ensure_ascii=False)
            packets=[{'choices':[{'index':0,'delta':{'content':content[:10]}}]},{'choices':[{'index':0,'delta':{'content':content[10:]},'finish_reason':'stop'}]}]
            payload=''.join('data: '+json.dumps(p,ensure_ascii=False)+'\n\n' for p in packets)+'data: [DONE]\n\n'
            self.reply(200,payload.encode(),'text/event-stream');return
        content=json.dumps({'narrative':'山风拂过你的衣角。','options':[]},ensure_ascii=False)
        self.reply(200,json.dumps({'choices':[{'message':{'content':content}}],'model':'own-model'}).encode())
    do_GET=process
    do_POST=process

@pytest.fixture
def gateway():
    Gateway.received=[];Gateway.block=False;Gateway.fallback=False
    server=ThreadingHTTPServer(('127.0.0.1',0),Gateway);threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}/v1',Gateway
    server.shutdown();server.server_close()

def test_default_urllib_rejected_but_application_ua_accepts_own_gateway(gateway):
    base,server=gateway
    with pytest.raises(urllib.error.HTTPError) as caught:urllib.request.urlopen(base+'/models')
    assert caught.value.code==403 and server.received[-1]['ua'].startswith('Python-urllib/')
    result=list_endpoint_models(base,'test-key-only')
    assert result['models'][0]['id']=='own-model' and server.received[-1]['ua']==USER_AGENT

def test_model_json_and_sse_share_identity_and_preserve_auth_and_accept(gateway):
    base,server=gateway;provider=OpenAICompatibleProvider(base,api_key='test-key-only',model='own-model',max_retries=0)
    assert provider.complete({'allow_tools':False}).narrator.narrative=='山风拂过你的衣角。'
    updates=[];assert provider.stream({'allow_tools':False},updates.append).narrator.narrative=='山风拂过你的衣角。'
    assert updates and server.received[-1]['accept']=='text/event-stream'
    assert all(r['ua']==USER_AGENT and r['authorization']=='Bearer test-key-only' for r in server.received)
    assert all('test-key-only' not in r['path'] and 'test-key-only' not in r['ua'] for r in server.received)

def test_stream_fallback_keeps_identity(gateway):
    base,server=gateway;server.fallback=True
    p=OpenAICompatibleProvider(base,api_key='test-key-only',model='own-model',max_retries=0)
    assert p.stream({'allow_tools':False},lambda text:None).narrator
    assert len(server.received)>=2 and all(r['ua']==USER_AGENT for r in server.received)

def test_all_model_roles_use_application_ua(gateway):
    base,server=gateway
    roles=('narrator','settler','director','setup','arbiter','corrector')
    settings=merge_update(default_settings(),{'roles':{'separated':True,**{r:{'provider':'own','model':'own-model'} for r in roles}},'providers':{'own':{'preset':'custom','base_url':base,'api_key':'test-key-only','model':'own-model','max_retries':0}}})
    router=build_router(settings)
    for role in roles:router.complete(role,{'allow_tools':False})
    assert len(server.received)==6 and all(r['ua']==USER_AGENT for r in server.received)

@pytest.mark.parametrize('kind',['models','complete','stream'])
def test_cloudflare_1010_is_explicit_and_does_not_echo_secrets(gateway,kind):
    base,server=gateway;server.block=True
    with pytest.raises((RuntimeError,ValueError)) as caught:
        if kind=='models':list_endpoint_models(base,'never-display-key')
        else:
            provider=OpenAICompatibleProvider(base,api_key='never-display-key',model='own-model',max_retries=0)
            provider.complete({'allow_tools':False}) if kind=='complete' else provider.stream({'allow_tools':False},lambda text:None)
    error=str(caught.value)
    assert 'Cloudflare 1010' in error and USER_AGENT in error and 'fixture-ray-SJC' in error
    assert 'never-display-key' not in error and '<html' not in error
    assert len(server.received)==1

def test_plain_401_not_misreported_as_cloudflare(gateway):
    assert cloudflare_1010_hint(401,'invalid key',{'Server':'cloudflare'})==''
    assert cloudflare_1010_hint(403,'error code 1020',{'Server':'cloudflare'})==''
