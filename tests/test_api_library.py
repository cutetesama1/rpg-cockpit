"""API：游戏库（列表/新建/复制/选择）与世界构筑（世界书/技能/提示词）。"""
from __future__ import annotations

import sys

from conftest import ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as api_main  # noqa: E402
from main import app, manager  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_USER_PACKS", str(tmp_path / "packs"))
    monkeypatch.setenv("RPG_LIBRARY", str(tmp_path / "library.json"))
    saved = (
        manager.user_dir,
        manager.pack_dir,
        manager.session,
        dict(manager.library),
        manager.settings,
    )
    manager.user_dir = tmp_path / "packs"
    manager.library = {}
    manager.select("night-convenience-store")
    test_client = TestClient(app)
    test_client.post("/api/reset")
    yield test_client
    (
        manager.user_dir,
        manager.pack_dir,
        manager.session,
        manager.library,
        manager.settings,
    ) = saved


def _library(client):
    data = client.get("/api/library").json()
    assert data["ok"] is True
    return data


def test_library_lists_builtin_packs(client):
    data = _library(client)
    by_id = {row["id"]: row for row in data["packs"]}
    assert "night-convenience-store" in by_id
    night = by_id["night-convenience-store"]
    assert night["builtin"] is True
    assert night["editable"] is False
    assert night["active"] is True
    assert data["active_pack"] == "night-convenience-store"


def test_world_of_builtin_is_read_only(client):
    data = client.get("/api/world").json()
    assert data["ok"] is True
    assert data["editable"] is False
    assert data["worldbook"]
    assert set(data["prompts"]) == {"pre", "narrator", "settler"}
    resp = client.put(
        "/api/world/worldbook", json={"entries": [{"id": "x", "title": "x", "content": "x"}]}
    )
    assert resp.status_code == 400
    assert "只读" in resp.json()["detail"]


def test_clone_builtin_then_edit_worldbook(client):
    cloned = client.post(
        "/api/library/clone",
        json={"source": "night-convenience-store", "title": "我的便利店"},
    )
    assert cloned.status_code == 200
    data = cloned.json()
    assert data["active_pack"] == "我的便利店" or data["active_pack"]
    new_id = data["active_pack"]
    assert new_id != "night-convenience-store"

    world = client.get("/api/world").json()
    assert world["editable"] is True
    assert world["title"] == "我的便利店"

    entries = [
        {
            "id": "my_lore",
            "title": "我的设定",
            "content": "只在玩家提到灯塔时注入。",
            "keywords": ["灯塔"],
        }
    ]
    saved = client.put("/api/world/worldbook", json={"entries": entries})
    assert saved.status_code == 200
    assert saved.json()["warnings"] == []
    assert [entry["id"] for entry in client.get("/api/world").json()["worldbook"]] == [
        "my_lore"
    ]
    # 保存世界书会重建会话（回到开场）
    assert client.get("/api/state").json()["turn"] == 0


