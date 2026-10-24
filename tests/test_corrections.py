import json
import pytest
from conftest import make_session
from rpg_core.adjudication import DecisionError,revision
from rpg_core.contracts import NarratorOutput,ToolCall,LlmProfile
from rpg_core.corrections import Correction,apply,undo,effective_narratives,preferences
from rpg_core.runtime import GameSession
from rpg_gateway.providers import LlmResponse,OpenAICompatibleProvider
from rpg_gateway.settings import merge_update,default_settings

class Provider:
    name='correction-test'
    def __init__(self,result):self.result=result;self.requests=[]
    def complete(self,request):self.requests.append(request);return self.result

def game(result):
    p=Provider(result);g=make_session(p)
    g._record(turn=0,kind='narrative.generated',payload={'narrative':'你走进书店，雨还未停。','options':[],'opening':True})
    return g,p

def response(changes):
    return LlmResponse(tool_calls=[ToolCall(id='correction',name='correct_values',args={'changes':changes})])

def body(g,mode='state',instruction='把体力改为18',request_id='a',**extra):
    return Correction(pack_id=g.pack.manifest.id,revision=revision(g),request_id=request_id,mode=mode,instruction=instruction,**extra)

def test_numeric_atomic_idempotent_restore_undo_and_stateless():
    g,p=game(response([{'field':'hp','value':18,'evidence':'体力改为18'}]));original=g.state.copy();b=body(g)
    a=apply(g,b);assert g.turn==0 and g.state['hp']==18 and g.verify()['equal']
    assert p.requests[0]['narrative']==b.instruction
    assert not set(p.requests[0]) & {'recent','history','worldbook','current_narrative','messages'}
    assert apply(g,b)['reused'] and len(p.requests)==1
    restored=GameSession(g.pack,g.router);restored.load_events(g.ledger.to_dicts());assert restored.state==g.state
    undo(restored,g.pack.manifest.id,a['receipt_id']);assert restored.state==original
    assert restored.verify()['equal']

@pytest.mark.parametrize('changes',[
    [{'field':'missing','value':1,'evidence':'体力'}],
    [{'field':'hp','value':999999,'evidence':'体力'}],
    [{'field':'hp','value':float('inf'),'evidence':'体力'}],
    [{'field':'hp','value':True,'evidence':'体力'}],
    [{'field':'hp','value':1.5,'evidence':'体力'}],
    [{'field':'hp','value':18,'evidence':'不是输入原文'}],
    [{'field':'hp','value':18,'evidence':'体力'},{'field':'hp','value':17,'evidence':'体力'}],
    [{'field':'hp','value':18,'evidence':'体力'},{'field':'not_registered','value':2,'evidence':'体力'}],
])
def test_bad_model_output_never_partly_commits(changes):
    g,_=game(response(changes));before=g.state.copy()
    with pytest.raises(DecisionError):apply(g,body(g))
    assert g.state==before and g.turn==0
    assert not any(e.kind in ('correction.applied','tool.applied') for e in g.ledger.events)

def test_rewrite_does_not_settle_and_updates_future_context():
    text='我走进书店，雨还未停。';g,p=game(LlmResponse(narrator=NarratorOutput(narrative=text)))
    original=g.state.copy();b=body(g,mode='narrative',instruction='改为第一人称，后续保持',persist=True)
    a=apply(g,b);assert len(p.requests)==1 and p.requests[0]['phase']=='narrative_correction'
    assert not p.requests[0]['allow_tools'] and g.state==original and g.turn==0
    assert g.opening_event().payload['narrative']==text
    assert effective_narratives(g.ledger.events)[0].payload['narrative']==text
    request=g.assembler.build(turn=1,action={'kind':'text','text':'继续'},state=g.state,events=g.ledger.events)
    assert text in request['recent'] and b.instruction in request['system_prompt']
    undo(g,g.pack.manifest.id,a['receipt_id']);assert g.opening_event().payload['narrative'].startswith('你') and not preferences(g.ledger.events)

def test_wrong_world_stale_and_changed_retry_rejected_before_call():
    g,p=game(response([]));b=body(g)
    with pytest.raises(DecisionError):apply(g,b.model_copy(update={'pack_id':'other'}))
    with pytest.raises(DecisionError):apply(g,b.model_copy(update={'revision':'stale'}))
    assert not p.requests
    apply(g,b)
    with pytest.raises(DecisionError):apply(g,b.model_copy(update={'instruction':'different'}))
    assert len(p.requests)==1

def test_gameplay_undo_reverts_anchored_correction_and_progress_blocks_direct_undo():
    g,_=game(response([{'field':'hp','value':18,'evidence':'体力'}]))
    g._record(turn=1,kind='turn.committed',payload={})
    apply(g,body(g));assert g.state['hp']==18
    assert g.undo()['ok'] and g.state['hp']==g.pack.state.defaults()['hp']
    a=apply(g,body(g,request_id='b'));g._record(turn=2,kind='turn.committed',payload={})
    with pytest.raises(DecisionError):undo(g,g.pack.manifest.id,a['receipt_id'])

def test_explicit_corrector_profile_without_separated_backend():
    g,main=game(response([]));other=Provider(response([]));other.name='isolated'
    g.router.providers[other.name]=other;g.router.config.corrector=LlmProfile(provider=other.name)
    apply(g,body(g));assert not main.requests and len(other.requests)==1
    assert other.requests[0]['temperature']==0
    saved=merge_update(default_settings(),{'roles':{'corrector':{'provider':'isolated'}}})
    assert saved.roles.corrector.provider=='isolated'
    assert merge_update(saved,{'roles':{'corrector':None}}).roles.corrector is None

def test_numeric_wire_has_no_other_mutators_or_history():
    g,p=game(response([]));apply(g,body(g));request=p.requests[0]
    provider=OpenAICompatibleProvider(base_url='https://example.com',api_key='unused',model='test')
    payload=provider._payload(request)
    assert [t['function']['name'] for t in payload['tools']]==['correct_values']
    assert len(payload['messages'])==2 and '你走进书店' not in json.dumps(payload,ensure_ascii=False)

def test_rewrite_rejects_tools_and_preserves_original():
    g,_=game(response([]));before=g.opening_event().payload['narrative']
    with pytest.raises(DecisionError):apply(g,body(g,mode='narrative'))
    assert g.opening_event().payload['narrative']==before
