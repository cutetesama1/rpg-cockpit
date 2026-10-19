"""调试台接口：读目录、改状态、改物品、跳场景、学技能、恢复默认。

调试写入必须走账本（`tool.applied` + `turn.committed`），所以能被「撤销上一回合」
回退、也能被回放校验；枚举写错必须 400，数值越界按字段 min/max 夹取。
"""
from __future__ import annotations

from conftest import ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

import sys

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture()
def client():
    client = TestClient(app)
    client.post("/api/reset")
    return client


def _fields(client) -> list[dict]:
    return client.get("/api/debug/catalog").json()["fields"]


def _int_field(client) -> dict:
    for field in _fields(client):
        if field["type"] == "int" and field["min"] is not None and field["max"] is not None:
            return field
    pytest.skip("内容包没有带上下界的整数字段")


def test_catalog_shape(client):
    data = client.get("/api/debug/catalog").json()
    assert data["pack"]["id"] == "night-convenience-store"
    assert data["turn"] == 0
    assert data["fields"], "调试台需要字段清单"
    for field in data["fields"]:
        assert field["id"] and field["label"] is not None and field["type"]
    assert data["state"], "需要当前状态快照"
    assert data["skills"] and data["scenes"]
    assert data["inventory"] == {} or isinstance(data["inventory"], dict)


def test_set_state_writes_turn_and_can_undo(client):
    field = _int_field(client)
    before = client.get("/api/debug/catalog").json()["state"][field["id"]]
    target = field["min"] if before != field["min"] else field["max"]

    result = client.post("/api/debug/state", json={"changes": {field["id"]: target}})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["ok"] is True and body["changed"] == 1
    assert body["status"]["state"][field["id"]] == target
    assert body["status"]["turn"] == 1

    catalog = client.get("/api/debug/catalog").json()
    applied = [event for event in catalog["events"] if event["kind"] == "tool.applied"]
    assert applied and applied[-1]["payload"]["tool"] == "debug.set_state"
    assert applied[-1]["payload"]["changes"][field["id"]]["after"] == target

    undone = client.post("/api/undo").json()
    assert undone["turn"] == 0
    assert client.get("/api/debug/catalog").json()["state"][field["id"]] == before


def test_set_state_rejects_unknown_field_and_bad_enum(client):
    unknown = client.post("/api/debug/state", json={"changes": {"no_such_field": 1}})
    assert unknown.status_code == 400
    assert "no_such_field" in unknown.json()["detail"]

    enum_field = next((f for f in _fields(client) if f.get("enum_values")), None)
    if enum_field is None:
        pytest.skip("内容包没有枚举字段")
    bad = client.post(
        "/api/debug/state", json={"changes": {enum_field["id"]: "definitely-not-a-value"}}
    )
    assert bad.status_code == 400
    assert enum_field["id"] in bad.json()["detail"]


def test_out_of_range_value_is_clamped(client):
    field = _int_field(client)
    result = client.post("/api/debug/state", json={"changes": {field["id"]: field["max"] + 999}})
    assert result.status_code == 200, result.text
    assert result.json()["status"]["state"][field["id"]] == field["max"]


def test_set_inventory_diff_and_jump_scene(client):
    catalog = client.get("/api/debug/catalog").json()
    if not catalog["items"]:
        pytest.skip("内容包没有物品")
    item_id = catalog["items"][0]["id"]
    result = client.post("/api/debug/inventory", json={"item_id": item_id, "count": 3}).json()
    assert result["ok"] is True and result["changed"] == 1
    assert client.get("/api/debug/catalog").json()["inventory"][item_id] == 3

    target = next((scene for scene in catalog["scenes"] if not scene["opening"]), None)
    if target is None:
        pytest.skip("内容包只有一个场景")
    jumped = client.post("/api/debug/scene", json={"scene_id": target["id"]}).json()
    assert jumped["scene_id"] == target["id"]
    assert client.get("/api/debug/catalog").json()["scene_id"] == target["id"]


def test_learn_skill_and_reset(client):
    skill = client.get("/api/debug/catalog").json()["skills"][0]
    learned = client.post("/api/debug/skill", json={"skill_id": skill["id"]}).json()
    assert learned["ok"] is True
    skills = client.get("/api/debug/catalog").json()["skills"]
    assert next(row for row in skills if row["id"] == skill["id"])["learned"] is True

    field = _int_field(client)
    client.post("/api/debug/state", json={"changes": {field["id"]: field["max"]}})
    reset = client.post("/api/debug/reset").json()
    assert reset["ok"] is True and reset["changed"] >= 1
    assert client.get("/api/debug/catalog").json()["state"][field["id"]] == field["default"]
