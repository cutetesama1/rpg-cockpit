"""叙事数值检查器：只拦状态语义+数字，不误伤世界观数字。"""
from __future__ import annotations

from rpg_core.narrative import find_leaks, scrub


def test_detects_field_number_combos(pack):
    schema = pack.state
    assert find_leaks("你的生命 7，体力 3。", schema)
    assert find_leaks("血量：12", schema)
    assert find_leaks("你掉了 7 点血", schema)
    assert find_leaks("精神还剩 4", schema)


def test_allows_world_numbers(pack):
    assert find_leaks("凌晨两点，3 号货架的牛奶倒了，价格 12 元。", pack.state) == []
    assert find_leaks("你走到门口，玻璃上映出你自己。", pack.state) == []


def test_bool_field_not_treated_as_number(pack):
    assert find_leaks("你见过店员，标记为 1。", pack.state) == []


def test_scrub_removes_digits(pack):
    text = "你受了伤，生命 7，体力 3。"
    scrubbed = scrub(text, pack.state)
    assert "生命 7" not in scrubbed
    assert "体力 3" not in scrubbed
    assert "7" not in scrubbed and "3" not in scrubbed
