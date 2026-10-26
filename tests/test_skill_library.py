from __future__ import annotations
import io,json,zipfile
from types import SimpleNamespace
import pytest
from conftest import ROOT,StubProvider,roles,say
from rpg_content import PackError,load_pack
from rpg_content.library import create_pack,save_prompts
from rpg_content.skill_library import load_library,import_skill_library_zip,bind_skill,SkillLibrary
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall
from rpg_core.runtime import GameSession
from rpg_gateway import LlmResponse,LlmRouter,ScriptedProvider
from rpg_gateway.skill_selection import configure_world_catalog

@pytest.fixture()
def library():return load_library(ROOT/'skill-libraries/standard-300')
@pytest.fixture()
def world(tmp_path):
    root=create_pack(tmp_path,pack_id='catalog-world',title='魔法世界')
    save_prompts(root,{'pre':'你是一名刚入门的魔法学徒，在魔法学院学习。'})
    return root

def zip_data(data,manifest=None,extra=None):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest or data['manifest']))
        z.writestr('skills.json',json.dumps({'skills':data['skills']}))
        if extra:
            info=zipfile.ZipInfo();info.filename=extra[0]
            z.writestr(info,extra[1])
    return out.getvalue()

def test_standard_library_has_300_distinct_complete_definitions(library):
    assert len(library.skills)==len({s.id for s in library.skills})==len({s.skill.name for s in library.skills})==300
    for kind in ('martial','magic'):
        for tier in ('low','mid','high'):assert sum(s.kind==kind and s.tier==tier for s in library.skills)==50
    assert all(s.skill.action_text and s.instruction and s.resource_cost for s in library.skills)
    assert len({s.school for s in library.skills})==20

def test_zip_roundtrip_and_template_use_same_format(tmp_path):
    lib=import_skill_library_zip((ROOT/'skill-libraries/standard-300.zip').read_bytes(),tmp_path)
    assert len(load_library(tmp_path/lib.manifest.id).skills)==300
    custom=import_skill_library_zip((ROOT/'skill-libraries/author-template.zip').read_bytes(),tmp_path)
    assert len(custom.skills)==1
    with pytest.raises(PackError,match='已存在'):import_skill_library_zip((ROOT/'skill-libraries/standard-300.zip').read_bytes(),tmp_path)
    assert len(list(tmp_path.iterdir()))==2

@pytest.mark.parametrize('bad', ['type','version','duplicate','cycle','missing_parent','nan','resource','target','nested_cost','mismatch'])
def test_invalid_libraries_never_install(tmp_path,library,bad):
    data=library.model_dump(mode='json');data['skills']=data['skills'][:2]
    if bad=='type':data['manifest']['type']='game-pack'
    elif bad=='version':data['manifest']['schema_version']=2
    elif bad=='duplicate':data['skills'][1]=data['skills'][0]
    elif bad=='cycle':data['skills'][0]['prerequisites']=[data['skills'][1]['id']];data['skills'][1]['prerequisites']=[data['skills'][0]['id']]
    elif bad=='missing_parent':data['skills'][0]['prerequisites']=['missing']
    elif bad=='nan':data['skills'][0]['resource_cost']={'effort':float('nan')}
    elif bad=='resource':data['skills'][0]['resource_cost']={'unbound':2}
    elif bad=='target':data['skills'][0]['skill']['targets']=['not_a_target']
    elif bad=='nested_cost':data['skills'][0]['skill']['cost']={'hp':1}
    elif bad=='mismatch':data['skills'][0]['skill']['id']='different'
    with pytest.raises(PackError):import_skill_library_zip(zip_data(data),tmp_path)
    assert not tmp_path.exists() or not list(tmp_path.iterdir())

@pytest.mark.parametrize('path',['../evil.json','/absolute.json','C:/bad.json','folder\\bad.json'])
def test_zip_paths_rejected_even_for_unrelated_members(tmp_path,library,path):
    with pytest.raises(PackError,match='非法路径'):import_skill_library_zip(zip_data(library.model_dump(mode='json'),extra=(path,'bad')),tmp_path)
    assert not list(tmp_path.iterdir())

