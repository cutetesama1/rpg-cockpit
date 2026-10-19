"""场景推进：默认场景、enter_scene 工具、进入条件、作者选项转场、回放一致性。"""
from __future__ import annotations

import pytest

from conftest import (
    PACK_DIR,
    PROBE_PACK_DIR,
    StubProvider,
    make_session,
    roles,
    say,
    tool,
)

from rpg_content import load_pack
from rpg_core.context import ContextAssembler
from rpg_core.contracts import Condition, ToolCall
from rpg_core.runtime import GameSession
from rpg_core.scenes import condition_holds, find_scene, unmet_conditions
from rpg_gateway import LlmResponse, LlmRouter, ScriptedProvider


def _session(pack_dir=PACK_DIR, provider=None) -> GameSession:
    router = LlmRouter(roles("stub"), {"stub": provider or StubProvider([say()])})
    return GameSession(load_pack(pack_dir), router)


def test_default_scene_is_opening(pack):
    session = make_session(ScriptedProvider())
    status = session.status()

    assert session.scene_id == "opening"
    assert status["scene"]["id"] == "opening"
    assert status["scene"]["title"] == "便利店门口"
    assert status["scene"]["requires_met"] is True
    assert [o["id"] for o in status["scene"]["options"]][0] == "opt_enter"


def test_enter_scene_tool_moves_and_records(pack):
    provider = StubProvider([tool("enter_scene", scene_id="aisle"), say("你走进了货架之间。")])
    session = make_session(provider)

    result = session.submit_action({"kind": "text", "text": "你推门走进店里"})

    assert result.ok is True
    assert result.scene_id == "aisle"
    assert session.scene_id == "aisle"
    kinds = [e["kind"] for e in result.events]
    assert "scene.entered" in kinds
    entered = next(e for e in result.events if e["kind"] == "scene.entered")
    assert entered["payload"]["scene_id"] == "aisle"
    assert entered["payload"]["from_scene"] == "opening"
    assert session.verify()["equal"] is True
    assert session.verify()["scene"] == {"live": "aisle", "replay": "aisle"}


def test_locked_scene_is_rejected_and_rolls_back(pack):
    provider = StubProvider(
        [tool("enter_scene", scene_id="backroom"), say("你撬开了后仓的门。")]
    )
    session = make_session(provider)

    result = session.submit_action({"kind": "text", "text": "你走向后仓"})

    assert result.ok is False
    assert session.scene_id == "opening"
    assert session.turn == 0
    assert "scene.entered" not in [e["kind"] for e in result.events]
    assert any("scene_locked" in e or "不可进入" in e for e in result.errors)
    rejected = [e for e in result.events if e["kind"] == "tool.rejected"]
    assert rejected and rejected[0]["payload"]["error_code"] == "scene_locked"


def test_set_flag_then_enter_scene_in_same_turn(pack):
    provider = StubProvider(
        [
            LlmResponse(
                tool_calls=[
                    ToolCall(id="tc_flag", name="set_flag", args={"flag": "met_clerk", "value": True}),
                    ToolCall(id="tc_scene", name="enter_scene", args={"scene_id": "backroom"}),
                ]
            ),
            say("后仓的门在你身后合上。"),
        ]
    )
    session = make_session(provider)

    result = session.submit_action({"kind": "text", "text": "你跟着店员走进后仓"})

    assert result.ok is True
    assert session.scene_id == "backroom"
    assert session.state["flag_met_clerk"] is True
    assert [e["kind"] for e in result.events].count("scene.entered") == 1


def test_unknown_scene_is_rejected(pack):
    provider = StubProvider([tool("enter_scene", scene_id="nowhere"), say("...")])
    session = make_session(provider)

    result = session.submit_action({"kind": "text", "text": "你走向虚空"})

    assert result.ok is False
    assert session.scene_id == "opening"
    rejected = [e for e in result.events if e["kind"] == "tool.rejected"]
    assert rejected[0]["payload"]["error_code"] == "unknown_scene"


def test_option_next_scene_transition_is_deterministic(pack):
    provider = StubProvider([say("店门上的风铃响了一声。")])
    session = make_session(provider)

    result = session.submit_action({"kind": "option", "option_id": "opt_enter"})

    assert result.ok is True
    assert session.scene_id == "aisle"
    assert result.state["hp"] == 20  # 转场不动数值
    assert "scene.entered" in [e["kind"] for e in result.events]


