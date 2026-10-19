"""World-specific resources, editable definitions and dependency-aware reconfiguration."""
import json,re,math
from pathlib import Path
from rpg_core.contracts import StateSchema,UiLayout,SkillSpec,CatalogSkill

def suggest_state(text:str)->dict:
    strong=bool(re.search(r'(?:你|主角|玩家|角色)[^。\n]{0,180}(?:强大|资深|传奇|精通|大法师|大师)',text))
    if re.search('修仙|仙侠|真元|灵石|修士',text):labels=('气血','真元','灵石');unit='枚'
    elif re.search('飞船|机甲|星际|机器人|科幻',text):labels=('机体完整度','能源','星币');unit='枚'
    elif re.search('魔法|法师|奇幻|施法',text):labels=('生命','魔力','金币');unit='枚'
    elif re.search('武侠|江湖|内力',text):labels=('气血','内力','银两');unit='两'
    else:labels=('生命','体力','金钱');unit='元'
    caps=(400,600) if strong else (100,100)
    fields=[]
    for i,(key,label,value) in enumerate(zip(('hp','focus','credits'),labels,(*caps,0))):
        fields.append({'id':key,'label':label,'type':'int','default':value,'min':0,'max':caps[i] if i<2 else None,'step':1,'display':'bar' if i<2 else 'number','group':'vitals' if i<2 else 'resources','unit':unit if i==2 else None,'color':('#ef4444','#38bdf8','#e4c18c')[i]})
    return {'fields':fields,'resource_bindings':{'health':'hp','mana':'focus','effort':'focus','currency':'credits'},'limits':{'max_delta_per_turn':{}}}

def normalize_state(data,text='')->dict:
    raw=data if isinstance(data,dict) else suggest_state(text)
    schema=StateSchema.model_validate(raw)
    ids=set();fields=schema.by_id()
    if not schema.resource_bindings:
        aliases={'health':['hp','health','vitality'],'mana':['mp','mana','focus'],'effort':['stamina','energy','focus'],'currency':['credits','money','gold']}
        schema.resource_bindings={role:next(k for k in names if k in fields) for role,names in aliases.items() if any(k in fields for k in names)}
    if not schema.fields:raise ValueError('至少需要一个基础数值')
    for f in schema.fields:
        if f.id in ids or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',f.id):raise ValueError('数值 id 重复或不合法：'+f.id)
        ids.add(f.id)
        if not f.label.strip():raise ValueError('数值名称不能为空')
        if f.type in ('int','float'):
            values=[f.default,f.step,*[v for v in (f.min,f.max) if v is not None]]
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):raise ValueError('数值必须为有限数字')
            if f.step<=0 or f.min is not None and f.max is not None and f.min>f.max:raise ValueError('上下限或步进无效')
            if f.min is not None and f.default<f.min or f.max is not None and f.default>f.max:raise ValueError('初始值超出上下限')
            if f.type=='int' and any(float(v)!=int(v) for v in values):raise ValueError('整数资源不能使用小数')
            if f.display=='bar' and (f.min is None or f.max is None):f.display='number'
    for role,key in schema.resource_bindings.items():
        if role not in ('health','mana','effort','currency') or key and (key not in fields or fields[key].type not in ('int','float')):raise ValueError('资源用途绑定无效：'+role)
    return schema.model_dump(mode='json')

def layout_for(schema,previous=None):
    layout=previous.model_copy(deep=True) if previous else UiLayout()
    layout.bars=[f.id for f in schema.fields if f.display=='bar']
    layout.numbers=[f.id for f in schema.fields if f.display in ('number','text') and f.type!='bool']
    layout.badges=[f.id for f in schema.fields if f.display=='badge']
    return layout

def write_initial_state(root:Path,data:dict):
    schema=StateSchema.model_validate(normalize_state(data))
    (root/'state.json').write_text(json.dumps(schema.model_dump(mode='json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    layout=layout_for(schema)
    (root/'ui/layout.json').write_text(json.dumps(layout.model_dump(mode='json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def reconfigure(session,root,data,current_values=None):
    from rpg_core.world_config import config_of,apply_config
    from rpg_core.contracts import Event
    from .pack import validate_pack
    from .library import _replace_and_validate
    numeric=normalize_state(data)
    schema=StateSchema.model_validate(numeric)
    old=session.pack;fields=schema.by_id()
    catalog=[]
    for entry in old.skill_catalog:
        costs={}
        abstract=entry.resource_cost
        if not abstract and entry.library_id=="standard-martial-magic" and len(entry.skill.cost)==1:
            abstract={"mana" if entry.kind=="magic" else "effort":next(iter(entry.skill.cost.values()))}
        if abstract:
            for role,amount in abstract.items():
                if not amount:continue
                field=schema.resource_bindings.get(role)
                if field is None:
                    # Existing bound ids may be retained for legacy worlds.
                    candidates=[k for k in entry.skill.cost if k in fields]
                    field=candidates[0] if len(candidates)==1 else None
                if field not in fields:raise ValueError('技能资源需要重新绑定：'+entry.skill.name)
                costs[field]=costs.get(field,0)+amount
        else:costs=entry.skill.cost
        catalog.append(entry.model_copy(update={'resource_cost':abstract,'skill':entry.skill.model_copy(update={'cost':costs})}))
    by_id={e.skill.id:e.skill for e in catalog}
    skills=[by_id.get(s.id,s) for s in old.skills]
    candidate=old.model_copy(update={'state':schema,'ui':layout_for(schema,old.ui),'skills':skills,'skill_catalog':catalog})
    validate_pack(candidate)
    values={};current=session.state
    for field in schema.fields:
        value=(current_values or {}).get(field.id,current.get(field.id,field.default))
        if field.type in ('int','float'):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('当前值非法：'+field.id)
            if field.min is not None:value=max(field.min,value)
            if field.max is not None:value=min(field.max,value)
            if field.type=='int':value=int(round(value))
        else:value=session._debug_coerce(field,value)
        values[field.id]=value
    before=config_of(old);after=config_of(candidate)
    writes={root/'state.json':json.dumps(after['state'],ensure_ascii=False,indent=2),root/'ui/layout.json':json.dumps(after['ui'],ensure_ascii=False,indent=2),root/'vocab/skills.json':json.dumps({'skills':after['skills']},ensure_ascii=False,indent=2)}
    if old.skill_selection:writes[root/'vocab/skill_catalog.json']=json.dumps({'schema_version':1,'selection':old.skill_selection,'skills':after['skill_catalog']},ensure_ascii=False,indent=2)
    warnings=_replace_and_validate(root,writes)
    turn=session._next_turn()
    session._record(turn=turn,kind='world.configured',actor='player',payload={'before':before,'after':after,'values':values})
    session._record(turn=turn,kind='turn.committed',actor='player',payload={'configuration':True})
    session.pack=candidate;session._refresh_executor_skills()
    return warnings
