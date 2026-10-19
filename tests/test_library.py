"""游戏库：扫描/新建/复制/选择/库文件，以及世界构筑的保存与回滚。"""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import PACK_DIR

from rpg_content import PackError, load_pack
from rpg_content.library import (
    clone_pack,
    create_pack,
    find_pack,
    import_pack_zip,
    list_packs,
    load_library,
    resolve_pack_dir,
    save_library,
    save_prompts,
    save_skills,
    save_worldbook,
    slugify,
    user_packs_dir,
    world_payload,
)

BUILTIN = PACK_DIR.parent


# -- 扫描 / 库 --------------------------------------------------------------
def test_list_packs_includes_builtin(tmp_path):
    packs = list_packs(BUILTIN, tmp_path)
    ids = {pack.id for pack in packs}
    assert "night-convenience-store" in ids
    assert "probe-signal-station" in ids
    night = next(pack for pack in packs if pack.id == "night-convenience-store")
    assert night.builtin is True
    assert night.valid is True
    assert night.worldbook_entries >= 1


def test_list_packs_reports_broken_pack(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    packs = list_packs(BUILTIN, tmp_path)
    row = next(pack for pack in packs if pack.id == "broken")
    assert row.valid is False
    assert "manifest" in row.error


def test_user_pack_overrides_builtin(tmp_path):
    target = create_pack(
        tmp_path, pack_id="night-convenience-store", title="我的便利店"
    )
    assert target.is_dir()
    packs = list_packs(BUILTIN, tmp_path)
    matches = [pack for pack in packs if pack.id == "night-convenience-store"]
    assert len(matches) == 1
    assert matches[0].builtin is False
    assert matches[0].title == "我的便利店"


def test_create_pack_and_resolve(tmp_path):
    create_pack(tmp_path, pack_id="my-game", title="我的游戏")
    assert (tmp_path / "my-game" / "manifest.json").is_file()
    path = resolve_pack_dir("my-game", BUILTIN, tmp_path)
    assert path == (tmp_path / "my-game").resolve()
    info = find_pack("my-game", BUILTIN, tmp_path)
    assert info is not None and info.title == "我的游戏"


def test_create_pack_rejects_duplicate_and_bad_id(tmp_path):
    create_pack(tmp_path, pack_id="dup", title="重复")
    with pytest.raises(FileExistsError):
        create_pack(tmp_path, pack_id="dup", title="重复2")
    with pytest.raises(ValueError):
        create_pack(tmp_path, pack_id="Bad ID", title="x")
    with pytest.raises(ValueError):
        create_pack(tmp_path, pack_id="bad-title", title="   ")


def test_clone_pack_copies_content_and_rewrites_manifest(tmp_path):
    target = clone_pack(
        PACK_DIR, tmp_path, pack_id="night-copy", title="便利店副本"
    )
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "night-copy"
    assert manifest["title"] == "便利店副本"
    pack = load_pack(target)
    assert [skill.id for skill in pack.skills] == ["smash", "first_aid", "observe"]
    assert len(pack.scenes) == 10  # P4 第一晚：10 场景
    # 原包不受影响
    assert load_pack(PACK_DIR).manifest.id == "night-convenience-store"


def test_slugify():
    assert slugify("My New Game!") == "my-new-game"
    assert slugify("凌晨便利店") == "new-game"


def _pack_zip_bytes(source, prefix: str = "", pack_id: str | None = None) -> bytes:
    """把内容包目录打成 zip（可选改写 manifest.id、包一层目录）。"""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            if relative == "manifest.json" and pack_id is not None:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["id"] = pack_id
                archive.writestr(prefix + relative, json.dumps(manifest, ensure_ascii=False))
            else:
                archive.writestr(prefix + relative, path.read_bytes())
    return buffer.getvalue()


def test_import_pack_zip_roundtrip(tmp_path):
    data = _pack_zip_bytes(PACK_DIR, prefix="my-pack/", pack_id="imported-night")
    info = import_pack_zip(data, tmp_path)
    assert info.id == "imported-night"
    assert info.builtin is False
    assert info.valid is True
    assert (tmp_path / "imported-night" / "manifest.json").is_file()
    pack = load_pack(tmp_path / "imported-night")
    assert [skill.id for skill in pack.skills] == ["smash", "first_aid", "observe"]
    # 同名再导入要报错，不能覆盖已有包
    with pytest.raises(PackError, match="已存在"):
        import_pack_zip(data, tmp_path)


def test_import_pack_zip_rejects_bad_archives(tmp_path):
    import io
    import zipfile

    with pytest.raises(PackError, match="不是有效的 zip"):
        import_pack_zip(b"not a zip at all", tmp_path)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hi")
    with pytest.raises(PackError, match="manifest.json"):
        import_pack_zip(buffer.getvalue(), tmp_path)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"id": "evil", "title": "x"}))
        archive.writestr("../escape.txt", "boom")
    with pytest.raises(PackError, match="非法路径"):
        import_pack_zip(buffer.getvalue(), tmp_path)
    assert not (tmp_path.parent / "escape.txt").exists()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{broken")
    with pytest.raises(PackError, match="manifest"):
        import_pack_zip(buffer.getvalue(), tmp_path)

    # 失败后不应该留下临时目录
    assert [child.name for child in tmp_path.iterdir() if child.name.startswith(".import-")] == []


def test_library_file_roundtrip(tmp_path):
    path = tmp_path / "library.json"
    assert load_library(path) == {"active_pack": ""}
    save_library({"active_pack": "my-game"}, path)
    assert load_library(path)["active_pack"] == "my-game"
    path.write_text("broken", encoding="utf-8")
    assert load_library(path) == {"active_pack": ""}


def test_user_packs_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RPG_USER_PACKS", str(tmp_path / "packs"))
    assert user_packs_dir() == tmp_path / "packs"


# -- 世界构筑保存 ----------------------------------------------------------
@pytest.fixture()
def user_pack(tmp_path):
    return clone_pack(PACK_DIR, tmp_path, pack_id="edit-me", title="可编辑")


def test_world_payload_marks_editable(user_pack):
    payload = world_payload(user_pack, editable=True)
    assert payload["editable"] is True
    assert payload["pack_id"] == "edit-me"
    assert payload["worldbook"]
    assert set(payload["prompts"]) == {"pre", "narrator", "settler"}
    builtin = world_payload(PACK_DIR, editable=False)
    assert builtin["editable"] is False


def test_save_worldbook_roundtrip(user_pack):
    entries = [
        {
            "id": "new_lore",
            "title": "新设定",
            "content": "这是一段新的世界设定。",
            "keywords": ["灯塔"],
            "always_on": False,
            "priority": 10,
            "category": "地点",
        }
    ]
    warnings = save_worldbook(user_pack, entries)
    assert warnings == []
    pack = load_pack(user_pack)
    assert [entry.id for entry in pack.worldbook] == ["new_lore"]


def test_save_worldbook_invalid_restores_file(user_pack):
    before = (user_pack / "vocab" / "worldbook.json").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        save_worldbook(
            user_pack,
            [{"id": "x", "title": "缺", "content": ""}],
        )
    after = (user_pack / "vocab" / "worldbook.json").read_text(encoding="utf-8")
    assert after == before


def test_save_skills_roundtrip(user_pack):
    skills = [
        {
            "id": "look",
            "name": "看看",
            "description": "观察",
            "cost": {"stamina": 1},
            "cooldown": 0,
            "targets": ["scene"],
            "action_text": "我看看四周",
            "effect_hint": "",
            "brief": "观察",
            "category": "探索",
        }
    ]
    save_skills(user_pack, skills)
    pack = load_pack(user_pack)
    assert [skill.id for skill in pack.skills] == ["look"]


def test_save_skills_unknown_cost_field_restores(user_pack):
    before = (user_pack / "vocab" / "skills.json").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        save_skills(
            user_pack,
            [
                {
                    "id": "bad",
                    "name": "坏技能",
                    "cost": {"nope": 1},
                    "targets": ["self"],
                    "action_text": "x",
                }
            ],
        )
    assert (user_pack / "vocab" / "skills.json").read_text(encoding="utf-8") == before


def test_save_prompts_roundtrip(user_pack):
    warnings = save_prompts(
        user_pack,
        {
            "pre": "# 新前置\n保持克制。",
            "narrator": (
                "# 新叙事\n用克制的笔触描写场景：声音、温度、光线，别解释超自然；"
                "每次给玩家两到三个可执行的具体选项，不要替玩家做决定。"
            ),
        },
    )
    assert warnings == []
    pack = load_pack(user_pack)
    assert pack.prompts["pre"].startswith("# 新前置")
    assert pack.prompts["narrator"].startswith("# 新叙事")
    assert "settler" in pack.prompts


def test_save_prompts_rejects_unknown_and_empty(user_pack):
    with pytest.raises(ValueError):
        save_prompts(user_pack, {"nope": "x"})
    with pytest.raises(ValueError):
        save_prompts(user_pack, {"pre": "   "})
