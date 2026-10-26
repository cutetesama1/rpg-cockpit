import json
from pathlib import Path

import pytest
from conftest import ROOT,roles
from rpg_content import load_pack
from rpg_core.contracts import LlmProfile,LlmRolesConfig,NarratorOutput,ToolCall
from rpg_core.dice import Check,DiceError,evaluate,parse_dice,resolve
from rpg_core.plot_director import Candidate,DirectorConfig,PlotClue,configure,put_clue,request_once,view
from rpg_core.runtime import GameSession
from rpg_core.saves import snapshot_payload,restore_session,export_log
from rpg_core.settlement import DOMAINS
from rpg_gateway import LlmResponse,LlmRouter,OpenAICompatibleProvider
from rpg_gateway.settings import default_settings,merge_update

def batch(ops=None):
    return LlmResponse(tool_calls=[ToolCall(id='batch',name='settle_turn',args={'checked':list(DOMAINS),'operations':ops or []})])

def candidate(id='harbor_fog',chance=1,**extra):
    return {'id':id,'title':'港口薄雾','scope':'environment','trigger':{'kind':'probability','chance':chance},'success':'雾气笼罩了远方的船灯。',**extra}

class Provider:
    name='director-test'
    def __init__(self, candidates=None):
        self.candidates=candidates or [];self.requests=[];self.fail_narrator=0;self.fail_director=False;self.settlements=[]
    def complete(self,request):
        self.requests.append(request)
        if request['phase']=='director':
            if self.fail_director:raise RuntimeError('PRIVATE_DIRECTOR_FAILURE')
            return LlmResponse(narrator=NarratorOutput(narrative=json.dumps({'candidates':self.candidates},ensure_ascii=False)))
        if request['phase']=='settlement':return self.settlements.pop(0) if self.settlements else batch()
        if self.fail_narrator:
            self.fail_narrator-=1;raise RuntimeError('failed narration')
        return LlmResponse(narrator=NarratorOutput(narrative='你观察着码头，风吹过栏杆。'))

def game(candidates=None,**options):
    p=Provider(candidates)
    g=GameSession(load_pack(ROOT/'packs/night-convenience-store'),LlmRouter(roles(p.name),{p.name:p}))
    if options:configure(g,DirectorConfig(**options))
    return g,p

def requests(p,phase):return [r for r in p.requests if r['phase']==phase]

@pytest.mark.parametrize('expression,canonical',[('d20','1d20'),('2d6+3','2d6+3'),('2d20KH1','2d20kh1'),('2d20kl1','2d20kl1'),('d%','1d100'),('4df','4dF')])
def test_common_dice(expression,canonical):
    assert parse_dice(expression)['dice']==canonical
    result=evaluate('00'*32,'example',Check(dice=expression))
    assert len(result['rolls'])==parse_dice(expression)['count']
    assert result['total']==sum(result['kept'])+result['modifier']
    assert len(result['kept'])==parse_dice(expression)['keep']

@pytest.mark.parametrize('expression',['','d1','0d6','101d6','d1000001','2d6kh3','1d6+1000001','2d6;__import__("os")','1d6+NaN'])
def test_bad_dice_rejected(expression):
    with pytest.raises(ValueError):parse_dice(expression)

@pytest.mark.parametrize('chance',[0,0.25,1])
def test_probability_is_deterministic(chance):
    check=Check(kind='probability',chance=chance)
    a=evaluate('ab'*32,'probability',check)
    assert a==evaluate('ab'*32,'probability',check)
    if chance in (0,1):assert a['passed']==bool(chance)

@pytest.mark.parametrize('bad',[-.1,1.1,True,'0.5',float('nan'),float('inf')])
def test_probability_contract_is_finite_numeric(bad):
    with pytest.raises(ValueError):Check(kind='probability',chance=bad)

def test_advantage_disadvantage_and_fate_ranges():
    hi=evaluate('12'*32,'roll',Check(dice='2d20kh1'))
    lo=evaluate('12'*32,'roll',Check(dice='2d20kl1'))
    assert hi['rolls']==lo['rolls'] and hi['total']==max(hi['rolls']) and lo['total']==min(lo['rolls'])
    assert set(evaluate('12'*32,'fate',Check(dice='100dF'))['rolls'])=={-1,0,1}

def test_event_id_is_immutable_and_save_reuses_draw_without_new_entropy():
    g,_=game();a,reused=resolve(g,'event_one',Check(dice='2d6+3'),turn=0)
    assert not reused
    saved=snapshot_payload(g,slot='dice')
    restored,_=game();restore_session(restored,saved)
    before=len(restored.ledger.events)
    b,reused=resolve(restored,'event_one',Check(dice='2d6+3'),turn=0)
    assert a==b and reused and len(restored.ledger.events)==before
    with pytest.raises(DiceError,match='不能改参数'):resolve(restored,'event_one',Check(dice='1d20'),turn=0)
    assert len(restored.ledger.events)==before

