import base64,json
import pytest
from test_api_library import client,manager
from test_character_cards import card,encoded,png,charx

def upload(value=None,**options):
    return {'filename':'card.json','data_base64':base64.b64encode(encoded(value or card())).decode(),'options':options}
def prepared(client,**options):
    body=upload(**options);p=client.post('/api/character-cards/preview',json=body)
    assert p.status_code==200,p.text
    return {**body,'preview_token':p.json()['preview_token'],'expected_pack_id':p.json()['active_pack_id'],'request_id':'import-one'}

def test_preview_is_read_only_then_import_export_and_retry_are_exact(client):
    before=manager.session
    body=prepared(client,id='imported-card',user_name='旅人')
    assert manager.session is before and not manager.user_dir.exists()
    result=client.post('/api/character-cards/import',json=body);assert result.status_code==200,result.text
    assert result.json()['imported_pack_id']=='imported-card'
    source=client.get('/api/character-cards/source?pack_id=imported-card');assert source.json()==card()
    original=client.get('/api/character-cards/source-file');assert original.content==encoded(card())
    current=client.get('/api/character-cards/current').json()['card'];assert current['name']=='莉瑟'
    assert 'raw' not in current and 'DO_NOT_EXECUTE' not in json.dumps(current)
    assert client.post('/api/opening',json={}).json()['narrative']=='导师向旅人点头。'
    session=manager.session
    retry=client.post('/api/character-cards/import',json=body)
    assert retry.status_code==200 and retry.json()['reused'] and manager.session is session

def test_changed_options_preview_token_and_active_world_cannot_be_replayed(client):
    body=prepared(client,id='card-one');body['options']['role']='player'
    assert client.post('/api/character-cards/import',json=body).status_code==409
    body=prepared(client,id='card-one');body['expected_pack_id']='different-game'
    assert client.post('/api/character-cards/import',json=body).status_code==409
    assert client.get('/api/character-cards/source?pack_id=wrong').status_code==409

def test_same_id_never_overwrites_and_same_request_id_cannot_change_payload(client):
    a=prepared(client,id='card-once');assert client.post('/api/character-cards/import',json=a).status_code==200
    b=prepared(client,id='card-twice')
    assert client.post('/api/character-cards/import',json=b).status_code==409
    b['request_id']='another-import';b['options']['id']='card-once'
    b['preview_token']=client.post('/api/character-cards/preview',json={k:b[k] for k in ('filename','data_base64','options')}).json()['preview_token']
    assert client.post('/api/character-cards/import',json=b).status_code==400

@pytest.mark.parametrize('raw,filename',[(png(ccv3=card()),'card.png'),(charx(card(),{'assets/other/file.txt':b'kept'}),'card.charx')])
def test_png_and_charx_original_files_export_byte_for_byte(client,raw,filename):
    body={'filename':filename,'data_base64':base64.b64encode(raw).decode(),'options':{}}
    p=client.post('/api/character-cards/preview',json=body);assert p.status_code==200
    body.update(request_id='binary',preview_token=p.json()['preview_token'],expected_pack_id=p.json()['active_pack_id'])
    response=client.post('/api/character-cards/import',json=body);assert response.status_code==200,response.text
    assert client.get('/api/character-cards/source-file').content==raw

def test_invalid_input_gives_error_without_writing_or_switching(client):
    before=manager.session
    body=upload();body['data_base64']='!not-base64!'
    r=client.post('/api/character-cards/preview',json=body);assert r.status_code==400 and r.json()['detail']
    assert manager.session is before
    assert client.get('/api/character-cards/source').status_code==404

def test_failed_activation_cleans_only_new_pack_and_restores_session(client,monkeypatch):
    before=(manager.pack_dir,manager.session,dict(manager.library));body=prepared(client,id='failed-import')
    def broken(path):raise ValueError('activation failed')
    monkeypatch.setattr(manager,'_activate',broken)
    assert client.post('/api/character-cards/import',json=body).status_code==400
    assert (manager.pack_dir,manager.session,manager.library)==before
    assert not (manager.user_dir/'failed-import').exists()
