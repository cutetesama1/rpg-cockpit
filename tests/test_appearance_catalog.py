import pytest
pytestmark = pytest.mark.skip(reason="Private art regression fixtures are not distributed; see public renderer contract tests.")
import json,copy
from pathlib import Path
import pytest
from conftest import ROOT
from rpg_content import load_pack
from rpg_content.appearance import attach_default_appearance
from rpg_core.appearance_catalog import choices_for,field_views
from rpg_core.saves import snapshot_payload,restore_session
from rpg_core.world_config import config_of,apply_config
from test_portrait import game

def test_real_wardrobe_catalog_matches_selectable_fields_and_rejects_unregistered_ids():
    g,_=game({});options=choices_for(g.pack);views={f['id']:f for f in field_views(g.pack)}
    assert len(g.pack.wardrobe.slots['upper'].items)==53
    assert len(g.pack.wardrobe.slots['lower'].items)==41
    for slot in g.pack.wardrobe.slots.values():assert views[slot.field]['enum_values']==list(slot.items)
    before=dict(g.state)
    with pytest.raises(ValueError,match='素材目录'):g.debug_set_state({'upper':'missing-coat','hp':1})
    assert g.state==before
    with pytest.raises(ValueError):g.debug_set_state({'pose':'sit-not-implemented'})

def test_legacy_values_remain_in_history_but_cannot_be_selected_again():
    g,_=game({})
    schema=g.pack.state.model_copy(deep=True);schema.by_id()['upper'].enum_values.append('retired-coat')
    g.pack=g.pack.model_copy(update={'state':schema})
    assert 'retired-coat' not in {f['id']:f for f in g.debug_catalog()['fields']}['upper']['enum_values']
    with pytest.raises(ValueError):g.debug_set_state({'upper':'retired-coat'})

def test_old_shared_roster_does_not_overwrite_new_wardrobe_on_disk(tmp_path):
    from rpg_content.library import create_pack
    target=create_pack(tmp_path,pack_id='old-catalog',title='旧目录')
    (target/'ui').mkdir(exist_ok=True)
    (target/'ui/sprites.json').write_text(json.dumps({'revision':1,'layers':[]}))
    (target/'appearance.json').write_text(json.dumps({'asset_pack':'new-game'}))
    # Simulate the previously tiny runtime catalog.
    old=json.loads((ROOT/'packs/new-game/wardrobe.json').read_text(encoding='utf8'))
    old['slots']['upper']['items']={'tshirt':'旧T恤'}
    (target/'wardrobe.json').write_text(json.dumps(old),encoding='utf8')
    assert attach_default_appearance(target,ROOT/'packs/new-game')
    pack=load_pack(target)
    assert 'winterjacket' in pack.wardrobe.slots['upper'].items
    assert 'winterjacket' in pack.state.by_id()['upper'].enum_values
    assert len(choices_for(pack)['upper'])==53

def test_old_snapshot_upgrades_catalog_without_changing_health_or_losing_ledger():
    current,_=game({});old=current.pack.model_copy(deep=True)
    old.sprites.revision=1;old.sprites.catalog_version=0
    old.sprites.controls['pose']={k:v for k,v in old.sprites.controls['pose'].items() if k not in ('read','bow','dodge','cheer','rest')}
    old.sprites.motions={k:v for k,v in old.sprites.motions.items() if k in old.sprites.controls['pose']}
    old.wardrobe.slots['upper'].items={'tshirt':'T恤'}
    from rpg_core.runtime import GameSession
    legacy=GameSession(old,current.router);legacy.debug_set_state({'hp':7})
    data=snapshot_payload(legacy,slot='legacy')
    restore_session(current,data)
    assert current.state['hp']==7 and current.verify()['equal']
    assert 'winterjacket' in current.pack.wardrobe.slots['upper'].items
    assert 'read' in choices_for(current.pack)['pose']
    config=config_of(current.pack)
    config['state']['fields'][0]['max']=999
    configured=apply_config(current.pack,config)
    assert configured.state.fields[0].max==999 and choices_for(configured)['upper']==choices_for(current.pack)['upper']

def test_all_new_clothes_and_poses_are_accepted_by_actual_settlement():
    from rpg_core.clothing import clothing_changes
    from rpg_core.portrait import portrait_changes
    g,_=game({});text='你换上冬季夹克和阔腿长裤，随后低头阅读。'
    changes=clothing_changes(g.pack.wardrobe,g.state,{'changes':[{'slot':'upper','garment':'winterjacket','evidence':text},{'slot':'lower','garment':'wide leg trousers','evidence':text}]},text)
    assert changes['upper']['after']=='winterjacket' and changes['lower']['after']=='wide leg trousers'
    for pose in ('read','bow','dodge','cheer','rest'):
        assert portrait_changes(g.pack,g.state,{'changes':{'pose':pose}})['pose']['after']==pose
        assert pose in g.pack.sprites.motion_notes and pose in g.pack.sprites.pose_arms
