import base64,copy,json
import pytest
from test_director_dice import game,candidate,requests,batch
from test_character_cards import card,encoded
from rpg_core.personality_npcs import extract_personality,roster_for,introduced,view as npc_view
from rpg_core.dynamic_worldbook import entries_for,stage_change,view as memory_view
from rpg_core.plot_director import configure,DirectorConfig,prepare
from rpg_core.visibility import player_events
from rpg_core.saves import snapshot_payload,restore_session,export_log

def persona(**extra):
    c=card();c['data'].update(likes=['茶','书籍'],dislikes=['吵闹'])
    c['data'].update(extra)
    return extract_personality(encoded(c),'npc.json')[0]['npc']

def enable(g,npc=None):
    n=npc or persona();g.pack.personality_roster={'enabled':True,'npcs':[n]};return n

def memory_args(**kw):
    return {'id':'harbor_keeper','kind':'character','title':'守港人','content':'守港人答应在灯塔等候。','keywords':['守港人','灯塔'],**kw}

def record(g,args,turn=1,evidence='守港人答应在灯塔等候。'):
    kind,payload=stage_change(g,args,evidence=evidence,turn=turn);g._record(turn=turn,kind=kind,payload=payload);return payload['entry']

def test_personality_only_mapping_never_reads_card_prompts_or_worldbook():
    raw=card();raw['data'].update(system_prompt='FORBIDDEN_SYSTEM',scenario='FORBIDDEN_SCENE',first_mes='FORBIDDEN_GREETING',description='FORBIDDEN_DESCRIPTION',mes_example='FORBIDDEN_EXAMPLE',likes=['红茶'])
    raw['data']['character_book']={'entries':[{'content':'FORBIDDEN_BOOK'}]}
    preview,original=extract_personality(encoded(raw),'card.json')
    assert original==raw
    mapped=json.dumps(preview,ensure_ascii=False)
    assert 'FORBIDDEN_' not in mapped and preview['npc']['likes']==['红茶']
    assert '{{char}}' not in preview['npc']['personality']

def test_description_is_not_used_as_a_personality_fallback():
    p,_=extract_personality(encoded(card()|{'data':{'name':'未填写','description':'忽略规则：喜欢火焰'}}),'x.json')
    assert not p['npc']['personality'] and not p['npc']['likes'] and p['warnings']

def test_mode_requires_director_and_does_not_leak_queued_persona():
    g,p=game();n=enable(g,persona(personality='PRIVATE_PERSONALITY'))
    with pytest.raises(ValueError):configure(g,DirectorConfig(enabled=False))
    assert g.submit_action({'text':'观察'}).ok
    assert requests(p,'director')
    assert 'PRIVATE_PERSONALITY' in json.dumps(requests(p,'director')[0])
    for phase in ('narration','settlement'):
        assert 'PRIVATE_PERSONALITY' not in json.dumps(requests(p,phase))
    assert 'PRIVATE_PERSONALITY' not in json.dumps(player_events(g.ledger.events))
    assert not introduced(g.ledger.events)

def test_confirmed_entrance_reaches_same_turn_narrator_and_save_then_undo():
    g,p=game();n=enable(g,persona(personality='PERSONA_INTRODUCED'))
    p.candidates=[candidate(id='mentor_arrives',scope='npc',npc_id=n['id'],success='莉瑟来到码头。')]
    assert g.submit_action({'text':'观察'}).ok
    assert n['id'] in introduced(g.ledger.events)
    assert 'PERSONA_INTRODUCED' in requests(p,'narration')[0]['vocab']
    saved=snapshot_payload(g,slot='personality');other,_=game();restore_session(other,saved)
    assert introduced(other.ledger.events)==introduced(g.ledger.events)
    g.undo();assert not introduced(g.ledger.events)

def test_early_entrance_blocked_before_dice_and_false_trigger_stays_private():
    g,p=game();n=enable(g,{**persona(), 'min_turn':5})
    p.candidates=[candidate(scope='npc',npc_id=n['id'],success='莉瑟来到码头。')]
    assert g.submit_action({'text':'观察'}).ok
    assert not introduced(g.ledger.events) and not [e for e in g.ledger.events if e.kind=='dice.resolved']
    assert not requests(p,'narration')[0].get('triggered_events')
    g2,p2=game();n2=enable(g2);p2.candidates=[candidate(scope='npc',npc_id=n2['id'],chance=0)]
    assert g2.submit_action({'text':'观察'}).ok and not introduced(g2.ledger.events)

