"""空内容包自举：生成的包必须能通过 strict lint、能加载、能用 CLI 跑起来。"""
from __future__ import annotations

import json

import pytest

from rpg_content import lint_pack_dir, load_pack, scaffold_files, scaffold_pack
from rpg_content.cli import main as cli_main

PACK_ID = "demo-signal"
TITLE = "演示：空白信号"


def test_scaffold_files_shape():
    files = scaffold_files(PACK_ID, TITLE)
    for required in (
        "manifest.json",
        "state.json",
        "vocab/skills.json",
        "vocab/items.json",
        "prompts/narrator.md",
        "prompts/settler.md",
        "ui/layout.json",
        "scenes/opening.json",
        "tests/scenarios.json",
    ):
        assert required in files, required
    manifest = json.loads(files["manifest.json"])
    assert manifest["id"] == PACK_ID
    assert manifest["title"] == TITLE


def test_scaffold_files_validate_id_and_title():
    with pytest.raises(ValueError):
        scaffold_files("Bad Id", TITLE)
    with pytest.raises(ValueError):
        scaffold_files(PACK_ID, "  ")


def test_scaffolded_pack_loads_and_lints_clean(tmp_path):
    target = tmp_path / "demo-signal"
    scaffold_pack(target, PACK_ID, TITLE)

    pack = load_pack(target, lint_warnings=True)  # strict：连 warning 都不允许
    assert pack.manifest.id == PACK_ID
    assert [f.id for f in pack.state.fields] == ["hp", "focus", "credits", "flag_started"]
    assert pack.opening.id == "opening"
    assert pack.opening.options
    assert pack.prompts["narrator"] and pack.prompts["settler"]
    # 默认前置提示词：讲述者人设 + 随机事件 + 三输入模式约定
    pre = pack.prompts["pre"]
    assert "大肥鱼" in pre
    assert "随机事件" in pre
    assert "话语" in pre and "动作" in pre and "心理" in pre
    assert "世界修改权限" in pre
    assert lint_pack_dir(target) == []


def test_cli_new_lint_validate(tmp_path, capsys):
    target = tmp_path / "cli-pack"
    assert cli_main(["new", str(target), "--id", "cli-pack", "--title", "CLI 包"]) == 0
    assert (target / "manifest.json").is_file()

    assert cli_main(["validate", str(target)]) == 0
    assert cli_main(["lint", str(target), "--strict"]) == 0
    out = capsys.readouterr().out
    assert "内容包可用" in out


def test_cli_new_refuses_existing_dir(tmp_path, capsys):
    target = tmp_path / "dup-pack"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    assert cli_main(["new", str(target), "--id", "dup-pack", "--title", "重复"]) == 2
    assert "已存在" in capsys.readouterr().err


def test_cli_lint_reports_errors(tmp_path, capsys):
    pack_dir = tmp_path / "broken"
    scaffold_pack(pack_dir, "broken-pack", "坏包")
    (pack_dir / "ui" / "layout.json").write_text(
        json.dumps({"title": "x", "bars": ["nope"]}, ensure_ascii=False), encoding="utf-8"
    )
    assert cli_main(["lint", str(pack_dir)]) == 1
    out = capsys.readouterr().out
    assert "ui.field_unknown" in out


def test_cli_lint_json(tmp_path, capsys):
    pack_dir = tmp_path / "json-pack"
    scaffold_pack(pack_dir, "json-pack", "JSON 包")
    assert cli_main(["lint", str(pack_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == []
