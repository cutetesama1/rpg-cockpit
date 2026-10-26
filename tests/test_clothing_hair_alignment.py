import pytest
pytestmark = pytest.mark.skip(reason="Private art regression fixtures are not distributed; see public renderer contract tests.")
import json,sys
from pathlib import Path
import pytest
from conftest import ROOT
sys.path.insert(0,str(ROOT/'tools'))
from dol_clothing_geometry import read_metadata,panel_for
from sprite_compose_preview import compose,visible,portrait_context
from pngio import read_png_rgba

PACK=ROOT/'packs/new-game'
def data():
    sheet=json.loads((PACK/'ui/sprites.json').read_text(encoding='utf8'))
    fields=json.loads((PACK/'state.json').read_text(encoding='utf8'))['fields']
    return sheet,fields,{f['id']:f['default'] for f in fields}

def test_literal_geometry_parser_distinguishes_slots_and_never_executes_scripts(tmp_path):
    source=tmp_path/'test.html'
    source.write_text('new ClothesItem({\n slot: "head", variable: "coat", breast_img: 0\n\t\t}),new ClothesItem({\n slot: "upper", variable: "coat", breast_img: {0:null,1:1,2:2,3:4,4:4,5:5,6:5}, sleeve_img:1\n\t\t}),',encoding='utf8')
    meta=read_metadata(source)['upper']['coat']
    assert panel_for(0,{1,2,4,5},meta) is None
    assert panel_for(3,{1,2,4,5},meta)==4
    assert panel_for(6,{1,2,4,5},meta)==5
    assert panel_for(0,{2,3,6}) is None
    assert panel_for(2,{2,3,6})==2

def test_all_registered_tops_follow_exact_null_and_shared_panel_mappings():
    sheet,_,_=data();meta=json.loads((PACK/'ui/clothing-geometry.json').read_text(encoding='utf8'))['upper']
    for garment,config in meta.items():
        for size in range(7):
            matching=[l for l in sheet['layers'] if l['id'].startswith('upper_piece_') and '_front_' in l['id'] and
               any(c.get('field')=='upper' and c.get('value')==garment for c in l.get('when',[])) and
               any(c.get('field')=='breast_size' and c.get('value')==size for c in l.get('when',[]))]
            target=config['breast_img'].get(str(size))
            if target is None:assert not matching,(garment,size)
            else:
                assert len(matching)==1,(garment,size)
                assert matching[0]['src'].endswith(f'/panel-{target}.png'),(garment,size,target)
    assert meta['tshirt']['breast_img']['0'] is None

def test_idle_sleeves_are_behind_torso_and_lining_never_overpaints_coat():
    sheet,_,state=data()
    for pose in ('stand','guard','read','hold'):
        ctx=portrait_context({**state,'upper':'winterjacket','pose':pose},sheet)
        selected=[l for l in sheet['layers'] if visible(l,ctx,False)]
        main=next(l for l in selected if l['id']=='upper_winterjacket')
        for l in selected:
            if l['id'].startswith('upper_piece_') and l['id'].endswith(('_left_None','_right_None')):assert l['z']<main['z']
            if l['id'].startswith('outerwear_lining_'):
                raised=any(c.get('field') in ('portrait_left_arm','portrait_right_arm') and c.get('value') in ('cover','hold') for c in l.get('when',[]))
                assert l['z']==53 if raised else l['z']<main['z']
        assert all(l['z']==52 for l in selected if l['id'].startswith('portrait_arm_'))

@pytest.mark.parametrize('style',['classic','default','aerial','hime'])
def test_side_hair_covers_temples_instead_of_being_hidden_by_head(style):
    sheet,fields,state=data();state.update(hair_style=style,hair_length='shoulder')
    ctx=portrait_context(state,sheet)
    side=next(l for l in sheet['layers'] if l['id'].startswith('hair_sides_') and visible(l,ctx,False))
    assert side['z']>43
    sw,sh,hair=read_png_rgba(PACK/side['src']);hw,hh,head=read_png_rgba(PACK/'ui/sprites/body/base-head.png')
    # Temple above the ear: require actual head and side-hair overlap, not a bbox test.
    candidates=[(x,y) for y in range(35,48) for x in range(99,107) if hair[(y*sw+x)*4+3]==255 and head[(y*hw+x)*4+3]==255]
    assert candidates,style
    w,h,result,_=compose(PACK,sheet,state,fields=fields)
    color=bytes.fromhex(state['hair_color'][1:])
    assert any(result[((y-sheet['crop']['y'])*2*w+(x-sheet['crop']['x'])*2)*4:((y-sheet['crop']['y'])*2*w+(x-sheet['crop']['x'])*2)*4+3]==color for x,y in candidates),style
