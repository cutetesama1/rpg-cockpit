import copy,json,time,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from rpg_content import load_pack
from rpg_core.party import PartyManager,PartyError
from rpg_core.contracts import ToolCall
from rpg_gateway.providers import LlmResponse,OpenAICompatibleProvider
from rpg_gateway.party_server import create_party_app,PartyHost

ROOT=Path(__file__).resolve().parents[1]
class Router:
    def __init__(self):self.calls=[];self.ops=[];self.fail=False;self.block=None;self.text=None
    def stream(self,role,request,on_text):
        self.calls.append(copy.deepcopy(request))
        if self.block:self.block.wait(5)
        text=self.text or '阿澄受了轻伤。小岚观察四周。阿澄取到了绷带。小岚换上了衬衫。阿澄把绷带交给小岚。'
        on_text(text[:6]);on_text(text)
        return LlmResponse(raw=json.dumps({'narrative':text,'options':[]},ensure_ascii=False))
    def complete(self,role,request):
        self.calls.append(copy.deepcopy(request))
        if self.fail:raise RuntimeError('mock provider unavailable')
        return LlmResponse(tool_calls=[ToolCall(id='party',name='settle_party_round',args={'operations':self.ops})])

@pytest.fixture
def party(tmp_path):
    router=Router();manager=PartyManager(tmp_path,lambda:router);pack=load_pack(ROOT/'packs/night-convenience-store')
    a=manager.create(pack,ROOT/'packs/night-convenience-store',ROOT/'packs/new-game','阿澄',4)
    b=manager.join(a['invite_code'],'小岚','join_request_123456')
    manager.rooms[a['room_id']]['opening_generated']=True  # Existing generated-world fixtures exercise turn settlement.
    yield manager,router,a,b
    manager.close()

def view(m,p):return m.view(p['room_id'],p['token'])
def act(m,p,text='观察四周',skills=()):
    v=view(m,p);me=next(x for x in v['players'] if x['id']==v['me'])
    return m.intent(p['room_id'],p['token'],'intent_'+str(time.time_ns()),v['round_token'],me['intent_revision'],{'text':text,'skills':list(skills),'modes':['action']})
def ready(m,p,request_id=None):
    v=view(m,p);me=next(x for x in v['players'] if x['id']==v['me'])
    return m.ready(p['room_id'],p['token'],request_id or 'ready_'+str(time.time_ns()),v['round_token'],me['intent_revision'],True)
def finish(m,p):
    for _ in range(300):
        v=view(m,p)
        if v['phase'] in ('collecting','failed') and v['task']:return v
        time.sleep(.01)
    pytest.fail('room did not finish')
def play(m,a,b):act(m,a);act(m,b);ready(m,a);ready(m,b);return finish(m,a)
def state(v,p):return next(x['state'] for x in v['players'] if x['id']==p['player_id'])
def op(p,name,args,evidence,**kw):return {'actor_id':p['player_id'],'name':name,'args':args,'evidence':evidence,**kw}

def test_shared_story_isolated_state_and_no_rollback_for_unknown_flag(party):
    m,r,a,b=party;r.ops=[op(a,'damage',{'amount':3},'阿澄受了轻伤'),{'actor_id':'world','name':'set_flag','args':{'flag':'not_registered','value':True},'evidence':'小岚观察四周'}]
    v=play(m,a,b)
    assert v['phase']=='collecting' and v['round']==1
    assert state(v,a)['hp']==17 and state(v,b)['hp']==20 and v['pending_count']==1
    assert view(m,b)['history']==v['history']
    backend=r.calls[-1];assert backend['phase']=='party_settlement' and 'recent' not in backend and 'inputs' in backend
    assert len(backend['inputs'])==2
    assert {p['actor_id'] for p in backend['players']}=={a['player_id'],b['player_id']}
    assert all('inventory' in p and 'cooldowns' in p for p in backend['players'])

def test_ready_waits_for_everyone_and_does_not_leak_draft(party):
    m,r,a,b=party;act(m,a,'尚未公开的行动')
    va=view(m,b);other=next(p for p in va['players'] if p['id']==a['player_id'])
    assert other['intent'] is None and other['inventory'] is None
    ready(m,a);assert not r.calls
    act(m,b);ready(m,b);assert finish(m,a)['round']==1
    assert len([c for c in r.calls if c['phase']=='party_narration'])==1

def test_skill_cost_is_per_actor_and_paid_once(party):
    m,r,a,b=party;r.ops=[op(a,'damage',{'target':'stamina','amount':2},'阿澄受了轻伤',source='skill_cost')]
    act(m,a,skills=['smash']);act(m,b);ready(m,a);ready(m,b);v=finish(m,a)
    assert state(v,a)['stamina']==8 and state(v,b)['stamina']==10

