"""世界构筑助手：把一段完整素材拆成可运行的内容包草稿。

用户给出世界观/剧情/规则/角色等原始素材，模型按 `BUILDER_SYSTEM_PROMPT`
输出一份 JSON 草稿（前置/叙事/结算提示词 + 世界书 + 技能），本模块负责：

- 提供提示词（可复制给任何外部 AI 使用）；
- 解析模型输出（容忍 markdown 代码块、前后废话）；
- 归一化并校验成 `WorldbookEntry` / `SkillSpec`，生成可直接落盘的草稿。

注意：提示词本身不允许给玩法加任何限制（不设回合上限、不锁结局），
这条约束与 P4 起的产品原则一致。
"""
from __future__ import annotations

import json
import re
from typing import Any

from rpg_core.contracts import SkillSpec, WorldbookEntry

# 新内容包（minimal 模板）里声明的状态字段：技能消耗只能引用它们
STATE_FIELDS = ("hp", "focus", "credits")
# 与 rpg_content.lint.KNOWN_TARGETS 保持一致
KNOWN_TARGETS = {"self", "enemy", "scene", "item", "npc", "any", "all", "ally"}
PROMPT_KEYS = ("pre", "narrator", "settler")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)

BUILDER_SYSTEM_PROMPT = """你是文字冒险世界初始化器。将素材转为一个可运行的 JSON 草稿，不输出代码围栏。
字段：title,description,prompts:{pre,narrator,settler},worldbook:[],skills:[],state:{fields:[],resource_bindings:{},limits:{max_delta_per_turn:{}}},character_profile:{}。
pre（前置提示词）只写作者世界设定和主角身份；narrator（叙事者提示词）只写视角、篇幅和文风，不包含数值、工具或状态栏职责；settler（结算器提示词）只写本世界结算语义和判断依据。叙事与结算始终分离。
state.fields 每个数值必须有 id(小写英文下划线)、label(符合世界观)、type(int/float)、default、min、max(无上限=null)、step、display(bar/number)、unit、color(#rrggbb)。
气血/真元/灵石、生命/魔力/金币、机体完整度/能源/星币等仅为例子，按世界和主角实力制定初始值、上限与货币单位，不固定 hp/focus/credits 或20/10/999。资源可增删。
resource_bindings 将 health/mana/effort/currency 绑定到实际数值 id；相同资源可兼任两种用途，缺失的用途不绑定。limits 是每回合最大变化量，未声明表示不另设限制。
character_profile 输出 power(novice/trained/master/legendary)、schools(精通流派名列表)、limitations(限制列表)、evidence(素材原文)。区分主角现有能力、NPC能力和未来目标。强者不按新手配置。
skills 只收录作者明确的特殊技能，不用生成整个常规技能库。每项有 id,name,description,cost(本世界数值id到消耗),cooldown,targets,action_text,effect_hint,category,brief。标准预设会由框架另行匹配。
worldbook（世界书）每项含 id,title,content,keywords,always_on,priority,category；关键词具体，主角身份和世界硬规则应常驻。
工具契约由运行时提供，不在提示词中发明 inventory/flag 等工具名，不设回合上限、不锁死结局、不锁死剧情。
只输出一个 JSON 对象，保持作者素材的限制和风格。
"""


# -- 提示词拼装 -------------------------------------------------------------
def compose_prompt(material: str, *, title_hint: str = "", extra_rules: str = "") -> str:
    """把系统提示词与素材拼成「一段可以直接粘贴给任何 AI」的完整提示词。"""
    parts = [BUILDER_SYSTEM_PROMPT.rstrip(), "", "--- 素材开始 ---", material.strip()]
    if title_hint.strip():
        parts += ["", f"（希望的作品名：{title_hint.strip()}；不合适你可以自己换一个）"]
    if extra_rules.strip():
        parts += ["", f"（额外要求：{extra_rules.strip()}）"]
    parts += ["--- 素材结束 ---"]
    return "\n".join(parts) + "\n"


def build_request(material: str, *, title_hint: str = "", extra_rules: str = "") -> dict[str, Any]:
    """构造 router.complete 的请求：素材放在 user 行动里，方便各 provider 复用。"""
    return {
        "system_prompt": BUILDER_SYSTEM_PROMPT,
        "state_brief": "",
        "vocab": "",
        "recent": "",
        "scene": {},
        "action": {"kind": "text", "text": compose_prompt(material, title_hint=title_hint, extra_rules=extra_rules)},
        "tool_results": [],
    }


# -- 输出解析 ---------------------------------------------------------------
def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里取出第一个 JSON 对象；容忍 markdown 代码块与前后解释。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型输出为空，没有可解析的 JSON")
    fence = _FENCE_RE.search(raw)
    candidates: list[str] = []
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(raw)
    for candidate in candidates:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("模型输出里没有找到合法的 JSON 对象（应为一个 { ... }）")


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


