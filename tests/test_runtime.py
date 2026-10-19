"""运行时测试：回合事务、事件、撤销、回放、泄漏重试、拒绝回滚。"""
from __future__ import annotations

import pytest

from conftest import StubProvider, make_session, say, tool

from rpg_core.contracts import NarratorStatus, ToolCall
from rpg_gateway import LlmResponse, ScriptedProvider


def learn_skill(**args) -> LlmResponse:
    """构造一个 learn_skill 工具调用（conftest.tool 的 id 参数与技能 id 同名，这里直接构造）。"""
    return LlmResponse(tool_calls=[ToolCall(id="tc_learn", name="learn_skill", args=args)])



def test_smash_applies_damage_and_events(pack):
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "skill", "skill_id": "smash"})

    assert result.ok is True
    assert result.state["hp"] == 13
    kinds = [e["kind"] for e in result.events]
    assert kinds[0] == "turn.started"
    assert kinds[-1] == "turn.committed"
    assert "roll.resolved" in kinds
    assert kinds.count("roll.resolved") == 1
    assert kinds.count("tool.applied") == 1  # roll 不再重复记 tool.applied
    assert "narrative.generated" in kinds
    assert len(result.events) >= 5
    assert result.leaks == []
    assert session.verify()["equal"] is True


def test_undo_restores_state(pack):
    session = make_session(ScriptedProvider())
    session.submit_action({"kind": "skill", "skill_id": "smash"})
    assert session.state["hp"] == 13

    undo = session.undo()
    assert undo["ok"] is True
    assert undo["state"]["hp"] == 20
    assert session.turn == 0
    assert session.verify()["equal"] is True


def test_action_after_undo_uses_fresh_turn_id(pack):
    """撤销后新回合不能复用旧回合号，否则折叠会把新事件当成已撤销。"""
    session = make_session(ScriptedProvider())
    session.submit_action({"kind": "skill", "skill_id": "smash"})
    assert session.turn == 1
    session.undo()
    assert session.turn == 0

    result = session.submit_action({"kind": "skill", "skill_id": "smash"})
    assert result.ok is True
    assert session.turn == 2  # 回合 1 已撤销，新回合拿 2 而不是 1
    assert session.state["hp"] == 13
    assert session.verify()["equal"] is True


def test_multiple_turns_replay_equals_live(pack):
    session = make_session(ScriptedProvider())
    session.submit_action({"kind": "skill", "skill_id": "smash"})
    session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    assert session.state["hp"] == 18
    verification = session.verify()
    assert verification["equal"] is True
    assert verification["diff"] == {}


def test_first_aid_never_exceeds_max(pack):
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    assert result.ok is True
    assert result.state["hp"] == 20


def test_observe_has_no_tool_effects(pack):
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "skill", "skill_id": "observe"})
    assert result.ok is True
    assert result.state == pack.state.defaults()
    assert not [e for e in result.events if e["kind"] == "tool.applied"]


def test_numeric_leak_triggers_regeneration(pack):
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "text", "text": "报数看看"})
    assert result.ok is True
    assert "生命 7" not in result.narrative
    assert result.leaks == []
    checked = [e for e in result.events if e["kind"] == "narrative.checked"]
    assert checked and checked[0]["payload"]["action"] == "regenerated"


def test_leak_scrubbed_when_retry_also_leaks(pack):
    provider = StubProvider([say("你受了伤，生命 7，体力 3。")])
    session = make_session(provider)
    result = session.submit_action({"kind": "text", "text": "随便走走"})
    assert result.ok is True
    assert "7" not in result.narrative and "3" not in result.narrative
    checked = [e for e in result.events if e["kind"] == "narrative.checked"]
    assert checked and checked[0]["payload"]["action"] == "scrubbed"


def test_guardrail_rejection_rolls_back_whole_turn(pack):
    provider = StubProvider([tool("damage", amount=30), say()])
    session = make_session(provider)
    result = session.submit_action({"kind": "skill", "skill_id": "smash"})

    assert result.ok is False
    assert session.state["hp"] == 20
    assert session.turn == 0
    kinds = [e["kind"] for e in result.events]
    assert "tool.rejected" in kinds
    assert "turn.rolled_back" in kinds
    assert "turn.committed" not in kinds
    assert any("后端结算失败" in e for e in result.errors)
    assert session.verify()["equal"] is True


