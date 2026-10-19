"""上下文组装器：每回合把框架真实状态注入 LLM。

这是"数值同步靠实时注入"的落点：LLM 读到的永远是当前真实值，
不是它自己上下文里记的旧值。
"""
from __future__ import annotations

from typing import Any

from rpg_core.contracts import ContentPack, Event
from rpg_core.scenes import (
    find_scene,
    format_scene_brief,
    scene_view,
    transitions_brief,
)


class ContextAssembler:
    def __init__(self, pack: ContentPack, recent_events: int = 8) -> None:
        self.pack = pack
        self.recent_events = recent_events

    # -- 摘要 ------------------------------------------------------------
    def state_snapshot(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        snap: dict[str, dict[str, Any]] = {}
        for field in self.pack.state.fields:
            if not field.llm_visible:
                continue
            snap[field.id] = {
                "label": field.label,
                "value": state.get(field.id),
                "type": field.type,
                "min": field.min,
                "max": field.max,
                "display": field.display,
            }
        return snap

    def state_brief(self, state: dict[str, Any]) -> str:
        lines = []
        for field in self.pack.state.fields:
            if not field.llm_visible:
                continue
            value = state.get(field.id)
            lines.append(f"- {field.label}：{value}")
        return "\n".join(lines)

    def vocab_brief(self) -> str:
        parts: list[str] = []
        if self.pack.skills:
            parts.append("技能：\n" + "\n".join(
                f"- {s.name}（{s.id}）：{s.description or s.effect_hint}"
                for s in self.pack.skills
            ))
        if self.pack.items:
            parts.append("物品：\n" + "\n".join(
                f"- {i.name}（{i.id}）：{i.description}" for i in self.pack.items
            ))
        if self.pack.npcs:
            parts.append("人物：\n" + "\n".join(
                f"- {n.name}（{n.id}）：{n.description}" for n in self.pack.npcs
            ))
        return "\n\n".join(parts)

    def recent_brief(self, events: list[Event]) -> str:
        from .state import cancelled_turns
        cancelled = cancelled_turns(events)
        recent = [e for e in events if e.turn not in cancelled and e.kind in ("narrative.generated", "tool.applied", "roll.resolved")]
        lines: list[str] = []
        for event in recent[-self.recent_events:]:
            if event.kind == "narrative.generated":
                text = str(event.payload.get("narrative", ""))[:200]
                lines.append(f"第{event.turn}回合：{text}")
            elif event.kind == "tool.applied":
                data = event.payload.get("data", {})
                lines.append(f"第{event.turn}回合结算：{event.payload.get('tool')} {data}")
            elif event.kind == "roll.resolved":
                lines.append(f"第{event.turn}回合掷骰：{event.payload}")
        return "\n".join(lines)

    # -- 世界书 ----------------------------------------------------------
    def select_lore(
        self,
        *,
        action: dict[str, Any] | None = None,
        recent_events: list[Event] | None = None,
        scene_text: str = "",
        max_entries: int = 8,
    ) -> list[dict[str, Any]]:
        """常驻条目 + 关键词命中条目（按优先级排序、最多 max_entries 条）。"""
        entries = [entry for entry in self.pack.worldbook if entry.enabled]
        if not entries:
            return []
        action = action or {}
        haystack_parts = [
            str(action.get("text") or ""),
            str(action.get("skill_id") or ""),
            str(action.get("target") or ""),
            scene_text or "",
        ]
        for event in (recent_events or [])[-6:]:
            if event.kind == "narrative.generated":
                haystack_parts.append(str(event.payload.get("narrative") or "")[:400])
        haystack = "\n".join(haystack_parts)

        selected: list[dict[str, Any]] = []
        for entry in entries:
            hit = entry.always_on or any(
                keyword and keyword in haystack for keyword in entry.keywords
            )
            if not hit:
                continue
            selected.append(
                {
                    "id": entry.id,
                    "title": entry.title,
                    "content": entry.content,
                    "always_on": entry.always_on,
                    "priority": entry.priority,
                    "category": entry.category,
                }
            )
        selected.sort(key=lambda item: (not item["always_on"], -item["priority"]))
        return selected[:max_entries]

    @staticmethod
    def lore_brief(lore: list[dict[str, Any]]) -> str:
        return "\n".join(f"- 【{item['title']}】{item['content']}" for item in lore)

    # -- prompt ----------------------------------------------------------
    def system_prompt(self) -> str:
        pre = self.pack.prompts.get("pre", "").strip()
        narrator = self.pack.prompts.get("narrator", "")
        parts = []
        if pre:
            parts.append(f"# 前置设定\n{pre}")
        parts.append(narrator)
        parts.append("你只负责叙事和选项。禁止调用状态修改工具，禁止输出状态栏或数值结算。")
        merged = "\n\n".join(part for part in parts if part)
        return merged.strip()

    def _wardrobe_snapshot(self, state: dict[str, Any]) -> dict:
        from .clothing import wardrobe_snapshot
        return wardrobe_snapshot(self.pack.wardrobe, state) if self.pack.wardrobe else {}

    def build_clothing(self, narrative: str, state: dict[str, Any], scene_id: str) -> dict:
        from .clothing import wardrobe_snapshot
        return {
            "phase": "clothing", "role": "settler", "narrative": narrative,
            "wardrobe": wardrobe_snapshot(self.pack.wardrobe, state),
            "scene": scene_view(find_scene(self.pack, scene_id) or self.pack.opening, state, self.pack),
            "allow_tools": True,
        }

    def build(
        self,
        *,
        turn: int,
        action: dict[str, Any],
        state: dict[str, Any],
        events: list[Event],
        tool_results: list[dict[str, Any]] | None = None,
        tool_exchanges: list[dict[str, Any]] | None = None,
        retry_reason: str | None = None,
        scene_id: str | None = None,
    ) -> dict[str, Any]:
        current_scene_id = scene_id or self.pack.opening.id
        scene = find_scene(self.pack, current_scene_id) or self.pack.opening
        lore = self.select_lore(
            action=action, recent_events=events, scene_text=scene.text
        )
        from .state import cancelled_turns
        cancelled=cancelled_turns(events)
        facts={e.payload["id"]:{"title":e.payload["title"],"value":e.payload["value"]} for e in events if e.kind=="story.fact" and e.turn not in cancelled}
        return {
            "facts": facts,
            "turn": turn,
            "role": "narrator",
            "phase": "narration",
            "allow_tools": False,
            "system_prompt": self.system_prompt(),
            "state": self.state_snapshot(state),
            "state_brief": self.state_brief(state),
            "wardrobe": self._wardrobe_snapshot(state),
            "vocab": self.vocab_brief(),
            "recent": self.recent_brief(events),
            "action": action,
            "tool_results": tool_results or [],
            # P3 续：规范工具回喂（assistant.tool_calls → role:"tool"）
            "tool_exchanges": tool_exchanges or [],
            "retry_reason": retry_reason,
            "prompt_versions": dict(self.pack.prompt_versions),
            # 场景推进：当前场景 + 可进入的相邻场景（含锁住原因）
            "scene_id": current_scene_id,
            "scene": scene_view(scene, state, self.pack),
            "scene_brief": format_scene_brief(self.pack, state, current_scene_id),
            "transitions": transitions_brief(self.pack, state, current_scene_id),
            # 世界书：命中关键词的设定条目（只作事实参考，不要逐字复述）
            "lore": lore,
            "lore_brief": self.lore_brief(lore),
        }