def test_resources_bind_without_silently_making_missing_costs_free(world,library):
    schema=load_pack(world).state
    magic=next(s for s in library.skills if s.id=='magic_fire_low_01')
    entry=bind_skill(library,magic,schema)
    assert entry.skill.cost=={'focus':1}
    assert entry.skill.action_text==magic.skill.action_text and entry.instruction==magic.instruction
    fields=[f for f in schema.fields if f.id!='focus']
    assert bind_skill(library,magic,schema.model_copy(update={'fields':fields})) is None

class SelectionRouter:
    separated=False
    def __init__(self,data):self.data=data;self.requests=[]
    def profile(self,role):return SimpleNamespace(provider='test-selector')
    def complete(self,role,request):
        self.requests.append((role,request))
        return LlmResponse(narrator=NarratorOutput(narrative=json.dumps(self.data)),model='selector-test',usage={'total_tokens':10})

def test_powerful_mage_can_start_with_all_150_magic_skills(world,library):
    save_prompts(world,{'pre':'你是一名十分强大的空间大法师，已经精通多个魔法体系。世界允许空间法术。'})
    refs=[f'{library.manifest.id}:{s.id}' for s in library.skills if s.kind=='magic' and s.tier=='high']
    router=SelectionRouter({'world_tags':['magic','spatial_magic'],'skill_refs':refs,'initial_refs':refs,'reason':'角色已是强大的多系空间法师'})
    result=configure_world_catalog(world,[library],router)
    loaded=load_pack(world)
    assert result['method']=='llm' and result['initial_count']==150
    assert len(loaded.skills)==151 and len(loaded.skill_catalog)==150
    assert any(skill.id=='look' for skill in loaded.skills)
    assert sum(e.tier=='high' for e in loaded.skill_catalog)==50
    assert router.requests[0][0]=='settler'
    assert len(router.requests[0][1]['candidates'])==300

def test_novice_has_small_initial_set_but_large_learnable_pool(world,library):
    refs=[f'{library.manifest.id}:{s.id}' for s in library.skills if s.kind=='magic' and s.school!='空间']
    initial=[ref for ref in refs if ref.endswith('low_01')][:2]
    result=configure_world_catalog(world,[library],SelectionRouter({'world_tags':['magic'],'skill_refs':refs,'initial_refs':initial}))
    assert len(load_pack(world).skills)==3  # two presets plus the author's look action
    assert result['pool_count']==135

def test_no_magic_world_rejects_model_magic_and_falls_back(world,library):
    save_prompts(world,{'pre':'你是现代现实城市的普通人。这个世界没有魔法，也无超自然力量。'})
    ref=library.manifest.id+':magic_fire_low_01'
    result=configure_world_catalog(world,[library],SelectionRouter({'world_tags':['magic'],'skill_refs':[ref],'initial_refs':[ref]}))
    assert result['warnings'] and result['method']=='tags'
    assert all(e.kind=='martial' for e in load_pack(world).skill_catalog)

def test_offline_fallback_respects_powerful_background(world,library):
    save_prompts(world,{'pre':'你是一名十分强大的法师，熟练掌握各种魔法。'})
    router=LlmRouter(roles(),{'scripted':ScriptedProvider()})
    result=configure_world_catalog(world,[library],router)
    assert result['initial_count']>100 and result['warnings']

def game_with_catalog(world,library,responses,ids=('magic_fire_low_01',)):
    pack=load_pack(world);selected=[s for s in library.skills if s.id in ids]
    pack.skill_catalog=[bind_skill(library,s,pack.state) for s in selected]
    pack.skill_selection={'library_versions':{library.manifest.id:'1.0.0'}}
    pack.skills=[]
    provider=StubProvider(responses)
    return GameSession(pack,LlmRouter(roles(provider.name),{provider.name:provider})),provider

