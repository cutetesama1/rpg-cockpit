import json
from uuid import uuid4
import pytest
from test_stateless_settlement import game,response,op,TEXT
from rpg_core.adjudication import Decision,DecisionError,view,preview,act
from rpg_core.saves import snapshot_payload,restore_session,export_log
from rpg_gateway import LlmResponse
from rpg_core.contracts import ToolCall
from rpg_core.settlement import DOMAINS


def pending_game(*,ops=None,visibility='public',confirmed=None,uncertain=None,wardrobe=False):
    pending={'title':'伤势需要裁定','reason':'伤害程度不明','evidence':TEXT,'visibility':visibility,
             'operations':ops if ops is not None else [op('damage',{'amount':2})]}
    batch=LlmResponse(tool_calls=[ToolCall(id='settle',name='settle_turn',args={
        'checked':list(DOMAINS),'operations':confirmed or [],'pending':[pending], 'uncertain':uncertain or []})])
    g,n,s=game([batch],wardrobe=wardrobe);assert g.submit_action({'text':'观察'}).ok
    return g,n,s


def decision(g,action='confirm',**kwargs):
    return Decision(request_id=str(uuid4()),revision=view(g)['revision'],action=action,**kwargs)


def execute(g,key,d,**kwargs):
    if d.action in ('confirm','modify'):
        d=d.model_copy(update={'preview_token':preview(g,key,d,**kwargs)['preview_token']})
    return act(g,key,d,**kwargs),d


def first(g,internal=False):return view(g,include_internal=internal)['items'][0]['id']


def test_pending_has_no_state_effect_and_confirm_is_atomic_idempotent_and_no_model():
    g,n,_=pending_game(confirmed=[op('damage',{'amount':1})]);key=first(g)
    assert g.state['hp']==19 and not view(g)['items'][0]['stale']
    before=len(n.requests);d=decision(g)
    result=preview(g,key,d)
    assert result['changes']==[{'domain':'state','field':'hp','before':19,'after':17}]
    assert g.state['hp']==19
    receipt,d=execute(g,key,d)
    assert not receipt['reused'] and g.state['hp']==17 and g.turn==1 and g._next_turn()==2
    assert act(g,key,d)['reused'] and g.state['hp']==17 and len(n.requests)==before
    assert g.verify()['equal']
    with pytest.raises(DecisionError,match='不同裁定'):act(g,key,d.model_copy(update={'reason':'different'}))


def test_invalid_second_operation_or_status_cannot_partially_write():
    g,_,_=pending_game(ops=[op('damage',{'amount':2}),op('set_stat',{'field':'missing','value':3})]);key=first(g)
    before=g.ledger.to_dicts()
    with pytest.raises(DecisionError):preview(g,key,decision(g))
    assert before==g.ledger.to_dicts() and g.state['hp']==20


def test_modify_is_a_validated_draft_then_confirm_and_undo_restore_every_projection():
    g,_,_=pending_game();key=first(g)
    d=decision(g,'modify',reason='我裁定伤势较轻，仅扣一点体力，并记住码头线索',operations=[
        op('damage',{'amount':1}),op('record_fact',{'id':'harbor','title':'码头线索','value':True})],status_patch={'name':'旅人'})
    execute(g,key,d)
    assert g.state['hp']==20 and not g.status()['story_facts']
    execute(g,key,decision(g));assert g.state['hp']==19 and g.narrative_status()['name']=='旅人'
    assert g.status()['story_facts']['story.harbor']['value']
    assert not g.undo()['ok']
    execute(g,key,decision(g,'undo'))
    assert g.state['hp']==20 and not g.status()['story_facts'] and g.narrative_status() is None
    assert view(g)['items'][0]['state']=='pending' and not view(g)['items'][0]['stale']
    assert g.undo()['ok'] and not view(g)['items']


def test_defer_resume_reject_and_reopen_preserve_state_and_history():
    g,_,_=pending_game();key=first(g)
    for action,state in [('defer','deferred'),('resume','pending'),('reject','rejected'),('undo','pending')]:
        execute(g,key,decision(g,action,reason='玩家选择'))
        assert view(g)['items'][0]['state']==state and g.state['hp']==20
    assert [r['action'] for r in view(g)['history']]==['defer','resume','reject','undo']


def test_preview_required_and_stale_token_revision_and_stale_source_rejected():
    g,n,_=pending_game();key=first(g);d=decision(g)
    with pytest.raises(DecisionError,match='预览'):act(g,key,d)
    token=preview(g,key,d)['preview_token']
    execute(g,key,decision(g,'defer'))
    with pytest.raises(DecisionError,match='已更新'):act(g,key,d.model_copy(update={'preview_token':token}))
    execute(g,key,decision(g,'resume'))
    n.queue=[response()];assert g.submit_action({'text':'继续'}).ok
    assert view(g)['items'][0]['stale']
    with pytest.raises(DecisionError,match='重新校对'):preview(g,key,decision(g))
    execute(g,key,decision(g,'modify',reason='我已核对当前状态，补计先前轻伤',operations=[op('damage',{'amount':1})]))
    execute(g,key,decision(g));assert g.state['hp']==19


@pytest.mark.parametrize('name,args',[('roll',{'dice':'1d6'}),('damage',{'amount':9999}),('add_item',{'item_id':'missing','count':1}),('set_value',{'field':'missing','value':True})])
def test_manual_correction_cannot_bypass_existing_guards(name,args):
    g,_,_=pending_game();key=first(g);before=g.ledger.to_dicts()
    with pytest.raises((DecisionError,ValueError)):
        preview(g,key,decision(g,'modify',reason='玩家裁定',operations=[op(name,args)]))
    assert before==g.ledger.to_dicts()