def test_option_unknown_and_locked():
    provider = StubProvider([say("...")])
    session = _session(PACK_DIR, provider)

    unknown = session.submit_action({"kind": "option", "option_id": "nope"})
    assert unknown.ok is False
    assert "未知选项" in unknown.errors[0]
    assert session.turn == 0
    assert session.ledger.events == []

    # 后仓只有在 flag_met_clerk 为 true 时才在选项里可用（这里从 aisle 走）
    session.submit_action({"kind": "option", "option_id": "opt_enter"})
    locked = session.submit_action({"kind": "option", "option_id": "to_backroom"})
    assert locked.ok is False
    assert "不可用" in locked.errors[0]
    assert session.scene_id == "aisle"


def test_undo_restores_previous_scene(pack):
    provider = StubProvider([tool("enter_scene", scene_id="aisle"), say("你推门进去。")])
    session = make_session(provider)

    session.submit_action({"kind": "text", "text": "你推门进店"})
    assert session.scene_id == "aisle"

    undone = session.undo()
    assert undone["ok"] is True
    assert session.scene_id == "opening"
    assert session.verify()["scene"] == {"live": "opening", "replay": "opening"}


def test_context_includes_scene_and_transitions(pack):
    assembler = ContextAssembler(pack)
    request = assembler.build(
        turn=0,
        action={"kind": "text", "text": "看看"},
        state=pack.state.defaults(),
        events=[],
        scene_id="aisle",
    )

    assert request["scene"]["id"] == "aisle"
    assert "货架之间" in request["scene_brief"]
    transitions = {t["scene_id"]: t for t in request["transitions"]}
    assert "backroom" in transitions
    assert transitions["backroom"]["available"] is False
    assert "见过店员" in transitions["backroom"]["blocked_reason"]


def test_condition_helpers(pack):
    state = pack.state.defaults()
    assert condition_holds(Condition(field="flag_met_clerk", op="==", value=False), state)
    assert not condition_holds(Condition(field="flag_met_clerk", op="==", value=True), state)
    state["flag_met_clerk"] = True
    reasons = unmet_conditions(
        [Condition(field="flag_met_clerk", op="==", value=True)], state, pack
    )
    assert reasons == []
    missing = unmet_conditions([Condition(field="nope", op="==", value=1)], state, pack)
    assert missing and "未声明字段" in missing[0]


def test_probe_pack_scene_flow():
    session = _session(PROBE_PACK_DIR, StubProvider([say("...")]))
    assert session.scene_id == "opening"
    assert find_scene(session.pack, "core") is not None

    result = session.submit_action({"kind": "option", "option_id": "corridor"})
    assert result.ok is True
    assert session.scene_id == "corridor"

    locked = session.submit_action({"kind": "option", "option_id": "to_core"})
    assert locked.ok is False
    assert session.scene_id == "corridor"


def test_scripted_provider_navigates_by_text():
    session = _session(PACK_DIR, ScriptedProvider())
    result = session.submit_action({"kind": "text", "text": "我推门走进店里"})

    assert result.ok is True
    assert session.scene_id == "aisle"
    assert "货架" in result.narrative or "走进" in result.narrative


def test_scripted_provider_locked_scene_produces_rejection():
    session = _session(PACK_DIR, ScriptedProvider())
    session.submit_action({"kind": "option", "option_id": "opt_enter"})  # → aisle
    result = session.submit_action({"kind": "text", "text": "我走进后仓"})

    assert result.ok is False
    assert session.scene_id == "aisle"
    assert any("后仓" in e or "scene_locked" in e for e in result.errors)


def test_status_reports_scene_options_availability(pack):
    session = make_session(ScriptedProvider())
    session.submit_action({"kind": "option", "option_id": "opt_enter"})
    status = session.status()
    scene = status["scene"]

    assert scene["id"] == "aisle"
    options = {o["id"]: o for o in scene["options"]}
    assert options["to_backroom"]["available"] is False
    assert options["to_checkout"]["next_scene"] == "checkout"


def test_content_has_three_endings_and_does_not_lock_play():
    pack = load_pack(PACK_DIR)
    endings = [scene for scene in pack.scenes if scene.ending]
    assert {scene.id for scene in endings} == {
        "ending_leave",
        "ending_stay",
        "ending_truth",
    }
    assert len(pack.scenes) >= 9  # P4：一个晚上 9~10 个场景
    for scene in endings:
        assert scene.options, "结局场景必须保留可做的动作（不锁死可玩性）"
        assert any(option.next_scene for option in scene.options), "结局场景必须能继续走"


def test_ending_scene_view_and_brief():
    from rpg_core.scenes import format_scene_brief, scene_view

    pack = load_pack(PACK_DIR)
    scene = find_scene(pack, "ending_leave")
    view = scene_view(scene, pack.state.defaults(), pack)
    assert view["ending"] is True
    assert "结局" in view["ending_title"]
    brief = format_scene_brief(pack, pack.state.defaults(), "ending_leave")
    assert "结局标记" in brief
    assert "不锁死" in brief
