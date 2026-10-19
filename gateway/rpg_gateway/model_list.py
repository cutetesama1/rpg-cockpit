"""读取 OpenAI 兼容端点的可用模型列表（GET {base_url}/models）。

只做一件事：带上用户填的（或已保存的）API Key 请求端点的 `/models`，
把 id 列表整理好返回给界面。这样用户不必手打模型名，而是从真实可用的
模型里选——DeepSeek / OpenAI / Gemini(OpenAI 兼容) / xAI / Ollama / LM Studio
等端点都实现了这个接口。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 10.0
MAX_MODELS = 500


class ModelListError(RuntimeError):
    """读取模型列表失败（端点不可达、鉴权失败、返回格式不对等）。"""


def models_url(base_url: str) -> str:
    """把用户填的 base_url 规范成 /models 地址（容忍已带 /v1 或尾部斜杠）。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ModelListError("模型端点未配置：请先填写 base_url")
    if not (base.startswith("http://") or base.startswith("https://")):
        raise ModelListError("base_url 需要以 http:// 或 https:// 开头")
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, dict):
        items = data.get("data")
        if items is None:
            items = data.get("models")
        if items is not None:
            return items if isinstance(items, list) else []
        # 少数端点把模型放在对象里：{"gpt-4o": {...}}
        if all(isinstance(value, (dict, str)) for value in data.values()):
            return list(data.keys())
        return []
    if isinstance(data, list):
        return data
    return []


def list_endpoint_models(
    base_url: str,
    api_key: str = "",
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """请求 `{base_url}/models` 并返回 `{models, count, latency_ms, base_url}`。

    `models` 按 id 排序去重，每项 `{id, owned_by}`（owned_by 可能为空）。
    任何失败都抛 `ModelListError`，消息可直接展示给用户。
    """
    url = models_url(base_url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        head = detail.lstrip()[:15].lower()
        if head.startswith("<!doctype") or head.startswith("<html"):
            detail = " ".join(detail.lstrip()[:80].split())
            raise ModelListError(
                "读取模型列表失败：HTTP %s（端点返回的是网页 HTML 而不是 API JSON："
                "检查 base_url 是否填成了网页地址（例如取 Key 的页面），"
                "或被网关/WAF 拦截）%s" % (exc.code, detail)
            ) from exc
        hint = ""
        if exc.code in (401, 403):
            hint = "（API Key 无效或没有权限？）"
        elif exc.code == 404:
            hint = "（该端点没有 /models 接口，请改用「自定义」页签手填模型名）"
        raise ModelListError(f"读取模型列表失败：HTTP {exc.code}{hint} {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelListError(f"无法连接模型端点：{exc.reason}") from exc
    except TimeoutError as exc:
        raise ModelListError(f"读取模型列表超时（{timeout:g}s）") from exc

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelListError(
            "模型端点返回的不是 JSON（可能不是 OpenAI 兼容端点）"
        ) from exc

    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _extract_items(data):
        if isinstance(item, str):
            model_id, owned_by = item.strip(), ""
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
            owned_by = str(item.get("owned_by") or "")
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "owned_by": owned_by})

    models.sort(key=lambda entry: entry["id"])
    if not models:
        raise ModelListError(
            "端点返回的模型列表为空：确认 base_url 是否少了 /v1，或该账号暂无可用模型"
        )
    return {
        "base_url": models_url(base_url)[: -len("/models")],
        "models": models[:MAX_MODELS],
        "count": len(models),
        "latency_ms": latency_ms,
    }
