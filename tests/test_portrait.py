"""Narrative-only portrait updates must survive undo/save and reject mixed bad patches."""
import json
import pytest
from conftest import ROOT
from rpg_content import load_pack
from rpg_content.appearance import attach_default_appearance
from rpg_content.library import create_pack
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall,StateSchema,SpriteSheet,WardrobeConfig
from rpg_core.runtime import GameSession
from rpg_core.saves import snapshot_payload,restore_session
from rpg_core.settlement import DOMAINS
from rpg_gateway import LlmResponse,LlmRouter,OpenAICompatibleProvider

def fixture_pack():
    pack=load_pack(ROOT/'packs/new-game')
    fixture=json.loads((ROOT/'tests/fixtures/portrait_contract.json').read_text(encoding='utf-8'))
    state=pack.state.model_dump(mode='json');replacements={f['id']:f for f in fixture['fields']}
    state['fields']=[f for f in state['fields'] if f['id'] not in replacements]+fixture['fields']
    pack.state=StateSchema.model_validate(state)
    pack.sprites=SpriteSheet.model_validate(fixture['sheet'])
    wardrobe=pack.wardrobe.model_dump(mode='json');wardrobe['slots'].update(fixture['slots'])
    pack.wardrobe=WardrobeConfig.model_validate(wardrobe)
    return pack

TEXT='你戴上巫师帽，握住雨伞，微笑着向左看去；随后举起右手施法。'
class Provider:
    name='portrait-fixture'
    def __init__(self, changes, evidence=TEXT):self.changes=changes;self.evidence=evidence;self.requests=[]
    def complete(self,request):
        self.requests.append(request)
        if request['phase']=='settlement':
            ops=[{'name':'update_portrait','args':{'changes':self.changes},'evidence':self.evidence},
                 {'name':'update_clothing','args':{'changes':[{'slot':'headwear','garment':'witch','evidence':TEXT},{'slot':'handheld','garment':'umbrella','evidence':TEXT}]},'evidence':TEXT}]
            return LlmResponse(tool_calls=[ToolCall(id='portrait',name='settle_turn',args={'checked':list(DOMAINS),'operations':ops})])
        return LlmResponse(narrator=NarratorOutput(narrative=TEXT))
def game(changes,evidence=TEXT):
    p=Provider(changes,evidence);profile=LlmProfile(provider=p.name)
    g=GameSession(fixture_pack(),LlmRouter(LlmRolesConfig(narrator=profile),{p.name:p}))
    return g,p

def test_portrait_and_accessories_are_one_stateless_transaction_with_undo_and_save():
    g,p=game({'pose':'cast','expression':'smile','gaze':'left','tears':2})
    result=g.submit_action({'text':'继续'})
    assert result.ok,(result.error if hasattr(result,'error') else result)
    assert result.state['pose']=='cast' and result.state['headwear']=='witch' and result.state['handheld']=='umbrella'
    assert result.state['gaze']=='left' and result.state['expression']=='smile' and result.state['tears']==2
    request=[r for r in p.requests if r['phase']=='settlement'][0]
    assert 'portrait' in request and request['portrait']['pose']['options']['cast']=='施法表现'
    assert len(request['portrait']['expression']['options'])==25 and len(request['portrait']['earring_graphic']['options'])==69
    assert not {'recent','events','action'} & request.keys()
    wire=OpenAICompatibleProvider(base_url='http://unused',model='test')._payload(request)
    assert 'portrait' in json.loads(wire['messages'][1]['content'])
    assert [x['function']['name'] for x in wire['tools']]==['settle_turn']
    saved=snapshot_payload(g,slot='portrait')
    restored,_=game({});restore_session(restored,saved)
    assert restored.state['pose']=='cast' and restored.state['headwear']=='witch' and restored.verify()['equal']
    g.undo();assert g.state['pose']=='stand' and g.state['headwear']=='none' and g.state['tears']==0
    assert g.verify()['equal']

@pytest.mark.parametrize('bad',[
    {'pose':'undefined_attack'}, {'pose':'cast','tears':5}, {'freckles':1},
    {'tears':True},{'tears':1.5},{'hp':1},{'headwear':'witch'}, {'pose':['stand']},
])
def test_illegal_portrait_patch_cannot_partially_equip_accessories(bad):
    g,_=game(bad);before=dict(g.state)
    assert not g.submit_action({'text':'继续'}).ok
    assert g.state==before and g.turn==0 and g.verify()['equal']

def test_portrait_evidence_cannot_come_from_player_input():
    g,_=game({'pose':'cast'},evidence='你在玩家输入中说想施法')
    assert not g.submit_action({'text':'你在玩家输入中说想施法'}).ok
    assert g.state['pose']=='stand'

