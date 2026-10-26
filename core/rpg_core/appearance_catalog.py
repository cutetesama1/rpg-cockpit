"""Selectable appearance capabilities, separate from legacy ledger values."""
def choices_for(pack):
    sheet=pack.sprites
    if not sheet or not sheet.catalog_version:return {}
    result={key:list(options) for key,options in sheet.controls.items() if options}
    if pack.wardrobe:
        result.update({slot.field:list(slot.items) for slot in pack.wardrobe.slots.values()})
    return result

def field_views(pack):
    choices=choices_for(pack)
    return [{**field.model_dump(mode='json'),**({'enum_values':choices[field.id]} if field.type=='enum' and field.id in choices else {})} for field in pack.state.fields]

def wardrobe_fields(pack):
    return {slot.field for slot in pack.wardrobe.slots.values()} if pack.wardrobe else set()
