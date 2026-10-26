import json,time,threading,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from rpg_content import load_pack
from rpg_core.party import PartyManager,PartyError
from rpg_gateway.providers import LlmResponse
from rpg_gateway.tunnel_connections import RoomConnections,origin
ROOT=Path(__file__).resolve().parents[1]

class Router:
    def __init__(self):self.calls=[];self.wait=threading.Event();self.wait.set();self.fail=False
    def stream(self,role,request,on_text):
        self.calls.append(request);self.wait.wait(5);on_text('队伍在旧路标前会合。')
        return LlmResponse(raw=json.dumps({'narrative':'队伍在旧路标前会合。','options':[]}))
    def complete(self,role,request):
        if self.fail:raise RuntimeError('offline')
        return LlmResponse(raw='{"operations":[]}')
def wait(m,a):
    for _ in range(500):
        v=m.view(a['room_id'],a['token'])
        if v['phase'] in ('collecting','failed') and v['task']:return v
        time.sleep(.01)
    pytest.fail('timeout')
@pytest.fixture
def fresh(tmp_path):
    r=Router();m=PartyManager(tmp_path,lambda:r);p=load_pack(ROOT/'packs/new-game');a=m.create(p,ROOT/'packs/new-game',ROOT/'packs/new-game','甲');b=m.join(a['invite_code'],'乙','join_new_opening_1')
    yield m,r,a,b
    r.wait.set();m.close()
def test_create_join_refresh_do_not_generate_and_intent_requires_start(fresh):
    m,r,a,b=fresh;v=m.view(a['room_id'],a['token']);m.view(b['room_id'],b['token'])
    assert not r.calls and not v['opening_generated'] and not v['opening'] and not v['opening_text']
    with pytest.raises(PartyError):m.intent(a['room_id'],a['token'],'intent_before_start',v['round_token'],0,{'text':'行动'})
    with pytest.raises(PartyError):m.generate_opening(b['room_id'],b['token'],'guest_start_request')
def test_host_start_is_idempotent_and_opening_is_turn_zero(fresh):
    m,r,a,b=fresh;r.wait.clear()
    def start():return m.generate_opening(a['room_id'],a['token'],'same_start_request')
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:start(),range(2)))
    assert results[0]['task']['id']==results[1]['task']['id'];r.wait.set();v=wait(m,a)
    assert v['opening_generated'] and v['round']==0 and v['opening']['narrative']=='队伍在旧路标前会合。' and not v['history']
    assert len(r.calls)==1 and r.calls[0]['opening'] and all(not i['text'] and not i['skills'] for i in r.calls[0]['inputs'])
    m.generate_opening(a['room_id'],a['token'],'different_start_request');assert len(r.calls)==1
    with pytest.raises(PartyError):m.join(a['invite_code'],'丙','late_opening_join_1')
def test_failed_opening_retries_only_settlement(fresh):
    m,r,a,b=fresh;r.fail=True;m.generate_opening(a['room_id'],a['token'],'failed_start_request');v=wait(m,a)
    assert v['phase']=='failed' and not v['opening_generated']
    r.fail=False;m.retry(a['room_id'],a['token'],'retry_start_request');v=wait(m,a)
    assert v['opening_generated'] and len(r.calls)==1
def test_one_player_cannot_generate_shared_start(tmp_path):
    r=Router();m=PartyManager(tmp_path,lambda:r);p=load_pack(ROOT/'packs/new-game');a=m.create(p,ROOT/'packs/new-game',ROOT/'packs/new-game','甲')
    try:
        with pytest.raises(PartyError):m.generate_opening(a['room_id'],a['token'],'one_player_start')
        assert not r.calls
    finally:m.close()

class Remote(BaseHTTPRequestHandler):
    received=[]
    def do_GET(self):
        self.received.append((self.path,self.headers.get('Authorization')))
        body=json.dumps({'mode':'cooperative','protocol':1,'ok':True}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
def test_named_tunnel_origin_custom_port_selected_without_sending_credentials(tmp_path):
    Remote.received=[];server=ThreadingHTTPServer(('127.0.0.1',0),Remote);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://localhost:{server.server_port}'
    try:
        selected=RoomConnections(tmp_path/'connections.json');assert not selected.permits(base)
        assert selected.select(base)==base and selected.permits(base+'/api/rooms/join')
        assert Remote.received==[('/api/party/health',None)]
        assert not selected.permits(f'http://localhost:{server.server_port+1}/api/rooms/join')
        assert RoomConnections(tmp_path/'connections.json').permits(base)
    finally:server.shutdown();server.server_close()
def test_public_ipv6_and_default_https_origins_normalize():
    assert origin('https://Tunnel.Example:443/api/party/health')=='https://tunnel.example'
    assert origin('http://[2001:db8::1]:32100')=='http://[2001:db8::1]:32100'
    for value in ['file:///x','https://user:pass@host','https://host:99999','https://host?token=secret']:
        with pytest.raises(PartyError):origin(value)
def test_relay_uses_only_selected_host_and_keeps_admin_paths_blocked():
    import main
    Remote.received=[];server=ThreadingHTTPServer(('127.0.0.1',0),Remote);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://localhost:{server.server_port}';client=TestClient(main.app)
    try:
        assert client.get('/api/multiplayer/relay',params={'target':base+'/api/party/health'}).status_code==403
        assert client.post('/api/multiplayer/connections',json={'server_url':base},headers={'Origin':'https://unrelated.invalid'}).status_code==403
        assert client.post('/api/multiplayer/connections',json={'server_url':base}).status_code==200
        headers={'Authorization':'Bearer scoped-room-session'}
        assert client.get('/api/multiplayer/relay',params={'target':base+'/api/party/health'},headers=headers).status_code==200
        assert Remote.received[-1][1]=='Bearer scoped-room-session'
        assert client.get('/api/multiplayer/relay',params={'target':base+'/api/settings'},headers=headers).status_code==403
    finally:server.shutdown();server.server_close()
