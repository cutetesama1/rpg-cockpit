import io
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from rpg_core.contracts import LlmProfile, ProviderSettings, VoiceSettings
from rpg_gateway import default_settings, merge_update, public_view, build_router
from rpg_gateway.providers import LlmResponse, OpenAICompatibleProvider
from rpg_gateway.speech import SpeechService, quotes_in, narrative_for, synthesize, character_id
from conftest import make_session


class CastProvider:
    name='cast'
    def __init__(self, items=()):self.requests=[];self.items=list(items)
    def complete(self,request):
        self.requests.append(request)
        return LlmResponse(raw=json.dumps({'lines':self.items},ensure_ascii=False),provider=self.name)

def game(text='莉瑟说：“沿着灯光走。”你说：“我知道了。”你心想：“先休息吧。”', *, imported=True, items=()):
    provider=CastProvider(items)
    session=make_session(provider)
    session.router.config.voice_cast=LlmProfile(provider='cast')
    roster={'enabled':False,'npcs':[]}
    if imported:roster['npcs']=[{'id':'npc_'+'a'*20,'name':'莉瑟','personality':'温和','source_hash':'b'*64}]
    session._record(turn=0,kind='npc.roster.configured',payload={'roster':roster})
    session._record(turn=0,kind='narrative.generated',payload={'narrative':text,'opening':True})
    event=session.ledger.events[-1]
    settings=default_settings();settings.speech=VoiceSettings(enabled=True,model='test-speech',base_url='https://voice.test/v1')
    return session,settings,'ai-'+str(event.seq),provider

def test_keys_copy_into_independent_role_slots_and_never_leak():
    settings=default_settings()
    settings.providers['old']=ProviderSettings(base_url='https://old.test/v1',api_key='secret-key-abc',model='old')
    settings.roles.narrator=LlmProfile(provider='old')
    update={'roles':{'separated':True},'providers':{},'speech':{'api_key':'voice-secret','model':'speech'}}
    for role in ('narrator','settler','director','setup','arbiter','corrector','voice_cast'):
        update['roles'][role]={'provider':'role_'+role}
        update['providers']['role_'+role]={'copy_from':'old','base_url':'https://'+role+'.test/v1','model':role}
    merged=merge_update(settings,update)
    assert all(merged.providers['role_'+r].api_key=='secret-key-abc' for r in update['roles'] if r!='separated')
    changed=merge_update(merged,{'providers':{'role_settler':{'api_key':'backend-only','base_url':'https://changed.test/v1'}}})
    assert changed.providers['role_narrator'].api_key=='secret-key-abc'
    assert changed.providers['role_director'].base_url=='https://director.test/v1'
    assert changed.providers['role_settler'].api_key=='backend-only'
    view=json.dumps(public_view(changed));assert all(key not in view for key in ('secret-key-abc','backend-only','voice-secret'))
    assert merge_update(changed,{'speech':{'api_key':'','speed':1.5}}).speech.api_key=='voice-secret'

def test_independent_director_is_not_overridden_by_legacy_reuse_switch():
    settings=default_settings();settings.roles.separated=True
    for role in ('narrator','settler','director'):
        settings.providers['role_'+role]=ProviderSettings(base_url='https://'+role+'.test/v1',model=role)
        setattr(settings.roles,role,LlmProfile(provider='role_'+role))
    router=build_router(settings)
    for name in router.providers:
        router.providers[name]=CastProvider()
        router.providers[name].name=name
    router.complete('narrator',{'phase':'narration'})
    router.complete('settler',{'phase':'settlement'})
    router.complete('director',{'phase':'director','reuse_narrator':True})
    assert [len(router.providers['role_'+r].requests) for r in ('narrator','settler','director')]==[1,1,1]

