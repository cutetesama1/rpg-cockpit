"""模型设置的持久化 / 打码 / 合并 / 校验。"""
from __future__ import annotations

import json

import pytest

from rpg_core.contracts import LlmProfile, ProviderSettings
from rpg_gateway import (
    build_router,
    default_settings,
    load_settings,
    merge_update,
    public_view,
    save_settings,
    validate_settings,
)

DEEPSEEK = "https://api.deepseek.com/v1"


def _configured():
    settings = default_settings()
    settings.providers["openai"] = ProviderSettings(
        base_url=DEEPSEEK, api_key="sk-secret-1234", model="deepseek-chat"
    )
    settings.roles.narrator = LlmProfile(provider="openai", temperature=0.3)
    return settings


def test_default_is_single_scripted_model():
    settings = default_settings()
    assert settings.roles.separated is False
    assert settings.roles.narrator.provider == "scripted"
    assert "openai" in settings.providers


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(_configured(), path)
    loaded = load_settings(path)
    assert loaded.providers["openai"].api_key == "sk-secret-1234"
    assert loaded.providers["openai"].model == "deepseek-chat"
    assert loaded.roles.narrator.provider == "openai"


def test_corrupt_file_falls_back_to_scripted(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path).roles.narrator.provider == "scripted"


def test_public_view_masks_api_key():
    view = public_view(_configured())
    dumped = json.dumps(view, ensure_ascii=False)
    assert "sk-secret-1234" not in dumped
    assert view["providers"]["openai"]["has_key"] is True
    assert view["providers"]["openai"]["key_hint"] == "***1234"
    assert view["roles"]["narrator"]["provider"] == "openai"


def test_merge_update_keeps_key_when_blank():
    current = _configured()
    merged = merge_update(
        current,
        {"providers": {"openai": {"base_url": "https://x/v1", "api_key": ""}}},
    )
    assert merged.providers["openai"].api_key == "sk-secret-1234"
    assert merged.providers["openai"].base_url == "https://x/v1"

    replaced = merge_update(
        current, {"providers": {"openai": {"api_key": "sk-new"}}}
    )
    assert replaced.providers["openai"].api_key == "sk-new"


def test_merge_update_partial_roles_preserves_provider():
    """只提交 max_tokens 之类的局部字段时，不能把角色重置回默认 scripted。"""
    current = _configured()
    current.roles.narrator = LlmProfile(provider="openai", model="gpt-4o")
    merged = merge_update(
        current, {"roles": {"narrator": {"max_tokens": 8192}}}
    )
    assert merged.roles.narrator.provider == "openai"
    assert merged.roles.narrator.model == "gpt-4o"
    assert merged.roles.narrator.max_tokens == 8192
    assert merged.roles.settler.provider == current.roles.settler.provider


def test_merge_update_roles_can_change_provider():
    current = default_settings()
    merged = merge_update(
        current,
        {"roles": {"narrator": {"provider": "openai"}, "separated": True}},
    )
    assert merged.roles.narrator.provider == "openai"
    assert merged.roles.separated is True


def test_validate_rejects_missing_endpoint():
    settings = default_settings()
    settings.roles.narrator = LlmProfile(provider="openai")
    with pytest.raises(ValueError):
        validate_settings(settings)


def test_validate_rejects_unknown_provider():
    settings = default_settings()
    settings.roles.narrator = LlmProfile(provider="nope")
    with pytest.raises(ValueError):
        validate_settings(settings)


def test_validate_accepts_configured_provider():
    validate_settings(_configured())  # 不抛异常即通过
    build_router(_configured())


def test_validate_accepts_shared_model_with_separate_role_profiles():
    settings=_configured();settings.roles.separated=True
    validate_settings(settings)


def test_validate_accepts_separated_with_different_models():
    settings = _configured()
    settings.roles.separated = True
    settings.roles.settler = LlmProfile(provider="openai", model="small-model")
    validate_settings(settings)


def test_pricing_and_retry_fields_roundtrip(tmp_path):
    settings = _configured()
    settings.providers["openai"] = settings.providers["openai"].model_copy(
        update={
            "price_in": 2.0,
            "price_out": 8.0,
            "max_retries": 3,
            "retry_backoff_ms": 1200,
        }
    )
    path = tmp_path / "settings.json"
    save_settings(settings, path)
    loaded = load_settings(path)
    cfg = loaded.providers["openai"]
    assert (cfg.price_in, cfg.price_out) == (2.0, 8.0)
    assert (cfg.max_retries, cfg.retry_backoff_ms) == (3, 1200)

    view = public_view(loaded)
    assert view["providers"]["openai"]["price_in"] == 2.0
    assert view["providers"]["openai"]["max_retries"] == 3

    merged = merge_update(loaded, {"providers": {"openai": {"price_in": 0.5}}})
    assert merged.providers["openai"].price_in == 0.5
    assert merged.providers["openai"].price_out == 8.0


def test_negative_price_is_rejected():
    with pytest.raises(ValueError):
        ProviderSettings(base_url="https://x/v1", price_in=-1.0)


def test_preset_and_reasoning_effort_roundtrip(tmp_path):
    settings = merge_update(
        _configured(),
        {
            "providers": {
                "openai": {
                    "preset": "deepseek",
                    "reasoning_effort": "high",
                    "model": "deepseek-reasoner",
                }
            }
        },
    )
    assert settings.providers["openai"].preset == "deepseek"
    assert settings.providers["openai"].reasoning_effort == "high"
    assert settings.providers["openai"].model == "deepseek-reasoner"

    path = tmp_path / "settings.json"
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.providers["openai"].preset == "deepseek"
    assert loaded.providers["openai"].reasoning_effort == "high"

    view = public_view(loaded)
    assert view["providers"]["openai"]["preset"] == "deepseek"
    assert view["providers"]["openai"]["reasoning_effort"] == "high"
    assert view["active_provider"] == "openai"
    assert view["catalog"]["presets"]
    assert "sk-secret-1234" not in json.dumps(view, ensure_ascii=False)


def test_merge_update_rejects_unknown_preset():
    with pytest.raises(ValueError, match="未知的模型供应商"):
        merge_update(_configured(), {"providers": {"openai": {"preset": "claude"}}})


def test_merge_update_rejects_unknown_effort():
    with pytest.raises(ValueError, match="未知的思考强度"):
        merge_update(
            _configured(), {"providers": {"openai": {"reasoning_effort": "extreme"}}}
        )


def test_build_router_carries_preset_and_effort():
    settings = _configured()
    settings.providers["openai"] = settings.providers["openai"].model_copy(
        update={"preset": "deepseek", "reasoning_effort": "medium"}
    )
    router = build_router(settings)
    provider = router.providers["openai"]
    assert provider.preset == "deepseek"
    assert provider.reasoning_effort == "medium"
