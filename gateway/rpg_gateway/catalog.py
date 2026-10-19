"""模型供应商目录：DeepSeek / ChatGPT / Gemini / Grok + 自定义兼容端点。

这是给设置界面用的静态数据（不进契约）：供应商预设、常见模型清单、
每个模型是否支持「思考强度」（reasoning_effort）以及参考单价。

- 所有供应商都走 OpenAI 兼容的 `/chat/completions` 协议，只差 base_url；
- 模型清单只是下拉建议，用户仍可在「自定义」里手填任意模型名；
- 单价是参考值（USD / 1M tokens），仅用于驾驶舱成本估算，可随时改。
"""
from __future__ import annotations

from typing import Any

# reasoning_effort 的合法值：空 = 不传（用模型默认）
EFFORT_IDS: tuple[str, ...] = ("low", "medium", "high")
EFFORT_LABELS: dict[str, str] = {
    "": "自动（用模型默认）",
    "low": "低（更快更省）",
    "medium": "中（均衡）",
    "high": "高（更慢更深入）",
}

# 自定义端点：允许手填 base_url / 模型名
CUSTOM_PRESET_ID = "custom"


def _model(
    model_id: str,
    label: str,
    *,
    note: str = "",
    efforts: tuple[str, ...] = (),
    price_in: float = 0.0,
    price_out: float = 0.0,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "label": label,
        "note": note,
        "efforts": list(efforts),
        "price_in": price_in,
        "price_out": price_out,
    }


PRESETS: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "key_hint": "sk-...（platform.deepseek.com）",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "note": "国内直连，价格低；chat 快、reasoner 会先思考再回答。",
        "models": [
            _model(
                "deepseek-chat",
                "DeepSeek Chat（V3）",
                note="通用对话，速度快，适合做 GM。",
                price_in=0.27,
                price_out=1.10,
            ),
            _model(
                "deepseek-reasoner",
                "DeepSeek Reasoner（R1）",
                note="推理模型，先思考再输出；结算更稳但更慢。",
                price_in=0.55,
                price_out=2.19,
            ),
        ],
    },
    {
        "id": "chatgpt",
        "label": "ChatGPT / OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-...（platform.openai.com）",
        "docs_url": "https://platform.openai.com/api-keys",
        "note": "官方 OpenAI 端点；o 系列支持思考强度。",
        "models": [
            _model(
                "gpt-4o",
                "GPT-4o",
                note="均衡，工具调用稳定。",
                price_in=2.50,
                price_out=10.00,
            ),
            _model(
                "gpt-4o-mini",
                "GPT-4o mini",
                note="便宜快速，适合只做叙事。",
                price_in=0.15,
                price_out=0.60,
            ),
            _model(
                "gpt-4.1",
                "GPT-4.1",
                note="长上下文，指令跟随好。",
                price_in=2.00,
                price_out=8.00,
            ),
            _model(
                "o3",
                "o3（推理）",
                note="推理模型，支持思考强度。",
                efforts=("low", "medium", "high"),
                price_in=2.00,
                price_out=8.00,
            ),
            _model(
                "o4-mini",
                "o4-mini（推理）",
                note="便宜的推理模型，支持思考强度。",
                efforts=("low", "medium", "high"),
                price_in=1.10,
                price_out=4.40,
            ),
        ],
    },
    {
        "id": "gemini",
        "label": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_hint": "AIza...（aistudio.google.com）",
        "docs_url": "https://aistudio.google.com/apikey",
        "note": "走 Google 的 OpenAI 兼容端点；2.5 系列支持思考强度。",
        "models": [
            _model(
                "gemini-2.5-pro",
                "Gemini 2.5 Pro",
                note="强推理，支持思考强度。",
                efforts=("low", "medium", "high"),
                price_in=1.25,
                price_out=10.00,
            ),
            _model(
                "gemini-2.5-flash",
                "Gemini 2.5 Flash",
                note="快且便宜，支持思考强度。",
                efforts=("low", "medium", "high"),
                price_in=0.30,
                price_out=2.50,
            ),
            _model(
                "gemini-2.0-flash",
                "Gemini 2.0 Flash",
                note="上一代快速模型。",
                price_in=0.10,
                price_out=0.40,
            ),
        ],
    },
    {
        "id": "grok",
        "label": "Grok / xAI",
        "base_url": "https://api.x.ai/v1",
        "key_hint": "xai-...（console.x.ai）",
        "docs_url": "https://console.x.ai",
        "note": "xAI 官方端点；grok-3-mini 支持思考强度。",
        "models": [
            _model(
                "grok-4",
                "Grok 4",
                note="最新旗舰，长上下文。",
                efforts=("low", "high"),
                price_in=3.00,
                price_out=15.00,
            ),
            _model(
                "grok-3",
                "Grok 3",
                note="上一代旗舰。",
                price_in=3.00,
                price_out=15.00,
            ),
            _model(
                "grok-3-mini",
                "Grok 3 mini",
                note="小模型，支持思考强度。",
                efforts=("low", "high"),
                price_in=0.30,
                price_out=0.50,
            ),
        ],
    },
    {
        "id": CUSTOM_PRESET_ID,
        "label": "自定义",
        "base_url": "",
        "key_hint": "本地端点可留空（Ollama / LM Studio / vLLM）",
        "docs_url": "",
        "note": "任何 OpenAI 兼容端点（Ollama、LM Studio、vLLM、中转站……）。",
        "models": [],
    },
]


def preset_map() -> dict[str, dict[str, Any]]:
    return {preset["id"]: preset for preset in PRESETS}


def get_preset(preset_id: str) -> dict[str, Any] | None:
    return preset_map().get((preset_id or "").strip())


def preset_ids() -> list[str]:
    return [preset["id"] for preset in PRESETS]


def default_preset() -> str:
    return "deepseek"


def validate_preset(preset_id: str) -> str:
    """空 = 未指定（按自定义处理）；未知 preset 抛 ValueError。"""
    value = (preset_id or "").strip()
    if not value:
        return CUSTOM_PRESET_ID
    if value not in preset_map():
        raise ValueError(f"未知的模型供应商：{value}")
    return value


def normalize_effort(effort: str) -> str:
    """空 = 不传；合法值 low/medium/high，其它抛 ValueError。"""
    value = (effort or "").strip().lower()
    if value and value not in EFFORT_IDS:
        raise ValueError(f"未知的思考强度：{effort}（可选 low / medium / high）")
    return value


def model_efforts(preset_id: str, model_id: str) -> list[str]:
    """某个预设下某模型支持的思考强度；找不到模型时返回全部（让用户自选）。"""
    preset = get_preset(preset_id)
    if preset is None:
        return list(EFFORT_IDS)
    wanted = (model_id or "").strip()
    for model in preset.get("models", []):
        if model["id"] == wanted:
            return list(model.get("efforts") or [])
    if wanted and preset["id"] == CUSTOM_PRESET_ID:
        return list(EFFORT_IDS)
    return []


def catalog_payload() -> dict[str, Any]:
    """给设置界面的完整目录。"""
    return {
        "presets": PRESETS,
        "efforts": [
            {"id": key, "label": label} for key, label in EFFORT_LABELS.items()
        ],
        "default_preset": default_preset(),
        "custom_preset": CUSTOM_PRESET_ID,
    }
