"""技能经济：冷却、消耗、可用性（框架权威，不走 LLM 工具）。"""
from __future__ import annotations

from conftest import make_session

from rpg_gateway import ScriptedProvider


def test_skill_cost_is_framework_event_and_replayable():
    session = make_session(ScriptedProvider())
    result = session.submit_action({"kind": "skill", "skill_id": "smash"})

    assert result.ok is True
    assert result.state["hp"] == 13
    assert result.state["stamina"] == 8  # smash 消耗体力 2
    kinds = [e["kind"] for e in result.events]
    assert kinds[:2] == ["turn.started", "skill.used"]  # 技能事件在 LLM 结算之前
    used = [e for e in result.events if e["kind"] == "skill.used"][0]
    assert used["payload"]["skill_id"] == "smash"
    assert used["payload"]["changes"]["stamina"] == {"before": 10, "after": 8}
    assert session.verify()["equal"] is True


def test_cooldown_blocks_reuse_then_expires():
    session = make_session(ScriptedProvider())
    first = session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    assert first.ok is True

    blocked = session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    assert blocked.ok is False
    assert any("冷却" in e for e in blocked.errors)
    assert blocked.events == []

    session.submit_action({"kind": "skill", "skill_id": "observe"})  # 回合 2
    again = session.submit_action({"kind": "skill", "skill_id": "first_aid"})  # 回合 3
    assert again.ok is True
    assert session.turn == 3
    assert session.verify()["equal"] is True


def test_skill_unaffordable_when_cost_exceeds_resource():
    session = make_session(ScriptedProvider())
    for _ in range(5):  # 体力 10，每次 smash 消耗 2
        assert session.submit_action({"kind": "skill", "skill_id": "smash"}).ok is True
    assert session.state["stamina"] == 0

    blocked = session.submit_action({"kind": "skill", "skill_id": "smash"})
    assert blocked.ok is False
    assert any("不足" in e for e in blocked.errors)
    assert session.turn == 5
    assert session.state["stamina"] == 0
    assert session.verify()["equal"] is True


def test_skill_status_reports_availability():
    session = make_session(ScriptedProvider())
    before = {s["id"]: s for s in session.skill_states()}
    assert before["first_aid"]["available"] is True
    assert before["first_aid"]["cooldown_remaining"] == 0

    session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    after = {s["id"]: s for s in session.skill_states()}
    assert after["first_aid"]["available"] is False
    assert after["first_aid"]["cooldown_remaining"] == 1
    assert "冷却" in after["first_aid"]["blocked_reason"]
    # 冷却不计入下一回合的内部剩余，但状态查询保持一致
    assert after["smash"]["available"] is True


def test_undo_restores_skill_cost_and_cooldown():
    session = make_session(ScriptedProvider())
    session.submit_action({"kind": "skill", "skill_id": "smash"})
    assert session.state["stamina"] == 8

    session.undo()
    assert session.state["stamina"] == 10
    assert session.turn == 0
    status = {s["id"]: s for s in session.skill_states()}
    assert status["smash"]["available"] is True
