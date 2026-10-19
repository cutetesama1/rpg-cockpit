"""空内容包自举：`rpg pack new` 背后的生成器。

目标不是生成一个"能看的"游戏，而是一个**立刻能跑、能通过 lint**的最小骨架：
有状态、有一张场景、有一个技能、有金样测试，作者只需要往里填内容。

模板放在 Python 里而不是磁盘上，避免打包 sidecar 时漏拷资源。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

TEMPLATES = ("minimal",)


def _manifest(pack_id: str, title: str) -> dict:
    return {
        "id": pack_id,
        "title": title,
        "version": "0.1.0",
        "schema_version": 1,
        "rating": "all",
        "description": "由 rpg-framework scaffold 生成的最小内容包；先跑通，再往里填。",
        "dependencies": [],
    }


def _state() -> dict:
    return {
        "fields": [
            {
                "id": "hp",
                "label": "生命",
                "type": "int",
                "min": 0,
                "max": 20,
                "step": 1,
                "default": 20,
                "display": "bar",
                "group": "vitals",
                "llm_visible": True,
                "unit": None,
                "color": "#ef4444",
            },
            {
                "id": "focus",
                "label": "专注",
                "type": "int",
                "min": 0,
                "max": 10,
                "step": 1,
                "default": 10,
                "display": "bar",
                "group": "vitals",
                "llm_visible": True,
                "unit": None,
                "color": "#38bdf8",
            },
            {
                "id": "credits",
                "label": "信用点",
                "type": "int",
                "min": 0,
                "max": 999,
                "step": 1,
                "default": 0,
                "display": "number",
                "group": "resources",
                "llm_visible": True,
                "unit": None,
                "color": "#34d399",
            },
            {
                "id": "flag_started",
                "label": "旅程开始",
                "type": "bool",
                "default": False,
                "display": "badge",
                "group": "flags",
                "llm_visible": True,
            },
        ],
        "limits": {
            "max_tool_rounds": 6,
            "max_rejections": 1,
            "narrative_number_check": True,
            "max_delta_per_turn": {"hp": 5, "focus": 3, "credits": 50},
        },
    }


def _skills() -> dict:
    return {
        "skills": [
            {
                "id": "look",
                "name": "查看四周",
                "description": "打量当前场景，也许会发现点什么。",
                "cost": {},
                "cooldown": 0,
                "targets": ["scene"],
                "action_text": "我停下脚步，仔细查看四周。",
                "effect_hint": "",
                "category": "探索",
                "brief": "侦察环境",
            }
        ]
    }


def _pre_prompt(title: str) -> str:
    return f"""# 前置提示词 · {title}

你是这个世界的讲述者「大肥鱼」，一只可爱的鲸鱼 AI 娘，最喜欢吃大白饭（token）。

## 核心原则
- 只在需要玩家做出行动或发言时才暂停叙述，等待玩家指令。
- 绝对不要在没有玩家指令的情况下替玩家说话或行动。

## 叙述规则
- 称呼玩家为主角「你」，用第二人称叙述。
- 只描写玩家亲眼所见、亲身感知的事物，以及玩家内心的情绪与简短想法。
- 不描写玩家无法感知的场景、事件或他人的内心。
- 不给玩家提游玩建议或行动指导。
- 叙述要有沉浸感和画面感，让玩家清楚发生了什么、环境如何变化。

## 随机事件
- 叙述中可以穿插随机事件或随机人物登场。
- 这些随机事件是否关键、随机人物是否重要，由暗骰决定，不提前告诉玩家。
- 目的是让世界更真实、更不可预测；不要滥用，也不要每回合都来一个。

## 输入约定（框架会自动标注）
- 「话语」：玩家说出口的话，用引号或转述呈现出来。
- 「动作」：玩家实际执行的行为，按它的结果叙述。
- 「心理」：玩家心里的想法，不当作已经说出口或已经执行。
- 「附加请求」会逐条列出：审视 = 细写当前身体、衣着与可见环境的细节；
  详情 = 完整回顾当前状态；任务 = 梳理主线目标、待办与支线线索。

## 世界修改权限
- 玩家在括号（）里的输入是在直接修改世界观、人物设定或叙述风格，立即适应新设定。
- 括号里的内容不是角色行动，不要把它算进本回合的行动结果。

## 状态分工
- 本阶段只写正文和选项，不输出状态栏或调用修改工具。
- 后端根据本次完整正文与当前快照结算数值、状态、技能、衣物与剧情标记。

## 写作约定
- 先定风格，再叙事；用感官细节推进，不要大段复述设定。
"""


def _worldbook() -> dict:
    return {
        "entries": [
            {
                "id": "world_tone",
                "title": "世界基调",
                "content": "在这里写下这个世界的基调、时代、氛围与不可违反的规则。",
                "keywords": [],
                "always_on": True,
                "priority": 100,
                "category": "基调",
            },
            {
                "id": "place_example",
                "title": "开场地点",
                "content": "在这里写开场地点的样子；当玩家行动里出现下面的关键词时，这段设定会被注入提示词。",
                "keywords": ["开场", "四周"],
                "priority": 50,
                "category": "地点",
            },
        ]
    }


def _narrator_prompt(title: str) -> str:
    return f"""# 叙事者

你在主持一场文字冒险，作品名为《{title}》。

- 每回合根据「玩家行动 + 当前状态 + 最近事件」写一段 600~1200 字的中文叙事。
- 有画面感、有感官细节，让玩家知道发生了什么、环境如何变化。
- **不要报出任何具体数值**（生命、专注、信用点、伤害点数、属性值都不行）。
  可以说"你被撞得踉跄""伤口火辣辣地疼"，但不要说"你掉了 5 点生命"。
