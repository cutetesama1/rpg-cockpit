import base64,copy,io,json,struct,zlib,zipfile
from pathlib import Path
import pytest
from rpg_content.character_cards import CardError,CardOptions,parse_card,preview_card,create_card_pack
from rpg_content import load_pack
from rpg_core.runtime import GameSession
from rpg_gateway import build_router,default_settings
from rpg_core.saves import snapshot_payload,restore_session

def card(version=3):
    return {'spec':f'chara_card_v{version}','spec_version':f'{version}.0','root_custom':{'keep':True},'data':{
        'name':'莉瑟','nickname':'导师','description':'{{char}}是一位传奇法师。','personality':'{{char}}言简意赅。','scenario':'你来到琉璃港。',
        'first_mes':'{{char}}向{{user}}点头。','alternate_greetings':['<BOT>向<USER>递来一张地图。'],
        'group_only_greetings':['导师向旅人们致意。'],'mes_example':'<START>\n{{user}}：你好。\n{{char}}：你好。',
        'creator':'测试作者','creator_notes':'CREATOR_NOTES_NOT_IN_PROMPT','creator_notes_multilingual':{'zh':'中文作者备注，仅供阅读'},
        'system_prompt':'{{original}}\n温和地叙述。','post_history_instructions':'{{original}}保持角色连贯。',
        'character_version':'1.2','extensions':{'test/plugin':{'script':'DO_NOT_EXECUTE'}},'custom_unknown':{'deep':['保留',3]},
        'character_book':{'name':'琉璃港设定','scan_depth':20,'entries':[
            {'id':9,'name':'港口','keys':['Harbor'],'secondary_keys':['bell'],'selective':True,'content':'港口的钟声悠远。','enabled':True,'insertion_order':2},
            {'id':9,'keys':[],'constant':True,'content':'琉璃群岛间以飞艇往来。','enabled':True,'insertion_order':1},
            {'keys':['secret.*'],'content':'REGEX_SECRET','use_regex':True,'enabled':True,'insertion_order':0},
        ]}}}
def encoded(value):return json.dumps(value,ensure_ascii=False).encode()
def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
def png(chara=None,ccv3=None):
    result=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))
    for key,value in ((b'chara',chara),(b'ccv3',ccv3)):
        if value is not None:result+=chunk(b'tEXt',key+b'\0'+base64.b64encode(encoded(value)))
    return result+chunk(b'IDAT',zlib.compress(b'\0\0\0\0\0'))+chunk(b'IEND',b'')
def charx(value,extra=None):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('card.json',encoded(value))
        for path,data in (extra or {}).items():z.writestr(path,data)
    return out.getvalue()

@pytest.mark.parametrize('version',[2,3])
def test_json_maps_known_fields_and_preserves_every_unknown_field(version):
    value=card(version);before=copy.deepcopy(value);p=preview_card(encoded(value),'card.json',CardOptions(user_name='旅人'))
    assert p['raw']==before==value and p['raw_preserved']
    assert p['greetings'][0]['text']=='导师向旅人点头。'
    assert p['greetings'][1]['text']=='导师向旅人递来一张地图。'
    assert '传奇法师' in p['prompts']['pre'] and '言简意赅' in p['prompts']['pre']
    assert 'CREATOR_NOTES_NOT_IN_PROMPT' not in json.dumps(p['prompts'])
    assert 'DO_NOT_EXECUTE' not in json.dumps(p['prompts'])
    assert p['creator_notes']=='中文作者备注，仅供阅读'
    assert len(p['worldbook'])==3 and len({e['id'] for e in p['worldbook']})==3
    assert not p['worldbook'][2]['enabled']
    assert any(x['path']=='data.custom_unknown' for x in p['unsupported'])

def test_png_prefers_v3_and_preserves_original_image_bytes_in_pack(tmp_path):
    v2=card(2);v2['data']['name']='旧数据';v3=card();raw=png(v2,v3)
    parsed,format,_=parse_card(raw,'card.png');assert parsed==v3 and format=='png'
    path,p=create_card_pack(raw,'card.png',CardOptions(),tmp_path,'png-request')
    assert (path/'character-card/source.bin').read_bytes()==raw
    assert json.loads((path/'character-card/source.json').read_text(encoding='utf-8'))==v3
    assert load_pack(path).character_card['raw']==v3

def test_charx_reads_card_without_extracting_assets_or_executing_extensions(tmp_path):
    raw=charx(card(),{'assets/other/code/do-not-execute.js':b'throw new Error("never");','assets/icon/images/main.png':png()})
    path,p=create_card_pack(raw,'card.charx',CardOptions(),tmp_path,'charx-request')
    assert p['format']=='charx' and len(p['archive_files'])==3
    assert not (path/'assets').exists()
    assert (path/'character-card/source.bin').read_bytes()==raw

