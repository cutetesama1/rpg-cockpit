"""Narrative-driven settlement regressions: diagnostics, repair and replay safety."""
import copy
import json
import pytest
from test_stateless_settlement import game, response, op, TEXT
from rpg_core.settlement import DOMAINS
from rpg_core.contracts import NarratorOutput
from rpg_gateway import LlmResponse, OpenAICompatibleProvider


def with_uncertain(batch, *notes):
    batch.tool_calls[0].args['uncertain']=list(notes)
    return batch


def test_uncertain_item_does_not_undo_confirmed_damage_and_survives_replay():
    batch=with_uncertain(response([op('damage',{'amount':2})]),'提到的披风不在衣物目录，保持原衣着')
    g,n,_=game([batch])
    result=g.submit_action({'text':'继续'})
    assert result.ok and result.state['hp']==18
    assert len([r for r in n.requests if r['phase']=='settlement'])==1
    assert '待确认' in result.ignored[0]
    assert any(e.kind=='settlement.warning' for e in g.ledger.events)
    assert not any(e.kind=='turn.rolled_back' for e in g.ledger.events)
    assert g.verify()['equal']
    g.undo();assert g.state['hp']==20


def test_uncertain_cannot_hide_an_invalid_operation_or_partial_commit():
    bad=with_uncertain(response([op('damage',{'amount':2}),op('set_stat',{'field':'missing','value':3})]),'未知信息')
    g,_,_=game([bad]);result=g.submit_action({'text':'继续'})
    assert not result.ok and g.state['hp']==20
    assert not any(e.kind in ('tool.applied','settlement.warning') for e in g.ledger.events)


@pytest.mark.parametrize('as_json',[False,True])
def test_repair_receives_complete_rejected_draft_error_location_and_original_state(as_json):
    bad=response([op('damage',{'amount':2}),op('set_stat',{'field':'missing','value':3})])
    original=copy.deepcopy(bad.tool_calls[0].args)
    if as_json:bad=LlmResponse(narrator=NarratorOutput(narrative=json.dumps(original)))
    g,n,_=game([bad,response([op('damage',{'amount':2})])])
    assert g.submit_action({'text':'继续'}).state['hp']==18
    backend=[r for r in n.requests if r['phase']=='settlement']
    first,retry=backend
    assert 'validation_feedback' not in first
    assert first['state']==retry['state'] and first['state']['hp']==20
    feedback=retry['validation_feedback']
    assert feedback['previous_proposal']==original
    assert feedback['failed_at']=='operations[1] (set_stat)'
    assert feedback['code']=='unknown_field'
    assert sum(e.kind=='tool.applied' for e in g.ledger.events)==1
    assert g.verify()['equal']


@pytest.mark.parametrize('key',['遇见守门人','story.met_gatekeeper','a'*100])
def test_story_fact_id_is_stable_and_never_grants_a_system_flag(key):
    g,_,_=game([response([op('set_flag',{'flag':key,'value':True})]),response([op('record_fact',{'id':key,'value':False})])])
    assert g.submit_action({'text':'继续'}).ok
    facts=g.status()['story_facts'];assert len(facts)==1
    fact_id=next(iter(facts));assert fact_id.startswith('story.') and not fact_id.startswith('story.story.')
    assert key not in g.state
    assert g.submit_action({'text':'继续'}).ok
    assert g.status()['story_facts'][fact_id]['value'] is False
    assert g.verify()['equal']
    g.undo();assert g.status()['story_facts'][fact_id]['value'] is True


@pytest.mark.parametrize('key',['',None,3,'story.'])
def test_empty_or_nontext_fact_ids_still_fail_atomically(key):
    g,_,_=game([response([op('damage',{'amount':2}),op('record_fact',{'id':key,'value':True})])])
    assert not g.submit_action({'text':'继续'}).ok and g.state['hp']==20


def test_old_world_prompts_cannot_change_the_runtime_wire_contract():
    g,n,_=game()
    g.pack.prompts['settler']='逐个调用 inventory 和 flag，输出全部状态。'
    g.pack.prompts['narrator']='你负责所有状态和工具。'
    assert g.submit_action({'text':'继续'}).ok
    front=n.requests[0]['system_prompt']
    assert '当前状态' in front and '你只负责叙事和选项' in front
    backend=n.requests[-1]
    messages=OpenAICompatibleProvider._messages(backend)
    assert len(messages)==2
    assert '旧版逐工具调用、输出格式指令不适用' in messages[0]['content']
    assert messages[0]['content'].endswith('只提交一次 settle_turn 完整草案；字段、目录、已收费用与累计限额以本次输入为准。')
    assert 'recent' not in backend and 'events' not in backend


def test_forty_turns_with_uncertainty_facts_and_repairs_keep_state_and_replay():
    batches=[]
    for i in range(40):
        ops=[op('damage' if i%2==0 else 'heal',{'amount':1}),op('record_fact',{'id':'story.round_note','title':'训练轮次','value':i})]
        if i%5==0:batches.append(response(ops+[op('set_stat',{'field':'bad_field','value':1})]))
        batches.append(with_uncertain(response(ops),*(['陌生装饰未登记，不更换'] if i%3==0 else [])))
    g,n,_=game(batches)
    for i in range(40):
        result=g.submit_action({'text':'训练'})
        assert result.ok and result.state['hp']==(19 if i%2==0 else 20)
        assert g.status()['story_facts']['story.round_note']['value']==i
    requests=[r for r in n.requests if r['phase']=='settlement']
    assert len(requests)==48
    assert all('events' not in r and 'recent' not in r for r in requests)
    assert len([e for e in g.ledger.events if e.kind=='tool.applied'])==40
    assert not any(e.kind=='turn.rolled_back' for e in g.ledger.events)
    assert g.verify()['equal']
    g.undo();assert g.state['hp']==19 and g.status()['story_facts']['story.round_note']['value']==38


def test_narrator_payment_instruction_never_delegates_mutations_to_frontend():
    g,n,_=game()
    assert g.submit_action({'kind':'skill','skill_id':'observe'}).ok
    req=n.requests[0]
    req['payments']=[{'field':'stamina','label':'体力','amount':1,'remaining':9}]
    text=OpenAICompatibleProvider._messages(req)[1]['content']
    assert '由独立后端结算' in text
    assert '照常调用工具结算' not in text
    assert '你不调用任何状态工具' in text