def test_internal_proposals_receipts_and_facts_do_not_leak_to_public_views():
    g,_,_=pending_game(visibility='internal',ops=[op('record_fact',{'id':'secret','title':'PRIVATE_SECRET','value':True})])
    assert not view(g)['items'];key=first(g,True)
    with pytest.raises(DecisionError):preview(g,key,decision(g))
    execute(g,key,decision(g),include_internal=True)
    assert not g.status()['story_facts'] and not view(g)['history']
    assert 'PRIVATE_SECRET' not in json.dumps(g.status(),ensure_ascii=False)
    assert 'PRIVATE_SECRET' not in json.dumps(export_log(g),ensure_ascii=False)
    assert 'PRIVATE_SECRET' in json.dumps(view(g,include_internal=True),ensure_ascii=False)


def test_save_restore_preserves_pending_receipt_dedup_undo_and_no_game_turn_consumed():
    g,_,_=pending_game();key=first(g);_,d=execute(g,key,decision(g))
    saved=snapshot_payload(g,slot='adjudication');restored,_,_=game();restore_session(restored,saved)
    assert restored.state['hp']==18 and view(restored)['items'][0]['state']=='confirmed'
    assert act(restored,key,d)['reused']
    execute(restored,key,decision(restored,'undo'));assert restored.state['hp']==20
    assert restored.turn==1 and restored._next_turn()==2


def test_new_uncertain_and_legacy_warning_are_migrated_without_guessing_operations():
    g,_,_=pending_game(uncertain=['物品没有目录映射'])
    assert len(view(g)['items'])==2
    assert view(g)['items'][1]['operations']==[]
    legacy,_,_=game();legacy._record(turn=0,kind='settlement.warning',payload={'uncertain':['旧版待确认事项']})
    key=first(legacy)
    with pytest.raises(DecisionError,match='重新校对'):preview(legacy,key,decision(legacy))
    execute(legacy,key,decision(legacy,'modify',reason='仅确认说明，不改变任何状态',operations=[]))
    execute(legacy,key,decision(legacy));assert legacy.turn==0


def test_undo_refuses_to_overwrite_later_progress_but_works_after_gameplay_undo():
    g,n,_=pending_game();key=first(g);execute(g,key,decision(g));n.queue=[response()]
    assert g.submit_action({'text':'继续'}).ok
    with pytest.raises(DecisionError,match='已有游戏进度'):execute(g,key,decision(g,'undo'))
    assert g.undo()['ok']
    execute(g,key,decision(g,'undo'));assert g.state['hp']==20


def test_inventory_skill_and_scene_are_projected_and_undo_is_exact():
    g,_,_=pending_game(ops=[op('add_item',{'item_id':'bandage','count':2}),
        op('learn_skill',{'id':'careful_step','name':'谨慎步伐','cost':{},'cooldown':1})])
    key=first(g);skills=[s.id for s in g.all_skills()]
    execute(g,key,decision(g));assert g.inventory['bandage']==2
    assert 'careful_step' in [s.id for s in g.all_skills()] and 'careful_step' in g.executor.skill_ids
    execute(g,key,decision(g,'undo'))
    assert g.inventory=={} and [s.id for s in g.all_skills()]==skills and 'careful_step' not in g.executor.skill_ids


def test_clothing_and_pose_use_existing_catalogs_and_undo():
    g,_,_=pending_game(wardrobe=True,ops=[op('update_clothing',{'changes':[{'slot':'upper','garment':'hoodie','evidence':TEXT}]}),
        op('update_portrait',{'changes':{'pose':'stand'}})])
    key=first(g);before=g.state.copy();execute(g,key,decision(g))
    assert g.state['upper']=='hoodie'
    execute(g,key,decision(g,'undo'));assert g.state==before


def test_internal_fact_and_tool_details_never_reach_narrator_context():
    g,_,_=pending_game(visibility='internal',ops=[op('record_fact',{'id':'secret','title':'NARRATOR_PRIVATE_SECRET','value':'INTERNAL_RESULT'})])
    execute(g,first(g,True),decision(g),include_internal=True)
    request=g.assembler.build(turn=2,action={'text':'观察'},state=g.state,events=g.ledger.events,scene_id=g.scene_id)
    assert 'NARRATOR_PRIVATE_SECRET' not in json.dumps(request,ensure_ascii=False)
    assert 'INTERNAL_RESULT' not in json.dumps(request,ensure_ascii=False)


def test_failed_source_turn_has_no_pending_items():
    g,_,_=pending_game();assert g.undo()['ok']
    assert view(g)['items']==[] and view(g)['history']==[]


def test_history_survives_source_turn_undo_without_reopening_pending():
    g,_,_=pending_game();key=first(g)
    execute(g,key,decision(g,'reject'))
    assert g.undo()['ok']
    assert view(g)['items']==[]
    assert view(g)['history'][0]['source_withdrawn']
    assert view(g)['history'][0]['title']=='伤势需要裁定'


def test_empty_confirmation_also_reserves_a_unique_auxiliary_transaction_id():
    g,_,_=pending_game(ops=[]);key=first(g)
    execute(g,key,decision(g))
    first_receipt=[e for e in g.ledger.events if e.kind=='adjudication.decided'][-1]
    from rpg_core.adjudication import propose
    from rpg_core.settlement import Pending
    propose(g,g.turn,Pending(title='另一个说明',reason='无需状态变化',evidence=TEXT),9)
    other=view(g)['items'][1]['id']
    execute(g,other,decision(g))
    last_receipt=[e for e in g.ledger.events if e.kind=='adjudication.decided'][-1]
    assert last_receipt.payload['transaction_turn']<first_receipt.payload['transaction_turn']<0
