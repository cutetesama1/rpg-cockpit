"""核心运行时：一个回合 = 一次 LLM 调用链 + 护栏 + 账本事务。

不变式：
- 状态只通过 tool.applied（LLM 结算）与 skill.used（框架技能消耗）事件改变；state = project(events)
- 回合原子性：任一护栏拒绝超出预算 → turn.rolled_back，投影自动回退
- 叙事不报数：检查器命中先重试，仍命中则擦除并记事件
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from rpg_gateway.roles import LlmRouter

from .contracts import ContentPack, Event, NarratorOutput, Option, SkillSpec
from .context import ContextAssembler
from .guardrails import GuardrailError, ToolExecutor
from .ledger import EventLedger
from .narrative import find_leaks, scrub
from .replay import verify as verify_replay
from .scenes import (
    current_scene_id,
    find_scene,
    scene_map,
    scene_view,
    unmet_conditions,
)
from .state import cancelled_turns, initial_state, inventory_from_events, project


@dataclass
class TurnResult:
    ok: bool
    turn: int
    narrative: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, int] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # 被框架忽略的重复扣费（技能已结算过同一字段），不算拒绝、不回滚回合
    ignored: list[str] = field(default_factory=list)
    scene_id: str = ""
    status: dict[str, Any] | None = None


class GameSession:
    def __init__(
        self,
        pack: ContentPack,
        router: LlmRouter,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.pack = pack
        self.router = router
        self.ledger = EventLedger()
        self.assembler = ContextAssembler(pack)
        self.executor = ToolExecutor(
            pack.state,
            {item.id for item in pack.items},
            {flag.id for flag in pack.flags},
            scene_map(pack),
            {skill.id for skill in pack.skills},
            wardrobe=pack.wardrobe,
            skill_catalog=pack.skill_catalog,
            catalog_mode=bool(pack.skill_selection.get("library_versions")),
            known_skills=pack.skills,
        )
        # 幂等：同一 patch_id 只应用一次（重试/回放安全）
        self._applied_patch_ids: set[str] = set()
        # SSE：每写一条事件就回调（失败不影响回合）
        self.on_event = on_event
        # Transient narrator previews never enter the event ledger or saved state.
        self.on_narrative: Callable[[dict[str, Any]], None] | None = None

    def _record(self, **kwargs: Any) -> None:
        """写账本并通知事件订阅者（SSE）。"""
        event = self.ledger.append(**kwargs)  # type: ignore[arg-type]
        if self.on_event is not None:
            try:
                self.on_event(event.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 - 订阅者异常不能影响游戏事务
                pass

    def _notify_narrative(self, turn: int, text: str, phase: str = "writing") -> None:
        if self.on_narrative is not None:
            try:
                self.on_narrative({"turn": turn, "text": scrub(text, self.pack.state), "phase": phase})
            except Exception:
                pass

    def _complete_narrator(self, role: str, request: dict, turn: int):
        if role != "narrator" or self.on_narrative is None:
            return self.router.complete(role, request)
        self._notify_narrative(turn, "", "waiting")
        stream = getattr(self.router, "stream", None)
        if callable(stream):
            response = stream(role, request, lambda text: self._notify_narrative(turn, text))
        else:
            response = self.router.complete(role, request)
        if response.narrator is not None and not response.tool_calls:
            self._notify_narrative(turn, response.narrator.narrative, "settling")
        else:
            self._notify_narrative(turn, "", "waiting")
        return response

    def _record_usage(
        self, turn: int, role: str, response: Any, totals: dict[str, float]
    ) -> None:
        """记一次 LLM 调用的 token/成本/延迟（调用即计费，失败重试也算）。"""
        usage = dict(getattr(response, "usage", None) or {})
        cost = float(getattr(response, "cost_usd", 0.0) or 0.0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            totals[key] = totals.get(key, 0) + int(usage.get(key) or 0)
        totals["cost_usd"] = round(float(totals.get("cost_usd", 0.0)) + cost, 6)
        totals["calls"] = int(totals.get("calls", 0)) + 1
        totals["latency_ms"] = round(
            float(totals.get("latency_ms", 0.0))
            + float(getattr(response, "latency_ms", 0.0) or 0.0),
            1,
        )
        self._record(
            turn=turn,
            kind="llm.usage",
            role=role,
            payload={
                "provider": getattr(response, "provider", ""),
                "model": (getattr(response, "model", "") or ""),
                "usage": usage,
                "cost_usd": cost,
                "latency_ms": float(getattr(response, "latency_ms", 0.0) or 0.0),
                "attempts": int(getattr(response, "attempts", 1) or 1),
            },
            model=(getattr(response, "model", "") or None),
        )

    def load_events(self, events: list[dict[str, Any]]) -> None:
        """从存档恢复账本（P4）：按 seq 装回事件，重建幂等集合。

        状态/背包/回合/场景都是账本投影，装回事件即恢复；不做任何削减或重置，
        因此读档不会降低可玩能力。
        """
        parsed = sorted(
            (Event.model_validate(row) for row in events), key=lambda e: e.seq
        )
        self.ledger = EventLedger()
        self.ledger.events = parsed
        self.ledger._seq = max((event.seq for event in parsed), default=0)
        self._applied_patch_ids = {
            str(event.payload.get("patch_id"))
            for event in parsed
            if event.kind == "tool.applied" and event.payload.get("patch_id")
        }
        self._refresh_executor_skills()

    def _refresh_executor_skills(self) -> None:
        """把「内容包内置 + 账本里已习得」的技能 id 同步给护栏（learn_skill 查重）。"""
        from .world_config import from_events
        self.pack=from_events(self.pack,self.ledger.events)
        self.assembler=ContextAssembler(self.pack)
        self.executor.schema=self.pack.state
        self.executor.fields=self.pack.state.by_id()
        self.executor.limits=self.pack.state.limits
        self.executor.skill_catalog={e.ref:e for e in self.pack.skill_catalog}
        self.executor.wardrobe=self.pack.wardrobe
        self.executor.scenes=scene_map(self.pack)
        self.executor.item_ids={i.id for i in self.pack.items}
        self.executor.flag_ids={f.id for f in self.pack.flags}
        self.executor.catalog_mode=bool(self.pack.skill_selection.get('library_versions'))
        self.executor.skill_ids = {skill.id for skill in self.pack.skills} | {
            skill.id for skill in self._learned_skills()
        }
        self.executor.skill_names = {skill.name.casefold() for skill in self.all_skills()}

    # -- 投影 ------------------------------------------------------------
    @property
    def state(self) -> dict[str, Any]:
        return project(self.ledger.events, self.pack.state)

    @property
    def inventory(self) -> dict[str, int]:
        return inventory_from_events(self.ledger.events)

    @property
    def turn(self) -> int:
        return self.ledger.last_committed_turn()

    def _next_turn(self) -> int:
        """回合号只增不减：撤销后新回合不能复用旧号，否则折叠无法区分。

        账本按 turn 号标记撤销，若撤销后复用同一号，新回合的 tool.applied 会被
        误判为已撤销（历史 bug）。这里取账本中出现过的最大回合号 + 1。
        """
        return max((event.turn for event in self.ledger.events), default=0) + 1

    def events_of(self, turn: int) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in self.ledger.for_turn(turn)]

    # -- 场景 ------------------------------------------------------------
    @property
    def scene_id(self) -> str:
        return current_scene_id(self.ledger.events, self.pack.opening.id)

    def _scene(self, scene_id: str | None = None):
        return find_scene(self.pack, scene_id or self.scene_id) or self.pack.opening

    def scene_status(self) -> dict[str, Any]:
        """驾驶舱/API 用的当前场景视图（含选项可用性与进入条件）。"""
        scene = self._scene()
        view = scene_view(scene, self.state, self.pack)
        lock_reasons = unmet_conditions(scene.requires, self.state, self.pack)
        return {
            **view,
            "requires_met": not lock_reasons,
            "blocked_reason": "；".join(lock_reasons) or None,
        }

    def _record_scene_entered(
        self,
        turn: int,
        from_scene: str,
        to_scene: str,
        reason: str = "",
        role: str | None = None,
    ) -> None:
        self._record(
            turn=turn,
            kind="scene.entered",
            role=role,
            payload={
                "scene_id": to_scene,
                "from_scene": from_scene,
                "title": (find_scene(self.pack, to_scene).title if find_scene(self.pack, to_scene) else ""),
                "reason": reason,
            },
        )

    # -- 技能经济：冷却 / 消耗（框架权威，不走 LLM 工具） -----------------
    def _last_skill_turns(self) -> dict[str, int]:
        cancelled = cancelled_turns(self.ledger.events)
        used: dict[str, int] = {}
        for event in sorted(self.ledger.events, key=lambda e: e.seq):
            if event.kind != "skill.used" or event.turn in cancelled:
                continue
            skill_id = event.payload.get("skill_id")
            if skill_id:
                used[str(skill_id)] = event.turn
        return used

    def _learned_skills(self) -> list[SkillSpec]:
        """从账本投影出本局习得的技能（skill.learned，撤销过的回合不算）。"""
        cancelled = cancelled_turns(self.ledger.events)
        learned: dict[str, SkillSpec] = {}
        for event in sorted(self.ledger.events, key=lambda e: e.seq):
            if event.kind != "skill.learned" or event.turn in cancelled:
                continue
            raw = event.payload.get("skill")
            if not isinstance(raw, dict):
                continue
            try:
                skill = SkillSpec.model_validate(raw)
            except Exception:  # noqa: BLE001 - 坏存档里的坏技能条目不能拖垮整局
                continue
            current = next((e.skill for e in self.pack.skill_catalog if e.skill.id == skill.id),None)
            learned[skill.id] = current or skill
        return list(learned.values())

    def all_skills(self) -> list[SkillSpec]:
        """内容包内置技能 + 本局习得技能（同名 id 以内置为准）。"""
        learned = self._learned_skills()
        seen = {skill.id for skill in self.pack.skills}
        return [*self.pack.skills, *[s for s in learned if s.id not in seen]]

    def skill_state(self, skill: SkillSpec) -> dict[str, Any]:
        state = self.state
        last_turn = self._last_skill_turns().get(skill.id)
        remaining = 0
        if last_turn is not None and skill.cooldown > 0:
            remaining = max(0, last_turn + skill.cooldown - self.turn)
        short_fields: list[str] = []
        for field_id, amount in skill.cost.items():
            current = state.get(field_id, 0)
            if not isinstance(current, (int, float)) or current < amount:
                short_fields.append(field_id)
        reasons: list[str] = []
        if remaining > 0:
            reasons.append(f"冷却中，还需 {remaining} 回合")
        if short_fields:
            reasons.append(f"{'/'.join(short_fields)} 不足")
        source = next((entry for entry in self.pack.skill_catalog if entry.skill.id == skill.id), None)
        return {
            **skill.model_dump(mode="json"),
            **({"source_ref": source.ref, "kind": source.kind, "tier": source.tier, "school": source.school} if source else {}),
            "available": not reasons,
            "cooldown_remaining": remaining,
            "affordable": not short_fields,
            "blocked_reason": "；".join(reasons) or None,
        }

    def skill_states(self) -> list[dict[str, Any]]:
        return [self.skill_state(skill) for skill in self.all_skills()]

    @staticmethod
    def _clamp_cost(value: float, field_def: Any) -> Any:
        lowest = field_def.min if field_def.min is not None else float("-inf")
        highest = field_def.max if field_def.max is not None else float("inf")
        value = max(lowest, min(highest, value))
        return int(round(value)) if field_def.type == "int" else value

    def _append_skill_used(
        self, turn: int, skill: SkillSpec, working: dict[str, Any]
    ) -> None:
        """框架结算技能消耗：写 skill.used 事件（可回放、可撤销）。"""
        changes: dict[str, dict[str, Any]] = {}
        for field_id, amount in skill.cost.items():
            field_def = self.pack.state.by_id().get(field_id)
            if field_def is None:
                continue
            before = working.get(field_id, field_def.default)
            after = self._clamp_cost(float(before) - float(amount), field_def)
            changes[field_id] = {"before": before, "after": after}
            working[field_id] = after
        self._record(
            turn=turn,
            kind="skill.used",
            actor="player",
            payload={
                "skill_id": skill.id,
                "name": skill.name,
                "cost": dict(skill.cost),
                "changes": changes,
            },
        )

    # -- 回合 ------------------------------------------------------------
    def _guard_fail(self, error: str) -> TurnResult:
        """不产生任何事件的快捷失败（未知/不可用选项等）。"""
        return TurnResult(
            ok=False,
            turn=self.turn,
            state=self.state,
            inventory=self.inventory,
            errors=[error],
            scene_id=self.scene_id,
        )

    def _resolve_turn_skills(self, action: dict[str, Any]) -> tuple[list[SkillSpec], str | None]:
        """解析本回合要一起结算的技能（单技能旧格式或勾选列表），并做整体校验。

        勾选的技能与输入内容属于同一回合：全部校验通过才一起扣费；
        任何一项未知/冷却中/累计消耗不够，整回合直接拒绝，不产生事件。
        这里刻意不设“每回合最多几个技能”的上限：只要资源和冷却允许就能选。
        """
        skills: list[SkillSpec] = []
        known = self.all_skills()
        if action.get("kind") == "skill":
            skill_id = str(action.get("skill_id") or "")
            found = next((s for s in known if s.id == skill_id), None)
            if found is None:
                return [], f"未知技能：{skill_id}"
            skills = [found]
        else:
            raw = action.get("skills") or []
            if not isinstance(raw, list):
                return [], "技能列表格式不对：skills 应该是数组"
            seen: set[str] = set()
            for item in raw:
                if isinstance(item, dict):
                    skill_id = str(item.get("skill_id") or "")
                else:
                    skill_id = str(item or "")
                if not skill_id or skill_id in seen:
                    continue
                seen.add(skill_id)
                found = next((s for s in known if s.id == skill_id), None)
                if found is None:
                    return [], f"未知技能：{skill_id}"
                skills.append(found)
        if not skills:
            return [], None

        simulated = dict(self.state)
        for candidate in skills:
            info = self.skill_state(candidate)
            if not info["available"]:
                reason = info["blocked_reason"] or "技能当前不可用"
                return [], f"技能「{candidate.name}」当前不可用：{reason}"
            for field_id, amount in candidate.cost.items():
                current = simulated.get(field_id)
                if not isinstance(current, (int, float)):
                    continue
                if float(current) < float(amount):
                    return [], (
                        f"技能「{candidate.name}」需要 {field_id} {amount:g}，"
                        f"本回合一起结算后只剩 {current:g}（勾选的技能会累计扣费）"
                    )
                simulated[field_id] = float(current) - float(amount)
        return skills, None

    def _with_skill_catalog(self, request: dict, chosen: list[SkillSpec] | None = None) -> dict:
        if not self.pack.skill_selection.get("library_versions"):
            return request
        from .skill_catalog import candidates, known_refs
        known = known_refs(self.pack.skill_catalog, self.all_skills())
        text = str((request.get("action") or {}).get("text") or "")
        nearby = candidates([e for e in self.pack.skill_catalog if e.ref not in known], text)
        request["catalog_mode"] = True
        request["catalog_candidates"] = [{"ref":e.ref,"name":e.skill.name,"kind":e.kind,"tier":e.tier,"school":e.school,"prerequisites":e.prerequisites,"known":e.ref in known} for e in nearby]
        ids = {skill.id for skill in (chosen or [])}
        request["preset_instructions"] = [{"ref":e.ref,"name":e.skill.name,"action_text":e.skill.action_text,"instruction":e.instruction,"paid_cost":e.skill.cost} for e in self.pack.skill_catalog if e.skill.id in ids]
        return request

    def submit_action(self, action: dict[str, Any], request_id: str | None = None) -> TurnResult:
        if request_id:
            started=next((e for e in self.ledger.events if e.kind=='turn.started' and e.payload.get('request_id')==request_id),None)
            if started is not None:
                cancelled=cancelled_turns(self.ledger.events)
                if started.turn in cancelled:return self._guard_fail('此请求已回滚，请重新发送新请求')
                event=next((e for e in self.ledger.events if e.turn==started.turn and e.kind=='narrative.generated'),None)
                if event is not None:
                    return TurnResult(ok=True,turn=started.turn,narrative=event.payload['narrative'],options=event.payload.get('options',[]),state=self.state,inventory=self.inventory,events=self.events_of(started.turn),scene_id=self.scene_id,status=self.status())
                return self._guard_fail('此请求尚未完成，请稍后读取当前状态')
        skills, skills_error = self._resolve_turn_skills(action)
        if skills_error:
            return self._guard_fail(skills_error)
        self.executor.set_skill_payments({})

        # 作者选项：带 next_scene 的选项由框架直接转场（仍需过条件），
        # 其余选项只是把 action_text 交给 LLM，由叙事角色自由发挥。
        scene_now = self._scene()
        option_transition: str | None = None
        if action.get("kind") == "option":
            option_id = str(action.get("option_id") or "")
            option = next((o for o in scene_now.options if o.id == option_id), None)
            if option is None:
                return self._guard_fail(f"未知选项：{option_id}")
            reasons = unmet_conditions(option.requires, self.state, self.pack)
            if reasons:
                return self._guard_fail(f"选项当前不可用：{'；'.join(reasons)}")
            if option.next_scene:
                target = find_scene(self.pack, option.next_scene)
                if target is None:
                    return self._guard_fail(f"选项指向未声明场景：{option.next_scene}")
                reasons = unmet_conditions(target.requires, self.state, self.pack)
                if reasons:
                    return self._guard_fail(
                        f"无法进入「{target.title or target.id}」：{'；'.join(reasons)}"
                    )
                option_transition = target.id

        turn = self._next_turn()
        limits = self.pack.state.limits
        display_text = ""
        if action.get("kind") == "option":
            display_text = option.action_text or option.label
        elif action.get("kind") == "skill" and skills:
            display_text = f"使用技能：{skills[0].name}"
        self._record(
            turn=turn,
            kind="turn.started",
            actor="player",
            payload={"action": action, "request_id":request_id, **({"display_text": display_text} if display_text else {})},
        )
        working = dict(self.state)
        scene_used = scene_now.id
        if option_transition is not None and option_transition != scene_used:
            self._record_scene_entered(
                turn,
                scene_used,
                option_transition,
                f"option:{action.get('option_id')}",
            )
            scene_used = option_transition
        for chosen in skills:
            self._append_skill_used(turn, chosen, working)
        # 本回合技能扣费汇总：既告诉模型「这些已经扣过」，也让工具层拒绝重复扣同一笔
        payments: dict[str, float] = {}
        for chosen in skills:
            for field_id, amount in chosen.cost.items():
                payments[field_id] = payments.get(field_id, 0.0) + float(amount)
        payments_info: list[dict[str, Any]] = []
        if payments:
            fields_by_id = self.pack.state.by_id()
            for field_id, amount in payments.items():
                field_def = fields_by_id.get(field_id)
                payments_info.append(
                    {
                        "field": field_id,
                        "label": field_def.label if field_def is not None else field_id,
                        "amount": amount,
                        "remaining": working.get(
                            field_id, field_def.default if field_def is not None else None
                        ),
                    }
                )
        self.executor.set_skill_payments(payments)
        delta_used: dict[str, float] = {}
        tool_results: list[dict[str, Any]] = []
        errors: list[str] = []
        rejections: list[str] = []
        ignored: list[str] = []
        narrative: NarratorOutput | None = None
        rejected = 0
        model_used = ""
        tool_exchanges: list[dict[str, Any]] = []
        usage_totals: dict[str, float] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "calls": 0,
            "latency_ms": 0.0,
        }

        request = self._with_skill_catalog(self.assembler.build(
            turn=turn, action=action, state=working, events=self.ledger.events, scene_id=scene_used), skills)
        request['payments'] = payments_info
        try:
            response = self._complete_narrator('narrator', request, turn)
            self._record_usage(turn, 'narrator', response, usage_totals)
            if response.tool_calls:
                return self._rollback(turn, ['叙事阶段禁止状态工具调用；请使用纯叙事提示词'])
            narrative = response.narrator
            model_used = response.model
            if narrative is None or not narrative.narrative.strip():
                return self._rollback(turn, ['叙事阶段没有有效正文'])
        except Exception as exc:
            return self._rollback(turn, [f'叙事调用失败：{exc}'])

        # 叙事数值检查：先重试，仍命中则擦除
        leaks = (
            find_leaks(narrative.narrative, self.pack.state)
            if limits.narrative_number_check
            else []
        )
        if leaks:
            retry_request = self.assembler.build(
                turn=turn,
                action=action,
                state=working,
                events=self.ledger.events,
                tool_results=tool_results,
                tool_exchanges=tool_exchanges,
                retry_reason="numbers",
                scene_id=scene_used,
            )
            retry_request = self._with_skill_catalog(retry_request, skills)
            retry = None
            try:
                retry = self._complete_narrator("narrator", retry_request, turn)
            except Exception:  # noqa: BLE001 - 重试失败就退回本地擦除，不让整回合白费
                retry = None
            if retry is not None:
                self._record_usage(turn, "narrator", retry, usage_totals)
            if retry is not None and retry.narrator and not find_leaks(
                retry.narrator.narrative, self.pack.state
            ):
                narrative = retry.narrator
                self._record(
                    turn=turn,
                    kind="narrative.checked",
                    payload={"leaks": leaks, "action": "regenerated"},
                )
            else:
                narrative = NarratorOutput(
                    narrative=scrub(narrative.narrative, self.pack.state),
                    options=narrative.options,
                    status=narrative.status,
                )
                self._record(
                    turn=turn,
                    kind="narrative.checked",
                    payload={"leaks": leaks, "action": "scrubbed"},
                )
            leaks = []

        self._notify_narrative(turn, narrative.narrative, "settling")
        from .settlement import settle
        settlement_error, working, scene_used, settled_status = settle(self, turn, narrative.narrative, working, skills, scene_used, usage_totals)
        if settlement_error:
            return self._rollback(turn, [settlement_error])
        ignored=[str(e.payload.get("error")) for e in self.ledger.for_turn(turn) if e.kind=="tool.rejected" and e.payload.get("ignored")]
        ignored += ["待确认，相关状态保持原值：" + str(note)
                    for e in self.ledger.for_turn(turn) if e.kind=='settlement.warning'
                    for note in e.payload.get('uncertain',[])]

        self._record(
            turn=turn,
            kind="narrative.generated",
            role="narrator",
            payload={
                "narrative": narrative.narrative,
                "options": [o.model_dump(mode="json") for o in narrative.options],
                "status": (
                    settled_status
                ),
                "prompt_versions": dict(self.pack.prompt_versions),
                "model": model_used or "unknown",
                "usage": dict(usage_totals),
            },
            prompt_version=self.pack.prompt_versions.get("narrator"),
            model=model_used,
        )
        self._record(
            turn=turn,
            kind="turn.committed",
            payload={"changes_applied": len(self.ledger.for_turn(turn)), "scene": scene_used},
        )

        return TurnResult(
            ok=True,
            turn=turn,
            narrative=narrative.narrative,
            options=[o.model_dump(mode="json") for o in narrative.options],
            state=self.state,
            inventory=self.inventory,
            events=self.events_of(turn),
            leaks=leaks,
            ignored=ignored,
            scene_id=scene_used,
            status=self.status(),
        )

    # -- 开局叙述（AI 生成，不改状态、不占回合） ---------------------------
    def opening_event(self) -> Event | None:
        for event in reversed(self.ledger.events):
            if event.kind == "narrative.generated" and event.payload.get("opening"):
                return event
        return None

    def narrative_status(self) -> dict[str, Any] | None:
        """最近一次有效叙事附带的角色状态（被撤销的回合跳过）。"""
        cancelled = cancelled_turns(self.ledger.events)
        result = None
        for event in self.ledger.events:
            if event.turn in cancelled or event.kind not in ('narrative.generated', 'status.updated'):
                continue
            patch = event.payload.get('status')
            if patch:
                result = {**(result or {}), **patch}
        if result is not None and not result.get("notes"):result.pop("notes",None)
        return result

    def start_opening(self) -> dict[str, Any]:
        """让叙事模型生成开局叙述；只写一条 narrative.generated(turn=0) 事件。

        幂等：已经生成过就直接返回旧的那条，不重复计费。
        """
        existing = self.opening_event()
        if existing is not None:
            return {
                "ok": True,
                "generated": False,
                "narrative": str(existing.payload.get("narrative") or ""),
                "options": list(existing.payload.get("options") or []),
            }
        request = self.assembler.build(
            turn=0,
            action={"kind": "text", "text": ""},
            state=self.state,
            events=self.ledger.events,
            scene_id=self.scene_id,
        )
        request = self._with_skill_catalog(request)
        request["opening"] = True
        # 开场不需要结算工具：关掉 tools，模型只能回 JSON 叙事
        request["allow_tools"] = False
        try:
            response = self._complete_narrator("narrator", request, 0)
        except Exception as exc:  # noqa: BLE001 - 网络/网关错误转成可展示的错误
            self._notify_narrative(0, "", "waiting")
            return {"ok": False, "generated": False, "error": f"LLM 调用失败：{exc}"}
        totals: dict[str, float] = {"calls": 0}
        self._record_usage(0, "narrator", response, totals)
        if response.tool_calls:
            return {"ok":False,"generated":False,"error":"开场叙事阶段禁止工具调用"}
        narrator = response.narrator
        if narrator is None or not narrator.narrative.strip():
            return {
                "ok": False,
                "generated": False,
                "error": "模型没有返回叙事文本，请重试（或检查模型设置）",
            }
        narrative = scrub(narrator.narrative, self.pack.state)
        self._notify_narrative(0, narrative, "settling")
        from .settlement import settle
        error, _, _, settled_status = settle(self, 0, narrative, dict(self.state), [], self.scene_id, totals)
        if error:
            self._notify_narrative(0, '', 'waiting')
            return {'ok':False, 'generated':False, 'error':error}
        options = [o.model_dump(mode="json") for o in narrator.options]
        model_used = getattr(response, "model", "") or ""
        self._record(
            turn=0,
            kind="narrative.generated",
            role="narrator",
            payload={
                "narrative": narrative,
                "options": options,
                "opening": True,
                "status": (
                    settled_status
                ),
                "prompt_versions": dict(self.pack.prompt_versions),
                "model": model_used or "unknown",
            },
            prompt_version=self.pack.prompt_versions.get("narrator"),
            model=model_used,
        )
        return {"ok": True, "generated": True, "narrative": narrative, "options": options}

    def _rollback(self, turn: int, errors: list[str]) -> TurnResult:
        self._notify_narrative(turn, "", "waiting")
        self._record(
            turn=turn,
            kind="turn.rolled_back",
            payload={"reason": "guardrail_or_llm_failure", "errors": errors},
        )
        self._refresh_executor_skills()
        return TurnResult(
            ok=False,
            turn=turn,
            state=self.state,
            inventory=self.inventory,
            events=self.events_of(turn),
            errors=errors,
            scene_id=self.scene_id,
        )

    # -- 撤销与校验 -------------------------------------------------------
    def undo(self) -> dict[str, Any]:
        turn = self.ledger.last_committed_turn()
        if turn == 0:
            return {"ok": False, "error": "没有可撤销的回合", **self.status()}
        self._record(
            turn=turn,
            kind="turn.rolled_back",
            payload={"reason": "undo"},
        )
        self._refresh_executor_skills()
        return {"ok": True, "undone_turn": turn, **self.status()}

    # -- 调试台（本地测试用：写账本事件，可回放、可撤销、可存档） ---------
    DEBUG_TOOL = "debug.set_state"

    def debug_catalog(self) -> dict[str, Any]:
        """调试台需要的全部素材：字段定义、物品、技能、场景、立绘概要、最近事件。"""
        sprite = self.pack.sprites
        learned = {skill.id for skill in self._learned_skills()}
        scenes = [
            {"id": self.pack.opening.id, "title": self.pack.opening.title, "opening": True}
        ]
        scenes += [
            {"id": scene.id, "title": scene.title, "opening": False}
            for scene in self.pack.scenes
            if scene.id != self.pack.opening.id
        ]
        skill_rows = [
            {
                "id": skill.id,
                "name": skill.name,
                "cost": dict(skill.cost),
                "cooldown": skill.cooldown,
                "description": skill.description,
                "category": skill.category,
                "learned": skill.id in learned,
            }
            for skill in self.pack.skills
        ]
        skill_rows += [
            {
                "id": skill.id,
                "name": skill.name,
                "cost": dict(skill.cost),
                "cooldown": skill.cooldown,
                "description": skill.description,
                "category": skill.category,
                "learned": True,
            }
            for skill in self._learned_skills()
            if skill.id not in {row["id"] for row in skill_rows}
        ]
        return {
            "pack": self.pack.manifest.model_dump(mode="json"),
            "turn": self.turn,
            "scene_id": self.scene_id,
            "state": self.state,
            "inventory": self.inventory,
            "fields": [field.model_dump(mode="json") for field in self.pack.state.fields],
            "limits": self.pack.state.limits.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in self.pack.items],
            "flags": [flag.model_dump(mode="json") for flag in self.pack.flags],
            "skills": skill_rows,
            "scenes": scenes,
            "sprite": (
                {
                    "frames": sprite.frames,
                    "fps": sprite.fps,
                    "layers": len(sprite.layers),
                    "views": sorted((sprite.views or {}).keys()),
                    "poses": sorted((sprite.poses or {}).keys()),
                    "crop": sprite.crop.model_dump(mode="json"),
                }
                if sprite is not None
                else None
            ),
            "events": [event.model_dump(mode="json") for event in self.ledger.events[-80:]],
        }

    @staticmethod
    def _debug_coerce(field: Any, value: Any) -> Any:
        if field.enum_values:
            text = str(value)
            if text not in field.enum_values:
                raise ValueError(f"{field.id} 只能取这些值：{', '.join(field.enum_values[:12])}…")
            return text
        if field.type == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if field.type in {"int", "float"}:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field.id} 需要数字：{value!r}") from exc
            if field.min is not None:
                number = max(field.min, number)
            if field.max is not None:
                number = min(field.max, number)
            return int(round(number)) if field.type == "int" else float(number)
        if isinstance(value, (dict, list)):
            return value
        return str(value)

    def debug_set_state(self, changes: dict[str, Any]) -> dict[str, Any]:
        """直接改任意状态字段（写一条 tool.applied，投影照常生效）。"""
        fields = self.pack.state.by_id()
        current = self.state
        folded: dict[str, dict[str, Any]] = {}
        for raw_id, value in (changes or {}).items():
            field_id = str(raw_id)
            field = fields.get(field_id)
            if field is None:
                raise ValueError(f"内容包没有声明字段 {field_id}")
            folded[field_id] = {
                "field": field_id,
                "before": current.get(field_id),
                "after": self._debug_coerce(field, value),
            }
        if not folded:
            return {"ok": True, "changed": 0, "turn": self.turn, "state": current}
        # 调试改动单独占一个新回合：既不影响正在进行的回合，也能用「撤销上一回合」整块回退
        turn = self._next_turn()
        self._record(
            turn=turn,
            kind="tool.applied",
            actor="debug",
            payload={"tool": self.DEBUG_TOOL, "data": {}, "changes": folded},
        )
        self._record(turn=turn, kind="turn.committed", actor="debug", payload={"debug": True})
        return {"ok": True, "changed": len(folded), "turn": turn, "state": self.state}

    def debug_set_inventory(self, item_id: str, count: int) -> dict[str, Any]:
        """把某个物品数量设成 count（正负差额都写成 add_item，投影按增量累计）。"""
        if item_id not in {item.id for item in self.pack.items}:
            raise ValueError(f"内容包没有物品 {item_id}")
        current = int(self.inventory.get(item_id, 0))
        target = max(0, int(count))
        delta = target - current
        if delta == 0:
            return {"ok": True, "changed": 0, "inventory": self.inventory}
        turn = self._next_turn()
        self._record(
            turn=turn,
            kind="tool.applied",
            actor="debug",
            payload={
                "tool": "add_item",
                "data": {"item_id": item_id, "count": delta, "reason": "debug"},
                "changes": {},
            },
        )
        self._record(turn=turn, kind="turn.committed", actor="debug", payload={"debug": True})
        return {
            "ok": True,
            "changed": 1,
            "delta": delta,
            "inventory": self.inventory,
        }

    def debug_jump_scene(self, scene_id: str) -> dict[str, Any]:
        """跳到指定场景（写 scene.entered，和正常转场同一条投影链）。"""
        target = find_scene(self.pack, scene_id)
        if target is None:
            raise ValueError(f"内容包没有场景 {scene_id}")
        current = self.scene_id
        if scene_id == current:
            return {"ok": True, "changed": 0, "scene_id": current}
        turn = self._next_turn()
        self._record_scene_entered(turn, current, scene_id, "debug", role="debug")
        self._record(turn=turn, kind="turn.committed", actor="debug", payload={"debug": True})
        return {"ok": True, "changed": 1, "scene_id": self.scene_id, "title": target.title}

    def debug_learn_skill(self, skill_id: str) -> dict[str, Any]:
        """把内容包里的技能直接记成已习得（写 skill.learned）。"""
        if skill_id in {skill.id for skill in self._learned_skills()}:
            return {"ok": True, "changed": 0, "skills": self.skill_states()}
        skill = next((item for item in self.pack.skills if item.id == skill_id), None)
        if skill is None:
            raise ValueError(f"内容包没有技能 {skill_id}")
        turn = self._next_turn()
        self._record(
            turn=turn,
            kind="skill.learned",
            actor="debug",
            payload={"skill": skill.model_dump(mode="json"), "reason": "debug"},
        )
        self._record(turn=turn, kind="turn.committed", actor="debug", payload={"debug": True})
        self._refresh_executor_skills()
        return {"ok": True, "changed": 1, "skills": self.skill_states()}

    def debug_reset_state(self) -> dict[str, Any]:
        """所有字段恢复内容包默认值（等价于一次性改回 default）。"""
        defaults = {field.id: field.default for field in self.pack.state.fields}
        return self.debug_set_state(defaults)

    def verify(self) -> dict[str, Any]:
        report = verify_replay(self.state, self.ledger.events, self.pack.state)
        live_scene = self.scene_id
        replayed_scene = current_scene_id(self.ledger.events, self.pack.opening.id)
        report["scene"] = {"live": live_scene, "replay": replayed_scene}
        report["equal"] = bool(report["equal"]) and live_scene == replayed_scene
        return report

    # -- 序列化 -----------------------------------------------------------
    def options(self) -> list[dict[str, Any]]:
        if self.turn == 0:
            opening = self.opening_event()
            if opening is not None and opening.payload.get("options"):
                return list(opening.payload.get("options") or [])
            return [o.model_dump(mode="json") for o in self._scene().options]
        for event in reversed(self.ledger.events):
            if event.kind == "narrative.generated" and event.turn == self.turn:
                return list(event.payload.get("options", []))
        return []

    def appearance_revision(self) -> str:
        import hashlib,json
        data={'sheet':self.pack.sprites.model_dump(mode='json') if self.pack.sprites else None,'resource_bindings':self.pack.state.resource_bindings}
        return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]

    def status(self) -> dict[str, Any]:
        from .settlement import facts
        return {
            "turn": self.turn,
            "appearance_revision": self.appearance_revision(),
            "story_facts": facts(self),
            "state": self.state,
            "inventory": self.inventory,
            "scene": self.scene_status(),
            "options": self.options(),
            "opening": self.pack.opening.model_dump(mode="json"),
            "opening_generated": self.opening_event() is not None,
            "narrative_status": self.narrative_status(),
            "events": self.ledger.to_dicts(),
            "replay": self.verify(),
            "fields": [f.model_dump(mode="json") for f in self.pack.state.fields],
            "layout": self.pack.ui.model_dump(mode="json"),
            "skills": self.skill_states(),
            "pack": self.pack.manifest.model_dump(mode="json"),
            "llm": self.llm_status(),
            "usage": self.usage_status(),
        }

    def usage_status(self) -> dict[str, Any]:
        """从账本折叠 token/成本（含回滚回合与重试——调用即计费）。"""
        totals: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "calls": 0,
            "latency_ms": 0.0,
        }
        for event in self.ledger.events:
            if event.kind != "llm.usage":
                continue
            payload = event.payload or {}
            usage = payload.get("usage") or {}
            totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            totals["total_tokens"] += int(usage.get("total_tokens") or 0)
            totals["cost_usd"] = round(
                float(totals["cost_usd"]) + float(payload.get("cost_usd") or 0.0), 6
            )
            totals["calls"] += 1
            totals["latency_ms"] = round(
                float(totals["latency_ms"]) + float(payload.get("latency_ms") or 0.0), 1
            )
        return totals

    def llm_status(self) -> dict[str, Any]:
        """当前模型路由摘要，给驾驶舱顶栏/设置面板用。

        除 provider/model 外还暴露 preset 与 reasoning_effort，
        驾驶舱据此在叙事栏上方显示「当前模型 / 思考强度」。
        """
        from rpg_gateway.catalog import get_preset

        config = self.router.config
        roles: dict[str, Any] = {}
        for role in ("narrator", "settler"):
            effective = "narrator" if role == "settler" and not config.separated else role
            profile = getattr(config, effective)
            provider = self.router.providers.get(profile.provider)
            preset = str(getattr(provider, "preset", "") or "")
            effort = str(getattr(provider, "reasoning_effort", "") or "")
            preset_info = get_preset(preset) if preset else None
            label = str((preset_info or {}).get("label") or "")
            if not label:
                label = "脚本假模型" if profile.provider == "scripted" else profile.provider
            roles[role] = {
                "provider": profile.provider,
                "model": profile.model or str(getattr(provider, "model", "") or ""),
                "temperature": profile.temperature,
                "preset": preset,
                "preset_label": label,
                "reasoning_effort": effort,
            }
        return {"separated": config.separated, "roles": roles}
