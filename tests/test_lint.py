"""内容包 lint：error 必须拦住，warning 必须说清，strict 模式把 warning 当失败。"""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import PACK_DIR, PROBE_PACK_DIR

from rpg_content import PackError, lint_pack, lint_pack_dir, load_pack


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


def _levels(issues, level: str) -> list[str]:
    return [i.code for i in issues if i.level == level]


@pytest.fixture()
def pack_copy(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(PACK_DIR, target)
    return target


def test_example_pack_lints_clean():
    issues = lint_pack(load_pack(PACK_DIR))
    assert _levels(issues, "error") == [], [i.format() for i in issues]


def test_example_pack_passes_strict():
    assert lint_pack_dir(PACK_DIR) == []
    load_pack(PACK_DIR, lint_warnings=True)


def test_probe_pack_lints_clean():
    issues = lint_pack_dir(PROBE_PACK_DIR)
    assert _levels(issues, "error") == [], [i.format() for i in issues]


def test_ui_unknown_field_is_error(pack_copy):
    layout = json.loads((pack_copy / "ui" / "layout.json").read_text(encoding="utf-8"))
    layout["bars"].append("luck")
    (pack_copy / "ui" / "layout.json").write_text(
        json.dumps(layout, ensure_ascii=False), encoding="utf-8"
    )
    issues = lint_pack_dir(pack_copy)
    assert "ui.field_unknown" in _codes(issues)
    assert any("luck" in i.message for i in issues)


def test_default_out_of_range_is_error(pack_copy):
    state = json.loads((pack_copy / "state.json").read_text(encoding="utf-8"))
    for field in state["fields"]:
        if field["id"] == "hp":
            field["default"] = 999
    (pack_copy / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    assert "state.default_out_of_range" in _codes(lint_pack_dir(pack_copy))


def test_bool_flag_field_mismatch(pack_copy):
    path = pack_copy / "vocab" / "flags.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["flags"].append({"id": "heard_whisper", "label": "听到低语"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded=load_pack(pack_copy)
    assert loaded.state.by_id()['heard_whisper'].type=='bool'
    assert loaded.state.defaults()['heard_whisper'] is False
    assert not [i for i in lint_pack_dir(pack_copy) if i.code=='flag.no_state_field']


def test_bad_scenarios_file(pack_copy):
    (pack_copy / "tests" / "scenarios.json").write_text("{broken", encoding="utf-8")
    issues = lint_pack_dir(pack_copy)
    assert "scenario.bad_json" in _codes(issues)


def test_missing_manifest_becomes_issue(tmp_path):
    empty = tmp_path / "empty-pack"
    empty.mkdir()
    issues = lint_pack_dir(empty)
    assert "pack.load_failed" in _codes(issues)
    assert any("manifest.json" in i.message for i in issues)


def test_lint_has_path_and_format(pack_copy):
    issues = lint_pack_dir(pack_copy)
    assert all(i.level in ("error", "warning") for i in issues)
    for issue in issues:
        assert issue.format()


def test_bad_field_color_is_warning(pack_copy):
    state = json.loads((pack_copy / "state.json").read_text(encoding="utf-8"))
    for field in state["fields"]:
        if field["id"] == "hp":
            field["color"] = "red"
    (pack_copy / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    issues = lint_pack_dir(pack_copy)
    assert "state.bad_color" in _codes(issues)
    assert _levels(issues, "error") == []
    # strict 模式会把 warning 当失败，自定义颜色必须写对
    with pytest.raises(PackError):
        load_pack(pack_copy, lint_warnings=True)


def test_valid_field_colors_roundtrip():
    pack = load_pack(PACK_DIR)
    hp = pack.state.by_id()["hp"]
    assert hp.color == "#ef4444"
    smash = next(skill for skill in pack.skills if skill.id == "smash")
    assert smash.category == "战斗"
    assert smash.brief
