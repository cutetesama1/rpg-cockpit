"""Contract probes for the current sample pack; no live provider or user saves."""
from pathlib import Path
import pytest
from conftest import StubProvider, roles, say, tool
from rpg_content import load_pack
from rpg_core.contracts import LlmProfile, LlmRolesConfig, StateField, ToolCall
from rpg_core.runtime import GameSession
from rpg_gateway import LlmResponse, LlmRouter

ROOT = Path(__file__).resolve().parents[1]

def session(responses, mp=False):
    pack = load_pack(ROOT / "packs/new-game")
    pack.wardrobe = None  # Legacy numeric-tool boundary; post-narrative clothing is tested separately.
    if mp:
        pack.state.fields.append(StateField(id="mp", label="魔力", default=10, min=0, max=10))
    return GameSession(pack, LlmRouter(roles(), {"stub": StubProvider(responses)}))

def test_prose_alone_cannot_change_game_state():
    game = session([say("你受了伤，换上卫衣，摆出战斗姿势，并学会了防御。")])
    before = dict(game.state)
    assert game.submit_action({"kind": "text", "text": "继续"}).ok
    assert game.state == before
    assert not game._learned_skills()
    assert game.verify()["equal"]

def test_hp_tools_apply_and_undo_replays():
    game = session([tool("damage", amount=3), say(), tool("heal", amount=1), say()])
    assert game.submit_action({"kind": "text", "text": "训练时擦伤"}).state["hp"] == 17
    assert game.submit_action({"kind": "text", "text": "包扎"}).state["hp"] == 18
    assert game.undo()["state"]["hp"] == 17
    assert game.verify()["equal"]

@pytest.mark.usefixtures("strict_settlement")
def test_mp_requires_a_declared_numeric_field():
    game = session([tool("add_stat", field="mp", delta=-2), say()])
    result = game.submit_action({"kind": "text", "text": "施法"})
    assert not result.ok
    assert "mp" not in result.state
    assert any(e["payload"].get("error_code") == "unknown_field" for e in result.events)
    assert game.verify()["equal"]

def test_declared_mp_can_pay_for_learned_skill_without_double_charge():
    learn = LlmResponse(tool_calls=[ToolCall(id="learn", name="learn_skill", args={
        "id": "light_spell", "name": "照明术", "cost": {"mp": 2}, "cooldown": 2,
    })])
    game = session([learn, say(), tool("add_stat", field="mp", delta=-2), say()], mp=True)
    assert game.submit_action({"kind": "text", "text": "学会照明术"}).ok
    result = game.submit_action({"kind": "text", "text": "照亮走廊", "skills": [{"skill_id": "light_spell"}]})
    assert result.ok and result.state["mp"] == 8
    assert next(e for e in result.events if e["kind"]=="settlement.checked")
    count = len(game.ledger.events)
    assert not game.submit_action({"kind": "skill", "skill_id": "light_spell"}).ok
    assert len(game.ledger.events) == count
    assert game.verify()["equal"]

@pytest.mark.parametrize(("field", "value"), [("upper", "hoodie"), ("pose", "standing")])
@pytest.mark.usefixtures("strict_settlement")
def test_clothes_and_pose_cannot_be_changed_with_numeric_tools(field, value):
    game = session([tool("set_stat", field=field, value=value), say()])
    before = dict(game.state)
    result = game.submit_action({"kind": "text", "text": "更换外观"})
    assert not result.ok and game.state == before
    assert any(e["payload"].get("error_code") == "not_numeric" for e in result.events)
    assert game.verify()["equal"]

def test_clothes_and_pose_are_not_visible_to_llm():
    game = session([say()])
    snapshot = game.assembler.state_snapshot(game.state)
    assert "hp" in snapshot
    assert not {"upper", "lower", "pose"} & snapshot.keys()

def test_separated_mode_routes_settler_then_narrator_after_tool():
    settler = StubProvider([tool("damage", amount=2)], name="settler")
    narrator = StubProvider([say()], name="narrator")
    config = LlmRolesConfig(separated=True, settler=LlmProfile(provider="settler"), narrator=LlmProfile(provider="narrator"))
    game = GameSession(load_pack(ROOT / "packs/night-convenience-store"), LlmRouter(config, {"settler": settler, "narrator": narrator}))
    assert game.submit_action({"kind": "text", "text": "擦伤"}).state["hp"] == 18
    assert len(settler.requests) == len(narrator.requests) == 1
    assert [e.role for e in game.ledger.events if e.kind == "llm.usage"] == ["narrator", "settler"]

def test_separated_mode_can_finish_with_settler_prose_without_calling_narrator():
    settler = StubProvider([say()], name="settler")
    narrator = StubProvider([say()], name="narrator")
    config = LlmRolesConfig(separated=True, settler=LlmProfile(provider="settler"), narrator=LlmProfile(provider="narrator"))
    game = GameSession(load_pack(ROOT / "packs/night-convenience-store"), LlmRouter(config, {"settler": settler, "narrator": narrator}))
    assert game.submit_action({"kind": "text", "text": "观察"}).ok
    assert len(settler.requests) == len(narrator.requests) == 1
    assert settler.requests[0]["phase"] == "settlement"
