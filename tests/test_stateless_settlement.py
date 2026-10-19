"""Strict wire-contract and cross-turn regression tests; no legacy fixture adapter."""
import json
from pathlib import Path
import pytest
from conftest import ROOT,roles
from rpg_content import load_pack
from rpg_content.library import create_pack,save_prompts
from rpg_content.state_config import normalize_state,suggest_state,write_initial_state,reconfigure
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall
from rpg_core.runtime import GameSession
from rpg_core.settlement import DOMAINS
from rpg_core.saves import snapshot_payload,restore_session
from rpg_gateway import LlmResponse,LlmRouter,OpenAICompatibleProvider

TEXT='你在训练室擦伤了手臂，随后换上卫衣。'
def response(ops=None,patch=None,checked=None):
    return LlmResponse(tool_calls=[ToolCall(id='batch',name='settle_turn',args={'checked':list(DOMAINS) if checked is None else checked,'operations':ops or [],'status_patch':patch or {}})])
def op(name,args,evidence=TEXT,**extra):return {'name':name,'args':args,'evidence':evidence,**extra}
class WireProvider:
    def __init__(self,name,settlements=None,text=TEXT):self.name=name;self.queue=list(settlements or [response()]);self.text=text;self.requests=[]
    def complete(self,request):
        self.requests.append(request)
        if request['phase']=='settlement':return self.queue.pop(0) if len(self.queue)>1 else self.queue[0]
        return LlmResponse(narrator=NarratorOutput(narrative=self.text))

def game(responses=None,separated=False,wardrobe=False):
    n=WireProvider('n',responses);s=WireProvider('s',responses)
    cfg=LlmRolesConfig(separated=separated,narrator=LlmProfile(provider='n'),settler=LlmProfile(provider='s'))
    pack=load_pack(ROOT/('packs/new-game' if wardrobe else 'packs/night-convenience-store'))
    return GameSession(pack,LlmRouter(cfg,{'n':n,'s':s})),n,s

@pytest.mark.parametrize('separated',[False,True])
@pytest.mark.parametrize('wardrobe',[False,True])
def test_narration_always_precedes_one_stateless_settlement(separated,wardrobe):
    g,n,s=game(separated=separated,wardrobe=wardrobe)
    g._record(turn=0,kind='narrative.generated',payload={'narrative':'旧历史暗号：不可带入后端'})
    assert g.submit_action({'text':'观察'}).ok
    backend=(s if separated else n).requests[-1]
    assert backend['phase']=='settlement'
    assert not {'recent','events','action','tool_results','tool_exchanges'} & backend.keys()
    assert '旧历史暗号' not in json.dumps(backend,ensure_ascii=False)
    assert [e.role for e in g.ledger.events if e.kind=='llm.usage']==['narrator','settler']
    p=OpenAICompatibleProvider(base_url='http://unused',model='test')
    assert 'tools' not in p._payload(n.requests[0])
    payload=p._payload(backend)
    assert len(payload['messages'])==2
    assert [x['function']['name'] for x in payload['tools']]==['settle_turn']


def test_backend_updates_each_turn_with_current_state_and_undo():
    g,n,_=game([response([op('damage',{'amount':2})]),response([op('damage',{'amount':3})])])
    assert g.submit_action({'text':'观察'}).state['hp']==18
    assert g.submit_action({'text':'观察'}).state['hp']==15
    req=[r for r in n.requests if r['phase']=='settlement']
    assert [r['state']['hp'] for r in req]==[20,18]
    assert g.undo()['state']['hp']==18 and g.verify()['equal']


def test_partial_status_patch_preserves_other_scores():
    g,_,_=game([response(patch={'name':'行者','sensitivity':37}),response(),response(patch={'name':'新名字'})])
    for i in range(3):assert g.submit_action({'text':'继续'}).ok
    assert g.narrative_status()['sensitivity']==37 and g.narrative_status()['name']=='新名字'
    g.undo();assert g.narrative_status()['name']=='行者'


