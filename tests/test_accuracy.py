import copy
import json
import pytest
from uuid import uuid4

from test_stateless_settlement import game, response, op, TEXT
from test_adjudication import decision, execute
from rpg_core.adjudication import view, preview, DecisionError
from rpg_core.accuracy_policy import evidence_excerpt, unique_ref, item_catalog
from rpg_core.contracts import ToolCall
from rpg_core.saves import snapshot_payload, restore_session
from rpg_gateway import LlmResponse, OpenAICompatibleProvider, default_settings, merge_update, build_router, public_view, save_settings, load_settings


def acquired(*names):
    return response([op('acquire_item', {'name': name, 'count': 2, 'description': '在巷口找到的普通物品'}) for name in names])


def fuzzy_game(batch):
    g, n, s = game([batch]); g.router.settlement_options = {'fuzzy_identification': True}
    return g, n, s


def test_only_current_player_input_is_sent_and_serialized():
    g,n,_=game()
    assert g.submit_action({'text':'旧回合暗号'}).ok
    action={'text':'我把旧钥匙交给店员，并说：“请保管好。”','modes':['action','speech']}
    assert g.submit_action(action).ok
    request=n.requests[-1]
    assert request['player_input']['action']==action
    payload=OpenAICompatibleProvider._messages(request)
    assert len(payload)==2 and action['text'] in json.loads(payload[1]['content'])['player_input']['action']['text']
    assert '旧回合暗号' not in json.dumps(request,ensure_ascii=False)
    assert not {'recent','events','tool_exchanges'} & request.keys()


def test_opening_does_not_reuse_old_player_action():
    g,n,_=game();assert g.start_opening()['ok']
    assert n.requests[-1]['player_input']=={}


def test_evidence_accepts_spacing_and_punctuation_but_keeps_negation_and_numbers():
    assert evidence_excerpt('你拿到钥匙,随后 离开', '你拿到钥匙，随后离开。', True)=='你拿到钥匙，随后离开'
    for changed in ['你拿到钥匙','你拿到2枚金币','你丢失钥匙','你拿到-3枚金币','你拿到0.3枚金币']:
        with pytest.raises(ValueError):evidence_excerpt(changed,'你没有拿到钥匙，也没有拿到3枚金币。',True)


def test_unique_id_aliases_do_not_guess_ambiguous_names():
    assert unique_ref('体力',[{'id':'stamina','label':'体力'}])=='stamina'
    assert unique_ref('火球',[{'id':'fire_a','name':'火球'},{'id':'fire_b','name':'火球'}])=='火球'


def test_label_lookup_and_second_failure_defer_only_invalid_operation():
    batch=response([op('add_stat',{'field':'生命','delta':-2}),op('set_stat',{'field':'missing','value':3})])
    g,_,_=game([batch]);assert g.submit_action({'text':'继续'}).ok
    assert g.state['hp']==18 and 'missing' not in g.state
    assert view(g)['pending_count']==1 and g.verify()['equal']
    with pytest.raises(DecisionError):preview(g,view(g)['items'][0]['id'],decision(g))
    assert g.undo()['ok'] and g.state['hp']==20 and not view(g)['items']


def test_fuzzy_currency_adds_to_existing_resource_and_records_estimate():
    text='你捡到了几张纸币，小心地收进钱袋。'
    g,n,_=fuzzy_game(response([op('add_stat',{'field':'money','delta':6},evidence=text,estimated=True,estimate_reason='按本世界小面额纸币估为三张，每张二元')]))
    n.text=text
    result=g.submit_action({'text':'我检查地上的纸币并捡起来。'})
    assert result.ok and g.state['money']==43
    assert sum(e.kind=='settlement.estimated' for e in g.ledger.events)==1
    assert not g.inventory and g.verify()['equal']
    g.undo();assert g.state['money']==37


def test_disabled_fuzzy_estimate_is_deferred_without_inventing_money():
    batch=response([op('add_stat',{'field':'money','delta':6},estimated=True,estimate_reason='估算')])
    g,_,_=game([batch]);assert g.submit_action({'text':'继续'}).ok
    assert g.state['money']==37 and view(g)['pending_count']==1


def test_new_item_has_implicit_id_but_no_catalog_or_inventory_until_yes():
    g,n,_=fuzzy_game(acquired('旧钥匙'))
    assert g.submit_action({'text':'捡起来'}).ok
    row=view(g)['items'][0];args=row['operations'][0]['args'];key=args['item_id']
    assert key.startswith('found_') and '是否' in row['question'] and '旧钥匙' in row['question']
    assert key not in item_catalog(g) and not g.inventory
    before=g.ledger.to_dicts();result=preview(g,row['id'],decision(g))
    assert before==g.ledger.to_dicts() and any(c['domain']=='items' for c in result['changes'])
    calls=len(n.requests);receipt,d=execute(g,row['id'],decision(g))
    assert not receipt['reused'] and g.inventory[key]==2 and item_catalog(g)[key]['name']=='旧钥匙'
    assert len(n.requests)==calls and g.status()['items'][-1]['name']=='旧钥匙'
    from rpg_core.adjudication import act
    assert act(g,row['id'],d)['reused'] and g.inventory[key]==2
    assert key in g.executor.item_ids and g.verify()['equal']
    restored,_,_=game();restore_session(restored,snapshot_payload(g,slot='items'))
    assert item_catalog(restored)[key]['name']=='旧钥匙' and restored.inventory[key]==2
    execute(restored,row['id'],decision(restored,'undo'))
    assert key not in item_catalog(restored) and restored.inventory.get(key,0)==0


