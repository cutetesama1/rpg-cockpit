"""世界构筑助手：提示词拼装、输出解析与草稿归一化。"""
from __future__ import annotations

from conftest import ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

import pytest  # noqa: E402

from rpg_gateway.world_builder import (  # noqa: E402
    BUILDER_SYSTEM_PROMPT,
    build_request,
    compose_prompt,
    draft_summary,
    extract_json,
    parse_draft,
)

GOOD_DRAFT = {
    "title": "雨夜便利店",
    "description": "一个店员、一个客人和一本不该存在的账本。",
    "prompts": {
        "pre": "这是一座凌晨两点也不会真正睡着的城市。" * 6,
        "narrator": "用第二人称、克制的悬疑口吻叙述，每回合 120~200 字。" * 4,
        "settler": "叙事里出现受伤才调用 damage，单次不超过 5 点；不确定就不调用。" * 4,
    },
    "worldbook": [
        {
            "id": "world_tone",
            "title": "世界基调",
            "content": "整座城市在凌晨两点后进入一种半梦半醒的状态，霓虹和雨水都在说谎。" * 2,
            "keywords": [],
            "always_on": True,
            "priority": 100,
            "category": "基调",
        },
        {
            "id": "backroom",
            "title": "后仓",
            "content": "货架后面那扇门常年锁着，门缝里漏出和冷库一样的白汽。" * 2,
            "keywords": ["后仓", "冷库", "那扇门"],
            "priority": 60,
            "category": "地点",
        },
    ],
    "skills": [
        {
            "id": "observe",
            "name": "观察四周",
            "description": "扫视货架、收银台和虚掩的门",
            "cost": {},
            "cooldown": 0,
            "targets": ["scene"],
            "action_text": "你环顾四周",
            "effect_hint": "获得信息",
            "category": "探索",
            "brief": "侦察环境",
        }
    ],
}


def test_prompt_covers_three_prompts_and_world_and_skills():
    for keyword in ("前置提示词", "叙事者提示词", "结算器提示词", "世界书", "技能", "JSON"):
        assert keyword in BUILDER_SYSTEM_PROMPT
    # 不限制可玩性：提示词里必须明确这条产品原则，而不是给出上限
    assert "不设回合上限" in BUILDER_SYSTEM_PROMPT
    assert "不锁死结局" in BUILDER_SYSTEM_PROMPT


def test_compose_prompt_includes_material_and_hints():
    text = compose_prompt("一座会移动的城市", title_hint="浮城", extra_rules="多写气味")
    assert text.startswith(BUILDER_SYSTEM_PROMPT.rstrip()[:20])
    assert "一座会移动的城市" in text
    assert "浮城" in text
    assert "多写气味" in text
    assert "素材开始" in text and "素材结束" in text


def test_build_request_puts_material_in_action():
    request = build_request("一段素材" * 10)
    assert request["system_prompt"] == BUILDER_SYSTEM_PROMPT
    assert "一段素材" in request["action"]["text"]
    assert request["tool_results"] == []


@pytest.mark.parametrize(
    "text",
    [
        '{"title": "a"}',
        '好的：\n```json\n{"title": "b"}\n```\n完毕',
        '解释一下 {"title": "c", "prompts": {}} 就这些',
    ],
)
def test_extract_json_tolerates_fences_and_prose(text):
    assert "title" in extract_json(text)


def test_extract_json_rejects_non_json():
    with pytest.raises(ValueError, match="没有找到合法的 JSON"):
        extract_json("模型没有按格式输出")
    with pytest.raises(ValueError, match="为空"):
        extract_json("   ")


def test_parse_draft_normalizes_and_validates():
    draft = parse_draft(GOOD_DRAFT)
    assert draft["title"] == "雨夜便利店"
    assert set(draft["prompts"]) == {"pre", "narrator", "settler"}
    assert [entry["id"] for entry in draft["worldbook"]] == ["world_tone", "backroom"]
    assert draft["worldbook"][0]["always_on"] is True
    assert draft["worldbook"][1]["keywords"] == ["后仓", "冷库", "那扇门"]
    skill = draft["skills"][0]
    assert skill["id"] == "observe"
    assert skill["targets"] == ["scene"]
    assert skill["brief"] == "侦察环境"
    assert draft["warnings"] == []


def test_parse_draft_fixes_bad_fields_and_warns():
    draft = parse_draft(
        {
            "title": "x",
            "prompts": {"pre": "前置" * 40},
            "worldbook": [
                {"id": "World Tone", "content": "基调" * 40, "priority": 500, "always_on": True},
                {"id": "empty", "title": "空", "content": "   "},
                "不是对象",
            ],
            "skills": [
                {"id": "观察", "name": "观察", "cost": {"mana": 3, "hp": -1}, "targets": ["bad"], "cooldown": 1000}
            ],
        }
    )
    entry = draft["worldbook"][0]
    assert entry["id"] == "world_tone"
    assert entry["priority"] == 100
    skill = draft["skills"][0]
    assert skill["id"] == "skill_1"
    assert skill["cost"] == {}
    assert skill["targets"] == ["self"]
    assert skill["cooldown"] == 99
    assert skill["action_text"] == "观察"
    joined = " ".join(draft["warnings"])
    assert "mana" in joined
    assert "content" in joined
    assert "不是对象" in joined


