"""Attach and upgrade the shared portrait without replacing world rules/progress."""
import copy
import hashlib
import json
from pathlib import Path


def attach_default_appearance(root: Path, template: Path) -> bool:
    template_sheet = template / 'ui/sprites.json'
    target_sheet = root / 'ui/sprites.json'
    if not template_sheet.is_file() or root.resolve() == template.resolve():
        return False
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    source_sheet = read(template_sheet)
    shared = root / 'appearance.json'
    if target_sheet.is_file():
        managed = shared.is_file() and read(shared).get('asset_pack') == 'new-game'
        recognised = hashlib.sha256(target_sheet.read_bytes()).hexdigest() in source_sheet.get('legacy_hashes', [])
        if not managed and not recognised:
            return False  # Author-supplied portrait.
        current = read(target_sheet)
        if current.get('revision', 0) >= source_sheet.get('revision', 0):
            return False
        backup = root / 'ui/sprites.before-portrait-v1.json'
        if not backup.exists():
            backup.write_bytes(target_sheet.read_bytes())
    state = read(root / 'state.json')
    existing = {f['id']: f for f in state['fields']}
    source = read(template / 'state.json')
    wardrobe_source = read(template / 'wardrobe.json') if (template / 'wardrobe.json').is_file() else {'slots':{}}
    registered = set(source_sheet.get('controls',{})) | {slot['field'] for slot in wardrobe_source['slots'].values()}
    for field in source['fields']:
        if field.get('group') not in ('appearance', 'sprite'):
            continue
        if field['id'] not in existing:
            state['fields'].append(copy.deepcopy(field))
        elif field['id'] in registered and field.get('enum_values'):
            old = existing[field['id']]
            old['enum_values'] = list(dict.fromkeys([*old.get('enum_values', []), *field['enum_values']]))
    (root / 'ui').mkdir(exist_ok=True)
    (root / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    target_sheet.write_bytes(template_sheet.read_bytes())
    if (template / 'wardrobe.json').is_file():
        wardrobe = read(template / 'wardrobe.json')
        if (root / 'wardrobe.json').is_file():
            current = read(root / 'wardrobe.json')
            if not source_sheet.get('catalog_version'):wardrobe['slots'].update(current.get('slots', {}))
        (root / 'wardrobe.json').write_text(json.dumps(wardrobe, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    shared.write_text(json.dumps({'asset_pack': 'new-game', 'revision': source_sheet.get('revision', 0)}), encoding='utf-8')
    return True
