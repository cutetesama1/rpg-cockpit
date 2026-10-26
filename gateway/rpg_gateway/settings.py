"""模型设置的读写：默认落在用户目录，api_key 只存后端。

- 默认路径：`~/.rpg-framework/settings.json`（可用 `RPG_CONFIG_DIR` / `RPG_SETTINGS` 覆盖）
- 对外只返回打码视图（has_key + key_hint），密钥不出后端
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rpg_core.contracts import LlmSettings

from .catalog import catalog_payload, normalize_effort, validate_preset


def config_dir() -> Path:
    env = os.environ.get("RPG_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".rpg-framework"


def settings_path() -> Path:
    env = os.environ.get("RPG_SETTINGS")
    return Path(env) if env else config_dir() / "settings.json"


def default_settings() -> LlmSettings:
    return LlmSettings()


def load_settings(path: Path | None = None) -> LlmSettings:
    target = path or settings_path()
    if not target.is_file():
        return default_settings()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return LlmSettings(**data)
    except (OSError, ValueError):
        # 配置损坏时回退默认（脚本假模型），不阻塞启动
        return default_settings()


def save_settings(settings: LlmSettings, path: Path | None = None) -> Path:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def mask_key(key: str) -> str:
    if not key:
        return ""
    return ("***" + key[-4:]) if len(key) > 4 else "***"


def public_view(settings: LlmSettings, path: Path | None = None) -> dict[str, Any]:
    """给前端的设置视图：不含 api_key 明文，附带模型供应商目录。"""
    providers = {
        name: {
            "base_url": cfg.base_url,
            "model": cfg.model,
            "preset": cfg.preset,
            "reasoning_effort": cfg.reasoning_effort,
            "timeout": cfg.timeout,
            "price_in": cfg.price_in,
            "price_out": cfg.price_out,
            "max_retries": cfg.max_retries,
            "retry_backoff_ms": cfg.retry_backoff_ms,
            "has_key": bool(cfg.api_key),
            "key_hint": mask_key(cfg.api_key),
        }
        for name, cfg in settings.providers.items()
    }
    return {
        "speech": {**settings.speech.model_dump(exclude={"api_key"}), "has_key": bool(settings.speech.api_key), "key_hint": mask_key(settings.speech.api_key)},
        "roles": settings.roles.model_dump(mode="json"),
        "providers": providers,
        "active_provider": settings.roles.narrator.provider,
        "catalog": catalog_payload(),
        "settings_path": str(path or settings_path()),
    }


def merge_update(
    current: LlmSettings, update: dict[str, Any]
) -> LlmSettings:
    """合并前端提交：api_key 留空表示沿用旧值（前端不回显明文）。"""
    merged = current.model_dump(mode="json")
    roles = update.get("roles")
    if roles is not None:
        # 逐角色合并：只改传进来的字段，未提交的 provider/model/温度沿用旧值
        # （否则「只改 max_tokens」这类部分更新会把 narrator 重置回 scripted）
        merged_roles = dict(merged.get("roles", {}))
        if "separated" in roles:
            merged_roles["separated"] = roles["separated"]
        for role_name in ("narrator", "settler", "arbiter", "setup", "director", "corrector", "voice_cast"):
            incoming_role = roles.get(role_name)
            if role_name in ("corrector", "voice_cast") and role_name in roles and incoming_role is None:
                merged_roles[role_name] = None
                continue
            if not isinstance(incoming_role, dict):
                continue
            base_role = dict(merged_roles.get(role_name) or {})
            for key in ("provider", "model", "temperature", "max_tokens"):
                if key in incoming_role and incoming_role[key] is not None:
                    base_role[key] = incoming_role[key]
            merged_roles[role_name] = base_role
        merged["roles"] = merged_roles
    if isinstance(update.get("speech"), dict):
        speech = dict(merged.get("speech") or {})
        for key, value in update["speech"].items():
            if key in ("has_key", "key_hint"): continue
            if key == "api_key" and (not isinstance(value, str) or not value.strip()): continue
            speech[key] = value.strip() if isinstance(value, str) else value
        merged["speech"] = speech
    incoming_providers = update.get("providers") or {}
    for name, cfg in incoming_providers.items():
        if not isinstance(cfg, dict):
            continue
        source = merged.get("providers", {}).get(str(cfg.get("copy_from") or ""), {})
        base = dict(merged.get("providers", {}).get(name, source))
        for key in (
            "base_url",
            "model",
            "timeout",
            "price_in",
            "price_out",
            "max_retries",
            "retry_backoff_ms",
        ):
            if key in cfg:
                base[key] = cfg[key]
        # 供应商预设与思考强度：非法值直接 400，不写坏配置
        if "preset" in cfg:
            base["preset"] = validate_preset(str(cfg.get("preset") or ""))
        if "reasoning_effort" in cfg:
            base["reasoning_effort"] = normalize_effort(
                str(cfg.get("reasoning_effort") or "")
            )
        api_key = cfg.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            base["api_key"] = api_key.strip()
        merged.setdefault("providers", {})[name] = base
    return LlmSettings(**merged)