def test_reject_other_actor_without_name_evidence(party):
    m,r,a,b=party;r.ops=[op(b,'damage',{'amount':3},'阿澄受了轻伤')]
    v=play(m,a,b);assert state(v,b)['hp']==20 and v['pending_count']==1

def test_duplicate_ready_produces_one_round(party):
    m,r,a,b=party;r.block=threading.Event();act(m,a);act(m,b);ready(m,a)
    v=view(m,b);me=next(p for p in v['players'] if p['id']==b['player_id'])
    def go():return m.ready(b['room_id'],b['token'],'same_ready_request',v['round_token'],me['intent_revision'],True)
    with ThreadPoolExecutor(2) as pool:responses=list(pool.map(lambda _:go(),range(2)))
    assert all(x['task']['id']==responses[0]['task']['id'] for x in responses)
    r.block.set();assert finish(m,a)['round']==1
    assert len([c for c in r.calls if c['phase']=='party_narration'])==1

def test_request_collision_and_old_round_are_rejected(party):
    m,r,a,b=party;v=view(m,a)
    m.intent(a['room_id'],a['token'],'request_collision',v['round_token'],0,{'text':'行动甲'})
    with pytest.raises(PartyError):m.intent(a['room_id'],a['token'],'request_collision',v['round_token'],0,{'text':'行动乙'})
    act(m,b);ready(m,a);ready(m,b);finish(m,a)
    with pytest.raises(PartyError):m.intent(a['room_id'],a['token'],'stale_round_request',v['round_token'],1,{'text':'过期行动'})

def test_failure_retry_keeps_narrative_and_costs_uncommitted(party):
    m,r,a,b=party;r.fail=True;act(m,a,skills=['smash']);act(m,b);ready(m,a);ready(m,b);v=finish(m,a)
    assert v['phase']=='failed' and state(v,a)['stamina']==10 and v['task']['narration_complete']
    with pytest.raises(PartyError):m.retry(b['room_id'],b['token'],'nonhost_retry')
    r.fail=False;m.retry(a['room_id'],a['token'],'host_retry_request');v=finish(m,a)
    assert v['round']==1 and state(v,a)['stamina']==8
    assert len([c for c in r.calls if c['phase']=='party_narration'])==1

def test_undo_requires_unanimity_restores_both_and_invalidates_replay(party):
    m,r,a,b=party;r.ops=[op(a,'damage',{'amount':3},'阿澄受了轻伤')];play(m,a,b)
    v=m.propose_undo(a['room_id'],a['token']);assert v['round']==1 and v['phase']=='undo_pending'
    v=m.vote_undo(b['room_id'],b['token'],v['undo']['id'],True)
    assert v['round']==0 and state(v,a)['hp']==20 and not v['history']
    act(m,a);act(m,b);ready(m,a);ready(m,b);assert finish(m,a)['round']==1

def test_rejecting_undo_keeps_progress(party):
    m,r,a,b=party;play(m,a,b);v=m.propose_undo(a['room_id'],a['token'])
    v=m.vote_undo(b['room_id'],b['token'],v['undo']['id'],False)
    assert v['round']==1 and v['phase']=='collecting' and not v['undo']

def test_persisted_room_reconnects_with_same_scoped_token(party):
    m,r,a,b=party;play(m,a,b)
    restored=PartyManager(m.directory,lambda:r)
    try:
        assert view(restored,a)['round']==1 and view(restored,b)['history']==view(m,b)['history']
    finally:restored.close()

def test_room_auth_and_remote_admin_isolation(party,tmp_path):
    m,r,a,b=party;client=TestClient(create_party_app(m,tmp_path))
    root='/api/rooms/'+a['room_id']
    assert client.get(root+'/state').status_code==401
    assert client.get(root+'/state',headers={'Authorization':'Bearer wrong'}).status_code==403
    assert client.get('/api/settings').status_code==404
    assert client.post('/api/multiplayer/host/rooms',json={}).status_code==404
    headers={'Authorization':'Bearer '+a['token']}
    assert client.get(root+'/state',headers=headers).json()['me']==a['player_id']
    with pytest.raises(PartyError):m.asset(a['room_id'],a['token'],'ui/../../settings.json')
    other=m.create(m._pack(m.rooms[a['room_id']]),tmp_path,tmp_path,'另一房主')
    assert client.get('/api/rooms/'+other['room_id']+'/state',headers=headers).status_code==403

def test_room_four_player_cap_and_no_midgame_join(party):
    m,r,a,b=party;m.rooms[a['room_id']]['opening_generated']=False
    c=m.join(a['invite_code'],'第三位','third_join_request');d=m.join(a['invite_code'],'第四位','fourth_join_request')
    with pytest.raises(PartyError):m.join(a['invite_code'],'第五位','fifth_join_request')
    m.rooms[a['room_id']]['opening_generated']=True
    for p in [a,b,c,d]:act(m,p);ready(m,p)
    assert finish(m,a)['round']==1
    with pytest.raises(PartyError):m.join(a['invite_code'],'迟到队友','late_join_request')

