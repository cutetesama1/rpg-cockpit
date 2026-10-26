"""API 存档：列表/保存/读档/删除 + 自动存档 + 日志导出脱敏。"""
from __future__ import annotations

import json
import sys

from conftest import ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app, manager  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_SAVES", str(tmp_path / "saves"))
    monkeypatch.setenv("RPG_NO_RESUME", "1")
    saved = (manager.pack_dir, manager.session, manager.settings, manager.resumed)
    manager.select("night-convenience-store")
    manager.resumed = False
    test_client = TestClient(app)
    test_client.post("/api/reset")
    yield test_client
    manager.pack_dir, manager.session, manager.settings, manager.resumed = saved


def _skill(client, skill_id: str = "observe"):
    return client.post("/api/action", json={"action": {"kind": "skill", "skill_id": skill_id}}).json()


def test_saves_list_empty(client):
    data = client.get("/api/saves").json()
    assert data["ok"] is True
    assert data["pack_id"] == "night-convenience-store"
    assert data["saves"] == []
    assert data["auto_slot"] == "auto"
    assert data["note"]


def test_manual_save_and_list(client, tmp_path):
    _skill(client)
    created = client.post("/api/saves", json={"slot": "s1", "label": "第一晚"}).json()
    assert created["ok"] is True
    assert created["save"]["turn"] == 1
    assert created["save"]["label"] == "第一晚"
    assert (tmp_path / "saves" / "s1.json").is_file()

    listing = client.get("/api/saves").json()
    slots = [row["slot"] for row in listing["saves"]]
    assert "s1" in slots
    assert "auto" in slots  # 动作成功后自动存档


def test_load_restores_progress(client):
    _skill(client)
    _skill(client)
    client.post("/api/saves", json={"slot": "mid"})
    client.post("/api/reset")
    assert client.get("/api/state").json()["turn"] == 0

    loaded = client.post("/api/saves/load", json={"slot": "mid"}).json()
    assert loaded["ok"] is True
    assert loaded["status"]["turn"] == 2
    assert loaded["status"]["state"]["stamina"] == 10 or loaded["status"]["state"]["stamina"]
    verify = client.get("/api/replay/verify").json()
    assert verify["equal"] is True


def test_load_missing_404(client):
    response = client.post("/api/saves/load", json={"slot": "nope"})
    assert response.status_code == 404


def test_invalid_slot_400(client):
    response = client.post("/api/saves", json={"slot": "../bad"})
    assert response.status_code == 400
    assert "槽位" in response.json()["detail"]


def test_delete_save(client):
    _skill(client)
    client.post("/api/saves", json={"slot": "temp"})
    removed = client.delete("/api/saves/temp").json()
    assert removed["ok"] is True
    assert removed["removed"] is True
    assert all(row["slot"] != "temp" for row in removed["saves"]["saves"])
    again = client.delete("/api/saves/temp").json()
    assert again["removed"] is False


def test_auto_save_after_action(client):
    _skill(client)
    listing = client.get("/api/saves").json()
    auto = [row for row in listing["saves"] if row["slot"] == "auto"]
    assert auto and auto[0]["turn"] == 1 and auto[0]["auto"] is True


def test_health_reports_saves_dir(client, tmp_path):
    data = client.get("/api/health").json()
    assert data["version"] == "0.998"
    assert data["saves_dir"] == str(tmp_path / "saves")
    assert data["resumed"] is False


def test_export_log_masks_api_key(client, tmp_path):
    provider = manager.settings.providers["openai"]
    provider.api_key = "sk-live-1234567890abcdef"
    _skill(client)
    response = client.get("/api/log/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert "sk-live-1234567890abcdef" not in body
    data = json.loads(body)
    assert data["export_version"] == 1
    assert data["pack"]["id"] == "night-convenience-store"
    assert data["events"]
