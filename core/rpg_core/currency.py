"""World-currency semantics for the game's single configured money resource.

This module never fetches or invents a real-world exchange rate.
"""
from __future__ import annotations
import math
import re

ALIASES = {
    'JPY': ('日元', '日圆', '日圆', '日圓', '日币', '日幣', '円', 'yen', 'jpy'),
    'CNY': ('人民币', '人民币元', 'rmb', 'cny'),
    'USD': ('美元', '美金', 'usd'),
    'EUR': ('欧元', 'eur'),
    'GBP': ('英镑', 'gbp'),
}
GENERIC = {'', '元', '钱', '金钱', '货币', '金币', '金', '点', '信用点', '币', 'credits', 'money', 'gold'}


def code(text):
    text=str(text).strip().casefold()
    return next((key for key, values in ALIASES.items() if text in values or any(v in text for v in values if len(v)>1)), None)


def context(session):
    fields=session.pack.state.by_id();field_id=session.pack.state.resource_bindings.get('currency')
    if not field_id:
        found=[f.id for f in fields.values() if f.type in ('int','float') and (f.id.casefold() in ('money','credits','gold','currency') or f.label in ('金钱','零钱','钱','信用点','金币'))]
        if len(found)==1:field_id=found[0]
    field=fields.get(field_id)
    if not field or field.type not in ('int','float'):return None
    setting=session.pack.prompts.get('pre','')
    explicit=code(field.unit) or code(field.label)
    if not explicit:
        # Generic 元 is a display label, rather than an implicit CNY declaration.
        declared=re.search(r'(?:通用货币|货币|结算货币|币种|使用货币|以)\s*(?:为|是|使用|采用|[:：])\s*(人民币|美元|欧元|英镑|日元|日圆|JPY|CNY|USD|EUR|GBP)',setting,re.I)
        if declared:explicit=code(declared.group(1))
    return {'field':field.id,'label':field.label,'display_unit':field.unit or '',
            'declared_currency':explicit,'unit_mode':'explicit_currency' if explicit else 'world_nominal',
            'balance':session.state.get(field.id),'generic_unit_is_not_cny':True}


def resolve(session,args,*,fuzzy):
    info=context(session)
    if not info:raise ValueError('世界没有唯一的金钱字段，请先绑定货币资源')
    amount=args.get('amount');unit=args.get('unit','')
    if isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount==0:
        raise ValueError('货币收支必须是有限的非零数值')
    if not isinstance(unit,str) or len(unit)>40:raise ValueError('货币单位需要为短文本')
    source=code(unit);target=info['declared_currency'];converted=args.get('converted_amount')
    note={'field':info['field'],'source_amount':amount,'source_unit':unit,'display_unit':info['display_unit'],'mode':'same_currency'}
    different=bool(target and (source and source!=target or not source and unit.strip().casefold() not in GENERIC and unit.strip().casefold()!=target.casefold()))
    if different:
        basis=args.get('conversion_reason','')
        if not fuzzy or isinstance(converted,bool) or not isinstance(converted,(int,float)) or not math.isfinite(converted) or converted==0 or converted*amount<=0 or not isinstance(basis,str) or not basis.strip():
            raise ValueError('世界明确区分此币种：需提供世界内兑换金额和依据，再由玩家确认；不使用未说明的实时汇率')
        delta=converted;note.update(mode='world_conversion',conversion_reason=basis[:500],target_currency=target)
    elif not target and unit.strip().casefold() not in GENERIC:
        if not fuzzy:raise ValueError('请开启模糊鉴定，或在当前世界明确货币单位')
        delta=amount;note.update(mode='world_nominal',reason='通用金钱栏按当前世界货币记账；显示“元”并不代表人民币，不执行现实汇率兑换')
    else:delta=amount
    field=session.pack.state.by_id()[info['field']]
    if field.type=='int' and delta!=int(delta):raise ValueError('当前金钱字段只接受整数，请按世界规则明确舍入金额')
    note['delta']=delta
    return {'field':info['field'],'delta':delta,'reason':str(args.get('reason') or '本轮明确发生的货币收支')[:500]},note


PROMPT = """
【金钱单位与世界语义：优先于旧模板的机械单位比较】
currency_context 指定实际金钱字段。字段标签“金钱/零钱”或单位“元”通常只是通用显示，不能据此推断为人民币，不能仅因正文写“日元”就拒绝记账。
日本背景或正文明确捡到100日元，金钱栏只泛称元时，用 credit_currency={amount:100,unit:"日元",reason:"本轮获得"} 计入现有金钱+100；这是世界货币的同义归一，不是把100日元按100人民币兑换。
美元、铜币、信用点等同理，先结合世界语义。有明确金额就保留金额；没有金额再给有依据的估算。不要只报告“单位不匹配”“后端未实现”。
credit_currency 的 amount 为本次增量（收入正、支出负），不写最终余额；单一货币栏一件收支只写一次，不再重复 add_stat 或 add_item。
开启模糊鉴定时，明确金额的金钱收支不受旧样例小额 max_delta_per_turn 误拦，仍保留字段最小值/最大值；HP和其他资源限额不改变。
若 currency_context.declared_currency 明确为 CNY、USD 等，而正文是另一独立币种，禁止1:1冒充兑换。可提交 credit_currency 的 converted_amount 和 conversion_reason（世界内汇率或说明的游戏估值），此类跨币种兑换必须放 pending 让玩家选择是/否。
没有兑换依据时提出可回答的是非问题，例如是否把这100日元现金单独作为物品收下；不能丢掉同轮其他合法状态变化。不得声称使用了实时市场汇率。
"""
