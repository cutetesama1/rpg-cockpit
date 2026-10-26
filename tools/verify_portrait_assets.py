"""Check every registered ordinary accessory has actual visible pixels."""
import collections,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from pngio import read_png_rgba

def verify(pack):
    sheet=json.loads((pack/'ui/sprites.json').read_text(encoding='utf-8'))
    wardrobe=json.loads((pack/'wardrobe.json').read_text(encoding='utf-8'))
    slots=set(wardrobe['slots'])-{'upper','lower'}
    coverage=collections.defaultdict(bool);cache={};missing=[]
    for layer in sheet['layers']:
        if not layer['id'].startswith('portrait_'):continue
        for condition in layer.get('when',[]):
            key,value=condition['field'],condition['value']
            if key not in slots or not isinstance(value,str):continue
            path=pack/layer['src']
            if not path.is_file():missing.append(layer['src']);continue
            if str(path) not in cache:
                w,h,rgba=read_png_rgba(path)
                cache[str(path)]=any(any(rgba[(y*w+12)*4+3:(y*w+min(w,224))*4:4]) for y in range(min(h,190)))
            coverage[(key,value)] |= cache[str(path)]
    empty=[{'slot':key,'id':value} for key in slots for value in wardrobe['slots'][key]['items'] if value!='none' and not coverage[(key,value)]]
    result={'missing_assets':missing,'items_without_visible_pixels':empty,'checked_images':len(cache),'catalog_items':sum(len(wardrobe['slots'][key]['items'])-1 for key in slots)}
    target=ROOT/'docs/previews/portrait-v1/accessory-coverage.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert not missing and not empty,result
    print(json.dumps(result,ensure_ascii=True))
    return result

if __name__=='__main__':verify(ROOT/'packs/new-game')