def test_clone_then_edit_prompts_and_skills(client):
    client.post(
        "/api/library/clone", json={"source": "night-convenience-store", "title": "副本二"}
    )
    resp = client.put(
        "/api/world/prompts",
        json={
            "pre": "# 新前置\n保持克制。",
            "narrator": "# 新叙事\n用克制的笔触描写场景：声音、温度、光线，别解释超自然；每次给玩家两到三个可执行的具体选项。",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []
    prompts = client.get("/api/world").json()["prompts"]
    assert prompts["pre"].startswith("# 新前置")

    skills = client.get("/api/world").json()["skills"]
    skills.append(
        {
            "id": "look",
            "name": "看看",
            "description": "观察四周",
            "cost": {"stamina": 1},
            "cooldown": 0,
            "targets": ["scene"],
            "action_text": "我看看四周",
            "brief": "观察",
            "category": "探索",
        }
    )
    resp = client.put("/api/world/skills", json={"skills": skills})
    assert resp.status_code == 200
    assert "look" in [skill["id"] for skill in client.get("/api/world").json()["skills"]]


def test_invalid_world_save_returns_400_and_keeps_file(client):
    client.post(
        "/api/library/clone", json={"source": "night-convenience-store", "title": "副本三"}
    )
    before = client.get("/api/world").json()["skills"]
    bad = [dict(before[0], cost={"nope": 1})]
    resp = client.put("/api/world/skills", json={"skills": bad})
    assert resp.status_code == 400
    after = client.get("/api/world").json()["skills"]
    assert [skill["id"] for skill in after] == [skill["id"] for skill in before]


def test_create_new_game_and_select_back(client):
    resp = client.post("/api/library/new", json={"title": "New Adventure"})
    assert resp.status_code == 200
    data = resp.json()
    new_id = data["active_pack"]
    assert new_id == "new-adventure"
    assert data["status"]["pack"]["title"] == "New Adventure"
    assert client.get("/api/state").json()["pack"]["id"] == new_id

    # 新游戏的世界书/提示词可编辑
    assert client.get("/api/world").json()["editable"] is True

    # 重复 id 报错
    dup = client.post("/api/library/new", json={"title": "New Adventure"})
    assert dup.status_code == 400

    # 切回内置包
    back = client.post("/api/library/select", json={"id": "night-convenience-store"})
    assert back.status_code == 200
    assert back.json()["active_pack"] == "night-convenience-store"
    assert client.get("/api/world").json()["editable"] is False


def test_create_new_game_with_explicit_id(client):
    resp = client.post(
        "/api/library/new", json={"title": "指定 id", "id": "my-custom-id"}
    )
    assert resp.status_code == 200
    assert resp.json()["active_pack"] == "my-custom-id"
    packs = {row["id"]: row for row in client.get("/api/library").json()["packs"]}
    assert packs["my-custom-id"]["builtin"] is False


def test_select_unknown_pack_returns_400(client):
    resp = client.post("/api/library/select", json={"id": "no-such-game"})
    assert resp.status_code == 400
    assert "找不到" in resp.json()["detail"]


def test_health_reports_pack_editable(client):
    data = client.get("/api/health").json()
    assert data["version"].startswith("0.998")
    assert data["pack"] == "night-convenience-store"
    assert data["pack_editable"] is False


def _import_zip(pack_id: str) -> dict:
    """把一个改了 id 的样例包打成 zip，按 API 格式（base64）返回请求体。"""
    import base64
    import io
    import json
    import zipfile

    from conftest import PACK_DIR

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACK_DIR.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(PACK_DIR).as_posix()
            if relative == "manifest.json":
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["id"] = pack_id
                manifest["title"] = f"导入测试 {pack_id}"
                archive.writestr("payload/" + relative, json.dumps(manifest, ensure_ascii=False))
            else:
                archive.writestr("payload/" + relative, path.read_bytes())
    return {
        "filename": f"{pack_id}.zip",
        "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def test_import_pack_then_select(client):
    result = client.post("/api/library/import", json=_import_zip("imported-night")).json()
    assert result["ok"] is True
    assert result["pack"]["id"] == "imported-night"
    assert result["pack"]["builtin"] is False

    ids = [item["id"] for item in client.get("/api/library").json()["packs"]]
    assert "imported-night" in ids
    # 导入后能切换过去，说明目录结构/校验都通过
    selected = client.post("/api/library/select", json={"id": "imported-night"}).json()
    assert selected["ok"] is True
    assert selected["status"]["pack"]["id"] == "imported-night"
    assert selected["status"]["turn"] == 0


def test_import_pack_rejects_bad_base64(client):
    resp = client.post("/api/library/import", json={"data_base64": "这不是 base64"})
    assert resp.status_code == 400
    assert "base64" in resp.json()["detail"]


def test_import_pack_rejects_broken_zip(client):
    import base64

    payload = base64.b64encode(b"definitely not a zip").decode("ascii")
    resp = client.post("/api/library/import", json={"data_base64": payload})
    assert resp.status_code == 400
    assert "zip" in resp.json()["detail"]