def test_disabled_director_has_zero_extra_requests():
    g,p=game([candidate()])
    assert g.submit_action({'text':'观察'}).ok
    assert [r['phase'] for r in p.requests]==['narration','settlement']

def test_only_resolved_branch_enters_narration_and_wire_has_no_candidates():
    c=candidate(resolution={'kind':'dice','dice':'1d6','target':0},failure='UNSELECTED_FAILURE_BRANCH')
    g,p=game([c],enabled=True)
    assert g.submit_action({'text':'观察'}).ok
    req=requests(p,'narration')[0]
    assert len(req['triggered_events'])==1
    final=req['triggered_events'][0]
    assert final['status']=='resolved' and final['resolution']['passed'] and final['outcome']==c['success']
    payload=OpenAICompatibleProvider(base_url='http://unused',model='x')._payload(req)
    text=json.dumps(payload,ensure_ascii=False)
    assert 'UNSELECTED_FAILURE_BRANCH' not in text and 'candidates' not in text
    assert sum(e.kind=='director.triggered' for e in g.ledger.events)==1
    assert sum(e.kind=='director.resolved' for e in g.ledger.events)==1

def test_failed_trigger_never_rolls_resolution_or_leaks_candidate():
    c=candidate(chance=0,success='UNTRIGGERED_PRIVATE_PLOT',resolution={'kind':'dice','dice':'1d6','target':3},failure='ANOTHER_UNFIRED_BRANCH')
    g,p=game([c],enabled=True)
    assert g.submit_action({'text':'观察'}).ok
    req=requests(p,'narration')[0]
    assert 'triggered_events' not in req
    assert 'UNTRIGGERED_PRIVATE_PLOT' not in json.dumps(req,ensure_ascii=False)
    assert len([e for e in g.ledger.events if e.kind=='dice.resolved'])==1
    assert not any(e.kind in ('director.triggered','director.resolved') for e in g.ledger.events)

def test_internal_events_seed_and_failure_text_are_not_in_status_stream_or_log():
    g,p=game([candidate(visibility='internal',success='SECRET_BACKSTORY')],enabled=True)
    streamed=[];g.on_event=streamed.append
    assert g.submit_action({'text':'观察'}).ok
    texts=[json.dumps(v,ensure_ascii=False) for v in (g.status(),streamed,export_log(g),requests(p,'narration'))]
    for text in texts:
        assert 'SECRET_BACKSTORY' not in text and 'dice.seeded' not in text and 'director.proposed' not in text
    assert 'SECRET_BACKSTORY' in json.dumps(view(g,include_internal=True),ensure_ascii=False)
    assert 'dice.seeded' not in json.dumps(view(g,include_internal=True))

def test_director_is_event_driven_not_called_every_turn_and_seen_id_cannot_repeat():
    g,p=game([candidate()],enabled=True,min_turn_gap=1)
    for _ in range(5):assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==1
    request_once(g);request_once(g)
    assert view(g)['pending_manual']
    assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==2
    assert len([e for e in g.ledger.events if e.kind=='director.triggered'])==1
    assert not view(g)['pending_manual']

def test_failed_narration_retry_and_undo_reuse_proposal_and_dice():
    g,p=game([candidate(resolution={'kind':'dice','dice':'1d6','target':3},failure='雾散了。')],enabled=True)
    p.fail_narrator=1
    assert not g.submit_action({'text':'观察'}).ok
    rolls=[e.payload['result'] for e in g.ledger.events if e.kind=='dice.resolved']
    assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==1
    assert [e.payload['result'] for e in g.ledger.events if e.kind=='dice.resolved']==rolls
    assert view(g)['triggered_count']==1 and g.verify()['equal']
    g.undo();assert view(g)['triggered_count']==0
    assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==1
    assert [e.payload['result'] for e in g.ledger.events if e.kind=='dice.resolved']==rolls

def test_director_failure_does_not_rollback_game_or_repeat_every_turn():
    g,p=game(enabled=True);p.fail_director=True
    assert g.submit_action({'text':'观察'}).ok
    assert view(g)['last_run']['failed']
    assert 'PRIVATE_DIRECTOR_FAILURE' not in json.dumps(g.status())
    assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==1

@pytest.mark.parametrize('bad',[
    {'trigger':{'kind':'dice','dice':'1d20'}},
    {'resolution':{'kind':'dice','dice':'1d6','target':4}},
    {'scope':'player'},
    {'id':'bad id'},
    {'clue_id':'unregistered_clue'},
])
def test_bad_director_proposal_never_mutates_game_or_triggers(bad):
    g,p=game([candidate(**bad)],enabled=True)
    before=dict(g.state)
    assert g.submit_action({'text':'观察'}).ok and g.state==before
    assert not any(e.kind=='director.triggered' for e in g.ledger.events)
    assert view(g)['last_run']['failed']

