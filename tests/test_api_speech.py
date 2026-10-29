import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from test_api_director import api
from test_speech import game, audio_server
from rpg_gateway.speech import SpeechService

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    g,settings,entry,provider=game()
    monkeypatch.setenv('RPG_CONFIG_DIR',str(tmp_path/'config'))
    monkeypatch.setenv('RPG_SAVES',str(tmp_path/'saves'))
    monkeypatch.setenv('RPG_AUTOSAVE','0')
    monkeypatch.setattr(api.manager,'session',g)
    monkeypatch.setattr(api.manager,'settings',settings)
    monkeypatch.setattr(api,'speech_service',SpeechService())
    return TestClient(api.app),g,entry,provider

def test_voice_api_rejects_arbitrary_text_and_other_worlds(fixture):
    client,g,entry,_=fixture;body={'pack_id':g.pack.manifest.id,'entry_id':entry}
    assert client.post('/api/voice/dialogue',json={**body,'pack_id':'other'}).status_code==409
    assert client.post('/api/voice/dialogue',json={**body,'entry_id':'user-1'}).status_code==400
    assert client.post('/api/voice/dialogue',json={**body,'text':'随意朗读旁白'}).status_code==422
    view=client.post('/api/voice/dialogue',json=body).json()
    assert len(view['lines'])==1
    audio={**body,'revision':view['revision'],'line_id':view['lines'][0]['id']}
    assert client.post('/api/voice/audio',json={**audio,'line_id':'f'*24}).status_code==400
    char=view['lines'][0]['character_id']
    assert client.post('/api/voice/character',json={'pack_id':g.pack.manifest.id,'character_id':char,'enabled':False,'voice':'quiet'}).status_code==200
    assert client.post('/api/voice/audio',json=audio).status_code==400

def test_audio_endpoint_returns_playable_bytes_and_never_returns_api_key(fixture,audio_server):
    client,g,entry,_=fixture;url,received,wav=audio_server
    api.manager.settings.speech.base_url=url+'/audio/speech';api.manager.settings.speech.api_key='only-test-voice-key'
    public=client.get('/api/voice');assert 'only-test-voice-key' not in public.text
    body={'pack_id':g.pack.manifest.id,'entry_id':entry};view=client.post('/api/voice/dialogue',json=body).json()
    r=client.post('/api/voice/audio',json={**body,'revision':view['revision'],'line_id':view['lines'][0]['id']})
    assert r.status_code==200 and r.content==wav and r.headers['content-type']=='audio/wav'
    assert r.headers['cache-control']=='no-store'
    assert received[0][0]=='/audio/speech'
    api.manager.settings.speech.enabled=False
    assert client.post('/api/voice/dialogue',json=body).status_code==400

def test_slow_speech_does_not_hold_game_state_lock_and_rechecks_withdrawal(fixture,monkeypatch):
    client,g,entry,_=fixture;body={'pack_id':g.pack.manifest.id,'entry_id':entry}
    view=client.post('/api/voice/dialogue',json=body).json()
    started=threading.Event();release=threading.Event()
    def slow(*args):
        started.set();assert release.wait(5);return b'fake audio','audio/mpeg'
    monkeypatch.setattr('rpg_gateway.speech.synthesize',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(client.post,'/api/voice/audio',json={**body,'revision':view['revision'],'line_id':view['lines'][0]['id']})
        assert started.wait(3)
        try:
            locked=api.manager.lock.acquire(timeout=.3)
            assert locked,'Slow TTS blocked authoritative game state'
            try:g._record(turn=0,kind='turn.rolled_back',payload={'reason':'undo'})
            finally:api.manager.lock.release()
        finally:release.set()
        assert future.result(timeout=3).status_code==409

def test_settings_test_uses_selected_role_instead_of_narrator(fixture,monkeypatch):
    client,g,entry,provider=fixture
    g.router.config.director=g.router.config.narrator.model_copy()
    monkeypatch.setattr(api,'build_router',lambda _:g.router)
    for role in ('narrator','settler','director','voice_cast'):
        r=client.post('/api/settings/test',json={'test_role':role})
        assert r.status_code==200 and r.json()['ok']
    assert len(provider.requests)==4

def test_elevenlabs_mp3_reaches_browser_without_json_conversion(fixture,monkeypatch):
    import json
    from email.message import Message
    from unittest.mock import MagicMock
    client,g,entry,_=fixture
    settings=api.manager.settings.speech
    settings.provider='elevenlabs';settings.base_url='https://api.elevenlabs.io/v1'
    settings.api_key='only-test-eleven-key';settings.model=''
    settings.voice='cJ90yKqmDMAuUmZ3fyB4'
    mp3=b'ID3\x04\x00\xff\xfb\x90\x00'
    response=MagicMock();response.__enter__.return_value=response
    response.headers=Message();response.headers['Content-Type']='audio/mpeg'
    response.read.return_value=mp3
    opener=MagicMock();opener.open.return_value=response
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:opener)
    body={'pack_id':g.pack.manifest.id,'entry_id':entry}
    view=client.post('/api/voice/dialogue',json=body).json()
    audio={**body,'revision':view['revision'],'line_id':view['lines'][0]['id']}
    result=client.post('/api/voice/audio',json=audio)
    assert result.status_code==200 and result.content==mp3
    assert result.headers['content-type']=='audio/mpeg'
    assert result.headers['cache-control']=='no-store'
    req=opener.open.call_args.args[0]
    assert req.full_url.endswith('/v1/text-to-speech/'+settings.voice)
    assert json.loads(req.data)['model_id']=='eleven_multilingual_v2'
    assert 'only-test-eleven-key' not in client.get('/api/voice').text
    assert client.post('/api/voice/audio',json=audio).content==mp3
    assert opener.open.call_count==1