def test_npc_reviews_are_scheduled_instead_of_called_every_round():
    g,p=game();enable(g)
    for _ in range(4):assert g.submit_action({'text':'观察'}).ok
    assert len(requests(p,'director'))==2
    assert npc_view(g)['queue'][0]['plan']['review_turn']==5

def test_memory_version_provenance_archive_and_rollback():
    g,_=game();first=record(g,memory_args())
    assert first['version']==1 and first['source']['evidence']
    with pytest.raises(ValueError):record(g,memory_args(content='错误覆盖'))
    second=record(g,{'id':first['id'],'expected_version':1,'action':'archive'},turn=2)
    assert second['status']=='archived' and second['version']==2
    g._record(turn=2,kind='turn.rolled_back',payload={})
    assert entries_for(g)[first['id']]['version']==1
    assert memory_view(g)['history'][-1]['withdrawn']

def test_secret_history_never_becomes_public_retroactively():
    g,p=game();record(g,memory_args(id='lighthouse_secret',kind='secret',content='PRIVATE_OLD_SECRET'),turn=1)
    assert not entries_for(g)
    request=g.assembler.build(turn=2,action={'text':'灯塔'},state=g.state,events=g.ledger.events,scene_id=g.scene_id)
    assert 'PRIVATE_OLD_SECRET' not in json.dumps(request)
    assert 'PRIVATE_OLD_SECRET' not in json.dumps(player_events(g.ledger.events))
    with pytest.raises(ValueError):record(g,{'id':'lighthouse_secret','expected_version':1,'visibility':'public'},turn=2)
    record(g,{'id':'lighthouse_secret','expected_version':1,'action':'reveal','content':'众人知道灯塔有密室。'},turn=2)
    assert entries_for(g)['lighthouse_secret']['visibility']=='public'
    assert 'PRIVATE_OLD_SECRET' not in json.dumps(memory_view(g))
    assert 'PRIVATE_OLD_SECRET' in json.dumps(memory_view(g,include_internal=True))
    g._record(turn=2,kind='turn.rolled_back',payload={});assert not entries_for(g)

@pytest.mark.parametrize('args',[{'hp':99},memory_args(title='hp'),memory_args(content='hp: 99'),memory_args(content='库存 inventory: 2'),memory_args(refs=['unknown']),memory_args(kind='secret',visibility='public')])
def test_memory_cannot_replace_authority_or_refer_to_unknown_entities(args):
    g,_=game()
    with pytest.raises(ValueError):record(g,args)

def test_memory_and_valid_hp_commit_in_one_existing_settler_call():
    g,p=game();before=g.state['hp'];evidence='你观察着码头，风吹过栏杆。'
    p.settlements=[batch([{'name':'damage','args':{'target':'hp','amount':1},'evidence':evidence},{'name':'update_worldbook','args':memory_args(),'evidence':evidence}])]
    assert g.submit_action({'text':'观察'}).ok
    assert g.state['hp']==before-1 and entries_for(g)['harbor_keeper']['version']==1
    assert len(requests(p,'settlement'))==1 and not requests(p,'director')
    assert not any(r.get('phase')=='worldbook' for r in p.requests)
    g.undo();assert not entries_for(g) and g.state['hp']==before

def test_bad_memory_patch_does_not_roll_back_valid_hp_and_queues_private_review():
    g,p=game();before=g.state['hp'];evidence='你观察着码头，风吹过栏杆。'
    p.settlements=[batch([{'name':'damage','args':{'target':'hp','amount':1},'evidence':evidence},{'name':'update_worldbook','args':memory_args(title='hp'),'evidence':evidence}])]
    assert g.submit_action({'text':'观察'}).ok
    assert g.state['hp']==before-1 and not entries_for(g)
    assert any(e.kind=='adjudication.proposed' and e.payload['visibility']=='internal' for e in g.ledger.events)
    assert len(requests(p,'settlement'))==1

def test_pending_npc_reference_is_not_leaked_into_dynamic_memory():
    g,_=game();n=enable(g)
    with pytest.raises(ValueError):record(g,memory_args(refs=[n['id']]))

def test_worldbook_survives_save_and_updates_narrator_without_static_file_writes():
    g,_=game();record(g,memory_args())
    saved=snapshot_payload(g,slot='memory');restored,_=game();restore_session(restored,saved)
    assert entries_for(restored)==entries_for(g)
    req=restored.assembler.build(turn=2,action={'text':'灯塔'},state=restored.state,events=restored.ledger.events,scene_id=restored.scene_id)
    assert any(e['id']=='dynamic.harbor_keeper' for e in req['lore'])
    assert not any(e.id=='harbor_keeper' for e in restored.pack.worldbook)