- 最后给出 2~4 个符合当前情境的选项；选项是行动描述，不是数值结算。
- 以当前注入状态为准，历史只作情节参考；写清已发生结果，不把心理、对白建议或计划写成已完成事件。
- 台词与叙述自然分段，不同说话者分别换行；不输出工具调用或状态栏。
"""


def _settler_prompt(title: str) -> str:
    return f"""你是《{title}》的独立结算器，不携带历史对话。
只依据本次完整叙述、当前全部状态、字段定义、合法目录和已收费用结算。
检查数值、状态说明、物品、标记、技能、衣物、动作和场景；无变化明确返回空变化。
依照运行时提供的真实上下限与工具契约，不自行发明字段或工具名，不重复技能费用。
每条变化给出本次正文证据，不把愿望、心理、否定或尚未发生的行动当作结果。
统一通过一次 settle_turn 提交完整草案，不单独调用内部操作，不续写正文，不输出全量状态。
无变化也完成八领域检查并提交空操作；无法确定的事项列入 uncertain 并保持原值，其他已确认变化照常提交。
普通新剧情事实用 record_fact，不冒充系统标记；已收技能费用不再扣。
重试时上一份草案尚未提交，保留有依据的其他变化，修正错误项后重交完整草案。"""


def _ui(title: str) -> dict:
    return {
        "title": title,
        "bars": ["hp", "focus"],
        "numbers": ["credits"],
        "badges": ["flag_started"],
        "skills_section": "技能",
        "options_section": "接下来",
    }


def _opening() -> dict:
    return {
        "id": "opening",
        "text": "你站在一扇半开的门前。门后很暗，隐约有风从里面吹出来。",
        "options": [
            {
                "id": "look_around",
                "label": "先看看四周",
                "action_text": "我先在门口停下，看清周围的环境。",
            },
            {
                "id": "move_on",
                "label": "推门进去",
                "action_text": "我推开门，走了进去。",
            },
        ],
    }


def _scenarios() -> dict:
    return {
        "scenarios": [
            {
                "id": "opening_look",
                "description": "自举包的第一个回合：文本行动不改变初始状态",
                "action": {"kind": "text", "text": "我先在门口停下，看清周围的环境。"},
                "expect": {"state": {"hp": 20}, "narrative_no_leaks": True},
            }
        ]
    }


def _readme(pack_id: str, title: str) -> str:
    return f"""# {title}

内容包 id：`{pack_id}`，由 `rpg-framework` 的 `rpg pack new` 生成。

## 目录

| 路径 | 作用 |
| --- | --- |
| `manifest.json` | 包身份、版本、年龄分级 |
| `state.json` | 状态字段（类型/范围/显示）+ 回合限额 |
| `vocab/` | 技能、物品、NPC、任务、标记、世界书 |
| `vocab/worldbook.json` | 世界书：常驻/关键词触发的世界观设定 |
| `prompts/pre.md` | 前置提示词（每回合拼在最前面的世界基调） |
| `prompts/narrator.md` | 叙事者提示词（玩家看到的文字） |
| `prompts/settler.md` | 结算器提示词（把叙事翻译成工具调用） |
| `ui/layout.json` | 驾驶舱里显示哪些字段 |
| `scenes/` | 场景与开场 |
| `tests/scenarios.json` | 金样场景（`pytest tests/test_golden.py` 会跑） |

## 下一步

1. 改 `scenes/opening.json` 写你的开场。
2. 在 `vocab/skills.json` 加技能；效果不要写公式，写在 `prompts/settler.md` 里。
3. 在 `state.json` 加你自己的数值字段，并在 `ui/layout.json` 里决定怎么显示。
4. 跑校验：`python -m rpg_content.cli lint <本目录>`。
5. 把第一个可玩场景写进 `tests/scenarios.json`，让它成为回归测试。
"""


def scaffold_files(pack_id: str, title: str, template: str = "minimal") -> dict[str, str]:
    """返回「相对路径 -> 文件内容」，测试可直接断言，不落盘。"""
    if template not in TEMPLATES:
        raise ValueError(f"未知模板 {template!r}，可选：{', '.join(TEMPLATES)}")
    if not PACK_ID_RE.match(pack_id):
        raise ValueError(
            f"包 id 不合法：{pack_id!r}（小写字母/数字/连字符，2-64 位，不以连字符开头）"
        )
    if not title.strip():
        raise ValueError("title 不能为空")

    def dump(data: object) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    return {
        "manifest.json": dump(_manifest(pack_id, title)),
        "state.json": dump(_state()),
        "vocab/skills.json": dump(_skills()),
        "vocab/items.json": dump({"items": []}),
        "vocab/npcs.json": dump({"npcs": []}),
        "vocab/quests.json": dump({"quests": []}),
        "vocab/flags.json": dump({"flags": []}),
        "vocab/worldbook.json": dump(_worldbook()),
        "prompts/pre.md": _pre_prompt(title),
        "prompts/narrator.md": _narrator_prompt(title),
        "prompts/settler.md": _settler_prompt(title),
        "ui/layout.json": dump(_ui(title)),
        "scenes/opening.json": dump(_opening()),
        "tests/scenarios.json": dump(_scenarios()),
        "README.md": _readme(pack_id, title),
    }


def scaffold_pack(
    target: str | Path,
    pack_id: str,
    title: str,
    template: str = "minimal",
    force: bool = False,
) -> list[Path]:
    """生成内容包目录；目标已存在且非空时默认拒绝（`force=True` 覆盖）。"""
    root = Path(target)
    files = scaffold_files(pack_id, title, template)
    if root.exists():
        existing = [p for p in root.iterdir()] if root.is_dir() else [root]
        if existing and not force:
            raise FileExistsError(f"目标目录已存在且非空：{root}（加 --force 覆盖）")
    written: list[Path] = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