def learn(ref,evidence,**overrides):
    return LlmResponse(tool_calls=[ToolCall(id='learn_presets',name='learn_catalog_skills',args={'skills':[{'ref':ref,'evidence':evidence,**overrides}]})])

def test_post_narrative_learning_uses_canonical_definition_and_use_cost_once(world,library):
    ref=library.manifest.id+':magic_fire_low_01';text='你经过练习，终于学会了火弹，能够稳定引出火光。'
    game,provider=game_with_catalog(world,library,[say(text),learn(ref,text),say('你施展火弹，暖光向前掠去。')])
    entry=game.pack.skill_catalog[0]
    result=game.submit_action({'kind':'text','text':'我学习火弹。'})
    assert result.ok and game.all_skills()[0]==entry.skill
    assert provider.requests[1]['phase']=='settlement'
    event=next(e for e in game.ledger.events if e.kind=='skill.learned')
    assert event.payload['source_ref']==ref and event.payload['instruction']==entry.instruction
    before=game.state['focus']
    used=game.submit_action({'kind':'text','text':'我使用火弹。','skills':[{'skill_id':entry.skill.id}]})
    assert used.ok and game.state['focus']==before-1
    assert provider.requests[2]['preset_instructions'][0]['instruction']==entry.instruction
    assert sum(e.kind=='skill.used' for e in game.ledger.events)==1
    assert game.verify()['equal']
    game.undo();assert len(game.all_skills())==1
    game.undo();assert not game.all_skills() and entry.skill.id not in game.executor.skill_ids

@pytest.mark.parametrize('bad',['override','desire','negative','unknown_ref','prerequisite'])
@pytest.mark.usefixtures("strict_settlement")
def test_invalid_learning_is_atomic_and_retracts_preview(world,library,bad):
    ref=library.manifest.id+':magic_fire_low_01';text='你经过练习，终于学会了火弹。';ids=('magic_fire_low_01',)
    extra={}
    if bad=='override':extra={'cost':{}}
    elif bad=='desire':text='你想要学会火弹。'
    elif bad=='negative':text='你仍然没有学会火弹。'
    elif bad=='unknown_ref':ref='outside:missing'
    elif bad=='prerequisite':ref=library.manifest.id+':magic_fire_high_01';text='你终于学会了日珥矢。';ids=('magic_fire_low_01','magic_fire_mid_01','magic_fire_high_01')
    response=learn(ref,text,**extra)
    game,_=game_with_catalog(world,library,[say(text),response,response],ids)
    updates=[];game.on_narrative=updates.append;before=dict(game.state)
    result=game.submit_action({'kind':'text','text':'学习'})
    assert not result.ok and game.state==before and not game.all_skills()
    assert updates[-1]['text']==''
    assert not any(e.kind=='skill.learned' for e in game.ledger.events)

@pytest.mark.usefixtures("strict_settlement")
def test_preset_world_blocks_legacy_generated_skill(world,library):
    arbitrary=LlmResponse(tool_calls=[ToolCall(id='invent',name='learn_skill',args={'id':'made_up','name':'模型自造技能'})])
    game,_=game_with_catalog(world,library,[arbitrary,say('你试着学习。')])
    result=game.submit_action({'kind':'text','text':'学习'})
    assert not result.ok and not game.all_skills()

def test_learning_survives_save_events_without_access_to_global_library(world,library):
    ref=library.manifest.id+':magic_fire_low_01';text='你终于学会了火弹，掌心浮起温和的光。'
    game,_=game_with_catalog(world,library,[say(text),learn(ref,text)])
    assert game.submit_action({'kind':'text','text':'学习火弹'}).ok
    restored=GameSession(game.pack,LlmRouter(roles(),{'scripted':ScriptedProvider()}))
    restored.load_events([e.model_dump(mode='json') for e in game.ledger.events])
    assert restored.all_skills()==game.all_skills()
    assert restored.verify()['equal']