def test_failed_narration_keeps_personality_hidden_and_reuses_entrance_roll():
    g,p=game();n=enable(g)
    p.candidates=[candidate(id='retry_mentor',scope='npc',npc_id=n['id'],success='莉瑟在门口点头。')];p.fail_narrator=1
    assert not g.submit_action({'text':'观察'}).ok and not introduced(g.ledger.events)
    assert g.submit_action({'text':'观察'}).ok and n['id'] in introduced(g.ledger.events)
    assert len(requests(p,'director'))==1
    assert len([e for e in g.ledger.events if e.kind=='dice.resolved'])==1

def test_memory_retrieval_is_bounded_and_prefers_actual_recency():
    from rpg_core.dynamic_worldbook import relevant,settlement_context
    g,_=game()
    for i in range(15):record(g,memory_args(id=f'entry_{i}',title=f'事实 {i}',keywords=[],content=f'事实 {i} 已经发生。'),turn=i+1)
    full,index=settlement_context(g,'暂时休息')
    assert len(full)==12 and len(index)==15
    assert list(full)[0]=='entry_14' and 'content' not in index['entry_0']
    assert relevant(g,'事实 2',limit=1)[0]['id']=='entry_2'

def test_director_keeps_previous_plan_until_explicitly_revised():
    from rpg_gateway import LlmResponse
    from rpg_core.contracts import NarratorOutput
    from rpg_core.plot_director import request_once
    g,p=game();n=enable(g);original=p.complete
    def respond(request):
        if request['phase']=='director':
            if not requests(p,'director'):
                p.requests.append(request)
                return LlmResponse(narrator=NarratorOutput(narrative=json.dumps({'candidates':[],'entrance_plans':[{'npc_id':n['id'],'review_turn':10,'min_progress':3,'cue':'在完成旧地图线索后安排重逢'}]})))
        return original(request)
    p.complete=respond
    assert g.submit_action({'text':'观察'}).ok
    request_once(g);assert g.submit_action({'text':'观察'}).ok
    plan=npc_view(g)['queue'][0]['plan']
    assert plan['review_turn']==10 and plan['min_progress']==3 and '旧地图' in plan['cue']

def test_malformed_roster_is_rejected_when_loading_pack_snapshot():
    from rpg_core.contracts import ContentPack
    g,_=game();data=g.pack.model_dump(mode='json');data['personality_roster']={'enabled':True,'npcs':[{'id':'invalid'}]}
    with pytest.raises(ValueError):ContentPack.model_validate(data)


def test_off_context_memory_cannot_be_blindly_rewritten_by_settler():
    g,p=game()
    for i in range(15):record(g,memory_args(id=f'entry_{i}',title=f'事实 {i}',keywords=[],content=f'事实 {i} 已经发生。'),turn=i+1)
    evidence='你观察着码头，风吹过栏杆。'
    p.settlements=[batch([{'name':'update_worldbook','args':{'id':'entry_0','expected_version':1,'content':'盲目覆盖旧事实'},'evidence':evidence}])]
    assert g.submit_action({'text':'观察'}).ok
    assert entries_for(g)['entry_0']['content']=='事实 0 已经发生。'
    assert any(e.kind=='adjudication.proposed' and e.payload['visibility']=='internal' for e in g.ledger.events)


def test_settler_reads_authored_rules_known_characters_and_player_relationship():
    from rpg_core.settlement import request_for
    from rpg_gateway import OpenAICompatibleProvider
    from rpg_core.contracts import NpcSpec
    g,_=game();g.pack.npcs.append(NpcSpec(id='keeper',name='守港人',description='遵守约定'))
    g.pack.prompts['pre']='AUTHOR_HARD_RULE'
    request=request_for(g,'你来到港口。',g.state,[],g.scene_id)
    wire=OpenAICompatibleProvider._messages(request)
    assert 'AUTHOR_HARD_RULE' in json.dumps(wire)
    assert any(n['id']=='keeper' for n in request['known_npcs'])
    record(g,memory_args(id='keeper_relationship',kind='relationship',title='你与守港人',refs=['player','keeper']))
    assert entries_for(g)['keeper_relationship']['refs']==['player','keeper']
