"""Read literal clothing geometry metadata without executing game scripts."""
from pathlib import Path
import re

def read_metadata(html: Path):
    text=Path(html).read_text(encoding='utf8')
    slots={'upper':{},'lower':{}}
    for chunk in text.split('new ClothesItem({')[1:]:
        chunk=chunk.split('\n\t\t}),',1)[0]
        slot=re.search(r'\bslot\s*:\s*"(upper|lower)"',chunk[:400])
        variable=re.search(r'\bvariable\s*:\s*"([^"\n]+)"',chunk[:700])
        if not slot or not variable:continue
        values={}
        for key in ('breast_img','sleeve_img','formfitting','mask_img','mainImage','one_piece'):
            found=re.search(r'\b'+key+r'\s*:\s*(\{[^}]*\}|\d+)',chunk)
            if not found:continue
            raw=found.group(1)
            if raw.startswith('{'):
                values[key]={int(size):None if value=='null' else int(value) for size,value in re.findall(r'(\d+)\s*:\s*(null|\d+)',raw)}
            else:values[key]=int(raw)
        slots[slot.group(1)][variable.group(1)]=values
    return slots

def panel_for(size,panels,metadata=None):
    """Null means no overlay, never the nearest larger panel."""
    setting=(metadata or {}).get('breast_img')
    if isinstance(setting,dict):return setting.get(size)
    if setting==0:return None
    return size if size in panels else None
