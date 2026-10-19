"""状态：初始化、事件折叠投影。

真相链：state = fold(events 中未被撤销回合的 tool.applied 与 skill.used)
skill.used 是框架自己写入的技能消耗（不是 LLM 工具），同样计入账本与回放。
"""
from __future__ import annotations

from typing import Any

from .contracts import Event, StateSchema

FOLDED_EVENT_KINDS = ("tool.applied", "skill.used")


def initial_state(schema: StateSchema) -> dict[str, Any]:
    return schema.defaults()


def _coerce(field_type: str, value: Any) -> Any:
    if field_type == "int" and isinstance(value, float):
        return int(round(value))
    if field_type == "bool":
        return bool(value)
    return value


def apply_changes(state: dict[str, Any], changes: dict[str, dict[str, Any]]) -> None:
    for field_id, change in changes.items():
        state[field_id] = change["after"]


def cancelled_turns(events: list[Event]) -> set[int]:
    return {e.turn for e in events if e.kind == "turn.rolled_back"}


def project(events: list[Event], schema: StateSchema) -> dict[str, Any]:
    """只折叠未撤销回合，按 seq 顺序应用 tool.applied / skill.used 的 after 值。"""
    state = initial_state(schema)
    cancelled = cancelled_turns(events)
    for event in sorted(events, key=lambda e: e.seq):
        if event.turn in cancelled:continue
        if event.kind == "world.configured":
            state=dict(event.payload["values"])
            continue
        if event.kind not in FOLDED_EVENT_KINDS:
            continue
        changes = event.payload.get("changes", {})
        apply_changes(state, changes)
    return state


def inventory_from_events(events: list[Event]) -> dict[str, int]:
    cancelled = cancelled_turns(events)
    inv: dict[str, int] = {}
    for event in sorted(events, key=lambda e: e.seq):
        if event.kind != "tool.applied" or event.turn in cancelled:
            continue
        if event.payload.get("tool") == "add_item":
            data = event.payload.get("data", {}) or {}
            item_id = data.get("item_id", "")
            count = int(data.get("count", 1))
            inv[item_id] = inv.get(item_id, 0) + count
    return inv
