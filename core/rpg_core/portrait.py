"""Validated portrait changes made by the one stateless turn settlement."""
from __future__ import annotations
import math
import re


def catalog_options(options, narrative, current, limit=24):
    """Keep the full catalog in the UI, but send relevant choices to the LLM."""
    if narrative is None or len(options) <= limit: return dict(options)
    text = narrative.casefold()
    ranked=[]
    for key,label in options.items():
        score = 100 if len(key)>2 and key.casefold() in text else 0
        for word in re.findall(r'[\u4e00-\u9fff]+', label):
            if word in text: score += len(word) * 4
            score += sum(1 for i in range(len(word)-1) if word[i:i+2] in text)
        if score: ranked.append((-score,key))
    keep = [key for key in ('none', current) if key in options]
    for _,key in sorted(ranked):
        if key not in keep: keep.append(key)
        if len(keep) >= limit: break
    return {key: options[key] for key in keep}


def portrait_snapshot(pack, state, narrative=None):
    if pack.sprites is None:
        return {}
    fields = pack.state.by_id()
    return {key: {
        'label': fields[key].label,
        'value': state.get(key, fields[key].default),
        'options': catalog_options(options,narrative,state.get(key, fields[key].default),limit=80 if len(options)<=80 else 24),
        **({'min': fields[key].min, 'max': fields[key].max} if fields[key].type in ('int', 'float') else {}),
    } for key, options in pack.sprites.controls.items() if key in fields}


def portrait_changes(pack, state, args):
    """Return a complete validated patch; the caller commits the whole turn."""
    from .guardrails import GuardrailError
    def fail(message):
        raise GuardrailError('portrait_value', message)
    changes = args.get('changes')
    if set(args) != {'changes'} or not isinstance(changes, dict) or not changes or len(changes) > 24:
        fail('立绘更新需提供1至24个 changes 字段')
    controls = pack.sprites.controls if pack.sprites else {}
    fields = pack.state.by_id()
    patch = {}
    for key, value in changes.items():
        if key not in controls or key not in fields:
            fail('立绘字段未注册；饰品与衣物请使用 update_clothing')
        field = fields[key]
        if field.type == 'enum':
            if not isinstance(value, str) or value not in controls[key] or value not in (field.enum_values or []):
                fail(f'{key} 不在当前立绘目录中')
        elif field.type in ('int', 'float'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                fail(f'{key} 必须为有限数值')
            if field.type == 'int' and int(value) != value:
                fail(f'{key} 必须为整数')
            if field.min is not None and value < field.min or field.max is not None and value > field.max:
                fail(f'{key} 超出允许范围')
        elif field.type == 'bool':
            if not isinstance(value, bool):
                fail(f'{key} 必须为布尔')
        elif field.type == 'string':
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                fail(f'{key} 必须为 #rrggbb 颜色')
            value = value.lower()
        else:
            fail('该字段不支持立绘更新')
        if state.get(key) != value:
            patch[key] = {'field': key, 'before': state.get(key), 'after': value}
    return patch
