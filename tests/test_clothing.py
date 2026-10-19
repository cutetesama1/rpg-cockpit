"""Post-narrative wardrobe transaction, provider isolation and save migration."""
import hashlib
import json
from pathlib import Path
import pytest
from conftest import StubProvider, roles, say, tool
from rpg_content import load_pack, PackError
from rpg_core.contracts import LlmProfile, LlmRolesConfig, ToolCall
from rpg_core.runtime import GameSession
from rpg_core.saves import snapshot_payload, restore_session
from rpg_gateway import LlmResponse, LlmRouter, OpenAICompatibleProvider

ROOT = Path(__file__).resolve().parents[1]
TEXT = "你在训练室换上卫衣和长裤。卫衣袖口被木桩刮破。"

def clothes(*changes):
    return LlmResponse(tool_calls=[ToolCall(id="wardrobe", name="update_clothing", args={"changes": list(changes)})])

def change(slot="upper", **kwargs):
    return {"slot": slot, "evidence": TEXT, **kwargs}

def game(narrator=None, settler=None, separated=True):
    narrator = narrator or StubProvider([say(TEXT)], name="narrator")
    settler = settler or StubProvider([clothes(change(garment="hoodie", condition="damaged"), change("lower", garment="trousers"))], name="settler")
    cfg = LlmRolesConfig(separated=separated, narrator=LlmProfile(provider="narrator"), settler=LlmProfile(provider="settler"))
    return GameSession(load_pack(ROOT / "packs/new-game"), LlmRouter(cfg, {"narrator": narrator, "settler": settler})), narrator, settler


def test_narrator_then_settler_reads_only_this_final_narrative_and_applies_atomically():
    session, narrator, settler = game()
    session._record(turn=0, kind="narrative.generated", payload={"narrative": "旧文本说换毛衣。", "opening": True})
    result = session.submit_action({"kind": "text", "text": "玩家输入中还说想换另一件。"})
    assert result.ok and result.state["upper"] == "hoodie" and result.state["lower"] == "trousers"
    assert result.state["upper_condition"] == "damaged"
    request = settler.requests[0]
    assert request["phase"] == "settlement" and request["narrative"] == TEXT
    assert not {"action", "recent", "events", "tool_exchanges"} & request.keys()
    assert "旧文本" not in json.dumps(request, ensure_ascii=False)
    assert [e.role for e in session.ledger.events if e.kind == "llm.usage"] == ["narrator", "settler"]
    checked = next(e for e in session.ledger.events if e.kind == "settlement.checked")
    assert checked.payload["narrative_sha256"] == hashlib.sha256(result.narrative.encode()).hexdigest()
    assert session.verify()["equal"]
    fresh, _, _ = game()
    restore_session(fresh, snapshot_payload(session, slot="probe"))
    assert fresh.state == session.state
    assert session.undo()["state"]["upper"] == "tshirt"
    assert session.state["upper_condition"] == "intact" and session.verify()["equal"]


def test_single_model_reuses_narrator_provider_as_separate_post_processing_call():
    provider = StubProvider([say(TEXT), clothes(change(garment="hoodie"))], name="narrator")
    session, _, unused = game(narrator=provider, separated=False)
    assert session.submit_action({"kind": "text", "text": "换衣"}).state["upper"] == "hoodie"
    assert len(provider.requests) == 2 and not unused.requests
    assert provider.requests[1]["phase"] == "settlement"
    assert provider.requests[1]["temperature"] == 0
    assert "max_tokens" not in provider.requests[1]


def test_only_numeric_checked_final_narrative_is_settled():
    narrator = StubProvider([say("你换上卫衣，hp 10。"), say(TEXT)], name="narrator")
    session, _, settler = game(narrator=narrator)
    result = session.submit_action({"kind": "text", "text": "换衣"})
    assert result.ok
    assert len(settler.requests) == 1 and settler.requests[0]["narrative"] == result.narrative == TEXT


@pytest.mark.parametrize("update,code", [
    (change(garment="nonexistent"), "clothing_garment"),
    (change(condition="missing"), "clothing_condition"),
    (change(color="url(evil)"), "clothing_color"),
    ({**change(garment="hoodie"), "evidence": "不是本次原文"}, "clothing_evidence"),
    (change("hp", garment="hoodie"), "clothing_slot"),
    ({**change(garment="hoodie"), "hp": 1}, "bad_params"),
])
def test_bad_clothing_rolls_back_hp_and_all_slot_changes(update, code):
    narrator = StubProvider([tool("damage", amount=2), say(TEXT)], name="narrator")
    backend = StubProvider([clothes(change("lower", garment="trousers"), update)], name="settler")
    session, _, _ = game(narrator, backend)
    before = dict(session.state)
    result = session.submit_action({"kind": "text", "text": "训练"})
    assert not result.ok and session.state == before and session.turn == 0
    assert any(e.kind == "tool.rejected" and e.payload.get("error_code") == code for e in session.ledger.events)
    assert session.verify()["equal"]


def test_duplicate_slot_rejected_as_whole_batch():
    session, _, _ = game(settler=StubProvider([clothes(change(garment="hoodie"), change(condition="damaged"))], name="settler"))
    result = session.submit_action({"kind": "text", "text": "训练"})
    assert not result.ok and session.state["upper"] == "tshirt"


