"""Verify selectable clothes have visible artwork and pose implementations."""
from pathlib import Path
import collections,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'core'),str(ROOT/'content')]
from pngio import read_png_rgba
from rpg_content import load_pack
from rpg_core.appearance_catalog import choices_for

def audit(pack_dir):
    pack_dir=Path(pack_dir);pack=load_pack(pack_dir);sheet=pack.sprites
    assert sheet is not None
    cache={};coverage=collections.defaultdict(bool);missing=[]
    slot_fields={s.field for s in pack.wardrobe.slots.values()}
    for layer in sheet.layers:
        if layer.adult:continue
        selectors=[c for c in layer.when if c.field in slot_fields and c.op=='==' and isinstance(c.value,str)]
        if not selectors or '{' in layer.src:continue
        path=pack_dir/layer.src
        if not path.is_file():missing.append(layer.src);continue
        if layer.src not in cache:
            width,height,rgba=read_png_rgba(path)
            crop=sheet.crop
            cache[layer.src]=any(any(rgba[(y*width+crop.x)*4+3:(y*width+min(width,crop.x+crop.w))*4:4]) for y in range(crop.y,min(height,crop.y+crop.h)))
        for condition in selectors:coverage[(condition.field,condition.value)] |= cache[layer.src]
    empty=[{'field':s.field,'id':value} for s in pack.wardrobe.slots.values() for value in s.items if value!='none' and not coverage[(s.field,value)]]
    choices=choices_for(pack)
    fields={f.id:f for f in pack.state.fields}
    assert all(set(s.items)<=set(fields[s.field].enum_values) for s in pack.wardrobe.slots.values())
    poses=set(sheet.controls.get('pose',{}))
    assert poses==set(sheet.motions)==set(sheet.motion_notes)==set(sheet.pose_arms)
    assert set(choices['pose'])==poses
    result={'registered_clothes_and_accessories':sum(len(s.items)-(1 if 'none' in s.items else 0) for s in pack.wardrobe.slots.values()),'checked_images':len(cache),'missing_assets':missing,'invisible_items':empty,'actions':len(poses),'upper':len(pack.wardrobe.slots['upper'].items),'lower':len(pack.wardrobe.slots['lower'].items)}
    destination=ROOT/'docs/previews/wardrobe-actions/asset-verification.json';destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    assert not missing and not empty,result
    print(json.dumps(result),flush=True);return result
if __name__=='__main__':audit(ROOT/'packs/new-game')
