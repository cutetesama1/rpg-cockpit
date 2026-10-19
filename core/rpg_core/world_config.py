"""Versioned world definitions in the event ledger, with stable resource ids."""
from .contracts import StateSchema,UiLayout,SkillSpec,CatalogSkill
from .state import cancelled_turns
KEYS=('state','ui','skills','skill_catalog','skill_selection')
def config_of(pack):
    import copy
    result={}
    for key in KEYS:
        value=getattr(pack,key)
        result[key]=[x.model_dump(mode='json') for x in value] if isinstance(value,list) else value.model_dump(mode='json') if hasattr(value,'model_dump') else copy.deepcopy(value)
    return result

def apply_config(pack,data):
    schema=StateSchema.model_validate(data['state'])
    if pack.sprites and pack.sprites.revision:
        import copy
        existing=schema.by_id()
        for field in pack.state.fields:
            if field.group not in ('appearance','sprite'): continue
            if field.id not in existing: schema.fields.append(copy.deepcopy(field))
            elif field.id in pack.sprites.controls and field.enum_values:
                existing[field.id].enum_values=list(dict.fromkeys([*(existing[field.id].enum_values or []),*field.enum_values]))
    return pack.model_copy(update={'state':schema,'ui':UiLayout.model_validate(data['ui']),
        'skills':[SkillSpec.model_validate(x) for x in data['skills']],'skill_selection':data.get('skill_selection',pack.skill_selection),'skill_catalog':[CatalogSkill.model_validate(x) for x in data['skill_catalog']]})
def from_events(pack,events):
    changes=[e for e in events if e.kind=='world.configured']
    if not changes:return pack
    config=changes[0].payload['before'];cancelled=cancelled_turns(events)
    for event in changes:
        if event.turn not in cancelled:config=event.payload['after']
    return apply_config(pack,config)