def test_clues_and_model_roles_are_configurable_and_persisted():
    g,p=game(enabled=True,on_scene_change=False)
    put_clue(g,PlotClue(id='missing_key',title='失踪钥匙',summary='钥匙在哪里？'))
    put_clue(g,PlotClue(id='hidden_key',title='幕后线索',summary='SECRET_CLUE',visibility='internal'))
    assert len(view(g)['clues'])==1
    assert g.submit_action({'text':'调查'}).ok
    director=requests(p,'director')[0]
    assert director['reason']=='clue_change' and len(director['unresolved_clues'])==2
    assert 'SECRET_CLUE' not in json.dumps(requests(p,'narration'),ensure_ascii=False)
    saved=snapshot_payload(g,slot='clues');restored,_=game();restore_session(restored,saved)
    assert view(restored)['config']['enabled'] and len(view(restored,include_internal=True)['clues'])==2
    updated=merge_update(default_settings(),{'roles':{'director':{'provider':'custom','temperature':0.1}}})
    assert updated.roles.director.provider=='custom' and updated.roles.narrator.provider=='scripted'

def test_custom_director_model_is_optional_and_json_only():
    n=Provider();d=Provider([candidate()]);d.name='separate-director'
    config=LlmRolesConfig(narrator=LlmProfile(provider=n.name),director=LlmProfile(provider=d.name))
    g=GameSession(load_pack(ROOT/'packs/night-convenience-store'),LlmRouter(config,{n.name:n,d.name:d}))
    configure(g,DirectorConfig(enabled=True,use_narrator_model=False))
    assert g.submit_action({'text':'观察'}).ok
    assert len(d.requests)==1 and d.requests[0]['phase']=='director'
    payload=OpenAICompatibleProvider(base_url='http://unused',model='test')._payload(d.requests[0])
    assert 'tools' not in payload and len(payload['messages'])==2

@pytest.mark.usefixtures("strict_settlement")
def test_settlement_repair_and_whole_turn_retry_do_not_reroll():
    g,p=game()
    text='你观察着码头，风吹过栏杆。'
    roll={'name':'roll','args':{'dice':'2d6+3'},'evidence':text}
    bad={'name':'set_stat','args':{'field':'missing','value':3},'evidence':text}
    p.settlements=[batch([roll,bad]),batch([roll,bad]),batch([roll])]
    assert not g.submit_action({'text':'观察'}).ok
    assert len([e for e in g.ledger.events if e.kind=='dice.resolved'])==1
    assert g.submit_action({'text':'观察'}).ok
    assert len([e for e in g.ledger.events if e.kind=='dice.resolved'])==1
    assert g.verify()['equal']


def test_failure_branch_is_final_and_backend_receives_no_other_candidate_branches():
    c=candidate(resolution={'kind':'dice','dice':'1d6','target':10},success='UNUSED_SUCCESS_BRANCH',failure='船灯熄灭，港湾陷入昏暗。')
    g,p=game([c],enabled=True)
    assert g.submit_action({'text':'观察'}).ok
    narration=requests(p,'narration')[0]
    assert narration['triggered_events'][0]['outcome']==c['failure']
    backend=requests(p,'settlement')[0]
    assert backend['determined_events'][0]['resolution']['passed'] is False
    assert 'UNUSED_SUCCESS_BRANCH' not in json.dumps(backend)


def test_milestone_activates_director_after_real_flag_change():
    g,p=game([candidate()],enabled=True,on_scene_change=False,min_turn_gap=1)
    p.settlements=[batch([{'name':'set_flag','args':{'flag':'met_clerk','value':True},'evidence':'你观察着码头，风吹过栏杆。'}])]
    assert g.submit_action({'text':'观察'}).ok
    assert not requests(p,'director')
    assert g.submit_action({'text':'继续'}).ok
    assert requests(p,'director')[0]['reason']=='milestone'


def test_narrative_numeric_repair_keeps_same_determined_result():
    g,p=game([candidate()],enabled=True)
    original=p.complete;first=True
    def complete(request):
        nonlocal first
        if request['phase']=='narration' and first:
            first=False;p.requests.append(request)
            return LlmResponse(narrator=NarratorOutput(narrative='你的生命还剩13。'))
        return original(request)
    p.complete=complete
    assert g.submit_action({'text':'观察'}).ok
    narrations=requests(p,'narration')
    assert len(narrations)==2
    assert narrations[0]['triggered_events']==narrations[1]['triggered_events']
    assert len(requests(p,'director'))==1
    assert len([e for e in g.ledger.events if e.kind=='dice.resolved'])==1


def test_new_public_clue_view_never_exposes_old_secret_in_before_diff():
    g,_=game()
    put_clue(g,PlotClue(id='key',title='钥匙',summary='OLD_SECRET_LOCATION',visibility='internal'))
    put_clue(g,PlotClue(id='key',title='钥匙',summary='这是一条公开线索',visibility='public'))
    assert 'OLD_SECRET_LOCATION' not in json.dumps(g.status(),ensure_ascii=False)
    assert 'OLD_SECRET_LOCATION' in json.dumps(view(g,include_internal=True),ensure_ascii=False)