def test_tool_round_limit_rolls_back(pack):
    provider = StubProvider([tool("damage", amount=1)])
    session = make_session(provider)
    result = session.submit_action({"kind": "text", "text": "一直打"})

    assert result.ok is False
    assert session.state["hp"] == 20
    assert any("叙事阶段禁止" in e for e in result.errors)
    assert session.verify()["equal"] is True


def test_unknown_skill_action_is_harmless(pack):
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "skill", "skill_id": "nope"})
    assert result.ok is False
    assert any("未知技能" in e for e in result.errors)
    assert result.state == pack.state.defaults()
    assert session.turn == 0
    assert result.events == []


def test_turn_input_with_segments_and_multiple_skills(pack):
    """一次输入可以混着动作/话语，同时勾选多个技能：一起结算、一起回放。"""
    session = make_session(ScriptedProvider())
    result = session.submit_action(
        {
            "kind": "text",
            "text": "推开门，喊了一句「有人吗」",
            "segments": [
                {"mode": "action", "text": "推开门"},
                {"mode": "speech", "text": "有人吗"},
            ],
            "skills": [
                {"skill_id": "smash", "name": "撬棍击打"},
                {"skill_id": "first_aid", "name": "急救包扎"},
            ],
        }
    )

    assert result.ok is True
    assert result.state["stamina"] == 7  # 10 - 2（smash）- 1（first_aid）
    used = [e for e in result.events if e["kind"] == "skill.used"]
    assert [e["payload"]["skill_id"] for e in used] == ["smash", "first_aid"]
    started = next(e for e in result.events if e["kind"] == "turn.started")
    assert started["payload"]["action"]["segments"][0]["mode"] == "action"
    assert session.verify()["equal"] is True


def test_turn_skills_are_validated_atomically(pack):
    """勾选列表里任何一项不合法，整回合失败：不扣费、不产生事件。"""
    session = make_session(ScriptedProvider())
    result = session.submit_action(
        {
            "kind": "text",
            "text": "一边砸一边包扎",
            "skills": [{"skill_id": "smash"}, {"skill_id": "nope"}],
        }
    )

    assert result.ok is False
    assert any("未知技能：nope" in e for e in result.errors)
    assert result.state["stamina"] == 10
    assert result.state["hp"] == 20
    assert session.turn == 0
    assert result.events == []
    assert session.verify()["equal"] is True


def test_turn_skills_reject_when_cooldown_blocks_one(pack):
    """已进入冷却的技能即便勾选也整体拒绝，不能只结算一半。"""
    session = make_session(ScriptedProvider())
    first = session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    assert first.ok is True
    stamina_after_first = session.state["stamina"]

    blocked = session.submit_action(
        {
            "kind": "text",
            "text": "再包扎一次",
            "skills": [{"skill_id": "smash"}, {"skill_id": "first_aid"}],
        }
    )
    assert blocked.ok is False
    assert any("冷却" in e for e in blocked.errors)
    assert session.state["stamina"] == stamina_after_first
    assert session.verify()["equal"] is True


def test_start_opening_generates_once_without_spending_turn(pack):
    """开局叙述由模型生成一次：不占回合、不改状态、重复调用不再计费。"""
    from conftest import StubProvider, say

    provider = StubProvider([say("你在一间冷柜嗡嗡作响的便利店里醒来。")])
    session = make_session(provider)

    first = session.start_opening()
    assert first["ok"] is True
    assert first["generated"] is True
    assert "便利店" in first["narrative"]
    assert session.turn == 0
    assert session.state == pack.state.defaults()
    assert session.ledger.events  # 事件已落账
    request = provider.requests[0]
    assert request["opening"] is True
    assert request["allow_tools"] is False
    assert request["turn"] == 0
    assert "你环顾四周" not in first["narrative"]

    status = session.status()
    assert status["opening_generated"] is True
    assert session.options()[0]["id"] == "o1"
    assert session.verify()["equal"] is True

    second = session.start_opening()
    assert second["generated"] is False
    assert second["narrative"] == first["narrative"]
    assert len(provider.requests) == 2  # 幂等：不再调一次模型


def test_opening_failure_is_reported_and_retryable(pack):
    """模型没给叙事就报错；失败不落账，重试仍会真正调用。"""
    from conftest import StubProvider

    from rpg_gateway import LlmResponse

    provider = StubProvider([LlmResponse(model="stub"), say("第二次终于写出来了。")])
    session = make_session(provider)

    failed = session.start_opening()
    assert failed["ok"] is False
    assert "叙事" in failed["error"]
    assert session.status()["opening_generated"] is False

    retried = session.start_opening()
    assert retried["ok"] is True
    assert retried["narrative"] == "第二次终于写出来了。"
    assert session.status()["opening_generated"] is True
    assert session.verify()["equal"] is True


