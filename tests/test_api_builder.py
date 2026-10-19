"""API：世界构筑助手（提示词 / 生成草稿 / 一键创建）。"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from conftest import ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as api_main  # noqa: E402
from main import app, manager  # noqa: E402

DRAFT_JSON = {
    "title": "浮城夜航",
    "description": "一座漂在夜里、靠记忆点灯的城市。",
    "prompts": {
        "pre": "这座城市没有白天，只有灯塔一盏盏亮起。" * 6,
        "narrator": "用第二人称、安静的语气叙述，每回合 100~180 字。" * 4,
        "settler": "只有叙事里真的受伤才调用 damage，单次不超过 4 点；不确定就不调用。" * 4,
    },
    "worldbook": [
        {
            "id": "world_tone",
            "title": "夜航基调",
            "content": "城市漂在黑色的海面上，灯光由居民的记忆点燃。" * 2,
            "keywords": [],
            "always_on": True,
            "priority": 100,
            "category": "基调",
        },
        {
            "id": "lighthouse",
            "title": "灯塔",
            "content": "每座灯塔都对应一个还愿意记得的人。" * 2,
            "keywords": ["灯塔", "灯光"],
            "priority": 50,
            "category": "地点",
        },
    ],
    "skills": [
        {
            "id": "night_walk",
            "name": "夜行",
            "description": "沿着没点灯的路往前走",
            "cost": {"focus": 2},
            "cooldown": 1,
            "targets": ["scene"],
            "action_text": "你沿着没点灯的路往前走",
            "effect_hint": "可能发现新地点",
            "category": "探索",
            "brief": "沿暗路前进",
        }
    ],
}


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


def test_builder_prompt_endpoint(client):
    data = client.get("/api/world/builder/prompt").json()
    assert data["ok"] is True
    assert "前置提示词" in data["prompt"]
    assert data["state_fields"] == ["hp", "focus", "credits"]
    assert "scene" in data["targets"]
    assert data["prompt_keys"] == ["pre", "narrator", "settler"]


def test_builder_generate_parses_model_output(client, monkeypatch):
    import json

    raw = "好的，这是草稿：\n```json\n" + json.dumps(DRAFT_JSON, ensure_ascii=False) + "\n```"
    fake_router = SimpleNamespace(
        complete=lambda role, request: SimpleNamespace(
            raw=raw,
            narrator=None,
            model="fake-model",
            provider="fake",
            usage={"total_tokens": 12},
            latency_ms=1.5,
        )
    )
    monkeypatch.setattr(api_main, "build_router", lambda settings: fake_router)
    data = client.post(
        "/api/world/builder/generate",
        json={"material": "一座漂在海上的城市，居民用记忆点灯，主角是守塔人。"},
    ).json()
    assert data["ok"] is True
    assert data["draft"]["title"] == "浮城夜航"
    assert data["summary"]["worldbook_count"] == 2
    assert data["summary"]["skill_count"] == 1
    assert data["model"] == "fake-model"


def test_builder_generate_rejects_short_material_and_bad_output(client):
    short = client.post("/api/world/builder/generate", json={"material": "太短"})
    assert short.status_code == 400
    assert "素材太短" in short.json()["detail"]

    fake_router = SimpleNamespace(
        complete=lambda role, request: SimpleNamespace(
            raw="模型跑了但没有 JSON",
            narrator=None,
            model="fake",
            provider="fake",
            usage={},
            latency_ms=1.0,
        )
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api_main, "build_router", lambda settings: fake_router)
    try:
        bad = client.post("/api/world/builder/generate", json={"material": "一段足够长的素材" * 5})
        assert bad.status_code == 400
        detail = bad.json()["detail"]
        assert "JSON" in detail
        assert "模型实际返回的开头" in detail
        assert "模型跑了但没有 JSON" in detail
    finally:
        monkeypatch.undo()


def test_builder_apply_creates_and_activates_pack(client):
    data = client.post("/api/world/builder/apply", json={"draft": DRAFT_JSON}).json()
    assert data["ok"] is True
    # 中文标题没有 ascii 骨架：退化为 world-<hash>，仍可读且唯一
    assert data["pack_id"].startswith("world-") and len(data["pack_id"]) == 14
    world = client.get("/api/world").json()
    assert world["editable"] is True
    assert world["title"] == "浮城夜航"
    assert len(world["worldbook"]) == 2
    assert world["skills"][0]["id"] == "night_walk"
    assert world["prompts"]["pre"]
    manifest = world["manifest"]
    assert manifest["description"] == DRAFT_JSON["description"]
    status = client.get("/api/state").json()
    assert status["turn"] == 0
    library = client.get("/api/library").json()
    assert library["active_pack"] == data["pack_id"]
    row = {r["id"]: r for r in library["packs"]}[data["pack_id"]]
    assert row["editable"] is True and row["active"] is True


def test_builder_apply_title_override_and_explicit_id(client):
    data = client.post(
        "/api/world/builder/apply",
        json={"draft": {"prompts": {"pre": "只有前置" * 30}, "worldbook": [], "skills": []}, "title": "我的世界", "id": "my-world"},
    ).json()
    assert data["pack_id"] == "my-world"
    world = client.get("/api/world").json()
    assert world["title"] == "我的世界"
    # 草稿没给叙事/结算时保留模板默认值，不阻塞创建
    assert world["prompts"]["pre"].strip()
    assert world["prompts"]["narrator"].strip()


def test_builder_apply_validation_errors(client):
    missing_prompt = client.post("/api/world/builder/apply", json={"draft": {"title": "x", "prompts": {}}})
    assert missing_prompt.status_code == 400
    assert "提示词" in missing_prompt.json()["detail"]

    no_title = client.post("/api/world/builder/apply", json={"draft": {"prompts": {"pre": "前置" * 30}}})
    assert no_title.status_code == 400
    assert "作品名" in no_title.json()["detail"]

    first = client.post("/api/world/builder/apply", json={"draft": DRAFT_JSON, "id": "dup-world"})
    assert first.status_code == 200
    again = client.post("/api/world/builder/apply", json={"draft": DRAFT_JSON, "id": "dup-world"})
    assert again.status_code == 400


@pytest.mark.parametrize("via_preview", [False, True])
def test_user_nested_draft_reaches_world_state_context_and_skill_runtime(client, monkeypatch, via_preview):
    import json
    from conftest import say
    from rpg_content import load_pack

    raw_text = (ROOT / "tests/fixtures/glass_magic_nested_prompts.json").read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    preview = client.post("/api/world/builder/parse", json={"text": raw_text})
    assert preview.status_code == 200
    preview = preview.json()
    assert preview["summary"]["worldbook_count"] == 6
    assert preview["summary"]["skill_count"] == 4
    assert len(preview["summary"]["warnings"]) == 2
    applied = client.post("/api/world/builder/apply", json={
        "draft": preview["draft"] if via_preview else raw, "id": "glass-magic-test",
    })
    assert applied.status_code == 200
    world = client.get("/api/world").json()
    status = client.get("/api/state").json()
    assert world["title"] == "琉璃魔法纪"
    assert len(world["worldbook"]) == 6
    assert len(world["skills"]) == len(status["skills"]) == 4
    assert {skill["id"] for skill in status["skills"]} == {
        "small_barrier", "levitate_shard", "glow_light", "steady_breath",
    }
    assert all(skill["available"] for skill in status["skills"])
    # Reload the files, rather than relying only on the preview/in-memory objects.
    loaded = load_pack(manager.pack_dir)
    assert len(loaded.worldbook) == 6
    assert len(loaded.skills) == 4
    library = client.get("/api/library").json()
    row = next(row for row in library["packs"] if row["id"] == "glass-magic-test")
    assert row["worldbook_entries"] == 6 and row["skills"] == 4
    assembler = manager.session.assembler
    lore = assembler.select_lore(action={"kind": "text", "text": "看天"})
    assert [item["id"] for item in lore] == ["world_tone"]
    lore = assembler.select_lore(action={"kind": "text", "text": "我到琉璃港找导师莉瑟"})
    assert {item["id"] for item in lore} >= {"world_tone", "location_glass_harbor", "npc_mentor_lise"}
    requests = []
    def complete(role, request):
        requests.append(request)
        if request.get("phase")=="settlement":
            from rpg_core.settlement import DOMAINS
            from rpg_gateway import LlmResponse
            from rpg_core.contracts import ToolCall
            return LlmResponse(tool_calls=[ToolCall(id="noop",name="settle_turn",args={"checked":list(DOMAINS),"operations":[]})])
        return say("你画出的光盾轻轻一震，琉璃色微光挡住了迎面的碎屑。")
    monkeypatch.setattr(manager.session.router, "complete", complete)
    focus = status["state"]["focus"]
    used = client.post("/api/action", json={"action": {"kind": "skill", "skill_id": "small_barrier"}})
    assert used.status_code == 200 and used.json()["ok"] is True
    after = client.get("/api/state").json()
    assert after["state"]["focus"] == focus - 2
    skill = next(skill for skill in after["skills"] if skill["id"] == "small_barrier")
    assert skill["cooldown_remaining"] > 0 and not skill["available"]
    assert "小型屏障" in requests[0]["vocab"]
    assert "琉璃群岛基调" in requests[0]["lore_brief"]
    assert world["prompts"]["pre"].strip() == raw["prompts"]["pre"]
