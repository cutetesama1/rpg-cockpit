"""LLM 网关：角色路由。

一期：narrator 与 settler 指向同一 profile（separated=False），
runtime 一次调用完成"叙事 + 结算"。
拆分多 LLM 只改配置：separated=True + settler 指向小模型。
"""
from __future__ import annotations

from typing import Callable, Protocol

from rpg_core.contracts import LlmProfile, LlmRolesConfig

from .providers import LlmResponse


class LlmProvider(Protocol):
    name: str

    def complete(self, request: dict) -> LlmResponse: ...


class RouterError(Exception):
    pass


class LlmRouter:
    def __init__(
        self, config: LlmRolesConfig, providers: dict[str, LlmProvider]
    ) -> None:
        self.config = config
        self.providers = providers

    def profile(self, role: str) -> LlmProfile:
        if role == "corrector" and self.config.corrector is None:
            role = "settler" if self.separated else "narrator"
        try:
            return getattr(self.config, role)
        except AttributeError as exc:
            raise RouterError(f"未知角色：{role}") from exc

    @property
    def separated(self) -> bool:
        return self.config.separated

    def complete(self, role: str, request: dict) -> LlmResponse:
        return self._invoke(role, request)

    def stream(self, role: str, request: dict, on_text: Callable[[str], None]) -> LlmResponse:
        return self._invoke(role, request, on_text)

    def _invoke(self, role: str, request: dict, on_text: Callable[[str], None] | None = None) -> LlmResponse:
        # 衣物阶段始终走后置结算；单模型时复用 narrator 的连接配置。
        clothing = request.get("phase") == "clothing"
        backend = request.get("phase") in ("clothing", "skill_selection", "skill_learning", "settlement")
        reuse_director = request.get('phase')=='director' and request.get('reuse_narrator',True)
        profile = self.profile("narrator" if reuse_director or backend and not self.separated else role)
        provider = self.providers.get(profile.provider)
        if provider is None:
            raise RouterError(f"角色 {role} 配置的 provider 不存在：{profile.provider}")
        # 角色级 profile 覆盖 provider 默认值（多 LLM 拆分后每条链路可独立调参）
        request = {
            **request,
            "temperature": profile.temperature,
            # max_tokens <= 0 表示不限制：完全不传给端点，避免截断长叙事
            **({"max_tokens": profile.max_tokens} if profile.max_tokens > 0 else {}),
        }
        if backend or role == "corrector":
            request["temperature"] = 0.0
        if clothing:
            request["temperature"] = 0.0
            request["max_tokens"] = min(profile.max_tokens if profile.max_tokens > 0 else 1024, 1024)
        if profile.model:
            request["model"] = profile.model
        stream = getattr(provider, "stream", None)
        response = stream(request, on_text) if on_text is not None and callable(stream) and not clothing else provider.complete(request)
        if not response.model:
            response.model = profile.model
        return response
