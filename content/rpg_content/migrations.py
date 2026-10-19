"""Upgrade only the built-in new-game user's wardrobe metadata, with a backup."""
from __future__ import annotations
import json
from pathlib import Path


def upgrade_wardrobe(root: Path, template: Path) -> bool:
    root, template = root.resolve(), template.resolve()
    if root == template or (root / "wardrobe.json").exists() or not (template / "wardrobe.json").is_file():
        return False
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    if read(root / "manifest.json").get("id") != "new-game" or not (root / "ui/sprites.json").is_file():
        return False
    state = read(root / "state.json")
    fields = {f["id"]: f for f in state["fields"]}
    config = read(template / "wardrobe.json")
    template_fields = {f["id"]: f for f in read(template / "state.json")["fields"]}
    slots = {}
    for key, slot in config["slots"].items():
        field = fields.get(slot["field"])
        if not field or field.get("type") != "enum":
            continue
        slot["items"] = {k: v for k, v in slot["items"].items() if k in field.get("enum_values", [])}
        if not slot["items"]:
            continue
        if slot["condition_field"] not in fields:
            state["fields"].append(template_fields[slot["condition_field"]])
        if slot.get("color_field") not in fields:
            slot["color_field"] = None
        slots[key] = slot
    if not slots:
        return False
    sheet = read(root / "ui/sprites.json")
    for layer in sheet.get("layers", []):
        for slot in slots.values():
            if any(c.get("field") == slot["field"] for c in layer.get("when", [])) and not layer.get("adult"):
                layer["wear_field"] = slot["condition_field"]
    writes = {"state.json": state, "ui/sprites.json": sheet, "wardrobe.json": {"slots": slots}}
    backup = root / ".wardrobe-v1-backup"
    originals = {}
    for name in writes:
        path = root / name
        originals[name] = path.read_bytes() if path.is_file() else None
        if path.is_file():
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Never overwrite the original migration backup.
            if not dest.exists():
                dest.write_bytes(originals[name])
    try:
        for name, data in writes.items():
            (root / name).write_text(json.dumps(data, ensure_ascii=False, indent=1)+"\n", encoding="utf-8")
        from .pack import load_pack
        load_pack(root)
    except Exception:
        for name, value in originals.items():
            path = root / name
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
        raise
    return True
