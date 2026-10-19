"""第二题材探针包：同一套运行时/账本/护栏，装下完全不同的世界。"""
from __future__ import annotations

from conftest import PROBE_PACK_DIR, StubProvider, roles, say, tool

from rpg_content import lint_pack_dir, load_pack
from rpg_core.runtime import GameSession
from rpg_gateway import LlmRouter


def probe_session(provider) -> GameSession:
    router = LlmRouter(roles(provider.name), {provider.name: provider})
    return GameSession(load_pack(PROBE_PACK_DIR), router)


def test_probe_pack_is_a_different_genre():
    pack = load_pack(PROBE_PACK_DIR, lint_warnings=True)
    assert pack.manifest.id == "probe-signal-station"
    assert pack.manifest.rating == "12+"
    assert [f.id for f in pack.state.fields] == [
        "oxygen",
        "integrity",
        "power",
        "credits",
        "flag_heard_signal",
        "flag_door_sealed",
    ]
    assert {s.id for s in pack.skills} == {"scan", "reroute", "seal_door"}
    assert sorted(s.id for s in pack.scenes) == ["core", "corridor", "opening"]
    assert pack.opening.id == "opening"
    assert "科幻" in pack.prompts["narrator"]


def test_probe_pack_lints_clean():
    assert [i.format() for i in lint_pack_dir(PROBE_PACK_DIR) if i.level == "error"] == []


def test_probe_skill_cost_hits_framework_ledger():
    session = probe_session(StubProvider([say("扫描器的绿点沿着舱壁慢慢爬。")]))
    result = session.submit_action({"kind": "skill", "skill_id": "scan"})

    assert result.ok is True
    assert result.state["power"] == 16  # 18 - 2
    kinds = [e["kind"] for e in result.events]
    assert kinds[:2] == ["turn.started", "skill.used"]
    assert session.verify()["equal"] is True


def test_probe_tool_damages_integrity_not_hp():
    provider = StubProvider(
        [
            tool("damage", target="integrity", amount=4, reason="舱壁被撞"),
            say("一声闷响从甲板下面传上来，刮痕震落了一层灰。"),
        ]
    )
    session = probe_session(provider)
    result = session.submit_action({"kind": "text", "text": "我用力推了推舱门。"})

    assert result.ok is True
    assert result.state["integrity"] == 92
    applied = [e for e in result.events if e["kind"] == "tool.applied"]
    assert applied and applied[0]["payload"]["changes"]["integrity"] == {
        "field": "integrity",
        "before": 96,
        "after": 92,
    }
    assert session.verify()["equal"] is True