@pytest.mark.parametrize("response", [say("我已经换好了。"), tool("invalid_operation", field="hp", value=1)])
def test_backend_must_return_only_one_wardrobe_tool(response):
    class Raw:
        name="settler"
        def complete(self,request):return response
    session, _, _ = game(settler=Raw())
    before = dict(session.state)
    result = session.submit_action({"kind": "text", "text": "训练"})
    assert not result.ok and session.state == before


def test_backend_failure_rolls_back_skill_payment_and_numeric_changes():
    class Broken:
        name = "settler"
        def complete(self, request): raise TimeoutError("test timeout")
    narrator = StubProvider([tool("damage", amount=2), say(TEXT)], name="narrator")
    session, _, _ = game(narrator, Broken())
    from rpg_core.contracts import SkillSpec
    session.pack.skills.append(SkillSpec(id="test_step", name="步法", cost={"focus": 2}))
    result = session.submit_action({"kind": "text", "text": "训练", "skills": ["test_step"]})
    assert not result.ok and session.state["hp"] == 20 and session.state["focus"] == 10
    assert session.verify()["equal"]


def test_no_change_does_not_reset_damage_and_replacement_resets_it():
    narrator = StubProvider([say(TEXT)], name="narrator")
    backend = StubProvider([clothes(change(condition="damaged")), clothes(), clothes(change(garment="hoodie"))], name="settler")
    session, _, _ = game(narrator, backend)
    for expected in ("damaged", "damaged", "intact"):
        result = session.submit_action({"kind": "text", "text": "继续"})
        assert result.ok and result.state["upper_condition"] == expected
    assert session.verify()["equal"]


def test_direct_narrator_cannot_call_clothing_tool():
    class Raw:
        name='narrator'
        def complete(self,request):return clothes(change(garment='hoodie'))
    session,_,backend=game(Raw())
    assert not session.submit_action({'text':'训练'}).ok
    assert not backend.requests and session.state['upper']=='tshirt'


def test_opening_clothing_is_idempotent_and_invalid_opening_writes_no_state():
    session, narrator, backend = game()
    result = session.start_opening()
    assert result["ok"] and session.state["upper"] == "hoodie"
    assert not session.start_opening()["generated"]
    assert len(narrator.requests) == len(backend.requests) == 1
    assert session.verify()["equal"]
    broken, _, _ = game(settler=StubProvider([clothes(change(garment="invalid"))], name="settler"))
    assert not broken.start_opening()["ok"]
    assert not broken.opening_event() and broken.state["upper"] == "tshirt"


def test_backend_payload_has_one_tool_no_history_or_narrator_instructions():
    session, _, _ = game()
    request = session.assembler.build_clothing(TEXT, session.state, session.scene_id)
    provider = OpenAICompatibleProvider(base_url="http://unused", model="test")
    payload = provider._payload(request)
    assert [t["function"]["name"] for t in payload["tools"]] == ["update_clothing"]
    assert payload["tool_choice"] == "auto"
    assert len(payload["messages"]) == 2
    assert "800" not in payload["messages"][1]["content"]
    normal = provider._payload(session.assembler.build(turn=1, action={}, state=session.state, events=[]))
    assert "tools" not in normal


def test_old_save_adds_only_new_condition_defaults_without_ignoring_tampering():
    session, _, _ = game()
    session._record(turn=0, kind="narrative.generated", payload={"narrative": "旧开场", "opening": True})
    payload = snapshot_payload(session, slot="old")
    for key in ("upper_condition", "lower_condition"): del payload["state"][key]
    fresh, _, _ = game()
    restore_session(fresh, payload)
    assert fresh.state["upper_condition"] == "intact"
    payload["state"]["hp"] = 1
    with pytest.raises(ValueError, match="不一致"): restore_session(fresh, payload)


def test_old_user_pack_migration_is_backed_up_idempotent_and_keeps_custom_prompts(tmp_path):
    import shutil
    from rpg_content.migrations import upgrade_wardrobe
    source = ROOT / "packs/new-game"
    target = tmp_path / "pack"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("sprites", "wardrobe.json"))
    state = json.loads((target / "state.json").read_text(encoding="utf-8"))
    state["fields"] = [f for f in state["fields"] if not f["id"].endswith("_condition")]
    (target / "state.json").write_text(json.dumps(state), encoding="utf-8")
    before = (target / "state.json").read_bytes()
    prompt = (target / "prompts/narrator.md").read_bytes()
    assert upgrade_wardrobe(target, source)
    assert (target / ".wardrobe-v1-backup/state.json").read_bytes() == before
    assert (target / "prompts/narrator.md").read_bytes() == prompt
    assert load_pack(target).wardrobe
    assert not upgrade_wardrobe(target, source)


def test_wardrobe_catalog_rejects_unknown_field_or_item():
    from rpg_content.pack import validate_pack
    session, _, _ = game()
    session.pack.wardrobe.slots["upper"].items["ghost"] = "不存在"
    assert any("衣物目录" in e for e in validate_pack(session.pack))


def test_invalid_evidence_can_be_corrected_once_without_applying_first_batch():
    backend = StubProvider([clothes({**change(garment="hoodie"), "evidence": "改写而非原文"}), clothes(change(garment="hoodie"))], name="settler")
    session, _, _ = game(settler=backend)
    result = session.submit_action({"kind":"text", "text":"换衣"})
    assert result.ok and session.state["upper"] == "hoodie"
    assert len(backend.requests) == 2
    assert backend.requests[1]["validation_feedback"]["code"] == "clothing_evidence"
    assert len([e for e in session.ledger.events if e.kind=="tool.applied"]) == 1
    assert session.verify()["equal"]
