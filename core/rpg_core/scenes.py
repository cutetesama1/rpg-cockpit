"""场景：当前场景的折叠、进入条件与可用转移。

设计（PLAN v2.1 的延伸）：
- 场景不是数值状态，而是叙事位置；当前场景 = 账本里最后一条未撤销的
  `scene.entered` 的目标场景（默认内容包的 opening）。
- 谁能换场景：① LLM 调 `enter_scene` 工具（护栏校验场景存在 + 进入条件）；
  ② 玩家选择带 `next_scene` 的作者选项（框架直接转场，同样校验条件）。
- 条件用结构化 Condition（字段/运算符/值），不解析自由文本；未知字段一律
  视为不满足并给出可读原因（会进 tool.rejected 的 message）。
"""
from __future__ import annotations

import operator
from typing import Any, Callable

from .contracts import Condition, ContentPack, Event, OpeningScene

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    # 值在列表里：用来兼容旧存档的枚举值（如 upper=full → 当作某件上衣）
    "in": lambda left, right: left in right if isinstance(right, (list, tuple, set)) else False,
    # 值不在列表里：给「裸着就不画内裤」这类相反条件用
    "not_in": lambda left, right: left not in right if isinstance(right, (list, tuple, set)) else True,
}


def _field_label(pack: ContentPack | None, field_id: str) -> str:
    if pack is not None:
        field_def = pack.state.by_id().get(field_id)
        if field_def is not None:
            return field_def.label
    return field_id


def condition_holds(cond: Condition, state: dict[str, Any]) -> bool:
    left = state.get(cond.field)
    if left is None:
        return False
    right = cond.value
    op = _OPS.get(cond.op)
    if op is None:
        return False
    # bool 与数字不混比；类型不兼容直接当不满足
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    try:
        return bool(op(left, right))
    except TypeError:
        return False


def condition_text(cond: Condition, pack: ContentPack | None = None) -> str:
    return f"{_field_label(pack, cond.field)} {cond.op} {cond.value!r}"


def unmet_conditions(
    conditions: list[Condition],
    state: dict[str, Any],
    pack: ContentPack | None = None,
) -> list[str]:
    """返回不满足条件的人类可读原因（空列表 = 全部满足）。"""
    reasons: list[str] = []
    for cond in conditions:
        if condition_holds(cond, state):
            continue
        current = state.get(cond.field)
        if pack is not None and cond.field not in pack.state.by_id():
            reasons.append(f"条件引用了未声明字段 {cond.field}")
        elif pack is not None:
            reasons.append(f"需要「{condition_text(cond, pack)}」，当前为 {current!r}")
        else:
            reasons.append(f"条件不满足：{cond.field} {cond.op} {cond.value!r}（当前 {current!r}）")
    return reasons


def scene_map(pack: ContentPack) -> dict[str, OpeningScene]:
    scenes = {scene.id: scene for scene in pack.scenes}
    scenes.setdefault(pack.opening.id, pack.opening)
    return scenes


def find_scene(pack: ContentPack, scene_id: str) -> OpeningScene | None:
    return scene_map(pack).get(scene_id)


def current_scene_id(events: list[Event], opening_id: str) -> str:
    """当前场景 = 最后一条未撤销 scene.entered 的目标；没有则 opening。"""
    from .state import cancelled_turns

    cancelled = cancelled_turns(events)
    current = opening_id
    for event in sorted(events, key=lambda e: e.seq):
        if event.kind != "scene.entered" or event.turn in cancelled:
            continue
        scene_id = str(event.payload.get("scene_id") or "")
        if scene_id:
            current = scene_id
    return current


def scene_view(scene: OpeningScene, state: dict[str, Any], pack: ContentPack) -> dict[str, Any]:
    """给驾驶舱/上下文用的场景视图（含每个选项是否可选）。"""
    options: list[dict[str, Any]] = []
    for option in scene.options:
        reasons = unmet_conditions(option.requires, state, pack)
        options.append(
            {
                "id": option.id,
                "label": option.label,
                "action_text": option.action_text,
                "next_scene": option.next_scene,
                "available": not reasons,
                "blocked_reason": "；".join(reasons) or None,
            }
        )
    return {
        "id": scene.id,
        "title": scene.title or scene.id,
        "text": scene.text,
        "ending": scene.ending,
        "ending_title": scene.ending_title,
        "requires": [c.model_dump(mode="json") for c in scene.requires],
        "options": options,
    }


def transitions_brief(pack: ContentPack, state: dict[str, Any], scene_id: str) -> list[dict[str, Any]]:
    """当前可尝试进入的场景（给 LLM 的候选，不保证条件满足）。"""
    current = find_scene(pack, scene_id)
    targets: list[str] = []
    if current is not None:
        for option in current.options:
            if option.next_scene and option.next_scene not in targets:
                targets.append(option.next_scene)
    for candidate in pack.scenes:
        if candidate.id != scene_id and candidate.id not in targets:
            targets.append(candidate.id)
    out: list[dict[str, Any]] = []
    for target_id in targets:
        target = find_scene(pack, target_id)
        if target is None:
            continue
        reasons = unmet_conditions(target.requires, state, pack)
        out.append(
            {
                "scene_id": target.id,
                "title": target.title or target.id,
                "available": not reasons,
                "blocked_reason": "；".join(reasons) or None,
            }
        )
    return out


def format_scene_brief(
    pack: ContentPack, state: dict[str, Any], scene_id: str
) -> str:
    scene = find_scene(pack, scene_id)
    if scene is None:
        return "（当前场景未声明）"
    lines = [f"# 当前场景：{scene.title or scene.id}（{scene.id}）", scene.text]
    if scene.ending:
        lines.append(
            f"（这是一个结局标记：{scene.ending_title or scene.title}。"
            "结局不锁死操作——玩家仍可选择继续停留、返回或做别的事；"
            "不要强行结束叙事，除非玩家自己选择结束这一晚。）"
        )
    view = scene_view(scene, state, pack)
    open_options = [o for o in view["options"] if o["available"]]
    if open_options:
        lines.append("可做的动作：")
        lines += [f"- {o['label']}：{o['action_text']}" for o in open_options]
    transitions = transitions_brief(pack, state, scene_id)
    if transitions:
        lines.append("可前往的场景（条件未满足的不可进入）：")
        for t in transitions:
            mark = "可进入" if t["available"] else f"锁住（{t['blocked_reason']}）"
            lines.append(f"- {t['title']}（{t['scene_id']}）：{mark}")
    return "\n".join(lines)
