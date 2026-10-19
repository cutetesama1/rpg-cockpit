"""叙事数值检查器：叙事不报数，靠检查而不是靠自觉。

只拦"状态字段语义 + 数字"的组合；时间、门牌、价格等世界观数字放行。
"""
from __future__ import annotations

import re

from .contracts import StateSchema

# 字段 id -> 同义词（中文为主）
SYNONYMS: dict[str, list[str]] = {
    "hp": ["生命", "血量", "血", "hp", "HP"],
    "stamina": ["体力", "耐力"],
    "sanity": ["精神", "理智", "神志"],
    "mp": ["法力", "魔力", "蓝量", "mp", "MP"],
    "money": ["零钱", "钱", "现金", "余额"],
}

_NUM = r"\d+(?:\.\d+)?"

# A: 字段名+数字，如 "生命 7"、"血量：12"
_PATTERN_LABEL = None


def _labels(field_id: str, field_label: str) -> list[str]:
    labels = [field_label]
    labels.extend(SYNONYMS.get(field_id, []))
    # 去重、长词优先，避免"血"抢先匹配"血量"
    return sorted({l for l in labels if l}, key=len, reverse=True)


def find_leaks(text: str, schema: StateSchema) -> list[str]:
    """返回命中的片段列表（去重、保序）。"""
    hits: list[str] = []
    if not text:
        return hits
    for field in schema.fields:
        if field.type not in ("int", "float") or field.type == "bool":
            continue
        labels = _labels(field.id, field.label)
        for label in labels:
            esc = re.escape(label)
            patterns = [
                rf"{esc}\s*[:：=]?\s*{_NUM}",  # 生命 7
                rf"{_NUM}\s*点\s*{esc}",  # 7 点生命
                rf"{esc}\s*(?:还剩|恢复|扣|掉|减|加|变为|是|剩)\s*{_NUM}",
            ]
            for pat in patterns:
                for m in re.finditer(pat, text):
                    hit = m.group(0)
                    if hit not in hits:
                        hits.append(hit)
    # 通用句式："掉了 7 点血" / "扣 3 点体力"
    for m in re.finditer(rf"{_NUM}\s*点(?:血|生命|体力|精神|理智|法力)", text):
        hit = m.group(0)
        if hit not in hits:
            hits.append(hit)
    return hits


def scrub(text: str, schema: StateSchema) -> str:
    """把数值片段中的数字抹掉（兜底，避免玩家看到泄漏）。"""
    scrubbed = text
    for hit in find_leaks(text, schema):
        replacement = re.sub(_NUM, "…", hit)
        scrubbed = scrubbed.replace(hit, replacement)
    return scrubbed
