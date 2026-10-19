"""内容包 lint：把"能不能加载"升级成"能不能上线"。

`lint_pack(pack)` 做纯对象校验，返回 `LintIssue` 列表（error / warning）。
`lint_pack_dir(path)` 额外把加载失败（缺文件 / 坏 JSON / 模型字段不合法）也变成 issue，
方便编辑器、CI 和作者工具一次性列出全部问题，而不是抛出第一个异常。

error：内容包不可用（`load_pack` 会拒绝加载）。
warning：能跑，但很可能是作者写错了（命名不一致、显示类型和值类型不匹配等）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from rpg_core.contracts import ContentPack, DisplayKind

Level = Literal["error", "warning"]

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
KNOWN_TARGETS = {"self", "enemy", "scene", "item", "npc", "any", "all", "ally"}
KNOWN_RATINGS = {"all", "0+", "6+", "12+", "16+", "18+"}

SCENARIO_KEYS = {"id", "description", "action", "expect"}


@dataclass(frozen=True)
class LintIssue:
    level: Level
    code: str
    message: str
    path: str = ""

    def format(self) -> str:
        where = f" [{self.path}]" if self.path else ""
        return f"{self.level.upper():7} {self.code}{where}：{self.message}"


class _Issues:
    def __init__(self) -> None:
        self.items: list[LintIssue] = []

    def error(self, code: str, message: str, path: str = "") -> None:
        self.items.append(LintIssue("error", code, message, path))

    def warning(self, code: str, message: str, path: str = "") -> None:
        self.items.append(LintIssue("warning", code, message, path))


def _dupes(issues: _Issues, ids: Iterable[str], what: str, code: str, path: str) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            issues.error(code, f"{what} id 重复：{item_id}", path)
        seen.add(item_id)


def _lint_conditions(
    issues: _Issues,
    conditions: Iterable[Any],
    fields: dict[str, Any],
    where: str,
) -> None:
    for cond in conditions:
        field = fields.get(cond.field)
        if field is None:
            issues.error(
                "scene.condition_unknown_field",
                f"进入条件引用了未声明字段 {cond.field}",
                where,
            )
            continue
        if field.type == "bool" and not isinstance(cond.value, bool):
            issues.warning(
                "scene.condition_type_mismatch",
                f"标记字段 {cond.field} 的条件值 {cond.value!r} 不是布尔",
                where,
            )
        if field.type in ("int", "float") and isinstance(cond.value, bool):
            issues.warning(
                "scene.condition_type_mismatch",
                f"数值字段 {cond.field} 的条件值 {cond.value!r} 是布尔",
                where,
            )


def lint_pack(pack: ContentPack) -> list[LintIssue]:
    out = _Issues()
    fields = pack.state.by_id()
    from rpg_core.skill_catalog import validate_catalog
    for message in validate_catalog(pack):
        out.error("skill_catalog.invalid", message, "vocab/skill_catalog.json")

    # ---- manifest -------------------------------------------------------
    manifest = pack.manifest
    if not PACK_ID_RE.match(manifest.id):
        out.error(
            "manifest.id_invalid",
            "id 只能是小写字母/数字/连字符（2-64 位，不以连字符开头）",
            "manifest.json",
        )
    if not manifest.title.strip():
        out.error("manifest.title_empty", "title 不能为空", "manifest.json")
    if not SEMVER_RE.match(manifest.version):
        out.error(
            "manifest.version_invalid",
            f"version 需要 x.y.z 形式，当前 {manifest.version!r}",
            "manifest.json",
        )
    if manifest.schema_version != 1:
        out.error(
            "manifest.schema_version",
            f"当前框架只支持 schema_version=1，收到 {manifest.schema_version}",
            "manifest.json",
        )
    if manifest.rating not in KNOWN_RATINGS:
        out.warning(
            "manifest.rating_unknown",
            f"rating {manifest.rating!r} 不在 {sorted(KNOWN_RATINGS)} 内，年龄门会按未知处理",
            "manifest.json",
        )
    for dep in manifest.dependencies:
        if not PACK_ID_RE.match(dep):
            out.error("manifest.dependency_invalid", f"依赖 id 不合法：{dep}", "manifest.json")

    # ---- state ----------------------------------------------------------
    if not pack.state.fields:
        out.error("state.no_fields", "至少需要一个状态字段", "state.json")
    _dupes(out, (f.id for f in pack.state.fields), "状态字段", "state.duplicate_id", "state.json")
    for field in pack.state.fields:
        where = f"state.json (field {field.id})"
        if not ID_RE.match(field.id):
            out.error("state.id_invalid", "字段 id 需匹配 ^[a-z][a-z0-9_]*$", where)
        if not field.label.strip():
            out.warning("state.label_empty", "字段没有 label，UI 会显示 id", where)
        if field.color is not None and not COLOR_RE.match(field.color):
            out.warning(
                "state.bad_color",
                f"color 需匹配 #rrggbb，当前 {field.color!r}；UI 会回退到默认配色",
                where,
            )
        if field.type in ("int", "float"):
            if field.min is not None and field.max is not None and field.min > field.max:
                out.error("state.bad_range", f"min {field.min} > max {field.max}", where)
            if isinstance(field.default, bool):
                out.error("state.bad_default", "数值字段的 default 不能是 bool", where)
            elif field.default is not None:
                if field.min is not None and float(field.default) < field.min:
                    out.error("state.default_out_of_range", f"默认值 {field.default} < min {field.min}", where)
                if field.max is not None and float(field.default) > field.max:
                    out.error("state.default_out_of_range", f"默认值 {field.default} > max {field.max}", where)
            if field.step <= 0:
                out.error("state.step_nonpositive", f"step 必须 > 0，当前 {field.step}", where)
            if field.display == "bar" and (field.min is None or field.max is None):
                out.error("state.bar_needs_range", "bar 显示需要同时声明 min 和 max", where)
        elif field.type == "bool":
            if not isinstance(field.default, bool):
                out.error("state.bad_default", f"bool 字段的 default 必须是 true/false，当前 {field.default!r}", where)
            if field.display not in ("badge", "hidden", "text"):
                out.warning(
                    "state.bool_display",
                    f"bool 字段建议用 badge/hidden，当前 display={field.display}",
                    where,
                )
        elif field.type == "enum":
            if not field.enum_values:
                out.error("state.enum_empty", "enum 字段必须声明 enum_values", where)
            elif field.default not in (field.enum_values or []):
                out.error(
                    "state.enum_default_missing",
                    f"default {field.default!r} 不在 enum_values 内",
                    where,
                )

    for role,field_id in pack.state.resource_bindings.items():
        if role not in ('health','mana','effort','currency') or field_id and (field_id not in fields or fields[field_id].type not in ('int','float')):
            out.error('state.invalid_resource_binding',f'资源用途 {role} 绑定无效：{field_id}','state.json')

    limits = pack.state.limits
    if limits.max_tool_rounds < 1:
        out.error("state.max_tool_rounds", "max_tool_rounds 必须 >= 1", "state.json")
    if limits.max_rejections < 0:
        out.error("state.max_rejections", "max_rejections 不能为负", "state.json")
    for field_id, cap in limits.max_delta_per_turn.items():
        if field_id not in fields:
            out.error(
                "state.max_delta_unknown_field",
                f"max_delta_per_turn 引用了未声明字段：{field_id}",
                "state.json",
            )
        elif fields[field_id].type not in ("int", "float"):
            out.error(
                "state.max_delta_non_numeric",
                f"max_delta_per_turn 只能限制数值字段：{field_id}",
                "state.json",
            )
        elif cap <= 0:
            out.error(
                "state.max_delta_nonpositive",
                f"max_delta_per_turn[{field_id}] 必须 > 0，当前 {cap}",
                "state.json",
            )

    # ---- ui -------------------------------------------------------------
    layout = pack.ui
    if not layout.title.strip():
        out.warning("ui.title_empty", "ui/layout.json 没有 title", "ui/layout.json")
    for section in (layout.bars, layout.numbers, layout.badges):
        for field_id in section:
            if field_id not in fields:
                out.error(
                    "ui.field_unknown",
                    f"UI 引用了未声明字段：{field_id}",
                    "ui/layout.json",
                )
    seen_ui = [f for f in layout.bars + layout.numbers + layout.badges]
    _dupes(out, seen_ui, "UI 字段", "ui.duplicate_field", "ui/layout.json")
    for field_id in layout.bars:
        field = fields.get(field_id)
        if field and field.type not in ("int", "float"):
            out.error("ui.bar_not_numeric", f"bars 只能放数值字段：{field_id}", "ui/layout.json")
    for field_id in layout.numbers:
        field = fields.get(field_id)
        if field and field.type == "bool":
            out.error("ui.number_on_bool", f"numbers 不能放 bool 字段：{field_id}", "ui/layout.json")
    for field_id in layout.badges:
        field = fields.get(field_id)
        if field and field.type != "bool":
            out.warning(
                "ui.badge_not_bool",
                f"badges 建议放 bool 字段，{field_id} 是 {field.type}",
                "ui/layout.json",
            )
    for field in pack.state.fields:
        if field.display == "bar" and field.id not in layout.bars:
            out.warning(
                "ui.display_not_in_layout",
                f"字段 {field.id} 标记为 bar 但不在 ui.bars",
                "ui/layout.json",
            )
        if field.display == "number" and field.id not in layout.numbers:
            out.warning(
                "ui.display_not_in_layout",
                f"字段 {field.id} 标记为 number 但不在 ui.numbers",
                "ui/layout.json",
            )

    # ---- vocab ----------------------------------------------------------
    _dupes(out, (s.id for s in pack.skills), "技能", "skill.duplicate_id", "vocab/skills.json")
    _dupes(out, (i.id for i in pack.items), "物品", "item.duplicate_id", "vocab/items.json")
    _dupes(out, (n.id for n in pack.npcs), "NPC", "npc.duplicate_id", "vocab/npcs.json")
    _dupes(out, (q.id for q in pack.quests), "任务", "quest.duplicate_id", "vocab/quests.json")
    _dupes(out, (f.id for f in pack.flags), "标记", "flag.duplicate_id", "vocab/flags.json")
    _dupes(out, (e.id for e in pack.worldbook), "世界书条目", "worldbook.duplicate_id", "vocab/worldbook.json")

    for skill in pack.skills:
        where = f"vocab/skills.json (skill {skill.id})"
        if not ID_RE.match(skill.id):
            out.error("skill.id_invalid", "技能 id 需匹配 ^[a-z][a-z0-9_]*$", where)
        if not skill.name.strip():
            out.error("skill.name_empty", "技能需要 name", where)
        if not skill.action_text.strip():
            out.warning("skill.action_text_empty", "没有 action_text，填入输入框的内容会为空", where)
        for cost_field, amount in skill.cost.items():
            target = fields.get(cost_field)
            if target is None:
                out.error("skill.cost_unknown_field", f"消耗字段未声明：{cost_field}", where)
            elif target.type not in ("int", "float"):
                out.error("skill.cost_non_numeric", f"消耗字段必须是数值：{cost_field}", where)
            elif amount <= 0:
                out.warning("skill.cost_nonpositive", f"消耗 {cost_field}={amount} 无意义", where)
        if skill.cooldown < 0 or skill.cooldown > 99:
            out.error("skill.cooldown_range", f"冷却需在 0~99，当前 {skill.cooldown}", where)
        if not skill.targets:
            out.warning("skill.targets_empty", "targets 为空，UI 无法提示目标", where)
        for target in skill.targets:
            if target not in KNOWN_TARGETS:
                out.warning("skill.target_unknown", f"未知目标类型 {target!r}", where)

    for entry in pack.worldbook:
        where = f"vocab/worldbook.json (entry {entry.id})"
        if not ID_RE.match(entry.id):
            out.error("worldbook.id_invalid", "世界书条目 id 需匹配 ^[a-z][a-z0-9_]*$", where)
        if not entry.title.strip():
            out.warning("worldbook.title_empty", f"条目 {entry.id} 缺少 title", where)
        if not entry.content.strip():
            out.error("worldbook.content_empty", "世界书条目必须有 content", where)
        keywords = [kw.strip() for kw in entry.keywords if kw.strip()]
        if not entry.always_on and not keywords:
            out.warning(
                "worldbook.never_triggers",
                "非常驻条目没有任何关键词，永远不会被注入（要么填 keywords，要么设 always_on）",
                where,
            )

    for item in pack.items:
        if not ID_RE.match(item.id):
            out.error("item.id_invalid", "物品 id 需匹配 ^[a-z][a-z0-9_]*$", "vocab/items.json")
        if not item.name.strip():
            out.error("item.name_empty", f"物品 {item.id} 缺少 name", "vocab/items.json")
    for npc in pack.npcs:
        if not ID_RE.match(npc.id) or not npc.name.strip():
            out.error("npc.invalid", f"NPC 定义不完整：{npc.id!r}", "vocab/npcs.json")
    for quest in pack.quests:
        if not ID_RE.match(quest.id) or not quest.name.strip():
            out.error("quest.invalid", f"任务定义不完整：{quest.id!r}", "vocab/quests.json")
    for flag in pack.flags:
        if not ID_RE.match(flag.id):
            out.error("flag.id_invalid", "标记 id 需匹配 ^[a-z][a-z0-9_]*$", "vocab/flags.json")
        if not flag.label.strip():
            out.warning("flag.label_empty", f"标记 {flag.id} 缺少 label", "vocab/flags.json")
        field = fields.get(flag.id) or fields.get(f"flag_{flag.id}")
        if field is None:
            out.warning(
                "flag.no_state_field",
                f"标记 {flag.id} 没有对应的 bool 状态字段（flag_{flag.id} 或 {flag.id}），只会在账本里留事件",
                "vocab/flags.json",
            )
        elif field.type != "bool":
            out.error(
                "flag.state_field_not_bool",
                f"标记 {flag.id} 对应的状态字段 {field.id} 不是 bool",
                "vocab/flags.json",
            )

    # ---- prompts --------------------------------------------------------
    for key in ("narrator", "settler"):
        text = pack.prompts.get(key)
        if text is None:
            out.error("prompt.missing", f"prompts/{key}.md 缺失", "prompts/")
            continue
        if len(text.strip()) < 40:
            out.warning("prompt.too_short", f"prompts/{key}.md 太短（{len(text.strip())} 字符）", "prompts/")

    # ---- scenes ---------------------------------------------------------
    scenes = list(pack.scenes)
    if pack.opening.id not in {s.id for s in scenes}:
        scenes.append(pack.opening)
    _dupes(out, (s.id for s in scenes), "场景", "scene.duplicate_id", "scenes/")
    for scene in scenes:
        where = f"scenes/{scene.id}.json"
        if not ID_RE.match(scene.id):
            out.error("scene.id_invalid", "场景 id 需匹配 ^[a-z][a-z0-9_]*$", where)
        if not scene.text.strip():
            out.warning("scene.text_empty", "场景没有 text", where)
        _dupes(out, (o.id for o in scene.options), "场景选项", "scene.option_duplicate_id", where)
        for option in scene.options:
            if not option.action_text.strip():
                out.warning(
                    "scene.option_action_text_empty",
                    f"选项 {option.id} 没有 action_text，点击填入会为空",
                    where,
                )
        if len(scene.options) > 4:
            out.warning("scene.options_too_many", f"选项 {len(scene.options)} 个，建议 ≤4", where)

    if not pack.opening.text.strip() and not pack.opening.options:
        out.error("scene.opening_empty", "scenes/opening.json 需要 text 或 options", "scenes/opening.json")

    # ---- 场景进入条件与转场引用 ----------------------------------------
    scene_ids = {s.id for s in scenes}
    incoming: set[str] = set()
    for scene in scenes:
        where = f"scenes/{scene.id}.json"
        _lint_conditions(out, scene.requires, fields, f"{where} 的 requires")
        for option in scene.options:
            _lint_conditions(
                out,
                option.requires,
                fields,
                f"{where} 选项 {option.id} 的 requires",
            )
            if not option.next_scene:
                continue
            incoming.add(option.next_scene)
            if option.next_scene not in scene_ids:
                out.error(
                    "scene.unknown_next_scene",
                    f"选项 {option.id} 指向未声明场景 {option.next_scene}",
                    where,
                )
    for scene in scenes:
        if scene.id == pack.opening.id:
            continue
        if scene.id not in incoming:
            out.warning(
                "scene.unreachable",
                f"场景 {scene.id} 没有任何作者的 next_scene 指向它（只能靠 LLM 的 enter_scene 进入）",
                f"scenes/{scene.id}.json",
            )

    if pack.wardrobe is not None:
        from rpg_core.clothing import validate_wardrobe
        for message in validate_wardrobe(pack.wardrobe, pack.state):
            out.error("wardrobe.invalid", message, "wardrobe.json")

    # ---- tests/scenarios.json（可选） ----------------------------------
    # 由 lint_pack_dir 读取原始 JSON 后校验，这里只做对象层提示
    return out.items


def _lint_scenarios_file(root: Path, out: _Issues) -> None:
    path = root / "tests" / "scenarios.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out.error("scenario.bad_json", f"scenarios.json 解析失败：{exc}", "tests/scenarios.json")
        return
    scenarios = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        out.error(
            "scenario.empty",
            "tests/scenarios.json 需要非空的 scenarios 数组",
            "tests/scenarios.json",
        )
        return
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        where = f"tests/scenarios.json (scenario #{index})"
        if not isinstance(scenario, dict):
            out.error("scenario.invalid", "场景必须是对象", where)
            continue
        extra = set(scenario) - SCENARIO_KEYS
        if extra:
            out.warning("scenario.unknown_keys", f"未知字段：{sorted(extra)}", where)
        scenario_id = str(scenario.get("id", ""))
        if not scenario_id:
            out.error("scenario.id_missing", "缺少 id", where)
        elif scenario_id in seen:
            out.error("scenario.duplicate_id", f"场景 id 重复：{scenario_id}", where)
        seen.add(scenario_id)
        action = scenario.get("action")
        if not isinstance(action, dict) or not action.get("kind"):
            out.error("scenario.action_invalid", "action 需要包含 kind", where)
        expect = scenario.get("expect")
        if not isinstance(expect, dict):
            out.error("scenario.expect_invalid", "expect 必须是对象", where)
        else:
            unknown_expect = set(expect) - {"state", "events_include", "narrative_no_leaks"}
            if unknown_expect:
                out.warning(
                    "scenario.expect_unknown_keys",
                    f"expect 未知字段：{sorted(unknown_expect)}（金样测试会忽略）",
                    where,
                )


def lint_pack_dir(pack_dir: str | Path) -> list[LintIssue]:
    """加载 + lint；加载阶段的异常也转成 issue（便于一次列全）。"""
    from rpg_content.pack import PackError, load_pack

    root = Path(pack_dir)
    out = _Issues()
    try:
        pack = load_pack(root, validate=False)
    except PackError as exc:
        out.error("pack.load_failed", str(exc), str(root.name))
        _lint_scenarios_file(root, out)
        return out.items
    for issue in lint_pack(pack):
        out.items.append(issue)
    _lint_scenarios_file(root, out)
    return out.items