def test_learn_skill_adds_skill_and_can_be_used_next_turn(pack):
    """AI 在回合里调用 learn_skill：技能进账本、出现在技能栏，下回合可勾选使用。"""
    provider = StubProvider(
        [
            learn_skill(
                id="shadow_step",
                name="潜行",
                description="放轻脚步，不易被发现。",
                cost={"stamina": 2},
                cooldown=2,
                action_text="我屏住呼吸，贴着墙根挪过去。",
                reason="在黑暗里走得多了，脚下自然轻。",
            ),
            say("你把脚步放到最轻，寒意沿着墙缝爬上脚踝。"),
            say("你贴着冷柜侧面挪过半排货架。"),
        ]
    )
    session = make_session(provider)

    learned = session.submit_action({"kind": "text", "text": "试着不出声地绕过去"})
    assert learned.ok is True
    events = [e for e in learned.events if e["kind"] == "skill.learned"]
    assert len(events) == 1
    assert events[0]["payload"]["skill"]["id"] == "shadow_step"
    assert any(s["id"] == "shadow_step" for s in session.status()["skills"])
    assert session.verify()["equal"] is True

    stamina_before = session.state["stamina"]
    used = session.submit_action(
        {
            "kind": "text",
            "text": "继续往里走",
            "skills": [{"skill_id": "shadow_step", "name": "潜行"}],
        }
    )
    assert used.ok is True
    assert session.state["stamina"] == stamina_before - 2
    assert any(
        e.get("payload", {}).get("skill_id") == "shadow_step" for e in used.events
    )
    assert session.verify()["equal"] is True


def test_learn_skill_rejects_existing_skill_and_rolls_back(pack):
    """learn_skill 只能新增内容包里没有的技能 id；被拒绝则整回合回滚。"""
    provider = StubProvider([learn_skill(id="smash", name="重击")])
    session = make_session(provider)

    result = session.submit_action({"kind": "text", "text": "学着他砸门的样子"})
    assert result.ok is False
    assert result.errors  # 工具被护栏拒绝 → 回合整体作废
    assert not any(e.kind == "skill.learned" for e in session.ledger.events)
    assert session.turn == 0
    assert session.verify()["equal"] is True


def test_undo_removes_learned_skill(pack):
    """撤销习得技能的那一回合：技能从技能栏消失，账本回放仍然一致。"""
    provider = StubProvider(
        [
            learn_skill(id="shadow_step", name="潜行"),
            say("你学会了他的走法。"),
            say("你继续往前走。"),
        ]
    )
    session = make_session(provider)
    assert session.submit_action({"kind": "text", "text": "跟着他走"}).ok is True
    assert any(s["id"] == "shadow_step" for s in session.status()["skills"])

    undone = session.undo()
    assert undone["ok"] is True
    assert not any(s["id"] == "shadow_step" for s in session.status()["skills"])
    assert session.verify()["equal"] is True


def test_learned_skill_survives_save_load(pack):
    """习得技能是账本投影：读档后仍在技能栏里，并且能继续勾选使用。"""
    provider = StubProvider(
        [
            learn_skill(id="shadow_step", name="潜行", cost={"stamina": 1}),
            say("你学会了他的走法。"),
        ]
    )
    session = make_session(provider)
    assert session.submit_action({"kind": "text", "text": "跟着他走"}).ok is True

    restored = make_session(ScriptedProvider())
    restored.load_events(
        [e.model_dump(mode="json") for e in session.ledger.events]
    )
    assert any(s["id"] == "shadow_step" for s in restored.status()["skills"])
    stamina_before = restored.state["stamina"]
    later = restored.submit_action(
        {"kind": "text", "text": "继续潜行", "skills": [{"skill_id": "shadow_step"}]}
    )
    assert later.ok is True
    assert restored.state["stamina"] == stamina_before - 1


