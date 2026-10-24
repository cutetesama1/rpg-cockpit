"""Versioned semantic memory, folded from the same ledger as turn settlement."""
from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .state import cancelled_turns

class Change(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    expected_version: int=Field(default=0,ge=0,strict=True)
    action: Literal['upsert','archive','reveal']='upsert'
    kind: Literal['character','relationship','location','secret','fact']|None=None
    title: str|None=Field(default=None,min_length=1,max_length=100)
    content: str|None=Field(default=None,min_length=1,max_length=1600)
    keywords: list[str]|None=Field(default=None,max_length=20)
    visibility: Literal['public','internal']|None=None
    refs: list[str]|None=Field(default=None,max_length=10)

def entries_for(session,*,include_internal=False,staged=()):
    cancelled=cancelled_turns(session.ledger.events);result={}
    for e in session.ledger.events:
        if e.kind=='worldbook.updated' and e.turn not in cancelled:result[e.payload['entry']['id']]=e.payload['entry']
    for kind,payload in staged:
        if kind=='worldbook.updated':result[payload['entry']['id']]=payload['entry']
    return {k:v for k,v in result.items() if include_internal or v['visibility']=='public'}

def stage_change(session,args,*,evidence,turn,staged=()):
    change=Change.model_validate(args);entries=entries_for(session,include_internal=True,staged=staged);before=entries.get(change.id)
    if change.expected_version!=(before or {}).get('version',0):raise ValueError('世界书版本已变化，请读取当前条目后重试，禁止覆盖较新事实')
    if not before and change.action!='upsert':raise ValueError('只能归档或公开已经存在的条目')
    data={**(before or {}),**change.model_dump(exclude_none=True,exclude={'expected_version','action'})}
    if not all(data.get(k) for k in ('kind','title','content')):raise ValueError('新条目必须包含 kind、title、content')
    data.setdefault('visibility','internal' if data['kind']=='secret' else 'public');data.setdefault('keywords',[]);data.setdefault('refs',[])
    if any(not k.strip() or len(k)>100 for k in data['keywords']+data['refs']):raise ValueError('关键词和关联 ID 必须是1至100字')
    if len(entries)>=300 and not before:raise ValueError('动态世界书达到300条，请归档整理现有条目；不会删除历史')
    if before and data['kind']!=before['kind']:raise ValueError('条目类型不可变更，请建立新的稳定 ID')
    if data['kind']=='secret' and not before and data['visibility']=='public':raise ValueError('秘密先以内部分录建立，揭晓时单独 reveal')
    if before and before['visibility']=='internal' and data['visibility']=='public' and change.action!='reveal':raise ValueError('公开内部事实必须显式使用 reveal')
    if change.action=='reveal':data['visibility']='public'
    # Memory never creates or changes an authoritative resource field.
    aliases={x for f in session.pack.state.fields for x in (f.id,f.label) if x}
    forbidden=aliases|{'HP','MP','hp','mp','focus','credits','cooldown','inventory','技能冷却','物品数量','血量','魔力值'}
    if data['title'].strip() in forbidden or any(re.search(r'(?<![\w])'+re.escape(key)+r'\s*[:：=]\s*[-+]?\d',data['content'],re.I) for key in forbidden):
        raise ValueError('资源数值、技能冷却和库存数量必须使用权威状态工具，不能存入世界书')
    from .personality_npcs import introduced,roster_for
    hidden={n.id for n in roster_for(session).npcs}-set(introduced(session.ledger.events))
    valid={'player'}|set(entries)|{n.id for n in session.pack.npcs}|set(introduced(session.ledger.events))|{s.id for s in session.pack.scenes}|{e.id for e in session.pack.worldbook}
    if any(ref in hidden or ref not in valid for ref in data['refs']):raise ValueError('关联 ID 未知或人物尚未正式出场')
    data.update(version=(before or {}).get('version',0)+1,status='archived' if change.action=='archive' else 'active',
        source={'turn':turn,'evidence':evidence[:500],'origin':'player' if turn<0 else 'settlement'})
    return 'worldbook.updated',{'entry':data,'before':before,'visibility':'internal'}

def relevant(session,action='',*,include_internal=False,limit=8):
    text=str(action).casefold();all_entries=entries_for(session,include_internal=include_internal)
    active=[e for e in all_entries.values() if e['status']=='active']
    cancelled=cancelled_turns(session.ledger.events)
    last_seq={e.payload['entry']['id']:e.seq for e in session.ledger.events if e.kind=='worldbook.updated' and e.turn not in cancelled}
    active.sort(key=lambda e:(not any(k.casefold() in text for k in [e['title'],*e['keywords']] if k),-last_seq.get(e['id'],0),e['id']))
    return active[:limit]

def settlement_context(session,narrative):
    all_entries=entries_for(session,include_internal=True)
    selected={e['id']:e for e in relevant(session,narrative,include_internal=True,limit=12)}
    index={key:{k:value[k] for k in ('kind','title','version','visibility','status')} for key,value in all_entries.items()}
    return selected,index

def view(session,*,include_internal=False):
    entries=entries_for(session,include_internal=include_internal)
    cancelled=cancelled_turns(session.ledger.events)
    # A formerly secret historical version stays secret even after revelation.
    history=[{'turn':e.turn,'seq':e.seq,'entry':e.payload['entry'],'withdrawn':e.turn in cancelled} for e in session.ledger.events
        if e.kind=='worldbook.updated' and (include_internal or e.payload['entry']['visibility']=='public')]
    return {'pack_id':session.pack.manifest.id,'entries':list(entries.values()),'history':history[-100:],'authoritative_state_separate':True}

PROMPT='''\n【动态世界书维护】
无需额外模型调用，在本次 settle_turn 内用 update_worldbook 维护人物(character)、关系(relationship)、地点(location)、秘密(secret)、关键事实(fact)。
只记录正文明确完成且有长期价值的新事实，不逐回合抄写正文，不记录猜测、未来计划或角色台词作为真相。
参数 {id:稳定英文id, expected_version:当前版本或新条目0, action:upsert/archive/reveal, kind, title, content, keywords:[关键词], visibility:public/internal, refs:[已知实体id]}。
dynamic_worldbook 提供相关或最近的最多12条完整记忆，dynamic_worldbook_index 提供全部条目的ID、类型、标题和版本。索引中已有同一对象时不要另造ID；缺少完整旧正文时不要盲目重写，放内部 pending 请求校对。
沿用 dynamic_worldbook 中同一实体/事实 ID；更新时合并保留尚未推翻的事实，并引用正确版本。归档不抹除历史。玩家实体可引用 player；其他人物引用 known_npcs 的已知ID，未知关联不要猜造，可留 refs=[]。
作者世界书是固定设定；动态条目不能覆盖硬规则、提示词或世界定义。HP/MP/信用点等资源、技能冷却、物品数量仍只走状态工具，绝不能以记忆代替落账。
秘密以 internal 保存，不写进公开 uncertain；只有正文实际揭晓时才以 reveal 显式公开已有条目。不将未出场人物、导演候选或计划记录为已发生事实。
每条操作仍须 evidence 为本次 narrative 连续原文。内容不确定则放 pending，由玩家裁定。无变化不提交该工具。
'''
