import json
from uuid import uuid4
import pytest
from test_accuracy import fuzzy_game, acquired
from test_stateless_settlement import game,response,op,TEXT
from test_adjudication import pending_game,decision,execute
from rpg_core.adjudication import answer,view,DecisionError
from rpg_core.currency import context
from rpg_gateway import OpenAICompatibleProvider


def test_yen_and_generic_yuan_are_one_world_money_resource_not_cny_exchange():
    text='你捡到了100日元，小心地收进钱袋。'
    g,n,_=fuzzy_game(response([op('credit_currency',{'amount':100,'unit':'日元'},evidence=text)]));n.text=text
    g.pack.prompts['pre']='你在东京的一家便利店外探险。'
    assert context(g)['unit_mode']=='world_nominal'
    result=g.submit_action({'text':'我捡起地上的钱。'})
    assert result.ok and g.state['money']==137 and not g.inventory
    assert g.pack.state.limits.max_delta_per_turn['money']==50  # definition never mutated
    audit=next(e for e in g.ledger.events if e.kind=='settlement.currency')
    assert audit.payload['mode']=='world_nominal' and audit.payload['source_unit']=='日元'
    wire=OpenAICompatibleProvider._messages(n.requests[-1])
    assert json.loads(wire[1]['content'])['currency_context']['field']=='money'
    assert g.verify()['equal'] and g.undo()['state']['money']==37


def test_explicit_foreign_exchange_waits_for_yes_and_never_implicitly_uses_one_to_one():
    text='你收到了100日元。'
    batch=response([op('credit_currency',{'amount':100,'unit':'日元','converted_amount':5,'conversion_reason':'本世界兑换站约定二十日元换一元'},evidence=text)])
    g,n,_=fuzzy_game(batch);n.text=text
    g.pack.state.by_id()['money'].unit='人民币元'
    assert g.submit_action({'text':'收下钱'}).ok and g.state['money']==37
    row=view(g)['items'][0];assert '100日元' in row['question'] and '5人民币元' in row['question']
    answer(g,row['id'],True,'exchange-yes',view(g)['revision'])
    assert g.state['money']==42 and g.verify()['equal']


def test_explicit_cny_without_conversion_does_not_mint_one_hundred_cny():
    g,n,_=fuzzy_game(response([op('credit_currency',{'amount':100,'unit':'日元'})]));g.pack.state.by_id()['money'].unit='人民币元'
    assert g.submit_action({'text':'继续'}).ok and g.state['money']==37
    assert view(g)['pending_count']==1


@pytest.mark.parametrize('amount',[True,float('inf'),0,'100'])
def test_bad_currency_amount_cannot_mutate_state(amount):
    g,n,_=fuzzy_game(response([op('credit_currency',{'amount':amount,'unit':'日元'})]))
    result=g.submit_action({'text':'继续'})
    assert g.state['money']==37 and g.verify()['equal']


def test_yes_no_is_idempotent_and_invokes_no_model():
    g,n,_=fuzzy_game(acquired('钥匙'));assert g.submit_action({'text':'拾取'}).ok
    row=view(g)['items'][0];revision=view(g)['revision'];calls=len(n.requests)
    receipt=answer(g,row['id'],True,'quick-yes',revision)
    assert not receipt['reused'] and sum(g.inventory.values())==2
    assert answer(g,row['id'],True,'quick-yes',revision)['reused']
    assert sum(g.inventory.values())==2 and len(n.requests)==calls
    with pytest.raises(DecisionError):answer(g,row['id'],False,'quick-yes',revision)


def test_no_records_rejection_without_any_state_changes():
    g,n,_=pending_game();row=view(g)['items'][0];revision=view(g)['revision'];before=g.state
    answer(g,row['id'],False,'quick-no',revision)
    assert g.state==before and view(g)['items'][0]['state']=='rejected'
    assert answer(g,row['id'],False,'quick-no',revision)['reused']


def test_two_relative_questions_in_same_round_can_be_answered_sequentially():
    g,n,_=pending_game()
    from rpg_core.adjudication import propose
    from rpg_core.settlement import Pending
    propose(g,g.turn,Pending(title='第二次擦伤',reason='另一处轻伤',question='是否补记第二处轻伤？',evidence=TEXT,operations=[op('damage',{'amount':1})]),99)
    rows=view(g)['items']
    for i,row in enumerate(rows):answer(g,row['id'],True,'quick-relative-'+str(i),view(g)['revision'])
    assert g.state['hp']==17 and g.verify()['equal']


def test_stale_absolute_edits_hidden_questions_and_untrusted_operations_stay_blocked():
    g,n,_=pending_game(ops=[op('set_stat',{'field':'hp','value':5})]);row=view(g)['items'][0]
    n.queue=[response()];assert g.submit_action({'text':'下一轮'}).ok
    with pytest.raises(DecisionError):answer(g,row['id'],True,'stale-yes',view(g)['revision'])
    assert g.state['hp']==20
    hidden,_,_=pending_game(visibility='internal')
    from rpg_core.adjudication import items_for
    key=next(iter(items_for(hidden)))
    with pytest.raises(DecisionError):answer(hidden,key,True,'secret-answer',view(hidden)['revision'])
    invalid,_,_=pending_game(ops=[op('set_stat',{'field':'not_a_field','value':7})])
    with pytest.raises(DecisionError):answer(invalid,view(invalid)['items'][0]['id'],True,'invalid-answer',view(invalid)['revision'])
    assert 'not_a_field' not in invalid.state


def test_new_custom_currency_is_normalized_but_foreign_unknown_unit_is_not_cny():
    g,n,_=fuzzy_game(response([op('credit_currency',{'amount':100,'unit':'卢布'})]))
    assert g.submit_action({'text':'继续'}).ok and g.state['money']==137
    assert any(e.kind=='settlement.currency' and e.payload['mode']=='world_nominal' for e in g.ledger.events)
    other,_,_=fuzzy_game(response([op('credit_currency',{'amount':100,'unit':'卢布'})]))
    other.pack.state.by_id()['money'].unit='人民币元'
    assert other.submit_action({'text':'继续'}).ok and other.state['money']==37


def test_text_only_question_can_be_acknowledged_after_another_answer():
    g,n,_=pending_game(uncertain=['另一条仅需确认的说明'])
    first,second=view(g)['items']
    answer(g,first['id'],True,'first-answer',view(g)['revision'])
    answer(g,second['id'],True,'ack-only',view(g)['revision'])
    assert g.state['hp']==18 and all(i['state']=='confirmed' for i in view(g)['items'])
