"""护栏：LLM 只能通过原子工具改值。

职责（对应 PLAN 第 4 节）：
- 工具白名单（只有 MUTATORS 中的名字）
- 参数类型 / 字段存在性
- 范围钳制（钳到 min/max）
- 单回合单字段变化量上限（超限直接拒绝）
- 未知物品/标记拒绝
- 幂等由 runtime 的 patch_id 保证（同 turn 同工具序号重复不重复应用）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import CatalogSkill, OpeningScene, SkillSpec, StateSchema, ToolCall, ToolResult, WardrobeConfig
from .scenes import unmet_conditions

_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")
_SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_NUMERIC_TYPES = ("int", "float")


class GuardrailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def roll_dice(dice: str) -> dict[str, Any]:
    m = _DICE_RE.match(dice.strip())
    if not m:
        raise GuardrailError("invalid_dice", f"不支持的骰式：{dice}（示例 1d6+2）")
    count, faces, modifier = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if not (1 <= count <= 20) or not (2 <= faces <= 100):
        raise GuardrailError("invalid_dice", "骰子数量需 1~20，面数需 2~100")
    import random

    rolls = [random.randint(1, faces) for _ in range(count)]
    total = sum(rolls) + modifier
    return {"dice": dice, "rolls": rolls, "modifier": modifier, "total": total}


@dataclass
class ToolOutcome:
    result: ToolResult
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)
    inventory_delta: dict[str, int] = field(default_factory=dict)
    rolls: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    # 场景转场：runtime 见到它才写 scene.entered（场景不是数值状态）
    scene: str | None = None


class ToolExecutor:
    def __init__(
        self,
        schema: StateSchema,
        item_ids: set[str],
        flag_ids: set[str],
        scenes: dict[str, OpeningScene] | None = None,
        skill_ids: set[str] | None = None,
        wardrobe: WardrobeConfig | None = None,
        skill_catalog: list[CatalogSkill] | None = None,
        catalog_mode: bool = False,
        known_skills: list[SkillSpec] | None = None,
    ) -> None:
        self.wardrobe = wardrobe
        self.skill_catalog = {entry.ref: entry for entry in (skill_catalog or [])}
        self.catalog_mode = catalog_mode
        self.skill_names = {skill.name.casefold() for skill in (known_skills or [])}
        self.schema = schema
        self.fields = schema.by_id()
        self.item_ids = item_ids
        self.flag_ids = flag_ids
        self.scenes = scenes or {}
        # 已知技能 id（内容包内置 + 本局已习得），learn_skill 用它挡住重复 id
        self.skill_ids = set(skill_ids or set())
        # 本回合已由框架按技能扣除的字段与金额；模型再对这些字段做扣减即视为重复扣费
        self.skill_payments: dict[str, float] = {}
        self.limits = schema.limits

    def set_skill_payments(self, payments: dict[str, float]) -> None:
        """由 runtime 在结算勾选技能后调用，告诉工具层哪些字段本回合已经扣过。"""
        self.skill_payments = {
            str(field_id): float(amount)
            for field_id, amount in (payments or {}).items()
            if amount
        }

    def _reject_double_spend(self, field_id: str, decreased: bool) -> None:
        paid = self.skill_payments.get(field_id, 0.0)
        if not decreased or not paid:
            return
        field = self.fields.get(field_id)
        label = field.label if field is not None else field_id
        raise GuardrailError(
            "double_spend",
            f"本回合技能已经由框架扣过 {label}（{field_id}）{paid:g} 点，"
            "不要再用工具重复扣同一笔：技能本身的消耗在叙事里用文字表现即可。"
            "技能之外的伤害/治疗/消耗/花费可以正常结算，但不要重复技能那一笔。",
        )

    # -- helpers ---------------------------------------------------------
    def _field(self, field_id: str):
        field = self.fields.get(field_id)
        if field is None:
            raise GuardrailError("unknown_field", f"内容包没有声明字段 {field_id}")
        return field

    def _numeric(self, field_id: str):
        field = self._field(field_id)
        if field.type not in _NUMERIC_TYPES:
            raise GuardrailError("not_numeric", f"字段 {field_id} 不是数值类型")
        return field

    @staticmethod
    def _number(args: dict[str, Any], key: str) -> float:
        if key not in args:
            raise GuardrailError("bad_params", f"缺少参数 {key}")
        try:
            value = float(args[key])
        except (TypeError, ValueError):
            raise GuardrailError("bad_params", f"参数 {key} 不是数字")
        if value != value or value in (float("inf"), float("-inf")):
            raise GuardrailError("bad_params", f"参数 {key} 非法")
        return value

    def _check_delta(
        self, field_id: str, delta: float, delta_used: dict[str, float]
    ) -> None:
        limit = self.limits.max_delta_per_turn.get(field_id)
        if limit is None:
            return
        used = delta_used.get(field_id, 0.0)
        if abs(delta) > limit or used + abs(delta) > limit:
            raise GuardrailError(
                "delta_limit",
                f"{field_id} 单回合变化上限 {limit}，本次 {abs(delta):g}"
                f"（已用 {used:g}）",
            )

    def _clamp(self, field, value: float) -> float:
        if field.min is not None:
            value = max(field.min, value)
        if field.max is not None:
            value = min(field.max, value)
        if field.type == "int":
            value = int(round(value))
        return value

    def _set(self, state: dict[str, Any], field, value: Any) -> dict[str, Any]:
        before = state.get(field.id)
        if field.type == "bool":
            return {"field": field.id, "before": before, "after": bool(value)}
        after = self._clamp(field, value)
        return {"field": field.id, "before": before, "after": after}

    # -- learn_skill：把模型给的新技能收成 SkillSpec（只做校验，不改状态） ----
    def _build_skill(self, args: dict[str, Any]) -> SkillSpec:
        if self.catalog_mode:
            raise GuardrailError("catalog_only", "本世界只从预设目录学习技能；由后置 learn_catalog_skills 按 ref 登记，不得生成新定义")
        skill_id = str(args.get("id") or "").strip().lower()
        if not _SKILL_ID_RE.match(skill_id):
            raise GuardrailError(
                "bad_params",
                "技能 id 需为小写英文字母开头、只含小写字母/数字/下划线，2~40 字符（如 shadow_step）",
            )
        if skill_id in self.skill_ids:
            raise GuardrailError("skill_exists", f"技能 id 已存在：{skill_id}")
        name = str(args.get("name") or "").strip()
        if not name:
            raise GuardrailError("bad_params", "缺少技能名 name")
        if len(name) > 30:
            raise GuardrailError("bad_params", "技能名过长（最多 30 字）")

        raw_cost = args.get("cost") or {}
        if not isinstance(raw_cost, dict):
            raise GuardrailError("bad_params", "cost 需为 {字段: 数值} 对象")
        if len(raw_cost) > 6:
            raise GuardrailError("bad_params", "消耗字段最多 6 个")
        cost: dict[str, float] = {}
        for field_id, amount in raw_cost.items():
            field = self._numeric(str(field_id))
            try:
                value = float(amount)
            except (TypeError, ValueError):
                raise GuardrailError("bad_params", f"消耗 {field.id} 不是数字")
            if value < 0 or value != value:
                raise GuardrailError("bad_params", f"消耗 {field.id} 必须 >= 0")
            cost[field.id] = value

        try:
            cooldown = int(args.get("cooldown") or 0)
        except (TypeError, ValueError):
            raise GuardrailError("bad_params", "cooldown 需为整数")
        if not 0 <= cooldown <= 20:
            raise GuardrailError("bad_params", "cooldown 需在 0~20 之间")

        def text(key: str, limit: int) -> str:
            value = str(args.get(key) or "").strip()
            if len(value) > limit:
                raise GuardrailError("bad_params", f"{key} 过长（最多 {limit} 字）")
            return value

        return SkillSpec(
            id=skill_id,
            name=name,
            description=text("description", 300),
            cost=cost,
            cooldown=cooldown,
            action_text=text("action_text", 200),
            effect_hint=text("effect_hint", 200),
            category=text("category", 20),
            brief=text("brief", 60),
        )

    # -- 主入口 ----------------------------------------------------------
    def execute(
        self,
        call: ToolCall,
        state: dict[str, Any],
        delta_used: dict[str, float],
        turn: int,
        patch_id: str,
        narrative: str | None = None,
    ) -> ToolOutcome:
        name = call.name
        args = call.args or {}

        if name == "update_clothing":
            from .clothing import clothing_changes
            changes = clothing_changes(self.wardrobe, state, args, narrative)
            for field_id, change in changes.items():
                state[field_id] = change["after"]
            data = {"updates": args["changes"], "changes": changes}
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                changes=changes, data=data,
            )

        if name == "roll":
            dice = str(args.get("dice", "1d6"))
            rolled = roll_dice(dice)
            return ToolOutcome(
                result=ToolResult(
                    tool_call_id=call.id, name=name, ok=True, data=rolled
                ),
                rolls=[rolled],
                data=rolled,
            )

        if name in ("damage", "heal"):
            if not args.get("target") and self.schema.resource_bindings.get("health", None)=="":
                raise GuardrailError("health_unbound", "本世界没有绑定生命资源，请明确指定数值字段")
            field_id = str(args.get("target") or self.schema.resource_bindings.get("health") or "hp")
            field = self._numeric(field_id)
            amount = self._number(args, "amount")
            if amount < 0:
                raise GuardrailError("bad_params", "amount 必须 >= 0")
            before = state.get(field_id)
            signed = -amount if name == "damage" else amount
            change = self._set(state, field, before + signed)
            self._reject_double_spend(field_id, name == "damage" and amount > 0)
            applied = abs(change["after"] - before)
            self._check_delta(field_id, applied, delta_used)
            state[field_id] = change["after"]
            delta_used[field_id] = delta_used.get(field_id, 0.0) + applied
            data = {
                "field": field_id,
                "before": change["before"],
                "after": change["after"],
                "applied": applied,
                "reason": args.get("reason", ""),
            }
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                changes={field_id: change},
                data=data,
            )

        if name in ("add_stat", "set_stat"):
            field_id = str(args.get("field", ""))
            field = self._numeric(field_id)
            before = state.get(field_id)
            if name == "add_stat":
                value = before + self._number(args, "delta")
            else:
                value = self._number(args, "value")
            change = self._set(state, field, value)
            self._reject_double_spend(field_id, float(change["after"]) < float(before))
            applied = abs(change["after"] - before)
            self._check_delta(field_id, applied, delta_used)
            state[field_id] = change["after"]
            delta_used[field_id] = delta_used.get(field_id, 0.0) + applied
            data = {
                "field": field_id,
                "before": change["before"],
                "after": change["after"],
                "reason": args.get("reason", ""),
            }
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                changes={field_id: change},
                data=data,
            )

        if name == "add_item":
            item_id = str(args.get("item_id", ""))
            if item_id not in self.item_ids:
                raise GuardrailError("unknown_item", f"内容包没有物品 {item_id}")
            count = int(args.get("count", 1))
            if count < 1:
                raise GuardrailError("bad_params", "count 必须 >= 1")
            data = {"item_id": item_id, "count": count, "reason": args.get("reason", "")}
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                inventory_delta={item_id: count},
                data=data,
            )

        if name == "set_flag":
            flag = str(args.get("flag", ""))
            value = bool(args.get("value", True))
            candidates = [flag, f"flag_{flag}"]
            field = next(
                (
                    self.fields[c]
                    for c in candidates
                    if c in self.fields and self.fields[c].type == "bool"
                ),
                None,
            )
            if field is None and flag not in self.flag_ids:
                raise GuardrailError("unknown_flag", f"内容包没有标记 {flag}")
            if field is None:
                data = {"flag": flag, "value": value, "reason": args.get("reason", "")}
                return ToolOutcome(
                    result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                    data=data,
                )
            before = state.get(field.id)
            change = {"field": field.id, "before": before, "after": value}
            state[field.id] = value
            data = {
                "flag": flag,
                "field": field.id,
                "before": before,
                "after": value,
                "reason": args.get("reason", ""),
            }
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                changes={field.id: change},
                data=data,
            )

        if name == "enter_scene":
            scene_id = str(args.get("scene_id", "")).strip()
            scene = self.scenes.get(scene_id)
            if scene is None:
                raise GuardrailError(
                    "unknown_scene", f"内容包没有声明场景 {scene_id or '（空）'}"
                )
            reasons = unmet_conditions(scene.requires, state)
            if reasons:
                raise GuardrailError(
                    "scene_locked",
                    f"场景「{scene.title or scene.id}」当前不可进入：" + "；".join(reasons),
                )
            data = {
                "scene_id": scene_id,
                "title": scene.title or scene_id,
                "reason": args.get("reason", ""),
            }
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                data=data,
                scene=scene_id,
            )

        if name == "learn_catalog_skills":
            from .skill_catalog import learning_signal
            if not self.catalog_mode or narrative is None:
                raise GuardrailError("catalog_phase", "预设技能只能在最终叙述后的技能结算阶段学习")
            if set(args) != {"skills"} or not isinstance(args["skills"], list):
                raise GuardrailError("bad_params", "仅允许 skills 数组，不允许覆盖技能定义")
            known = {ref for ref, entry in self.skill_catalog.items() if entry.skill.id in self.skill_ids or entry.skill.name.casefold() in self.skill_names}
            additions = {}; evidence_by_ref = {}
            for item in args["skills"]:
                if not isinstance(item, dict) or set(item) != {"ref", "evidence"}:
                    raise GuardrailError("bad_params", "学习条目只接受 ref 和 evidence")
                ref = item["ref"]; evidence = item["evidence"]
                if not isinstance(ref, str) or ref not in self.skill_catalog:
                    raise GuardrailError("unknown_catalog_skill", f"技能不在本世界可学习目录中：{ref}")
                entry = self.skill_catalog[ref]
                if not isinstance(evidence, str) or not 6 <= len(evidence) <= 240 or evidence not in narrative:
                    raise GuardrailError("learning_evidence", "学习证据须为本次最终叙述中的连续原文（6~240字）")
                if not any(name and name in evidence for name in [entry.skill.name,*entry.aliases]) or not learning_signal(evidence):
                    raise GuardrailError("learning_evidence", "证据必须明确写出学会或掌握对应技能")
                if not re.search(r"你|我|主角|玩家", evidence) or re.search(r"(?:尚未|还没|未能|没能|没有|不能|无法|不会|不曾)[^，。！？]{0,6}(?:学会|掌握|习得|领悟|学成)|(?:想要|打算|准备|希望|尝试|试图)(?:去|能|自己)?(?:学会|掌握|习得|领悟)", evidence):
                    raise GuardrailError("learning_evidence", "愿望、尝试、否定或其他角色的学习不能直接授予玩家技能")
                if ref not in known:
                    additions[ref] = entry; evidence_by_ref[ref] = evidence
            granted = known | additions.keys()
            for ref, entry in additions.items():
                if set(entry.prerequisites) - granted:
                    raise GuardrailError("skill_prerequisite", f"学习 {entry.skill.name} 的前置技能尚未掌握")
            data = {"learned": [{"ref": ref, "skill": entry.skill.model_dump(mode="json"), "instruction": entry.instruction, "evidence": evidence_by_ref[ref]} for ref, entry in additions.items()]}
            return ToolOutcome(result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data), data=data)

        if name == "learn_skill":
            skill = self._build_skill(args)
            data = {
                "skill": skill.model_dump(mode="json"),
                "reason": args.get("reason", ""),
            }
            return ToolOutcome(
                result=ToolResult(tool_call_id=call.id, name=name, ok=True, data=data),
                data=data,
            )

        raise GuardrailError("unknown_tool", f"不允许的工具 {name}")
