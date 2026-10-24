from test_adjudication import pending_game,first,decision,execute
from rpg_core.adjudication_editor import editor_catalog

def test_editor_uses_full_current_pack_catalog_and_typed_fields():
    g,_,_=pending_game(wardrobe=True)
    fields={f['id']:f for f in editor_catalog(g)['fields']}
    slot=g.pack.wardrobe.slots['upper']
    assert fields[slot.field]['options']==slot.items
    assert fields[slot.field]['tool']=='update_clothing'
    assert fields[slot.condition_field]['input']=='select'
    assert fields[slot.color_field]['input']=='color'
    assert fields['hp']['input']=='number'
    assert fields['pose']['tool']=='update_portrait'

def test_visual_clothing_correction_binds_player_reason_to_nested_evidence():
    g,_,_=pending_game(wardrobe=True);key=first(g)
    operations=[{'name':'update_clothing','args':{'changes':[{'slot':'upper','garment':'hoodie','color':'#1234ab','condition':'scuffed','evidence':'玩家裁定'}]},'evidence':'玩家裁定'}]
    execute(g,key,decision(g,'modify',reason='我裁定现在穿着轻微磨损的蓝色卫衣。',operations=operations))
    execute(g,key,decision(g))
    slot=g.pack.wardrobe.slots['upper']
    assert g.state[slot.field]=='hoodie'
    assert g.state[slot.color_field]=='#1234ab'
    assert g.state[slot.condition_field]=='scuffed'
