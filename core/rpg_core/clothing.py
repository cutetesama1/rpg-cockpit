"""单次叙述驱动的衣物事务；不解析玩家输入或历史叙述。"""
from __future__ import annotations
import re
from typing import Any
from .contracts import CLOTHING_CONDITIONS, WardrobeConfig, StateSchema


def validate_wardrobe(wardrobe: WardrobeConfig, schema: StateSchema) -> list[str]:
    errors = []
    fields = schema.by_id()
    used = set()
    for key, slot in wardrobe.slots.items():
        for field_id in (slot.field, slot.condition_field, slot.color_field):
            if field_id is None:
                continue
            if field_id in used:
                errors.append(f"衣物槽位不能共用字段 {field_id}")
            used.add(field_id)
        garment, condition = fields.get(slot.field), fields.get(slot.condition_field)
        if garment is None or garment.type != "enum" or not set(slot.items) <= set(garment.enum_values or []):
            errors.append(f"衣物目录 {key} 引用了未声明的款式/枚举字段 {slot.field}")
        if condition is None or condition.type != "enum" or set(condition.enum_values or []) != set(CLOTHING_CONDITIONS):
            errors.append(f"衣物槽位 {key} 的损坏字段需声明四档枚举 {slot.condition_field}")
        if slot.color_field and (slot.color_field not in fields or fields[slot.color_field].type != "string"):
            errors.append(f"衣物槽位 {key} 的颜色字段需声明 string")
    return errors


def wardrobe_snapshot(wardrobe: WardrobeConfig, state: dict[str, Any], narrative: str | None = None) -> dict:
    from .portrait import catalog_options
    return {key: {
        "garment": state.get(slot.field), "condition": state.get(slot.condition_field),
        "color": state.get(slot.color_field) if slot.color_field else None,
        "items": catalog_options(slot.items, narrative, state.get(slot.field), limit=80 if len(slot.items)<=80 else 24),
    } for key, slot in wardrobe.slots.items()}


def clothing_changes(wardrobe: WardrobeConfig | None, state: dict, args: dict, narrative: str | None) -> dict:
    # Import locally to avoid a dependency cycle with ToolExecutor.
    from .guardrails import GuardrailError
    def fail(code, message):
        raise GuardrailError(code, message)
    if wardrobe is None or narrative is None:
        fail("clothing_phase", "换装只能由已配置衣物目录的后置结算阶段执行")
    if set(args) != {"changes"} or not isinstance(args.get("changes"), list) or len(args["changes"]) > len(wardrobe.slots):
        fail("bad_params", "changes 需为数组，每个衣物槽位至多更新一次")
    changes = {}
    seen = set()
    for update in args["changes"]:
        if not isinstance(update, dict) or set(update) - {"slot", "garment", "condition", "color", "evidence"}:
            fail("bad_params", "衣物更新含非法字段")
        key = update.get("slot")
        if not isinstance(key, str) or key not in wardrobe.slots or key in seen:
            fail("clothing_slot", "衣物槽位不存在或重复")
        seen.add(key)
        slot = wardrobe.slots[key]
        evidence = update.get("evidence")
        if not isinstance(evidence, str) or not 2 <= len(evidence.strip()) <= 300 or evidence not in narrative:
            fail("clothing_evidence", "衣物变化必须引用本次叙述中实际存在的原文")
        if not {"garment", "condition", "color"} & update.keys():
            fail("bad_params", "衣物更新缺少款式、损坏或颜色")
        pending = {}
        if "garment" in update:
            garment = update["garment"]
            if not isinstance(garment, str) or garment not in slot.items:
                fail("clothing_garment", "衣物款式不在可用目录中")
            pending[slot.field] = garment
            if garment != state.get(slot.field):
                pending[slot.condition_field] = "intact"
        if "condition" in update:
            if update["condition"] not in CLOTHING_CONDITIONS:
                fail("clothing_condition", "衣物损坏程度不在四档枚举中")
            pending[slot.condition_field] = update["condition"]
        if "color" in update:
            color = update["color"]
            if not slot.color_field or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                fail("clothing_color", "衣物颜色需为 #rrggbb 且槽位支持颜色")
            pending[slot.color_field] = color.lower()
        for field_id, after in pending.items():
            before = state.get(field_id)
            if before != after:
                changes[field_id] = {"before": before, "after": after}
    # All changes have been validated before the caller mutates working state.
    return changes
