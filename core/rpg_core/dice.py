"""Session-scoped deterministic checks, replayable across retries and saves.

Entropy is private save data. A draw is a pure HMAC(seed, event ID, index)
operation; rejection sampling avoids modulo bias. Recorded requests cannot be
changed under an existing event ID, even if their owning game turn was undone.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,159}$")
DICE_RE = re.compile(r"^(\d*)d(%|f|\d+)(?:(kh|kl)(\d+))?([+-]\d+)?$", re.I)


class DiceError(ValueError):
    pass


def parse_dice(expression: str) -> dict:
    if not isinstance(expression, str) or len(expression) > 48:
        raise DiceError('骰式必须为不超过48字的文本')
    match = DICE_RE.fullmatch(expression.strip())
    if not match:
        raise DiceError('支持 d20、2d6+3、2d20kh1、2d20kl1、d%、4dF 等骰式')
    count = int(match[1] or 1)
    fate = match[2].lower() == 'f'
    sides = 3 if fate else 100 if match[2] == '%' else int(match[2])
    keep = int(match[4] or count)
    modifier = int(match[5] or 0)
    if not 1 <= count <= 100 or not 2 <= sides <= 1_000_000:
        raise DiceError('骰子数量需1至100，面数需2至1000000')
    if not 1 <= keep <= count or abs(modifier) > 1_000_000:
        raise DiceError('保留数量或修正值超出范围')
    canonical = f'{count}d'+('F' if fate else str(sides))
    if match[3]:
        canonical += match[3].lower()+str(keep)
    if modifier:
        canonical += f'{modifier:+d}'
    return {'dice':canonical,'count':count,'sides':sides,'fate':fate,'keep':keep,'selection':(match[3] or '').lower(),'modifier':modifier}


class Check(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['dice','probability','certain'] = 'dice'
    dice: str = '1d20'
    target: float | None = Field(default=None,allow_inf_nan=False)
    comparison: Literal['gte','lte','gt','lt','eq'] = 'gte'
    chance: float | None = Field(default=None,ge=0,le=1,allow_inf_nan=False)

    @field_validator('target','chance',mode='before')
    @classmethod
    def numeric(cls, value):
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float))):
            raise ValueError('检定阈值和概率必须是有限数字，不能是布尔或文本')
        return value

    @model_validator(mode='after')
    def validate_check(self):
        if self.kind == 'dice':
            self.dice = parse_dice(self.dice)['dice']
            if self.chance is not None:
                raise ValueError('骰子检定不能同时指定概率')
        elif self.kind == 'probability':
            if self.chance is None or self.target is not None:
                raise ValueError('概率检定需chance（0至1），不能指定target')
        elif self.target is not None or self.chance is not None:
            raise ValueError('确定事件不接受阈值或概率')
        return self

    def canonical(self) -> dict:
        if self.kind == 'probability':
            return {'kind':self.kind,'chance':self.chance}
        if self.kind == 'certain':
            return {'kind':self.kind}
        return {'kind':self.kind,'dice':self.dice,'target':self.target,'comparison':self.comparison}


def _uniform(seed: str, event_id: str, index: int, bound: int) -> int:
    ceiling = (1 << 256) - ((1 << 256) % bound)
    for nonce in range(100):
        message = json.dumps([event_id,index,nonce],separators=(',',':')).encode()
        sample = int.from_bytes(hmac.new(bytes.fromhex(seed),message,hashlib.sha256).digest(),'big')
        if sample < ceiling:
            return sample % bound
    raise DiceError('无法生成检定样本')


def evaluate(seed: str, event_id: str, check: Check) -> dict:
    if not isinstance(event_id,str) or not ID_RE.fullmatch(event_id):
        raise DiceError('事件ID需1至160字的稳定英文标识')
    if not isinstance(seed,str) or not re.fullmatch(r'[0-9a-f]{64}',seed):
        raise DiceError('检定种子损坏')
    result = {'event_id':event_id,**check.canonical()}
    if check.kind == 'certain':
        return {**result,'passed':True}
    if check.kind == 'probability':
        # Decimal avoids float boundary changes; resolution is one billionth.
        scale = 1_000_000_000
        threshold = int(Decimal(str(check.chance))*scale)
        sample = _uniform(seed,event_id,0,scale)
        return {**result,'sample':sample,'scale':scale,'passed':sample < threshold}
    parsed = parse_dice(check.dice)
    rolls = [_uniform(seed,event_id,i,parsed['sides'])+(-1 if parsed['fate'] else 1) for i in range(parsed['count'])]
    kept = sorted(rolls,reverse=parsed['selection']=='kh')[:parsed['keep']] if parsed['selection'] else list(rolls)
    total = sum(kept)+parsed['modifier']
    comparisons={'gte':lambda:total>=check.target,'lte':lambda:total<=check.target,'gt':lambda:total>check.target,'lt':lambda:total<check.target,'eq':lambda:total==check.target}
    passed = comparisons[check.comparison]() if check.target is not None else None
    return {**result,'rolls':rolls,'kept':kept,'modifier':parsed['modifier'],'total':total,'passed':passed}


def ensure_seed(session) -> str:
    seeded=next((e for e in session.ledger.events if e.kind=='dice.seeded'),None)
    if seeded:return seeded.payload['seed']
    seed=secrets.token_hex(32)
    session._record(turn=0,kind='dice.seeded',payload={'seed':seed})
    return seed


def resolve(session, event_id: str, check: Check, *, turn: int) -> tuple[dict,bool]:
    """Audit survives rollback deliberately: retries/undo never buy a new draw."""
    if not isinstance(event_id,str) or not ID_RE.fullmatch(event_id):
        raise DiceError('事件ID需1至160字的稳定英文标识')
    request = check.canonical()
    for event in session.ledger.events:
        if event.kind == 'dice.resolved' and event.payload.get('event_id') == event_id:
            if event.payload.get('request') != request:
                raise DiceError('同一事件ID已经用于不同检定，不能改参数重掷')
            return dict(event.payload['result']),True
    seed = ensure_seed(session)
    result = evaluate(seed,event_id,check)
    session._record(turn=turn,kind='dice.resolved',payload={'event_id':event_id,'request':request,'result':result})
    return result,False
