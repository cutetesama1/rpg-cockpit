"""Stateless settlement input, conservative identity matching and dynamic items."""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .contracts import ItemSpec
from .state import cancelled_turns


def options(session):
    return {'relaxed_validation': True, 'fuzzy_identification': False,
            'confirm_item_gains': True, **getattr(session.router, 'settlement_options', {})}


def current_input(session, turn):
    """Only this turn; opening and auxiliary transactions have no player turn."""
    if turn <= 0:
        return {}
    event = next((e for e in reversed(session.ledger.events)
                  if e.turn == turn and e.kind == 'turn.started'), None)
    if not event:
        return {}
    import copy
    return {'action': copy.deepcopy(event.payload.get('action') or {}),
            'display_text': event.payload.get('display_text', '')}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(text)).casefold()
                   if not c.isspace() and (c in '+-−./%:' or not unicodedata.category(c).startswith('P')))


def evidence_excerpt(evidence, narrative, relaxed=False):
    if evidence and evidence in narrative:
        return evidence
    if relaxed:
        # Match punctuation/spacing changes only, never synonyms, omitted words,
        # negation or numbers. Return the actual original span for the ledger.
        chars = []; positions = []
        for i, char in enumerate(narrative):
            for c in normalized(char):
                chars.append(c); positions.append(i)
        needle = normalized(evidence)
        start = ''.join(chars).find(needle) if needle else -1
        if start >= 0:
            return narrative[positions[start]:positions[start + len(needle) - 1] + 1]
    raise ValueError('变化证据不是本次正文的连续原文')


def unique_ref(value, rows):
    """Only exact normalized aliases; ambiguous labels never resolve at random."""
    if not isinstance(value, str):
        return value
    ids = {row['id'] for row in rows}
    if value in ids:
        return value
    matches = {row['id'] for row in rows
               if normalized(value) in {normalized(row['id']), normalized(row.get('name', '')),
                                         normalized(row.get('label', ''))} - {''}}
    return next(iter(matches)) if len(matches) == 1 else value


def item_catalog(session, *, include_internal=False):
    result = {item.id: item.model_dump(mode='json') for item in session.pack.items}
    cancelled = cancelled_turns(session.ledger.events)
    for event in session.ledger.events:
        if event.kind == 'item.registered' and event.turn not in cancelled:
            if include_internal or event.payload.get('visibility') != 'internal':
                item = ItemSpec.model_validate(event.payload['item'])
                result[item.id] = item.model_dump(mode='json')
    return result


def implicit_item(session, args):
    catalog = item_catalog(session, include_internal=True)
    requested = args.get('item_id', '')
    if not isinstance(requested,str):raise ValueError('物品ID必须是文本；新物品可省略ID，由框架生成')
    if requested in catalog:
        item = catalog[requested]
    else:
        name = args.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('新增物品需要1至100字的名称')
        name = name.strip()
        existing = unique_ref(name, list(catalog.values()))
        if existing in catalog:
            item = catalog[existing]
        else:
            description = args.get('description', '')
            if not isinstance(description, str) or len(description) > 1000:
                raise ValueError('物品描述最多1000字')
            item_id = 'found_' + hashlib.sha256(normalized(name).encode()).hexdigest()[:20]
            item = ItemSpec(id=item_id, name=name, description=description, stackable=True).model_dump(mode='json')
    count = args.get('count', 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000:
        raise ValueError('获得物品数量必须为1至100000的整数')
    return item, count


def acquisition_only(item):
    ops = item.get('operations', [])
    return bool(ops) and not item.get('status_patch') and all(
        op.get('name') == 'acquire_item' or
        op.get('name') == 'add_item' and isinstance(op.get('args', {}).get('count'), int)
        and not isinstance(op['args']['count'], bool) and op['args']['count'] > 0
        for op in ops)


PROMPT = """
【本轮玩家输入与宽容识别】
player_input 只含本轮行动/话语/心理/勾选技能，不含历史对话。必须一起读取，以识别玩家、目标、物品与指代。
玩家说“想拿”“尝试”“如果”“给我加钱”等不等于成功；叙述明确拒绝或失败时不得按玩家愿望结算。最终发生结果以 narrative 为准。
证据仍从 narrative 摘录；允许仅空白、全半角和标点差异，不能省略否定、改变数字或编造证据。
policy.relaxed_validation 开启时可用目录唯一名称/标签匹配现有ID；没有唯一匹配就提问，不随机猜测衣物、动作、技能接口。
普通新剧情事实可自行生成稳定ID走 record_fact，不要求作者预注册；不能因此解锁系统关卡、创建数值字段或执行自定义指令。
【物品获取与隐式ID】
明确获得正数物品时，policy.confirm_item_gains 开启则先问玩家是否放入背包，暂不直接入账。
目录已有物品用 add_item；未注册的新物品在 policy.fuzzy_identification 开启时用 acquire_item={name:物品名称,count:具体正整数,description:简短描述,reason:获得原因}。
框架为新物品生成稳定的 found_ 隐式ID并转为待裁定问题，玩家选择“是”才注册和放入背包；“否”不入账，“搁置”留待以后。不生成可执行脚本或使用效果指令。
没有开启模糊鉴定时，新物品也应放 pending，说明缺少目录映射，不能丢掉其他已确定结算。
pending.question 用一条清楚的是非问句，例如“是否把这把旧钥匙放进背包？”；附上数量、估算依据和拟改内容。
【可选模糊数量鉴定】
policy.fuzzy_identification=true 时，明确已发生但数量模糊的收入/支出、伤害/恢复，要依据世界经济、描述强弱和本次状态给出具体合理数值，不能仅因没有数字就漏结算。
例如“你捡到了几张纸币”：找到 resource_bindings 中货币对应的实际字段，按本世界面额估出总金额，用 add_stat 增加到现有金钱，不重置总额，不创建“纸币”物品。
估算操作标 estimated=true、estimate_reason=数量和面额等推定理由；有明确数字时不能标估算。没有货币绑定或世界币种/归属有冲突则提出 pending 问题。
估值遵守字段范围和累计限额；不得把未来计划、他人的物品/资源、否定或台词里的假设当作收益。关闭时不猜测模糊收入，而是询问玩家。
"""