def test_repaired_batch_applies_valid_operations_only_once():
    g,_,_=game([response([op('damage',{'amount':2}),op('set_stat',{'field':'missing','value':3})]),response([op('damage',{'amount':2})])])
    r=g.submit_action({'text':'继续'})
    assert r.ok and r.state['hp']==18
    assert sum(e.kind=='tool.applied' for e in g.ledger.events)==1
    assert any(e.kind=='settlement.rejected' for e in g.ledger.events)


def test_missing_domain_cannot_silently_commit():
    g,_,_=game([response(checked=['stats'])]);r=g.submit_action({'text':'继续'})
    assert not r.ok and g.state['hp']==20 and g.turn==0


def test_unregistered_flag_becomes_a_story_fact_without_system_unlock():
    g,_,_=game([response([op('set_flag',{'flag':'met_mira','value':True})])])
    assert g.submit_action({'text':'继续'}).ok
    assert g.status()['story_facts']['story.met_mira']['value'] is True
    assert 'met_mira' not in g.state
    g.undo();assert not g.status()['story_facts']


def test_wardrobe_and_hp_are_settled_together():
    g,_,_=game([response([op('damage',{'amount':2}),op('update_clothing',{'changes':[{'slot':'upper','garment':'hoodie','evidence':TEXT}]})])],wardrobe=True)
    r=g.submit_action({'text':'继续'})
    assert r.ok and r.state['hp']==18 and r.state['upper']=='hoodie'


def test_opening_is_settled_once():
    g,n,_=game([response([op('damage',{'amount':2})])])
    assert g.start_opening()['ok'] and g.state['hp']==18
    assert not g.start_opening()['generated'] and len(n.requests)==2


def test_narrator_tool_output_is_rejected_before_backend():
    g,n,s=game();n.complete=lambda request:LlmResponse(tool_calls=[ToolCall(id='bad',name='damage',args={'amount':3})])
    assert not g.submit_action({'text':'继续'}).ok and g.state['hp']==20 and not s.requests

@pytest.fixture()
def editable(tmp_path):
    root=create_pack(tmp_path,pack_id='config-world',title='修仙世界')
    write_initial_state(root,suggest_state('你是一位强大的修仙者。'))
    p=WireProvider('n')
    return root,GameSession(load_pack(root),LlmRouter(LlmRolesConfig(narrator=LlmProfile(provider='n')),{'n':p}))

def test_editing_caps_preserves_values_history_and_restores_schema_on_undo(editable):
    root,g=editable
    g.debug_set_state({'hp':123})
    data=g.pack.state.model_dump(mode='json');next(f for f in data['fields'] if f['id']=='hp').update(label='气血',max=800,default=800)
    reconfigure(g,root,data)
    assert g.state['hp']==123 and g.pack.state.by_id()['hp'].max==800
    restored=GameSession(load_pack(root),g.router);restore_session(restored,snapshot_payload(g,slot='config'))
    assert restored.state==g.state and restored.pack.state.by_id()['hp'].max==800
    assert restored.undo()['state']['hp']==123 and restored.pack.state.by_id()['hp'].max==400
    assert restored.verify()['equal']


def test_lowered_cap_clamps_once_and_new_initial_value_does_not_refill(editable):
    root,g=editable
    data=g.pack.state.model_dump(mode='json');next(f for f in data['fields'] if f['id']=='hp').update(max=50,default=50)
    reconfigure(g,root,data)
    assert g.state['hp']==50
    data=g.pack.state.model_dump(mode='json');next(f for f in data['fields'] if f['id']=='hp').update(max=100,default=100)
    reconfigure(g,root,data);assert g.state['hp']==50

@pytest.mark.parametrize('bad',['nan','range','binding','duplicate'])
def test_bad_numeric_definitions_rejected_without_mutation(editable,bad):
    root,g=editable;data=g.pack.state.model_dump(mode='json');before=(root/'state.json').read_bytes()
    if bad=='nan':data['fields'][0]['max']=float('nan')
    if bad=='range':data['fields'][0]['max']=-1
    if bad=='binding':data['resource_bindings']['mana']='not_a_field'
    if bad=='duplicate':data['fields'].append(data['fields'][0])
    with pytest.raises(ValueError):reconfigure(g,root,data)
    assert before==(root/'state.json').read_bytes()


