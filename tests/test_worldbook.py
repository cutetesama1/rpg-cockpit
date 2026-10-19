"""世界书 / 前置提示词：选中规则、上下文注入、系统提示词拼接、lint。"""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import PACK_DIR

from rpg_content import PackError, lint_pack_dir, load_pack
from rpg_core.context import ContextAssembler


@pytest.fixture()
def pack():
    return load_pack(PACK_DIR)


@pytest.fixture()
def assembler(pack):
    return ContextAssembler(pack)


def _ids(lore: list[dict]) -> list[str]:
    return [item["id"] for item in lore]


def test_always_on_entries_are_always_selected(assembler):
    lore = assembler.select_lore(action={"kind": "text", "text": "我抬头看天花板"})
    assert "world_tone" in _ids(lore)
    assert lore[0]["id"] == "world_tone"


def test_keyword_hit_selects_entry(assembler):
    lore = assembler.select_lore(action={"kind": "text", "text": "我走向便利店的后仓"})
    ids = _ids(lore)
    assert "store" in ids
    assert "backroom_lore" in ids
    # 没有提到店员/收银台，人物条目不应命中
    assert "clerk" not in ids


def test_scene_text_participates_in_matching(assembler):
    lore = assembler.select_lore(
        action={"kind": "text", "text": "我看看四周"},
        scene_text="收银台后面站着一个人",
    )
    assert "clerk" in _ids(lore)


def test_priority_ordering_always_on_first(assembler):
    lore = assembler.select_lore(action={"kind": "text", "text": "便利店 店员 后仓"})
    ids = _ids(lore)
    assert ids[0] == "world_tone"
    priorities = [item["priority"] for item in lore]
    assert priorities == sorted(priorities, reverse=True)


def test_max_entries_limits_injection(assembler):
    lore = assembler.select_lore(
        action={"kind": "text", "text": "便利店 店员 后仓"}, max_entries=2
    )
    assert len(lore) == 2


def test_disabled_entry_is_skipped(pack):
    entries = [
        entry.model_copy(update={"enabled": entry.id != "store"})
        for entry in pack.worldbook
    ]
    patched = pack.model_copy(update={"worldbook": entries})
    lore = ContextAssembler(patched).select_lore(
        action={"kind": "text", "text": "便利店"}
    )
    assert "store" not in _ids(lore)
    assert "world_tone" in _ids(lore)


def test_system_prompt_puts_pre_first(pack):
    prompt = ContextAssembler(pack).system_prompt()
    pre = pack.prompts["pre"].strip()
    assert prompt.startswith("# 前置设定")
    assert pre.splitlines()[0] in prompt
    assert "# 结算规则" not in prompt
    assert pack.prompts["settler"].strip() not in prompt


def test_build_exposes_lore_and_brief(assembler, pack):
    request = assembler.build(
        turn=1,
        action={"kind": "text", "text": "我走进便利店"},
        state={"hp": 20},
        events=[],
        scene_id="opening",
    )
    assert request["lore"]
    assert "【" in request["lore_brief"]
    assert request["system_prompt"].startswith("# 前置设定")
    assert request["scene_id"] == "opening"


def test_worldbook_lint_codes(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(PACK_DIR, target)
    path = target / "vocab" / "worldbook.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {"id": "Bad-ID", "title": "", "content": "", "keywords": []},
                    {"id": "ok_entry", "title": "正常", "content": "设定", "keywords": ["x"]},
                    {"id": "ok_entry", "title": "重复", "content": "设定", "keywords": ["y"]},
                    {"id": "nolore", "title": "空", "content": "  ", "keywords": []},
                    {"id": "never", "title": "不触发", "content": "内容", "keywords": []},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    codes = {issue.code for issue in lint_pack_dir(target)}
    assert "worldbook.duplicate_id" in codes
    assert "worldbook.id_invalid" in codes
    assert "worldbook.title_empty" in codes
    assert "worldbook.content_empty" in codes
    assert "worldbook.never_triggers" in codes


def test_missing_worldbook_file_is_optional(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(PACK_DIR, target)
    (target / "vocab" / "worldbook.json").unlink()
    loaded = load_pack(target, lint_warnings=True)
    assert loaded.worldbook == []