def test_unique_item_and_transfer_are_atomic(party):
    m,r,a,b=party;room=m.rooms[a['room_id']];item=m._pack(room).items[0].id;room['unique_items']=[item]
    r.ops=[op(a,'add_item',{'item_id':item,'count':1},'阿澄取到了绷带'),op(b,'add_item',{'item_id':item,'count':1},'小岚观察四周')]
    v=play(m,a,b);assert v['pending_count']==1 and next(p for p in v['players'] if p['id']==a['player_id'])['inventory'][item]==1
    r.ops=[op(a,'transfer_item',{'to_actor_id':b['player_id'],'item_id':item,'count':1},'阿澄把绷带交给小岚')]
    play(m,a,b);va=view(m,a);vb=view(m,b)
    assert next(p for p in va['players'] if p['id']==a['player_id'])['inventory'][item]==0
    assert next(p for p in vb['players'] if p['id']==b['player_id'])['inventory'][item]==1

def test_events_resume_only_target_room_and_no_tokens(party):
    m,r,a,b=party;cursor=view(m,a)['cursor'];act(m,a);rows=m.events(a['room_id'],b['token'],cursor)
    assert len(rows)==1 and rows[0]['kind']=='intent.updated'
    assert a['token'] not in json.dumps(rows) and '尚未公开' not in json.dumps(rows)

def test_host_create_is_idempotent(party):
    m,r,a,b=party;pack=m._pack(m.rooms[a['room_id']]);root=ROOT/'packs/new-game'
    c=m.create(pack,root,root,'新房主',request_id='create_request_123')
    assert m.create(pack,root,root,'新房主',request_id='create_request_123')==c
    with pytest.raises(PartyError):m.create(pack,root,root,'不同房主',request_id='create_request_123')

def test_model_wire_no_backend_history_and_exactly_one_party_tool():
    provider=OpenAICompatibleProvider(base_url='http://127.0.0.1:9999/v1',api_key='not-real',model='test')
    body=provider._payload({'phase':'party_settlement','system_prompt':'stateless','players':[],'narrative':'正文','recent':['must not leak']})
    assert len(body['tools'])==1 and body['tools'][0]['function']['name']=='settle_party_round'
    assert 'must not leak' not in json.dumps(body['messages'])
    body=provider._payload({'phase':'party_narration','system_prompt':'story','allow_tools':False,'players':[],'inputs':[]})
    assert 'tools' not in body

def test_failed_database_commit_cannot_mutate_authority(party,monkeypatch):
    m,r,a,b=party;r.ops=[op(a,'damage',{'amount':3},'阿澄受了轻伤')]
    original=m._save
    def save(room,kind,payload,before=None):
        if kind=='state.committed':raise OSError('simulated disk failure')
        return original(room,kind,payload,before)
    monkeypatch.setattr(m,'_save',save);v=play(m,a,b)
    assert v['phase']=='failed' and v['round']==0 and state(v,a)['hp']==20

def test_http_intent_cannot_claim_another_player(party,tmp_path):
    m,r,a,b=party;client=TestClient(create_party_app(m,tmp_path));v=view(m,a)
    res=client.put('/api/rooms/'+a['room_id']+'/intent',headers={'Authorization':'Bearer '+a['token']},json={'request_id':'unauthorized_actor','round_token':v['round_token'],'expected_intent_revision':0,'intent':{'text':'hello'},'actor_id':b['player_id']})
    assert res.status_code==422

def test_live_listener_has_no_single_player_api(party,tmp_path):
    import urllib.request,urllib.error
    m,r,a,b=party;service=PartyHost(m,tmp_path,port=0);service.start()
    try:
        assert json.load(urllib.request.urlopen(f'http://127.0.0.1:{service.port}/api/party/health'))['ok']
        with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(f'http://127.0.0.1:{service.port}/api/settings')
    finally:service.stop()

def test_unlabelled_double_skill_fee_is_rejected_without_losing_round(party):
    m,r,a,b=party;r.ops=[op(a,'damage',{'target':'stamina','amount':2},'阿澄受了轻伤')]
    act(m,a,skills=['smash']);act(m,b);ready(m,a);ready(m,b);v=finish(m,a)
    assert v['round']==1 and state(v,a)['stamina']==8 and v['pending_count']==1

def test_cancel_failed_round_preserves_all_authority(party):
    m,r,a,b=party;r.fail=True;act(m,a,skills=['smash']);act(m,b);ready(m,a);ready(m,b);finish(m,a)
    with pytest.raises(PartyError):m.cancel_failed(b['room_id'],b['token'])
    v=m.cancel_failed(a['room_id'],a['token']);assert v['phase']=='collecting' and not v['task'] and v['round']==0 and state(v,a)['stamina']==10