def test_new_world_initialization_accepts_custom_fields_and_skill_costs():
    from rpg_gateway.world_builder import parse_draft
    data={'title':'琉璃学院','prompts':{'pre':'你是魔法师。'},'state':{'fields':[{'id':'crystal','label':'琉璃魔力','type':'int','default':240,'min':0,'max':240,'display':'bar'}],'resource_bindings':{'mana':'crystal'}},'skills':[{'id':'glow','name':'点灯','cost':{'crystal':2}}]}
    parsed=parse_draft(data)
    assert parsed['state']['fields'][0]['label']=='琉璃魔力' and parsed['skills'][0]['cost']=={'crystal':2}


def test_replayed_request_id_does_not_double_charge_or_recall_model():
    g,n,_=game([response([op('damage',{'amount':2})])])
    r=g.submit_action({'text':'继续'},request_id='one-action')
    calls=len(n.requests);events=len(g.ledger.events)
    repeated=g.submit_action({'text':'继续'},request_id='one-action')
    assert r.ok and repeated.ok and repeated.state['hp']==18
    assert len(n.requests)==calls and len(g.ledger.events)==events
    g.undo();assert not g.submit_action({'text':'继续'},request_id='one-action').ok


def test_thirty_turns_keep_current_snapshot_without_history():
    batches=[response([op('damage' if i%2==0 else 'heal',{'amount':1})]) for i in range(30)]
    g,n,_=game(batches)
    for i in range(30):
        r=g.submit_action({'text':'训练'})
        assert r.ok and r.state['hp']==(19 if i%2==0 else 20)
    backend=[r for r in n.requests if r['phase']=='settlement']
    assert len(backend)==30 and all('events' not in r and 'recent' not in r for r in backend)
    assert g.verify()['equal']


def test_legacy_save_survives_shared_portrait_attachment(tmp_path):
    from rpg_content.appearance import attach_default_appearance
    root=create_pack(tmp_path,pack_id='legacy-world',title='旧世界')
    p=WireProvider('n');router=LlmRouter(LlmRolesConfig(narrator=LlmProfile(provider='n')),{'n':p})
    old=GameSession(load_pack(root),router);old.debug_set_state({'hp':7})
    saved=snapshot_payload(old,slot='legacy');saved.pop('pack_snapshot')
    attach_default_appearance(root,ROOT/'packs/new-game')
    upgraded=GameSession(load_pack(root),router);restore_session(upgraded,saved)
    assert upgraded.state['hp']==7 and upgraded.pack.sprites and upgraded.state['upper']=='tshirt'
    assert upgraded.verify()['equal']


def test_legacy_standard_preset_rebinds_when_focus_is_replaced(editable):
    from rpg_content.skill_library import load_library,bind_skill
    from rpg_core.contracts import StateField
    root,g=editable;library=load_library(ROOT/'skill-libraries/standard-300')
    raw=next(s for s in library.skills if s.id=='magic_fire_low_01')
    old_entry=bind_skill(library,raw,g.pack.state).model_copy(update={'resource_cost':{}})
    g.pack=g.pack.model_copy(update={'skills':[old_entry.skill],'skill_catalog':[old_entry],'skill_selection':{'library_versions':{library.manifest.id:'1.0.0'}}})
    data=g.pack.state.model_dump(mode='json');data['fields']=[f for f in data['fields'] if f['id']!='focus']
    data['fields'].append({'id':'essence','label':'真元','type':'int','min':0,'max':600,'default':600,'display':'bar'})
    data['resource_bindings'].update(mana='essence',effort='essence')
    reconfigure(g,root,data)
    assert g.all_skills()[0].cost=={'essence':1} and 'focus' not in g.state
    assert g.pack.skill_catalog[0].resource_cost=={'mana':1}
