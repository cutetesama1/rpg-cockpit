"""Share the bundled all-ages appearance without copying image trees into each world."""
import json
from pathlib import Path

def attach_default_appearance(root:Path,template:Path)->bool:
    if (root/'ui/sprites.json').is_file() or not (template/'ui/sprites.json').is_file():return False
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    state=read(root/'state.json');existing={f['id'] for f in state['fields']}
    source=read(template/'state.json')
    for field in source['fields']:
        if field['id'] not in existing and field.get('type') in ('enum','string') and field.get('group')!='flags':state['fields'].append(field)
    (root/'ui').mkdir(exist_ok=True)
    (root/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'ui/sprites.json').write_bytes((template/'ui/sprites.json').read_bytes())
    if (template/'wardrobe.json').is_file():(root/'wardrobe.json').write_bytes((template/'wardrobe.json').read_bytes())
    (root/'appearance.json').write_text(json.dumps({'asset_pack':'new-game'}),encoding='utf-8')
    return True