def test_imported_only_reads_named_npc_dialogue_without_model(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    session,settings,entry,provider=game()
    service=SpeechService();before=dict(session.state)
    result=service.analyze(session,settings,entry)
    assert [line['text'] for line in result['lines']]==['沿着灯光走。']
    assert not provider.requests and session.state==before and session.turn==0
    key=result['lines'][0]['character_id'];service.configure_character(session,key,False,'soft')
    assert not service.analyze(session,settings,entry)['lines'][0]['enabled']
    with pytest.raises(ValueError,match='关闭'):service.speak(session,settings,entry,result['revision'],result['lines'][0]['id'])
    assert SpeechService().characters(session)[0]['voice']=='soft'

def test_npc_addressing_player_is_not_mistaken_for_player_speech(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    session,settings,entry,_=game('莉瑟对你说道：“欢迎回来。”你说：“谢谢。”')
    assert [l['text'] for l in SpeechService().analyze(session,settings,entry)['lines']]==['欢迎回来。']

def test_automatic_cast_validates_quotes_and_public_context_and_caches(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    session,settings,entry,provider=game('守门人说：“请出示通行证。”你说：“好的。”你心想：“他很警觉。”',imported=False,
      items=[{'index':0,'kind':'npc','name':'守门人','description':'守在城门'}, {'index':1,'kind':'npc','name':'守门人'}, {'index':2,'kind':'npc','name':'守门人'}, {'index':9,'kind':'npc','name':'幽灵'}])
    settings.speech.mode='automatic';service=SpeechService()
    session._record(turn=0,kind='worldbook.updated',payload={'entry':{'id':'secret','kind':'secret','title':'秘密姓名','content':'不得泄露','visibility':'internal','status':'active'}})
    result=service.analyze(session,settings,entry)
    assert [line['text'] for line in result['lines']]==['请出示通行证。']
    assert provider.requests[0]['phase']=='voice_cast'
    assert '不得泄露' not in json.dumps(provider.requests,ensure_ascii=False)
    service.analyze(session,settings,entry);assert len(provider.requests)==1
    char=result['characters'][0];assert char['name']=='守门人' and char['source']=='automatic'
    other,_,_,_=game(imported=False);other.pack.manifest.id='another-world'
    assert not service.characters(other)
    settings.speech.mode='imported';assert not service.analyze(session,settings,entry)['lines']

def test_only_canonical_completed_and_current_narratives_can_be_read(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    session,settings,entry,_=game();service=SpeechService();result=service.analyze(session,settings,entry)
    with pytest.raises(ValueError):narrative_for(session,'user-1')
    with pytest.raises(ValueError):narrative_for(session,'live-narrative-2')
    session._record(turn=1,kind='narrative.generated',payload={'narrative':'莉瑟说：“旧台词。”'})
    incomplete='ai-'+str(session.ledger.events[-1].seq)
    with pytest.raises(ValueError,match='等待'):narrative_for(session,incomplete)
    event=next(e for e in session.ledger.events if 'ai-'+str(e.seq)==entry)
    session._record(turn=-1,kind='correction.applied',payload={'mode':'narrative','target_seq':event.seq,'anchor':0,'narrative':'莉瑟说：“新台词。”','options':[]})
    with pytest.raises(ValueError,match='更改'):service.speak(session,settings,entry,result['revision'],result['lines'][0]['id'])

@pytest.fixture
def audio_server():
    received=[];buffer=io.BytesIO()
    with wave.open(buffer,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*800)
    wav=buffer.getvalue()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path,self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200);self.send_header('Content-Type','audio/wav');self.end_headers();self.wfile.write(wav)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',received,wav
    finally:server.shutdown();server.server_close()

def test_real_http_speech_sends_only_selected_npc_text_and_caches(audio_server,tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    url,received,wav=audio_server;session,settings,entry,_=game();settings.speech.base_url=url+'/v1';settings.speech.api_key='voice-test-only'
    service=SpeechService();view=service.analyze(session,settings,entry);line=view['lines'][0]
    assert service.speak(session,settings,entry,view['revision'],line['id'])==(wav,'audio/wav')
    service.speak(session,settings,entry,view['revision'],line['id'])
    assert len(received)==1 and received[0][0]=='/v1/audio/speech'
    assert received[0][1]=='Bearer voice-test-only'
    assert received[0][2]=={'model':'test-speech','voice':'alloy','input':'沿着灯光走。','response_format':'mp3','speed':1.0}
    service.configure_character(session,line['character_id'],True,'another-voice')
    service.speak(session,settings,entry,view['revision'],line['id']);assert received[-1][2]['voice']=='another-voice'

def test_voice_recognition_wire_request_has_no_tools_history_or_state():
    provider=OpenAICompatibleProvider(base_url='https://example.test/v1',api_key='',model='cast')
    request={'phase':'voice_cast','allow_tools':False,'system_prompt':'classify','narrative':'守卫说：“停下。”','quotes':[{'index':0,'text':'停下。'}],'characters':[], 'state':{'secret':1},'recent':'private history'}
    wire=provider._payload(request)
    assert 'tools' not in wire and len(wire['messages'])==2
    assert 'private history' not in json.dumps(wire) and 'secret' not in json.dumps(wire)

@pytest.mark.parametrize('kwargs',[{'speed':float('nan')},{'speed':5},{'mode':'all'},{'timeout':0}])
def test_invalid_voice_settings_rejected(kwargs):
    with pytest.raises(ValueError):VoiceSettings(**kwargs)

def test_speech_provider_defaults_and_settings_roundtrip(tmp_path):
    from rpg_gateway.settings import save_settings, load_settings
    assert VoiceSettings().provider == 'openai'
    settings = merge_update(default_settings(), {'speech': {
        'provider': 'elevenlabs', 'base_url': 'https://api.elevenlabs.io/v1',
        'api_key': 'only-test-eleven-key', 'model': '', 'voice': 'cJ90yKqmDMAuUmZ3fyB4',
    }})
    path = tmp_path / 'settings.json'
    save_settings(settings, path)
    restored = load_settings(path)
    assert restored.speech.provider == 'elevenlabs'
    assert restored.speech.api_key == 'only-test-eleven-key'
    assert 'only-test-eleven-key' not in json.dumps(public_view(restored))
    assert merge_update(restored, {'speech': {'api_key': ''}}).speech.api_key == 'only-test-eleven-key'
    with pytest.raises(ValueError):VoiceSettings(provider='unknown')

def test_real_http_cast_response_unwraps_completion_envelope(tmp_path,monkeypatch):
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path))
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            content=json.dumps({'lines':[{'index':0,'kind':'npc','name':'守门人'}]},ensure_ascii=False)
            data=json.dumps({'choices':[{'message':{'content':content}}],'model':'cast-test','usage':{}}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        session,settings,entry,_=game('守门人说：“请出示通行证。”',imported=False)
        settings.speech.mode='automatic'
        session.router.providers['cast']=OpenAICompatibleProvider(base_url=f'http://127.0.0.1:{server.server_port}/v1',api_key='',model='cast-test')
        result=SpeechService().analyze(session,settings,entry)
        assert [line['name'] for line in result['lines']]==['守门人']
        assert [line['text'] for line in result['lines']]==['请出示通行证。']
    finally:server.shutdown();server.server_close()

