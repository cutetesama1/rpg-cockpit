"""API 测试：健康、会话、动作、撤销、回放、重置。"""
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


def test_health(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True
    assert data["pack"] == "night-convenience-store"


def test_reset_returns_opening(client):
    data = client.post("/api/reset").json()
    assert data["turn"] == 0
    assert data["state"]["hp"] == 20
    assert data["opening"]["options"]


def test_action_and_undo(client):
    result = client.post(
        "/api/action", json={"action": {"kind": "skill", "skill_id": "smash"}}
    ).json()
    assert result["ok"] is True
    assert result["state"]["hp"] == 13
    assert result["narrative"]
    assert len(result["events"]) >= 5

    undo = client.post("/api/undo").json()
    assert undo["ok"] is True
    assert undo["state"]["hp"] == 20


def test_action_with_input_mode_and_extras(client):
    """输入模式与附加请求随 action 一起落账，回放仍一致。"""
    result = client.post(
        "/api/action",
        json={
            "action": {
                "kind": "text",
                "text": "推开玻璃门",
                "mode": "action",
                "extras": ["inspect", "task"],
            }
        },
    ).json()
    assert result["ok"] is True
    started = next(e for e in result["events"] if e["kind"] == "turn.started")
    assert started["payload"]["action"]["mode"] == "action"
    assert started["payload"]["action"]["extras"] == ["inspect", "task"]
    state = client.get("/api/state").json()
    assert state["turn"] == 1
    assert client.get("/api/replay/verify").json()["equal"] is True


def test_replay_verify(client):
    client.post("/api/action", json={"action": {"kind": "skill", "skill_id": "smash"}})
    data = client.get("/api/replay/verify").json()
    assert data["equal"] is True
    assert data["diff"] == {}


def test_action_stream_emits_events_then_result(client):
    """SSE：回合内事件实时推送，最后推 result；链路与同步 API 等价。"""
    with client.stream(
        "POST",
        "/api/action/stream",
        json={"action": {"kind": "skill", "skill_id": "smash"}},
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: event" in body
    assert "event: result" in body
    assert "turn.started" in body
    assert "turn.committed" in body
    assert '"ok": true' in body
    assert client.get("/api/replay/verify").json()["equal"] is True
    assert client.get("/api/state").json()["state"]["hp"] == 13


def test_state_reports_usage(client):
    client.post("/api/action", json={"action": {"kind": "skill", "skill_id": "smash"}})
    status = client.get("/api/state").json()
    usage = status["usage"]
    assert usage["calls"] >= 1
    usage_events = [e for e in status["events"] if e["kind"] == "llm.usage"]
    assert usage_events
    assert usage_events[0]["payload"]["provider"] == "scripted"


def test_narrative_never_shows_numbers(client):
    result = client.post(
        "/api/action", json={"action": {"kind": "text", "text": "报数看看"}}
    ).json()
    assert result["ok"] is True
    assert "生命 7" not in result["narrative"]
    assert result["leaks"] == []


def test_guardrail_rejection_keeps_state(client):
    before = client.get("/api/state").json()["state"]
    result = client.post(
        "/api/action", json={"action": {"kind": "skill", "skill_id": "unknown"}}
    ).json()
    assert result["ok"] is False
    assert result["state"] == before
    assert any("未知技能" in error for error in result["errors"])


def test_invalid_body_returns_422(client):
    response = client.post("/api/action", json={"action": "not-a-dict"})
    assert response.status_code == 422


# -- 模型设置 ---------------------------------------------------------------
def test_get_settings_masks_keys(client):
    data = client.get("/api/settings").json()
    assert data["ok"] is True
    assert data["roles"]["separated"] is False
    assert "openai" in data["providers"]
    assert "api_key" not in data["providers"]["openai"]


def test_update_settings_rejects_unknown_provider(client):
    response = client.post(
        "/api/settings", json={"roles": {"narrator": {"provider": "nope"}}}
    )
    assert response.status_code == 400


def test_update_settings_persists_and_rebuilds(client):
    response = client.post(
        "/api/settings",
        json={"roles": {"narrator": {"provider": "scripted", "temperature": 0.2}}},
    )
    assert response.status_code == 200
    state = client.get("/api/state").json()
    assert state["llm"]["roles"]["narrator"]["provider"] == "scripted"
    assert state["llm"]["roles"]["narrator"]["temperature"] == 0.2
    assert client.get("/api/replay/verify").json()["equal"] is True
    client.post("/api/settings/reset")


def test_settings_test_scripted(client):
    data = client.post("/api/settings/test", json={}).json()
    assert data["ok"] is True
    assert data["provider"] == "scripted"


def test_settings_test_bad_endpoint(client):
    data = client.post(
        "/api/settings/test",
        json={
            "roles": {"narrator": {"provider": "openai"}},
            "providers": {
                "openai": {"base_url": "http://127.0.0.1:1/v1", "model": "x"}
            },
        },
    ).json()
    assert data["ok"] is False
    assert data["error"]


# -- 模型选择（供应商预设 + 思考强度）--------------------------------------
def test_models_catalog_endpoint(client):
    data = client.get("/api/models").json()
    assert data["ok"] is True
    ids = [preset["id"] for preset in data["presets"]]
    for expected in ("deepseek", "chatgpt", "gemini", "grok", "custom"):
        assert expected in ids
    assert data["custom_preset"] == "custom"
    assert {row["id"] for row in data["efforts"]} == {"", "low", "medium", "high"}


def test_settings_payload_includes_catalog_and_active_provider(client):
    data = client.get("/api/settings").json()
    assert data["catalog"]["presets"]
    assert data["active_provider"] == "scripted"
    view = data["providers"]["openai"]
    assert "preset" in view and "reasoning_effort" in view


def test_update_settings_selects_provider_model_and_effort(client):
    response = client.post(
        "/api/settings",
        json={
            "roles": {
                "narrator": {"provider": "deepseek"},
                "settler": {"provider": "deepseek"},
            },
            "providers": {
                "deepseek": {
                    "preset": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-reasoner",
                    "reasoning_effort": "medium",
                }
            },
        },
    )
    assert response.status_code == 200

    state = client.get("/api/state").json()
    narrator = state["llm"]["roles"]["narrator"]
    assert narrator["provider"] == "deepseek"
    assert narrator["preset"] == "deepseek"
    assert narrator["preset_label"] == "DeepSeek"
    assert narrator["model"] == "deepseek-reasoner"
    assert narrator["reasoning_effort"] == "medium"

    health = client.get("/api/health").json()
    assert health["version"] == "0.995"
    assert health["llm"]["roles"]["narrator"]["reasoning_effort"] == "medium"
    client.post("/api/settings/reset")


def test_update_settings_rejects_bad_preset_and_effort(client):
    bad_preset = client.post(
        "/api/settings", json={"providers": {"openai": {"preset": "claude"}}}
    )
    assert bad_preset.status_code == 400
    assert "未知的模型供应商" in bad_preset.json()["detail"]

    bad_effort = client.post(
        "/api/settings", json={"providers": {"openai": {"reasoning_effort": "extreme"}}}
    )
    assert bad_effort.status_code == 400
    assert "未知的思考强度" in bad_effort.json()["detail"]


def test_action_with_segments_and_picked_skills(client):
    """分段输入 + 勾选技能一起提交：一次扣费、一个回合、回放一致。"""
    result = client.post(
        "/api/action",
        json={
            "action": {
                "kind": "text",
                "text": "推开门，喊了一句「有人吗」",
                "segments": [
                    {"mode": "action", "text": "推开门"},
                    {"mode": "speech", "text": "有人吗"},
                ],
                "skills": [
                    {"skill_id": "smash", "name": "撬棍击打"},
                    {"skill_id": "first_aid", "name": "急救包扎"},
                ],
            }
        },
    ).json()
    assert result["ok"] is True
    assert result["state"]["stamina"] == 7
    started = next(e for e in result["events"] if e["kind"] == "turn.started")
    assert started["payload"]["action"]["segments"][1]["text"] == "有人吗"
    assert [s["skill_id"] for s in started["payload"]["action"]["skills"]] == [
        "smash",
        "first_aid",
    ]
    used = [e for e in result["events"] if e["kind"] == "skill.used"]
    assert len(used) == 2
    state = client.get("/api/state").json()
    assert state["turn"] == 1
    assert client.get("/api/replay/verify").json()["equal"] is True


def test_opening_endpoint_generates_once(client):
    """新游戏开局：可生成开场叙述，重复请求幂等，不占回合。"""
    first = client.post("/api/opening").json()
    assert first["ok"] is True
    assert first["generated"] is True
    assert first["narrative"]
    assert first["status"]["turn"] == 0
    assert first["status"]["opening_generated"] is True

    second = client.post("/api/opening").json()
    assert second["generated"] is False
    assert second["narrative"] == first["narrative"]

    state = client.get("/api/state").json()
    assert state["turn"] == 0
    assert state["opening_generated"] is True
    assert client.get("/api/replay/verify").json()["equal"] is True


@pytest.mark.parametrize("opening", [False, True])
def test_public_narrative_snapshots_precede_committed_result(client, monkeypatch, opening):
    import json
    from conftest import say
    from main import manager
    from rpg_gateway import LlmRouter

    router = manager.session.router
    def stream(role, request, on_text):
        on_text("第一段")
        on_text("第一段，第二段。")
        return say("第一段，第二段。")
    monkeypatch.setattr(router, "stream", stream)
    response = client.post("/api/opening/stream" if opening else "/api/action/stream",
        json={} if opening else {"action": {"kind": "skill", "skill_id": "observe"}})
    assert response.status_code == 200
    frames = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event:"):
            frames.append((lines[0][7:], json.loads(lines[1][6:])))
    previews = [(i, data) for i, (kind, data) in enumerate(frames) if kind == "narrative" and data["text"]]
    result_index = next(i for i, (kind, _) in enumerate(frames) if kind == "result")
    committed_index = next(i for i, (kind, data) in enumerate(frames)
        if kind == "event" and data["kind"] == "narrative.generated")
    assert previews[0][1]["text"] == "第一段"
    assert previews[0][0] < committed_index < result_index
    result = frames[result_index][1]
    assert result["ok"] and result["narrative"] == "第一段，第二段。"
    assert manager.session.on_event is None and manager.session.on_narrative is None
    events = client.get("/api/state").json()["events"]
    assert len([e for e in events if e["kind"] == "narrative.generated"]) == 1
    assert not any(e["kind"] == "narrative" for e in events)


def test_stream_rollback_retracts_text_and_restores_state(client, monkeypatch):
    from main import manager
    before = dict(manager.session.state)
    def stream(role, request, on_text):
        on_text("还在生成的内容")
        raise RuntimeError("模拟流式断线")
    monkeypatch.setattr(manager.session.router, "stream", stream)
    response = client.post("/api/action/stream", json={"action": {"kind": "skill", "skill_id": "observe"}})
    assert '"text": "还在生成的内容"' in response.text
    assert response.text.rfind('"text": ""') > response.text.find('还在生成的内容')
    assert '"ok": false' in response.text
    assert manager.session.state == before
    assert manager.session.on_narrative is None
