"""内容包校验：坏包必须给出明确错误，不静默通过。"""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import PACK_DIR

from rpg_content import PackError, load_pack


@pytest.fixture()
def pack_copy(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(PACK_DIR, target)
    return target


def test_missing_manifest(pack_copy):
    (pack_copy / "manifest.json").unlink()
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "manifest.json" in str(exc.value)


def test_missing_prompt(pack_copy):
    (pack_copy / "prompts" / "narrator.md").unlink()
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "narrator" in str(exc.value)


def test_ui_references_unknown_field(pack_copy):
    layout = json.loads((pack_copy / "ui" / "layout.json").read_text(encoding="utf-8"))
    layout["bars"].append("luck")
    (pack_copy / "ui" / "layout.json").write_text(
        json.dumps(layout, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "未声明字段" in str(exc.value)


def test_duplicate_skill_id(pack_copy):
    path = pack_copy / "vocab" / "skills.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skills"].append(dict(data["skills"][0]))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "id 重复" in str(exc.value)


def test_skill_cost_field_must_exist(pack_copy):
    path = pack_copy / "vocab" / "skills.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skills"][0]["cost"] = {"mana": 1}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "mana" in str(exc.value)


def test_invalid_json(pack_copy):
    (pack_copy / "state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_pack(pack_copy)
    assert "JSON" in str(exc.value)