def test_cooldown_advances_on_committed_shared_rounds(party):
    m,r,a,b=party;act(m,a,skills=['first_aid']);act(m,b);ready(m,a);ready(m,b);finish(m,a)
    with pytest.raises(PartyError):act(m,a,skills=['first_aid'])
    play(m,a,b);act(m,a,skills=['first_aid'])

def test_restarted_inflight_room_becomes_retryable(party):
    m,r,a,b=party;room=m.rooms[a['room_id']]
    act(m,a);act(m,b);r.block=threading.Event();ready(m,a);ready(m,b)
    restored=PartyManager(m.directory,lambda:Router())
    try:assert view(restored,a)['phase']=='failed' and view(restored,a)['round']==0
    finally:r.block.set();finish(m,a);restored.close()

def test_clothing_and_portrait_apply_to_named_actor_only(tmp_path):
    m=PartyManager(tmp_path,lambda:router);router=Router();pack=__import__('test_portrait').fixture_pack();pack.state.by_id()['pose'].enum_values.append('cheer');pack.sprites.controls['pose']['cheer']='欢呼表现';a=m.create(pack,ROOT/'packs/new-game',ROOT/'packs/new-game','阿澄');b=m.join(a['invite_code'],'小岚','clothing_join_request')
    router.ops=[op(b,'update_clothing',{'changes':[{'slot':'upper','garment':'hoodie','evidence':'小岚换上了卫衣'}]},'小岚换上了卫衣'),op(b,'update_portrait',{'changes':{'pose':'cheer'}},'小岚换上了卫衣')]
    router.text='阿澄观察四周。小岚换上了卫衣，向队友挥手。';m.rooms[a['room_id']]['opening_generated']=True
    try:
        original=state(view(m,a),a)['upper'];v=play(m,a,b)
        assert state(v,b)['upper']=='hoodie' and state(v,b)['pose']=='cheer' and state(v,a)['upper']==original and not v['pending_count']
    finally:m.close()

def test_lan_relay_rejects_unrelated_hosts_ports_paths_and_origins():
    import main
    client=TestClient(main.app)
    for target in ['http://8.8.8.8:8790/api/party/health','http://192.168.1.1:80/api/party/health','http://127.0.0.1:8790/api/settings','http://127.0.0.1:8790/api/rooms/room_aaaaaaaaaaaaaaaaaaaaaaaa/assets/ui/../../settings.json']:
        assert client.get('/api/multiplayer/relay',params={'target':target}).status_code==403
    assert client.get('/api/multiplayer/host/status',headers={'Origin':'https://unrelated.invalid'}).status_code==403

def test_lan_bridge_forwards_scoped_room_session(party):
    import main
    m,r,a,b=party;service=PartyHost(m,ROOT/'ui/dist',port=0);service.start()
    try:
        client=TestClient(main.app);base=f'http://127.0.0.1:{service.port}';assert client.post('/api/multiplayer/connections',json={'server_url':base}).status_code==200;target=base+f'/api/rooms/{a["room_id"]}/state'
        assert client.get('/api/multiplayer/relay',params={'target':target}).status_code==401
        result=client.get('/api/multiplayer/relay',params={'target':target},headers={'Authorization':'Bearer '+a['token']})
        assert result.status_code==200 and result.json()['me']==a['player_id']
    finally:
        service.stop();service.thread.join(timeout=3)

def test_bundled_asset_roots_rebase_after_exe_restarts(tmp_path):
    m=PartyManager(tmp_path/'data',lambda:Router());pack=load_pack(ROOT/'packs/new-game')
    a=m.create(pack,tmp_path/'removed-extraction/packs/new-game',tmp_path/'removed-extraction/packs/new-game','重连角色')
    try:
        m.rebase_assets(ROOT/'packs');room=m.rooms[a['room_id']]
        assert Path(room['asset_root'])==(ROOT/'packs/new-game').resolve()
        assert Path(room['fallback_root'])==(ROOT/'packs/new-game').resolve()
    finally:m.close()

def test_device_room_session_persists_without_model_credentials(party):
    import main
    m,r,a,b=party;client=TestClient(main.app)
    payload={k:a[k] for k in ('room_id','player_id','token')};payload['server_url']='http://127.0.0.1:8790'
    assert client.post('/api/multiplayer/client-session',json={'session':payload}).status_code==200
    assert client.get('/api/multiplayer/client-session').json()['session']==payload
    assert client.get('/api/multiplayer/client-session',headers={'Origin':'https://unrelated.invalid'}).status_code==403
    assert client.post('/api/multiplayer/client-session',json={'session':{**payload,'api_key':'not allowed'}}).status_code==422
    assert client.post('/api/multiplayer/client-session',json={'session':None}).status_code==200
