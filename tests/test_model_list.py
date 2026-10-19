"""读取端点可用模型列表：GET {base_url}/models 的解析 / 错误 / API 端点。

不依赖外网：本地线程里起一个只处理 GET 的假端点。
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import ROOT  # noqa: F401  （注入 core/gateway/content 到 sys.path）

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

from fastapi.testclient import TestClient  # noqa: E402

import main as api_main  # noqa: E402
from main import app, manager  # noqa: E402
from rpg_core.contracts import ProviderSettings  # noqa: E402
from rpg_gateway import ModelListError, list_endpoint_models, models_url  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    """GET /v1/models：按 class 状态回放。"""

    status = 200
    payload: object = {"data": []}
    received: list[dict] = []
    headers: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        type(self).received.append(
            {"path": self.path, "headers": dict(self.headers)}
        )
        raw = json.dumps(type(self).payload, ensure_ascii=False).encode("utf-8")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:  # 静音
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Handler.status = 200
    _Handler.payload = {"data": [{"id": "b-model"}, {"id": "a-model"}, {"id": "a-model"}]}
    _Handler.received = []
    base = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    yield base
    httpd.shutdown()
    httpd.server_close()


def test_models_url_normalizes():
    assert models_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1/models"
    assert models_url("https://api.deepseek.com/v1/models") == "https://api.deepseek.com/v1/models"
    with pytest.raises(ModelListError):
        models_url("   ")
    with pytest.raises(ModelListError):
        models_url("api.deepseek.com/v1")


def test_list_models_sorted_and_deduped(server):
    result = list_endpoint_models(server, "sk-test")
    assert result["count"] == 2
    assert [item["id"] for item in result["models"]] == ["a-model", "b-model"]
    assert result["base_url"] == server
    assert result["latency_ms"] >= 0
    request = _Handler.received[-1]
    assert request["path"] == "/v1/models"
    assert request["headers"].get("Authorization") == "Bearer sk-test"


def test_list_models_http_error_mentions_key(server):
    _Handler.status = 401
    _Handler.payload = {"error": {"message": "invalid api key"}}
    with pytest.raises(ModelListError) as excinfo:
        list_endpoint_models(server, "bad")
    message = str(excinfo.value)
    assert "401" in message
    assert "API Key" in message


def test_list_models_invalid_json(server):
    _Handler.payload = None
    with pytest.raises(ModelListError):
        # None 会序列化成 "null"，不是 {data: [...]}
        list_endpoint_models(server)


def test_list_models_empty_list(server):
    _Handler.payload = {"data": []}
    with pytest.raises(ModelListError) as excinfo:
        list_endpoint_models(server)
    assert "空" in str(excinfo.value)


def test_api_probe_uses_given_key(server):
    client = TestClient(app)
    response = client.post(
        "/api/models/probe",
        json={"base_url": server, "api_key": "sk-probe", "preset": "custom"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert [item["id"] for item in data["models"]] == ["a-model", "b-model"]
    assert _Handler.received[-1]["headers"].get("Authorization") == "Bearer sk-probe"


def test_api_probe_falls_back_to_saved_key(server):
    original = manager.settings
    try:
        manager.settings = original.model_copy(
            update={
                "providers": {
                    **original.providers,
                    "deepseek": ProviderSettings(
                        base_url=server, api_key="saved-key", model="deepseek-chat"
                    ),
                }
            }
        )
        client = TestClient(app)
        response = client.post(
            "/api/models/probe", json={"base_url": server, "preset": "deepseek"}
        )
        assert response.status_code == 200
        assert _Handler.received[-1]["headers"].get("Authorization") == "Bearer saved-key"
    finally:
        manager.settings = original


def test_api_probe_missing_base_url_is_400():
    client = TestClient(app)
    response = client.post("/api/models/probe", json={"preset": "custom"})
    assert response.status_code == 400
    assert "base_url" in response.json()["detail"]


def test_api_probe_unreachable_is_400():
    client = TestClient(app)
    response = client.post(
        "/api/models/probe",
        json={"base_url": "http://127.0.0.1:9/v1", "timeout": 1},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "无法连接" in detail or "超时" in detail
