"""从 LlmSettings 组装 Router：provider 注册 + 配置校验。

设置改动的唯一入口在这里，API 层只调用 build_router / validate_settings。
"""
from __future__ import annotations

from rpg_core.contracts import LlmSettings

from .providers import OpenAICompatibleProvider, ScriptedProvider
from .roles import LlmProvider, LlmRouter

ROLE_NAMES = ("narrator", "settler", "arbiter", "setup", "corrector")


def build_providers(settings: LlmSettings) -> dict[str, LlmProvider]:
    providers: dict[str, LlmProvider] = {"scripted": ScriptedProvider()}
    for name, cfg in settings.providers.items():
        if name == "scripted":
            continue
        providers[name] = OpenAICompatibleProvider(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            model=cfg.model,
            timeout=cfg.timeout,
            price_in=cfg.price_in,
            price_out=cfg.price_out,
            max_retries=cfg.max_retries,
            retry_backoff_ms=cfg.retry_backoff_ms,
            preset=cfg.preset,
            reasoning_effort=cfg.reasoning_effort,
        )
    return providers


def validate_settings(settings: LlmSettings) -> None:
    """配置不完整时抛 ValueError，API 转 400。"""
    if settings.roles.separated:
        # 多 LLM 拆分是合法配置，只需每个角色都能解析到 provider
        pass
    for role in ROLE_NAMES:
        profile = getattr(settings.roles, role)
        if profile is None: continue
        if profile.provider in ("", "scripted"):
            continue
        cfg = settings.providers.get(profile.provider)
        if cfg is None:
            raise ValueError(f"角色 {role} 的 provider 未配置：{profile.provider}")
        if not cfg.base_url.strip():
            raise ValueError(f"provider {profile.provider} 缺少 base_url")
        if not (profile.model or cfg.model).strip():
            raise ValueError(f"provider {profile.provider} 缺少 model")


def build_router(settings: LlmSettings) -> LlmRouter:
    validate_settings(settings)
    return LlmRouter(settings.roles, build_providers(settings))