def test_narrative_status_is_stored_and_rolls_back_with_undo(pack):
    first = NarratorStatus(
        name="露娜莉亚", lewd=8, body=20, sensitivity=35, desire=44
    )
    second = NarratorStatus(
        name="露娜莉亚", lewd=52, body=61, sensitivity=70, desire=83
    )
    session = make_session(StubProvider([say("第一段", status=first), say("第二段", status=second)]))
    assert session.status()["narrative_status"] is None

    assert session.submit_action({"kind": "text", "text": "打量四周"}).ok is True
    assert session.status()["narrative_status"] == {
        "name": "露娜莉亚",
        "lewd": 8,
        "body": 20,
        "sensitivity": 35,
        "desire": 44,
    }
    event = next(
        e for e in session.ledger.events if e.kind == "narrative.generated" and e.turn == 1
    )
    assert event.payload["status"]["desire"] == 44

    assert session.submit_action({"kind": "text", "text": "靠近一步"}).ok is True
    assert session.status()["narrative_status"]["lewd"] == 52

    session.undo()
    assert session.status()["narrative_status"]["lewd"] == 8


def test_opening_status_shows_in_status_bar(pack):
    status = NarratorStatus(name="露娜莉亚", lewd=3, body=5, sensitivity=7, desire=9)
    session = make_session(StubProvider([say("开场白", status=status)]))

    result = session.start_opening()

    assert result["ok"] is True
    assert session.status()["narrative_status"] == {
        "name": "露娜莉亚",
        "lewd": 3,
        "body": 5,
        "sensitivity": 7,
        "desire": 9,
    }


def test_skill_payment_ignores_duplicate_deduction(pack):
    """技能扣费已由框架结算：模型再扣同一字段会被忽略，不回滚、不重复扣。"""
    provider = StubProvider(
        [
            tool(
                "add_stat",
                id="tc_dup",
                field="stamina",
                delta=-2,
                reason="挥砍消耗体力",
            ),
            say("你抡起撬棍砸下去，虎口震得发麻。"),
        ]
    )
    session = make_session(provider)
    result = session.submit_action({"kind": "skill", "skill_id": "smash"})

    assert result.ok is True
    assert result.state["stamina"] == 8  # 框架只扣了 smash 的 2 点
    assert any(e["kind"]=="settlement.checked" for e in result.events) and "stamina" in result.ignored[0]
    rejected = [e for e in result.events if e["kind"] == "tool.rejected"]
    assert len(rejected) == 1
    assert rejected[0]["payload"]["error_code"] == "double_spend"
    assert rejected[0]["payload"]["ignored"] is True
    # 第二轮请求把「已扣 stamina 2，剩 8」写进提示词
    payments = provider.requests[0]["payments"]
    assert payments[0]["field"] == "stamina"
    assert payments[0]["amount"] == 2
    assert payments[0]["remaining"] == 8
    assert session.verify()["equal"] is True


def test_skill_turn_still_allows_other_field_changes(pack):
    """技能扣的是 stamina，模型改 hp（受伤）不受影响，数值照样落地。"""
    provider = StubProvider(
        [
            tool("damage", id="tc_dmg", target="hp", amount=2, reason="碎石擦伤"),
            say("碎石从脚边弹起，蹭破了你的小腿。"),
        ]
    )
    session = make_session(provider)
    result = session.submit_action({"kind": "skill", "skill_id": "smash"})

    assert result.ok is True
    assert result.state["hp"] == 18
    assert result.state["stamina"] == 8
    assert result.ignored == []
    kinds = [e["kind"] for e in result.events]
    assert "tool.applied" in kinds
    assert session.verify()["equal"] is True


def test_player_input_modes_survive_ledger_save_restore():
    from rpg_core.saves import snapshot_payload, restore_session
    provider=StubProvider([say("你停在门口，没有把心里的话说出声。")])
    session=make_session(provider)
    action={"kind":"text","text":"我停下，心想先等等。","modes":["action","thought"]}
    assert session.submit_action(action).ok
    fresh=make_session(StubProvider([say()]))
    restore_session(fresh,snapshot_payload(session,slot="chat"))
    started=next(e for e in fresh.ledger.events if e.kind=="turn.started")
    assert started.payload["action"]==action
    assert fresh.verify()["equal"]


def test_authored_option_text_is_saved_for_future_chat_history():
    session=make_session(StubProvider([say()]))
    option=session.pack.opening.options[0]
    assert session.submit_action({"kind":"option","option_id":option.id}).ok
    event=next(e for e in session.ledger.events if e.kind=="turn.started")
    assert event.payload["display_text"]==(option.action_text or option.label)