def test_shared_portrait_upgrade_keeps_custom_numbers_and_player_progress(tmp_path):
    root=create_pack(tmp_path,pack_id='old-portrait',title='旧世界')
    (root/'ui').mkdir(exist_ok=True)
    (root/'ui/sprites.json').write_text(json.dumps({'layers':[]}))
    (root/'appearance.json').write_text(json.dumps({'asset_pack':'new-game'}))
    before=json.loads((root/'state.json').read_text(encoding='utf-8'))
    before['fields'][0]['max']=999
    (root/'state.json').write_text(json.dumps(before),encoding='utf-8')
    import shutil
    template=tmp_path/'public-template'
    shutil.copytree(ROOT/'packs/new-game',template)
    fixture=fixture_pack()
    (template/'state.json').write_text(fixture.state.model_dump_json(),encoding='utf-8')
    (template/'ui/sprites.json').write_text(fixture.sprites.model_dump_json(),encoding='utf-8')
    (template/'wardrobe.json').write_text(fixture.wardrobe.model_dump_json(),encoding='utf-8')
    assert attach_default_appearance(root,template)
    pack=load_pack(root)
    assert pack.state.fields[0].max==999 and pack.state.by_id()['tears'].type=='int'
    assert 'cast' in pack.state.by_id()['pose'].enum_values and 'headwear' in pack.wardrobe.slots
    assert not attach_default_appearance(root,template)

def test_custom_portrait_is_not_replaced(tmp_path):
    root=create_pack(tmp_path,pack_id='own-portrait',title='自己的立绘')
    (root/'ui').mkdir(exist_ok=True);p=root/'ui/sprites.json';p.write_text('{"layers":[]}')
    assert not attach_default_appearance(root,ROOT/'packs/new-game') and p.read_text()=='{"layers":[]}'


def test_legacy_pack_snapshot_receives_new_portrait_but_keeps_numeric_history():
    g,p=game({})
    old=g.pack.model_copy(deep=True)
    old.sprites=old.sprites.model_copy(update={'revision':0,'controls':{},'motions':{}})
    baseline={'body_type','hair_style','hair_length','hair_color','expression','blush','breast_size','upper','outfit_color','lower','pants_color','eye_color','pose','under_upper','under_lower','genital','bodywriting','upper_condition','lower_condition'}
    old.state.fields=[f for f in old.state.fields if f.group not in ('appearance','sprite') or f.id in baseline]
    old.wardrobe=old.wardrobe.model_copy(update={'slots':{k:v for k,v in old.wardrobe.slots.items() if k in ('upper','lower')}})
    g=GameSession(old,g.router);g.debug_set_state({'hp':7})
    from rpg_core.world_config import config_of
    definitions=config_of(old)
    values=dict(g.state)
    g._record(turn=2,kind='world.configured',payload={'before':definitions,'after':definitions,'values':values})
    g._record(turn=2,kind='turn.committed',payload={'configuration':True})
    saved=snapshot_payload(g,slot='old-snapshot')
    restored,_=game({});restore_session(restored,saved)
    assert restored.state['hp']==7 and restored.state['tears']==0 and restored.pack.sprites.revision==1
    assert 'cast' in restored.pack.state.by_id()['pose'].enum_values and restored.verify()['equal']


def test_backend_catalog_is_relevant_without_losing_current_state():
    from rpg_core.portrait import catalog_options
    options={'none':'无',**{f'ring-{i}':f'戒指{i}' for i in range(50)},'ruby':'红宝石戒指'}
    selected=catalog_options(options,'你戴上红宝石戒指。','ring-49')
    assert 'ruby' in selected and 'ring-49' in selected and 'none' in selected and len(selected)<=24
    assert len(catalog_options(options,None,'none'))==52


def test_old_managed_template_is_recognised_by_content_hash(tmp_path):
    import hashlib
    root=create_pack(tmp_path,pack_id='legacy-copy',title='旧副本')
    import shutil
    template=tmp_path/'template'
    shutil.copytree(ROOT/'packs/night-convenience-store',template)
    legacy=b'{"width":32,"layers":[]}'
    (template/'ui').mkdir(exist_ok=True)
    (template/'ui/sprites.json').write_text(json.dumps({'layers':[],'revision':1,'legacy_hashes':[hashlib.sha256(legacy).hexdigest()]}))
    (root/'ui').mkdir(exist_ok=True);(root/'ui/sprites.json').write_bytes(legacy)
    assert not (root/'appearance.json').exists()
    assert attach_default_appearance(root,template)
    assert load_pack(root).sprites.revision==1


def test_resource_binding_change_refreshes_the_portrait_metadata():
    g,_=game({});before=g.appearance_revision()
    g.pack.state=g.pack.state.model_copy(update={'resource_bindings':{'health':'focus'}})
    assert g.appearance_revision()!=before