def test_no_and_defer_never_register_item_and_resume_can_confirm_later():
    g,n,_=fuzzy_game(acquired('旧钥匙','铜铃'));assert g.submit_action({'text':'捡起来'}).ok
    rows=view(g)['items'];execute(g,rows[0]['id'],decision(g,'reject'));execute(g,rows[1]['id'],decision(g,'defer'))
    assert not g.inventory and not any(k.startswith('found_') for k in item_catalog(g))
    n.queue=[response()];assert g.submit_action({'text':'离开'}).ok
    execute(g,rows[1]['id'],decision(g,'resume'))
    assert not next(i for i in view(g)['items'] if i['id']==rows[1]['id'])['stale']
    execute(g,rows[1]['id'],decision(g));assert sum(g.inventory.values())==2


def test_two_acquisitions_can_be_confirmed_sequentially_without_stale_rejection():
    g,_,_=fuzzy_game(acquired('旧钥匙','铜铃'));assert g.submit_action({'text':'捡起来'}).ok
    rows=view(g)['items']
    for row in rows:execute(g,row['id'],decision(g))
    assert len(g.inventory)==2 and sum(g.inventory.values())==4


def test_known_item_also_asks_then_inventory_loss_remains_direct():
    g,n,_=game();item=g.pack.items[0]
    n.queue=[response([op('add_item',{'item_id':item.id,'count':1})])]
    assert g.submit_action({'text':'拿起物品'}).ok and not g.inventory
    execute(g,view(g)['items'][0]['id'],decision(g));assert g.inventory[item.id]==1
    n.queue=[response([op('add_item',{'item_id':item.id,'count':-1})])]
    assert g.submit_action({'text':'用掉物品'}).ok and g.inventory[item.id]==0


def test_implicit_name_reuses_author_item_and_duplicate_names_share_stable_id():
    g,_,_=fuzzy_game(acquired('旧钥匙'));assert g.submit_action({'text':'拾取'}).ok
    from rpg_core.accuracy_policy import implicit_item
    first,_=implicit_item(g,{'name':'旧钥匙','count':1})
    second,_=implicit_item(g,{'name':'旧 钥匙','count':2})
    assert first['id']==second['id']
    existing=g.pack.items[0]
    assert implicit_item(g,{'name':existing.name,'count':1})[0]['id']==existing.id


@pytest.mark.parametrize('count',[0,-1,True,1.5,100001])
def test_bad_acquisition_count_cannot_register_or_hide_valid_damage(count):
    g,_,_=fuzzy_game(response([op('damage',{'amount':2}),op('acquire_item',{'name':'钥匙','count':count})]))
    assert g.submit_action({'text':'拾取'}).ok and g.state['hp']==18 and not g.inventory
    assert view(g)['pending_count']==1
    with pytest.raises(DecisionError):preview(g,view(g)['items'][0]['id'],decision(g))


def test_settings_merge_roundtrip_and_effective_router(tmp_path):
    original=default_settings();updated=merge_update(original,{'settlement':{'fuzzy_identification':True}})
    assert updated.settlement.relaxed_validation and updated.settlement.confirm_item_gains
    assert build_router(updated).settlement_options['fuzzy_identification']
    path=tmp_path/'settings.json';save_settings(updated,path)
    assert load_settings(path).settlement==updated.settlement
    assert public_view(updated)['settlement']['fuzzy_identification']
    with pytest.raises(ValueError):merge_update(original,{'settlement':{'unknown_switch':True}})


@pytest.mark.parametrize('relaxed',[True,False])
def test_bad_pending_quote_cannot_discard_valid_injury_in_relaxed_mode(relaxed):
    batch=response([op('damage',{'amount':2})])
    batch.tool_calls[0].args['pending']=[{'title':'是否获得线索','reason':'线索不明','question':'是否记录这条线索？','evidence':'这段引用并不在本轮正文'}]
    g,_,_=game([batch]);g.router.settlement_options={'relaxed_validation':relaxed}
    result=g.submit_action({'text':'继续'})
    assert result.ok==relaxed and g.state['hp']==(18 if relaxed else 20)
    if relaxed:assert view(g)['pending_count']==1


def test_nontext_item_id_is_deferred_without_losing_valid_damage():
    batch=response([op('damage',{'amount':1}),op('acquire_item',{'item_id':[],'name':'旧钥匙','count':1})])
    g,_,_=fuzzy_game(batch)
    assert g.submit_action({'text':'拾取'}).ok and g.state['hp']==19 and not g.inventory
    assert view(g)['pending_count']==1
