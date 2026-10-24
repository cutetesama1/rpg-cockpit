"""Full player-facing editor catalogs; never sent to a model."""
def editor_catalog(session):
    import re
    from .adjudication import revision
    conditions={'intact':'完好','scuffed':'轻微磨损','damaged':'破损','ruined':'严重破损'}
    wardrobe={}
    for key,slot in (session.pack.wardrobe.slots.items() if session.pack.wardrobe else []):
        for field,part in ((slot.field,'garment'),(slot.condition_field,'condition'),(slot.color_field,'color')):
            if field:wardrobe[field]={'tool':'update_clothing','slot':key,'part':part,'options':slot.items if part=='garment' else conditions if part=='condition' else {}}
    controls=session.pack.sprites.controls if session.pack.sprites else {}
    fields=[];state=session.state
    for f in session.pack.state.fields:
        row={**f.model_dump(mode='json'),'value':state.get(f.id),
             'tool':'update_portrait' if f.id in controls else 'set_stat' if f.type in ('int','float') else 'set_value',
             'options':controls.get(f.id,{}) or {v:v for v in (f.enum_values or [])}}
        row.update(wardrobe.get(f.id,{}))
        row['input']='select' if row['options'] or f.type=='bool' else 'number' if f.type in ('int','float') else 'color' if row.get('part')=='color' or f.type=='string' and (f.id in controls or re.fullmatch(r'#[0-9a-fA-F]{6}',str(row['value']))) else 'text'
        fields.append(row)
    return {'pack_id':session.pack.manifest.id,'revision':revision(session),'fields':fields,
            'health_field':session.pack.state.resource_bindings.get('health','hp')}