def test_parse_draft_requires_at_least_one_prompt():
    with pytest.raises(ValueError, match="没有可用的提示词"):
        parse_draft({"title": "x", "prompts": {}})
    with pytest.raises(ValueError, match="必须是一个 JSON 对象"):
        parse_draft(["not", "dict"])  # type: ignore[arg-type]


def test_parse_draft_accepts_aliases_and_nested_payload():
    draft = parse_draft(
        {
            "draft": {
                "title": "别名",
                "prompts": {"前置": "前置" * 40, "narrative": "叙事" * 40, "settlement": "结算" * 40},
                "worldbook": [],
                "skills": [],
            }
        }
    )
    assert set(draft["prompts"]) == {"pre", "narrator", "settler"}
    assert draft["worldbook"] == [] and draft["skills"] == []


def test_parse_draft_accepts_top_level_prompts():
    draft = parse_draft({"title": "顶层", "pre": "前置" * 40, "narrator": "叙事" * 40, "settler": "结算" * 40})
    assert set(draft["prompts"]) == {"pre", "narrator", "settler"}


def test_parse_draft_accepts_prompt_list_and_dict_values():
    draft = parse_draft(
        {
            "title": "列表",
            "prompts": [
                {"role": "pre", "content": ["第一段", "第二段"]},
                {"name": "叙事提示词", "text": "叙事" * 40},
            ],
        }
    )
    assert draft["prompts"]["pre"] == "第一段\n\n第二段"
    assert draft["prompts"]["narrator"] == "叙事" * 40


def test_parse_draft_accepts_loose_prompt_keys_and_wrapper():
    draft = parse_draft(
        {
            "世界构筑": {
                "title": "包装",
                "prompts": {"pre_setting": "前置" * 40, "narrator_prompt_v2": {"content": "叙事" * 40}},
            }
        }
    )
    assert set(draft["prompts"]) == {"pre", "narrator"}


def test_parse_draft_error_lists_top_level_keys():
    with pytest.raises(ValueError, match="顶层键") as exc:
        parse_draft({"title": "x", "worldview": "只有世界观", "characters": []})
    assert "worldview" in str(exc.value)


def test_draft_summary_counts():
    summary = draft_summary(parse_draft(GOOD_DRAFT))
    assert summary["worldbook_count"] == 2
    assert summary["skill_count"] == 1
    assert summary["prompt_keys"] == ["pre", "narrator", "settler"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_parse_user_glass_magic_preserves_nested_worldbook_and_skills(wrapped):
    import json

    raw = json.loads((ROOT / "tests/fixtures/glass_magic_nested_prompts.json").read_text(encoding="utf-8"))
    draft = parse_draft({"draft": raw} if wrapped else raw)
    assert draft["title"] == "琉璃魔法纪"
    assert draft["prompts"] == {key: raw["prompts"][key] for key in ("pre", "narrator", "settler")}
    assert len(draft["worldbook"]) == 6
    assert len(draft["skills"]) == 4
    for actual, expected in zip(draft["worldbook"], raw["prompts"]["worldbook"], strict=True):
        assert all(actual[key] == value for key, value in expected.items())
    for actual, expected in zip(draft["skills"], raw["prompts"]["skills"], strict=True):
        assert all(actual[key] == value for key, value in expected.items())
    assert any("prompts.worldbook" in item for item in draft["warnings"])
    assert any("prompts.skills" in item for item in draft["warnings"])
    # Preview -> apply normalizes twice; the second pass must retain all content.
    reapplied = parse_draft(draft)
    assert reapplied["worldbook"] == draft["worldbook"]
    assert reapplied["skills"] == draft["skills"]


@pytest.mark.parametrize("container", ["prompts", "prompt", "提示词", "worldbuilding"])
def test_nested_collection_supports_prompt_aliases(container):
    draft = parse_draft({container: {
        "pre": "前置", "world_book": GOOD_DRAFT["worldbook"], "skills": GOOD_DRAFT["skills"],
    }})
    assert len(draft["worldbook"]) == 2
    assert draft["skills"][0]["id"] == "observe"


@pytest.mark.parametrize("empty", [False, True])
def test_top_level_collections_win_without_merging_or_reviving(empty):
    from copy import deepcopy

    data = deepcopy(GOOD_DRAFT)
    data["prompts"]["worldbook"] = [{"id": "nested", "content": "嵌套条目"}]
    data["prompts"]["skills"] = [{"id": "nested", "name": "嵌套技能"}]
    if empty:
        data["worldbook"] = []
        data["skills"] = []
    draft = parse_draft(data)
    assert len(draft["worldbook"]) == (0 if empty else 2)
    assert len(draft["skills"]) == (0 if empty else 1)
    assert draft["warnings"] == []


def test_invalid_nested_collections_report_normal_validation_warnings():
    draft = parse_draft({"prompts": {
        "pre": "前置", "worldbook": [{"title": "缺正文"}], "skills": [{"description": "缺名称"}],
    }})
    assert draft["worldbook"] == draft["skills"] == []
    assert any("content" in warning for warning in draft["warnings"])
    assert any("name" in warning for warning in draft["warnings"])