_PROMPT_ALIASES: dict[str, tuple[str, ...]] = {
    "pre": ("pre", "pre_prompt", "前置", "前置提示词", "front", "premise", "world_setting"),
    "narrator": (
        "narrator",
        "narrator_prompt",
        "叙事",
        "叙事提示词",
        "叙事者",
        "叙事者提示词",
        "narrative",
        "storyteller",
    ),
    "settler": (
        "settler",
        "settler_prompt",
        "结算",
        "结算提示词",
        "结算器",
        "结算器提示词",
        "settlement",
        "resolver",
    ),
}
_PROMPT_CONTAINERS = ("prompts", "prompt", "提示词", "world_building", "worldbuilding")
_PROMPT_ROLE_KEYS = ("key", "role", "name", "type", "kind", "id", "stage")


def _prompt_text(value: Any) -> str:
    """提示词可能直接是字符串、字符串数组，或 {content|text|prompt|value|body} 对象。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [_prompt_text(item) for item in value]
        return "\n\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("content", "text", "prompt", "value", "body", "description"):
            text = _prompt_text(value.get(key))
            if text:
                return text
    return ""


def _match_prompt_role(role: str) -> str:
    role = (role or "").strip().lower()
    if not role:
        return ""
    for canonical, names in _PROMPT_ALIASES.items():
        if role in names:
            return canonical
    for canonical, names in _PROMPT_ALIASES.items():
        if any(name in role for name in names):
            return canonical
    return ""


def _collect_prompts(container: Any) -> dict[str, str]:
    """从 dict 或 [{role, content}] 列表里收集三份提示词（宽松匹配）。"""
    prompts: dict[str, str] = {}
    if isinstance(container, dict):
        for canonical, names in _PROMPT_ALIASES.items():
            for name in names:
                text = _prompt_text(container.get(name))
                if text:
                    prompts[canonical] = text
                    break
        # 宽松兜底：键名形如 "narrator_prompt_v2" / "pre_setting" 也能认出来
        for key, value in container.items():
            canonical = _match_prompt_role(str(key))
            if canonical and canonical not in prompts:
                text = _prompt_text(value)
                if text:
                    prompts[canonical] = text
    elif isinstance(container, (list, tuple)):
        for item in container:
            if not isinstance(item, dict):
                continue
            role = ""
            for key in _PROMPT_ROLE_KEYS:
                role = _as_text(item.get(key))
                if role:
                    break
            canonical = _match_prompt_role(role)
            text = _prompt_text(item)
            if canonical and text:
                prompts.setdefault(canonical, text)
    return prompts


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _slug(value: Any, *, prefix: str, index: int, used: set[str]) -> str:
    text = _as_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")  # id 只保留 ascii 骨架
    if not text or not text[0].isalpha():
        text = f"{prefix}_{index + 1}"
    text = re.sub(r"_+", "_", text)[:48].strip("_") or f"{prefix}_{index + 1}"
    candidate = text
    suffix = 2
    while candidate in used:
        candidate = f"{text}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_worldbook(items: Any, warnings: list[str]) -> list[dict[str, Any]]:
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(items)):
        if not isinstance(raw, dict):
            warnings.append(f"世界书第 {index + 1} 条不是对象，已跳过")
            continue
        content = _as_text(raw.get("content"))
        if not content:
            warnings.append(f"世界书第 {index + 1} 条没有 content，已跳过")
            continue
        title = _as_text(raw.get("title")) or content[:16]
        keywords = [str(k).strip() for k in _as_list(raw.get("keywords")) if str(k).strip()]
        entry = WorldbookEntry(
            id=_slug(raw.get("id"), prefix="entry", index=index, used=used),
            title=title[:60],
            content=content,
            keywords=list(dict.fromkeys(keywords))[:8],
            always_on=bool(raw.get("always_on", False)),
            enabled=bool(raw.get("enabled", True)),
            priority=max(0, min(100, _int(raw.get("priority"), 0))),
            category=_as_text(raw.get("category"))[:24],
        )
        out.append(entry.model_dump(mode="json"))
    return out


def _normalize_skills(items: Any, warnings: list[str], state_fields: tuple[str, ...] = STATE_FIELDS) -> list[dict[str, Any]]:
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(items)):
        if not isinstance(raw, dict):
            warnings.append(f"技能第 {index + 1} 条不是对象，已跳过")
            continue
        name = _as_text(raw.get("name"))
        if not name:
            warnings.append(f"技能第 {index + 1} 条没有 name，已跳过")
            continue
        cost_raw = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
        cost: dict[str, float] = {}
        for field, amount in cost_raw.items():
            key = str(field).strip()
            if key not in state_fields:
                warnings.append(f"技能「{name}」的消耗字段 {key!r} 不存在（必须绑定本世界已声明的数值字段），已忽略")
                continue
            try:
                number = float(amount)
            except (TypeError, ValueError):
                warnings.append(f"技能「{name}」的消耗 {key} 不是数字，已忽略")
                continue
            if number > 0:
                cost[key] = round(number, 2)
        targets = [
            str(t).strip()
            for t in _as_list(raw.get("targets"))
            if str(t).strip() in KNOWN_TARGETS
        ] or ["self"]
        skill = SkillSpec(
            id=_slug(raw.get("id"), prefix="skill", index=index, used=used),
            name=name[:30],
            description=_as_text(raw.get("description")),
            cost=cost,
            cooldown=max(0, min(99, _int(raw.get("cooldown"), 0))),
            targets=targets,
            usable_when=_as_text(raw.get("usable_when")) or None,
            action_text=_as_text(raw.get("action_text")) or name,
            effect_hint=_as_text(raw.get("effect_hint"))[:60],
            category=_as_text(raw.get("category"))[:20],
            brief=(_as_text(raw.get("brief")) or name)[:24],
        )
        out.append(skill.model_dump(mode="json"))
    return out


def _draft_collection(
    data: dict[str, Any], names: tuple[str, ...], warnings: list[str]
) -> Any:
    """顶层字段优先（包括显式空列表），兼容模型误塞进提示词容器的集合。"""
    for name in names:
        if name in data:
            return data[name]
    for container_name in _PROMPT_CONTAINERS:
        container = data.get(container_name)
        if not isinstance(container, dict):
            continue
        for name in names:
            if name in container:
                warnings.append(
                    f"已将 {container_name}.{name} 识别为顶层 {names[0]}，保留其中内容"
                )
                return container[name]
    return None


def parse_draft(payload: Any) -> dict[str, Any]:
    """把模型输出的 JSON 归一化成可直接落盘的草稿。

    返回 `{title, description, prompts, worldbook, skills, warnings}`；
    提示词至少提供一份，否则抛 ValueError。
    """
    if not isinstance(payload, dict):
        raise ValueError("草稿必须是一个 JSON 对象")
    data = payload
    for key in ("draft", "world", "content", "data", "result", "世界构筑", "world_building"):
        if isinstance(payload.get(key), dict):
            data = payload[key]
            break
    else:
        # 模型有时会把整份草稿塞进单个键里，例如 {"世界构筑": {...}}
        if not any(k in payload for k in ("title", "prompts", "worldbook", "skills", "state")) and len(payload) == 1:
            only = next(iter(payload.values()))
            if isinstance(only, dict):
                data = only

    prompts: dict[str, str] = {}
    for key in _PROMPT_CONTAINERS:
        if isinstance(data.get(key), (dict, list)):
            prompts = _collect_prompts(data[key])
            if prompts:
                break
    if not prompts:  # 兼容把 pre/narrator/settler 直接放在顶层的写法
        prompts = _collect_prompts(data)
    if not prompts:
        keys = "、".join(str(k) for k in list(data.keys())[:12]) or "（空对象）"
        raise ValueError(
            "草稿里没有可用的提示词（需要 prompts.pre / prompts.narrator / prompts.settler 至少一项）。"
            f"这份 JSON 的顶层键是：{keys}；"
            "请让模型按提示词里给出的 JSON 结构输出，或把三份提示词放进 prompts 对象再重试。"
        )

    warnings: list[str] = []
    worldbook = _normalize_worldbook(
        _draft_collection(data, ("worldbook", "world_book"), warnings), warnings
    )
    from rpg_content.state_config import normalize_state
    text="\n".join([_as_text(data.get("title")),_as_text(data.get("description")),prompts.get("pre","")])
    state=normalize_state(data.get("state"),text)
    skills = _normalize_skills(_draft_collection(data, ("skills",), warnings), warnings,tuple(f["id"] for f in state["fields"] if f["type"] in ("int","float")))
    title = _as_text(data.get("title"))[:40]
    return {
        "title": title,
        "description": _as_text(data.get("description"))[:120],
        "prompts": prompts,
        "state": state,
        "character_profile": data.get("character_profile") if isinstance(data.get("character_profile"),dict) else {},
        "worldbook": worldbook,
        "skills": skills,
        "warnings": warnings,
    }


def draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    """给前端预览用的轻量摘要（不含三份提示词全文）。"""
    prompts = draft.get("prompts") or {}
    return {
        "title": draft.get("title", ""),
        "description": draft.get("description", ""),
        "prompt_keys": list(prompts.keys()),
        "prompt_lengths": {key: len(text) for key, text in prompts.items()},
        "worldbook_count": len(draft.get("worldbook") or []),
        "skill_count": len(draft.get("skills") or []),
        "state_field_count": len((draft.get("state") or {}).get("fields",[])),
        "warnings": draft.get("warnings") or [],
    }