@pytest.mark.parametrize('bad',[b'',b'[]',b'null',b'{oops}',b'\xff',b'{"x":1,"x":2}',b'{"x":1e999}',encoded({'spec':'unknown','data':{'name':'x'}}),encoded({'spec':'chara_card_v3','data':[]})])
def test_bad_json_has_actionable_errors(bad):
    with pytest.raises(CardError):parse_card(bad,'card.json')

def test_png_crc_truncation_plain_image_and_invalid_base64_are_rejected():
    raw=bytearray(png(ccv3=card()));raw[-1]^=1
    for bad in [bytes(raw),png(),png(ccv3=card())[:-6]]:
        with pytest.raises(CardError):parse_card(bad,'card.png')
    bad=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'tEXt',b'ccv3\0%%%')+chunk(b'IEND',b'')
    with pytest.raises(CardError,match='Base64'):parse_card(bad,'card.png')

@pytest.mark.parametrize('path',['../outside','/absolute','C:/absolute','assets\\outside'])
def test_charx_invalid_paths_are_rejected_without_disk_writes(tmp_path,path):
    raw=charx(card(),{path.replace(chr(92),'/'):b'x'})
    if chr(92) in path:raw=raw.replace(path.replace(chr(92),'/').encode(),path.encode())
    with pytest.raises(CardError):create_card_pack(raw,'card.charx',CardOptions(),tmp_path,'bad')
    assert not list(tmp_path.iterdir())

def test_type_errors_and_invalid_greeting_are_reported_by_field():
    value=card();value['data']['description']={}
    with pytest.raises(CardError,match='description'):preview_card(encoded(value),'x.json',CardOptions())
    with pytest.raises(CardError,match='开场白'):preview_card(encoded(card()),'x.json',CardOptions(greeting=55))

def test_card_creates_playable_pack_with_exact_greeting_and_no_model_calls(tmp_path):
    path,p=create_card_pack(encoded(card()),'card.json',CardOptions(user_name='旅人',greeting=1),tmp_path,'once')
    pack=load_pack(path);router=build_router(default_settings())
    router.complete=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('Import opening must not invoke a model'))
    g=GameSession(pack,router)
    assert g.start_opening()['narrative']=='导师向旅人递来一张地图。'
    assert not g.start_opening()['generated'] and g.turn==0
    assert not any(e.kind=='tool.applied' or e.kind=='llm.usage' for e in g.ledger.events)
    assert len(g.all_skills())==1  # NPC's mastery is never granted to player.
    saved=snapshot_payload(g,slot='card-save');restored=GameSession(pack,router);restore_session(restored,saved)
    assert restored.pack.character_card['raw']==card()
    assert not restored.start_opening()['generated']

def test_embedded_worldbook_obeys_constant_case_secondary_keys_and_disabled_regex(tmp_path):
    path,p=create_card_pack(encoded(card()),'card.json',CardOptions(),tmp_path,'worldbook')
    g=GameSession(load_pack(path),build_router(default_settings()))
    lore=g.assembler.select_lore(action={'text':'HARBOR BELL'},scene_text='')
    assert {e['id'] for e in lore}=={'card_lore_0001','card_lore_0002'}
    assert {e['id'] for e in g.assembler.select_lore(action={'text':'Harbor'},scene_text='')}=={'card_lore_0002'}
    assert not any('REGEX_SECRET' in e['content'] for e in lore)

def test_explicit_mapping_can_exclude_fields_without_dropping_raw(tmp_path):
    options=CardOptions(role='player',include=['scenario'])
    path,p=create_card_pack(encoded(card()),'card.json',options,tmp_path,'partial');pack=load_pack(path)
    assert not pack.npcs and not pack.worldbook
    assert '传奇法师' not in pack.prompts['pre'] and '你来到琉璃港' in pack.prompts['pre']
    assert pack.character_card['raw']==card()

def test_existing_game_not_overwritten_and_newer_version_is_importable_with_warning(tmp_path):
    value=card();value['spec_version']='3.1'
    path,p=create_card_pack(encoded(value),'card.json',CardOptions(id='my-card'),tmp_path,'first')
    before=(path/'character-card.json').read_bytes()
    assert any('spec_version' in w for w in p['warnings'])
    with pytest.raises(CardError,match='已存在'):create_card_pack(encoded(card()),'card.json',CardOptions(id='my-card'),tmp_path,'second')
    assert (path/'character-card.json').read_bytes()==before


def test_placeholder_expansion_is_bounded_before_allocating_large_output():
    value=card();value['data']['nickname']='名'*200;value['data']['description']='{{char}}'*31000
    with pytest.raises(CardError,match='展开'):preview_card(encoded(value),'expansion.json',CardOptions())
