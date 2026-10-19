"""模型供应商目录：预设端点、模型清单、思考强度。"""
from __future__ import annotations

import pytest

from rpg_gateway.catalog import (
    CUSTOM_PRESET_ID,
    EFFORT_IDS,
    PRESETS,
    catalog_payload,
    get_preset,
    model_efforts,
    normalize_effort,
    preset_ids,
    validate_preset,
)


def test_catalog_has_the_four_main_providers():
    ids = preset_ids()
    for expected in ("deepseek", "chatgpt", "gemini", "grok"):
        assert expected in ids
    assert CUSTOM_PRESET_ID in ids


def test_every_preset_shape():
    for preset in PRESETS:
        assert preset["id"] and preset["label"]
        if preset["id"] == CUSTOM_PRESET_ID:
            assert preset["models"] == []
            assert preset["base_url"] == ""
            continue
        assert preset["base_url"].startswith("https://"), preset["id"]
        assert preset["models"], preset["id"]
        for model in preset["models"]:
            assert model["id"] and model["label"]
            assert set(model["efforts"]) <= set(EFFORT_IDS)


def test_reasoning_models_advertise_efforts():
    assert model_efforts("chatgpt", "o3") == ["low", "medium", "high"]
    assert model_efforts("gemini", "gemini-2.5-pro")
    assert model_efforts("grok", "grok-3-mini")
    # 普通对话模型不广告思考强度，避免发不支持的参数
    assert model_efforts("deepseek", "deepseek-chat") == []
    assert model_efforts("chatgpt", "gpt-4o") == []
    # 自定义端点：允许用户自己勾
    assert model_efforts(CUSTOM_PRESET_ID, "any-model") == list(EFFORT_IDS)


def test_normalize_effort():
    assert normalize_effort("") == ""
    assert normalize_effort(" HIGH ") == "high"
    with pytest.raises(ValueError):
        normalize_effort("extreme")


def test_validate_preset():
    assert validate_preset("deepseek") == "deepseek"
    assert validate_preset("") == CUSTOM_PRESET_ID
    assert validate_preset(" custom ") == CUSTOM_PRESET_ID
    with pytest.raises(ValueError):
        validate_preset("claude")


def test_catalog_payload_shape():
    payload = catalog_payload()
    assert payload["default_preset"] in preset_ids()
    assert payload["custom_preset"] == CUSTOM_PRESET_ID
    assert {row["id"] for row in payload["efforts"]} == {"", *EFFORT_IDS}
    assert get_preset("gemini")["label"] == "Gemini"
    assert get_preset("nope") is None
