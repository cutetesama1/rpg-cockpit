"""Player adjudications reuse settlement validation without invoking a model.

Negative turn IDs identify auxiliary transactions, never committed game turns.
Existing cancelled-turn projections undo their state, inventory, facts and skills.
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import Event
from .state import cancelled_turns


class DecisionError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9_.:-]+$')
    revision: str = Field(min_length=1, max_length=64)
    action: Literal['confirm', 'reject', 'modify', 'defer', 'resume', 'undo']
    reason: str = Field(default='', max_length=500)
    operations: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    status_patch: dict[str, Any] | None = None
    preview_token: str | None = Field(default=None, max_length=64)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def snapshot(session):
    from .settlement import facts
    from .dynamic_worldbook import entries_for
    from .personality_npcs import introduced
    from .accuracy_policy import item_catalog
    return {'items':item_catalog(session,include_internal=True),'worldbook': entries_for(session,include_internal=True), 'npcs': introduced(session.ledger.events), 'state': session.state, 'inventory': session.inventory,
            'scene': session.scene_id, 'status': session.narrative_status(),
            'skills': {s.id: s.model_dump(mode='json') for s in session.all_skills()},
            'facts': facts(session, include_internal=True),
            'schema': session.pack.state.model_dump(mode='json')}


def revision(session):
    return digest({'pack': session.pack.manifest.id, 'schema': session.pack.state.model_dump(mode='json'), 'events': session.ledger.to_dicts()})


def propose(session, turn, pending, index, *, origin='backend'):
    data = pending.model_dump(mode='json')
    item_id = 'decision_' + digest([turn, origin, index, data])[:24]
    session._record(turn=turn, kind='adjudication.proposed', role='settler', payload={
        **data, 'id': item_id, 'source_turn': turn, 'origin': origin,
        'basis': digest(snapshot(session)), 'anchor': turn,
    })


def pending_events(session, turn, proposal, narrative, staged):
    """Build pending records against the fully staged post-settlement state."""
    from .settlement import Pending
    shadow = copy.copy(session); shadow.ledger = copy.deepcopy(session.ledger)
    for kind, payload in staged: shadow.ledger.append(turn=turn, kind=kind, payload=payload)
    basis = digest(snapshot(shadow))
    pending = [(p, 'backend') for p in proposal.pending]
    pending += [(Pending(title=text[:100], reason=text[:500]), 'uncertain') for text in proposal.uncertain]
    result = []
    for index, (p, origin) in enumerate(pending):
        from .accuracy_policy import evidence_excerpt,options
        if p.evidence:
            try:p.evidence=evidence_excerpt(p.evidence,narrative,options(session)['relaxed_validation'])
            except ValueError:
                if not options(session)['relaxed_validation']:raise
                p.evidence=''
                p.reason=(p.reason+'；引用未能匹配正文，请在确认前核对原文和操作草案。')[:500]
        data = p.model_dump(mode='json')
        data['evidence_excerpt'] = data['evidence']; data['evidence'] = narrative
        item_id = 'decision_' + digest([turn, origin, index, data])[:24]
        result.append(('adjudication.proposed', {**data, 'id': item_id, 'source_turn': turn,
                                               'origin': origin, 'basis': basis, 'anchor': turn}))
    return result


def items_for(session):
    cancelled = cancelled_turns(session.ledger.events)
    items = {}
    for event in session.ledger.events:
        p = event.payload
        if event.kind == 'adjudication.proposed' and event.turn not in cancelled:
            items[p['id']] = {**copy.deepcopy(p), 'state': 'pending', 'version': event.seq, 'created_seq': event.seq}
        elif event.kind == 'settlement.warning' and event.turn not in cancelled and not p.get('adjudication_linked'):
            # Text-only uncertainties from old saves require an explicit edit.
            for index, text in enumerate(p.get('uncertain', [])):
                key = f'legacy_{event.seq}_{index}'
                items[key] = {'id': key, 'title': str(text)[:100], 'reason': str(text), 'evidence': '',
                              'visibility': 'public', 'operations': [], 'status_patch': {}, 'source_turn': event.turn,
                              'origin': 'legacy', 'basis': None, 'anchor': event.turn, 'state': 'pending',
                              'version': event.seq, 'created_seq': event.seq}
        elif event.kind == 'adjudication.decided' and p.get('id') in items:
            item = items[p['id']]
            action = p['action']
            if action == 'modify':
                item.update(copy.deepcopy(p['proposal'])); item['state'] = 'pending'
            else:
                item['state'] = {'confirm': 'confirmed', 'reject': 'rejected', 'defer': 'deferred', 'resume': 'pending', 'undo': 'pending'}[action]
            if action == 'confirm':
                item['transaction_turn'] = p.get('transaction_turn'); item['confirmed_seq'] = event.seq
            if action == 'undo':
                item['basis'] = p['basis']; item['anchor'] = p['anchor']
            item['version'] = event.seq
    return items


def _get(session, item_id, include_internal):
    item = items_for(session).get(item_id)
    if not item or item.get('visibility') == 'internal' and not include_internal:
        raise DecisionError('未找到该待裁定事项，或原回合已撤销', 404)
    return item


def _changes(before, after):
    result = []
    for domain in ('state', 'inventory', 'status', 'skills', 'facts', 'worldbook', 'npcs', 'items'):
        left, right = before[domain] or {}, after[domain] or {}
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                result.append({'domain': domain, 'field': key, 'before': left.get(key), 'after': right.get(key)})
    if before['scene'] != after['scene']:
        result.append({'domain': 'scene', 'field': 'scene', 'before': before['scene'], 'after': after['scene']})
    return result


def _validate(session, item, decision):
    from .contracts import ToolCall
    from .settlement import DOMAINS, Proposal, settle
    if decision.action not in ('confirm', 'modify'):
        raise DecisionError('该操作不需要状态预览')
    if item['state'] != 'pending':
        raise DecisionError('只有待裁定事项才能修改或确认；搁置事项请先恢复', 409)
    if decision.action == 'confirm':
        if decision.operations is not None or decision.status_patch is not None:
            raise DecisionError('确认不能夹带修改，请先保存修改并重新预览')
        from .accuracy_policy import acquisition_only
        if not acquisition_only(item) and (item.get('basis') != digest(snapshot(session)) or item['anchor'] != session.turn):
            raise DecisionError('原状态或游戏进度已变化，请先修改并按当前状态重新校对', 409)
        operations = copy.deepcopy(item['operations']); patch = item['status_patch']
        narrative = item['evidence']; reason = decision.reason.strip()
    else:
        reason = decision.reason.strip()
        if not reason: raise DecisionError('修改裁定需要填写玩家裁定依据')
        operations = copy.deepcopy(decision.operations if decision.operations is not None else item['operations'])
        patch = decision.status_patch if decision.status_patch is not None else item['status_patch']
        narrative = item['evidence'] + '\n玩家裁定：' + reason
        for operation in operations:
            operation['evidence'] = reason
            if operation.get('name') == 'update_clothing':
                for change in operation.get('args', {}).get('changes', []):
                    if isinstance(change, dict): change['evidence'] = reason[:300]
    proposal = Proposal.model_validate({'checked': list(DOMAINS), 'operations': operations, 'status_patch': patch})
    if any(op.name == 'roll' or op.source != 'narrative' for op in proposal.operations):
        raise DecisionError('裁定不能重掷骰子或重扣技能费用，请使用独立骰子工具')
    before = snapshot(session)
    shadow = copy.copy(session)
    shadow.pack = copy.deepcopy(session.pack); shadow.ledger = copy.deepcopy(session.ledger)
    shadow.executor = copy.deepcopy(session.executor)
    shadow.on_event = None; shadow.on_narrative = None
    shadow._record_usage = lambda *args, **kwargs: None
    response = SimpleNamespace(tool_calls=[ToolCall(id='player_decision', name='settle_turn', args=proposal.model_dump(mode='json'))])
    shadow.router = SimpleNamespace(complete=lambda *args, **kwargs: response)
    transaction_turn = min([0, *(e.turn for e in session.ledger.events),
                            *(e.payload.get('transaction_turn', 0) for e in session.ledger.events if e.kind == 'adjudication.decided')]) - 1
    offset = len(shadow.ledger.events)
    error, _, _, _ = settle(shadow, transaction_turn, narrative, session.state, [], session.scene_id, {})
    if error: raise DecisionError(error)
    staged = [e for e in shadow.ledger.events[offset:] if e.kind not in ('settlement.checked', 'settlement.rejected')]
    after = snapshot(shadow)
    return {'operations': [op.model_dump(mode='json') for op in proposal.operations], 'status_patch': proposal.status_patch,
            'evidence': narrative, 'reason': reason, 'basis': digest(before), 'anchor': session.turn}, staged, before, after, transaction_turn


def preview(session, item_id, decision, *, include_internal=False):
    item = _get(session, item_id, include_internal)
    current = revision(session)
    if decision.revision != current: raise DecisionError('裁定列表已更新，请刷新后重新预览', 409)
    proposal, staged, before, after, _ = _validate(session, item, decision)
    token = digest([current, item_id, decision.action, proposal, [e.model_dump(mode='json', exclude={'ts'}) for e in staged]])
    return {'pack_id': session.pack.manifest.id, 'revision': current, 'preview_token': token,
            'changes': _changes(before, after), 'no_state_change': before == after}


def _undo_allowed(session, receipt):
    authority = {'item.registered','correction.applied', 'worldbook.updated', 'npc.introduced', 'npc.roster.configured', 'turn.started', 'turn.committed', 'turn.rolled_back', 'tool.applied', 'skill.used', 'skill.learned', 'scene.entered', 'status.updated', 'story.fact', 'world.configured'}
    cancelled = cancelled_turns(session.ledger.events)
    return not any(e.seq > receipt.seq and e.kind in authority and e.turn not in cancelled for e in session.ledger.events)


def act(session, item_id, decision, *, include_internal=False):
    request_hash = digest([item_id, decision.model_dump(mode='json'), include_internal])
    for event in session.ledger.events:
        if event.kind == 'adjudication.decided' and event.payload.get('request_id') == decision.request_id:
            if event.payload['request_hash'] != request_hash: raise DecisionError('该请求编号已经用于不同裁定，请重新操作', 409)
            if event.payload.get('item_visibility') == 'internal' and not include_internal: raise DecisionError('未找到该待裁定事项', 404)
            return {'reused': True, 'receipt_id': event.seq}
    item = _get(session, item_id, include_internal)
    if decision.revision != revision(session): raise DecisionError('游戏状态或裁定列表已更新，请刷新后重新操作', 409)
    action = decision.action
    payload = {'id': item_id, 'title': item['title'], 'action': action, 'reason': decision.reason.strip(),
               'request_id': decision.request_id, 'request_hash': request_hash,
               'item_visibility': item['visibility'], 'visibility': 'internal',
               'before_state': item['state'], 'source_turn': item['source_turn'], 'changes': []}
    staged = []
    if action in ('confirm', 'modify'):
        result = preview(session, item_id, decision, include_internal=include_internal)
        if decision.preview_token != result['preview_token']: raise DecisionError('请先预览本次修改，再按预览结果提交', 409)
        proposal, staged, before, after, transaction_turn = _validate(session, item, decision)
        payload['proposal'] = proposal; payload['changes'] = _changes(before, after)
        if action == 'modify':
            staged = []
            payload['previous_proposal'] = {k: item[k] for k in ('operations', 'status_patch', 'evidence', 'reason', 'basis', 'anchor')}
        else: payload['transaction_turn'] = transaction_turn
    elif action == 'undo':
        if decision.operations is not None or decision.status_patch is not None or decision.preview_token: raise DecisionError('撤销不能夹带状态修改')
        if item['state'] not in ('confirmed', 'rejected'): raise DecisionError('只能撤销已确认或已否决的裁定', 409)
        receipt = next(e for e in reversed(session.ledger.events) if e.kind == 'adjudication.decided' and e.payload.get('id') == item_id)
        if item['state'] == 'confirmed':
            if not _undo_allowed(session, receipt): raise DecisionError('该裁定之后已有游戏进度或状态修改，不能直接撤销；请通过调试台修正', 409)
            transaction_turn = receipt.payload['transaction_turn']
            staged = [Event(seq=0, turn=transaction_turn, kind='turn.rolled_back', payload={'reason': 'adjudication_undo', 'visibility': 'internal', 'id': item_id})]
            payload['changes'] = [{**change, 'before': change['after'], 'after': change['before']} for change in receipt.payload['changes']]
        shadow = copy.copy(session); shadow.ledger = copy.deepcopy(session.ledger)
        for e in staged: shadow.ledger.append(turn=e.turn, kind=e.kind, payload=e.payload)
        payload['basis'] = digest(snapshot(shadow)); payload['anchor'] = session.turn
    else:
        allowed = {'reject': ('pending', 'deferred'), 'defer': ('pending',), 'resume': ('deferred',)}[action]
        if item['state'] not in allowed: raise DecisionError('事项当前状态不支持该操作', 409)
        if decision.operations is not None or decision.status_patch is not None or decision.preview_token: raise DecisionError('此操作不能夹带状态修改')
    events = []
    for e in staged:
        p = {**e.payload, 'adjudication_id': item_id}
        if item['visibility'] == 'internal': p['visibility'] = 'internal'
        events.append(Event(seq=0, turn=e.turn, kind=e.kind, actor='player', payload=p))
    events.append(Event(seq=0, turn=0, kind='adjudication.decided', actor='player', payload=payload))
    for e in events: session._record(turn=e.turn, kind=e.kind, actor=e.actor, payload=e.payload)
    session._refresh_executor_skills()
    return {'reused': False, 'receipt_id': session.ledger.events[-1].seq}


def view(session, *, include_internal=False):
    items = items_for(session)
    visible = {k: v for k, v in items.items() if include_internal or v['visibility'] != 'internal'}
    result = []; basis = digest(snapshot(session))
    for item in visible.values():
        row = copy.deepcopy(item)
        from .accuracy_policy import acquisition_only
        row['stale'] = not acquisition_only(row) and (row.get('basis') != basis or row['anchor'] != session.turn)
        row.pop('basis', None)
        if row['state'] in ('confirmed', 'rejected'):
            receipt = next(e for e in reversed(session.ledger.events) if e.kind == 'adjudication.decided' and e.payload.get('id') == row['id'])
            row['can_undo'] = row['state'] == 'rejected' or _undo_allowed(session, receipt)
        else: row['can_undo'] = False
        result.append(row)
    history = []
    for e in session.ledger.events:
        if e.kind == 'adjudication.decided' and (include_internal or e.payload.get('item_visibility') != 'internal'):
            p = e.payload
            history.append({'seq': e.seq, 'id': p['id'], 'action': p['action'], 'reason': p['reason'],
                            'changes': p['changes'], 'ts': e.ts.isoformat(), 'before_state': p['before_state'],
                            'title': p.get('title', p['id']), 'source_withdrawn': p['source_turn'] in cancelled_turns(session.ledger.events)})
    return {'pack_id': session.pack.manifest.id, 'revision': revision(session), 'items': result,
            'history': history, 'pending_count': sum(i['state'] == 'pending' for i in result),
            'deferred_count': sum(i['state'] == 'deferred' for i in result)}


def blocks_gameplay_undo(session, turn):
    return any(item['state'] == 'confirmed' and item.get('anchor', item['source_turn']) >= turn for item in items_for(session).values())
