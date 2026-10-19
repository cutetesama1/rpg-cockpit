"""契约测试：7 份契约、mutator 清单、内容包加载与 JSON Schema 可导出。"""
from __future__ import annotations

import json

from conftest import PACK_DIR

from rpg_core import contracts as c
from rpg_content import load_pack


def test_mutators_whitelist():
    assert {m.name for m in c.MUTATORS} == {
        "roll",
        "damage",
        "heal",
        "add_stat",
        "set_stat",
        "add_item",
        "set_flag",
        "enter_scene",
        "learn_skill",
        "learn_catalog_skills",
        "update_clothing",
    }
    assert all(m.permission == "settler" for m in c.MUTATORS)


def test_pack_loads():
    pack = load_pack(PACK_DIR)
    assert pack.manifest.id == "night-convenience-store"
    assert pack.manifest.rating == "12+"
    fields = pack.state.by_id()
    assert set(fields) == {
        "hp",
        "stamina",
        "sanity",
        "money",
        "flag_met_clerk",
        "flag_found_door",
        "flag_read_note",
        "flag_heard_voice",
        "flag_saw_ledger",
    }
    assert fields["hp"].max == 20
    assert fields["flag_met_clerk"].type == "bool"
    assert pack.state.limits.max_tool_rounds == 6
    assert pack.state.limits.max_delta_per_turn["hp"] == 8
    assert len(pack.skills) == 3
    assert set(pack.prompts) == {"pre", "narrator", "settler"}
    assert all(len(v) == 8 for v in pack.prompt_versions.values())
    assert pack.opening.options
    assert pack.ui.bars == ["hp", "stamina", "sanity"]


def test_contract_schemas_are_exportable():
    models = {
        "state-schema": c.StateSchema,
        "mutator": c.MutatorSpec,
        "event": c.Event,
        "content-pack": c.ContentPack,
        "narrator-io": c.NarratorOutput,
        "settler-io": c.SettlerOutput,
        "llm-role": c.LlmRolesConfig,
    }
    for name, model in models.items():
        schema = model.model_json_schema()
        assert isinstance(schema, dict), name
        assert json.dumps(schema), name


def test_llm_roles_default_is_single_llm():
    config = c.LlmRolesConfig()
    assert config.separated is False
    assert config.narrator.provider == "scripted"
    assert config.settler.temperature == 0.0
    assert config.narrator.model == config.settler.model


def test_narrator_status_clamps_scores_and_trims_name():
    status = c.NarratorStatus(
        name="  露娜莉亚  ",
        lewd=150,
        body=-20,
        sensitivity="45",
        desire=100,
    )

    assert status.name == "露娜莉亚"
    assert status.lewd == 100
    assert status.body == 0
    assert status.sensitivity == 45
    assert status.desire == 100


def test_narrator_output_status_defaults_to_none():
    out = c.NarratorOutput(narrative="一段叙事")

    assert out.status is None


def test_narrator_status_collects_notes():
    """四项评分可以各自带一句短描述，存进 notes；中文键与超长描述都会被收拾干净。"""
    status = c.NarratorStatus(
        name="露娜",
        lewd=12,
        body=0,
        sensitivity=18,
        desire=12,
        notes={
            "lewd": "  身体有点发热，还压得住 ",
            "色情程度": "重复的键应被忽略",
            "敏感度": "碰到就发抖",
            "无关字段": "丢弃",
            "desire": "x" * 80,
        },
    )
    assert status.notes["lewd"] == "身体有点发热，还压得住"
    assert status.notes["sensitivity"] == "碰到就发抖"
    assert len(status.notes["desire"]) == 60
    assert "无关字段" not in status.notes


def test_narrator_status_accepts_nested_score_objects():
    """模型把单项写成 {"score": …, "note": …} 时也能读。"""
    status = c.NarratorStatus.model_validate(
        {
            "name": "露娜",
            "lewd": {"score": 130, "note": "很想要"},
            "body": {"值": 42.4, "描述": "湿润"},
            "sensitivity": None,
            "desire": "7",
        }
    )
    assert status.lewd == 100
    assert status.body == 42
    assert status.sensitivity == 0
    assert status.desire == 7
