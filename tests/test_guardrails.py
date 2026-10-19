"""护栏单元测试：白名单、钳制、变化率、未知物品/标记/字段。"""
from __future__ import annotations

import pytest

from rpg_core.contracts import ToolCall
from rpg_core.guardrails import GuardrailError, ToolExecutor, roll_dice


def executor(pack) -> ToolExecutor:
    return ToolExecutor(
        pack.state,
        {item.id for item in pack.items},
        {flag.id for flag in pack.flags},
    )


def fresh_state(pack) -> dict:
    return pack.state.defaults()


def call(name: str, **args) -> ToolCall:
    return ToolCall(id="tc_1", name=name, args=args)


def test_roll_dice_range_and_validation():
    for _ in range(50):
        rolled = roll_dice("1d6+2")
        assert 3 <= rolled["total"] <= 8
        assert len(rolled["rolls"]) == 1
    assert 2 <= roll_dice("2d6")["total"] <= 12
    with pytest.raises(GuardrailError) as exc:
        roll_dice("d6")
    assert exc.value.code == "invalid_dice"
    with pytest.raises(GuardrailError):
        roll_dice("21d6")
    with pytest.raises(GuardrailError):
        roll_dice("1d1000")


def test_unknown_tool_is_rejected(pack):
    with pytest.raises(GuardrailError) as exc:
        executor(pack).execute(
            call("delete_everything"), fresh_state(pack), {}, 1, "p1"
        )
    assert exc.value.code == "unknown_tool"


def test_damage_clamps_at_zero(pack):
    state = fresh_state(pack)
    state["hp"] = 3
    outcome = executor(pack).execute(call("damage", amount=10), state, {}, 1, "p1")
    assert state["hp"] == 0
    assert outcome.changes["hp"]["before"] == 3
    assert outcome.changes["hp"]["after"] == 0


def test_heal_clamps_at_max(pack):
    state = fresh_state(pack)
    state["hp"] = 19
    executor(pack).execute(call("heal", amount=5), state, {}, 1, "p1")
    assert state["hp"] == 20


def test_negative_amount_rejected(pack):
    with pytest.raises(GuardrailError) as exc:
        executor(pack).execute(call("damage", amount=-1), fresh_state(pack), {}, 1, "p1")
    assert exc.value.code == "bad_params"


def test_non_numeric_amount_rejected(pack):
    with pytest.raises(GuardrailError) as exc:
        executor(pack).execute(
            call("heal", amount="很多"), fresh_state(pack), {}, 1, "p1"
        )
    assert exc.value.code == "bad_params"


def test_delta_limit_rejects_single_hit(pack):
    with pytest.raises(GuardrailError) as exc:
        executor(pack).execute(call("damage", amount=30), fresh_state(pack), {}, 1, "p1")
    assert exc.value.code == "delta_limit"


def test_delta_limit_accumulates_within_turn(pack):
    state = fresh_state(pack)
    ex = executor(pack)
    used: dict[str, float] = {}
    ex.execute(call("damage", amount=5), state, used, 1, "p1")
    assert state["hp"] == 15
    with pytest.raises(GuardrailError) as exc:
        ex.execute(call("damage", amount=5), state, used, 1, "p2")
    assert exc.value.code == "delta_limit"


def test_unknown_field_rejected(pack):
    with pytest.raises(GuardrailError) as exc:
        executor(pack).execute(
            call("add_stat", field="luck", delta=1), fresh_state(pack), {}, 1, "p1"
        )
    assert exc.value.code == "unknown_field"


def test_unknown_item_and_flag_rejected(pack):
    ex = executor(pack)
    with pytest.raises(GuardrailError) as exc:
        ex.execute(call("add_item", item_id="rocket"), fresh_state(pack), {}, 1, "p1")
    assert exc.value.code == "unknown_item"
    with pytest.raises(GuardrailError) as exc:
        ex.execute(call("set_flag", flag="nope"), fresh_state(pack), {}, 1, "p1")
    assert exc.value.code == "unknown_flag"


def test_add_item_and_set_flag_apply(pack):
    state = fresh_state(pack)
    ex = executor(pack)
    item_out = ex.execute(call("add_item", item_id="bandage", count=2), state, {}, 1, "p1")
    assert item_out.inventory_delta == {"bandage": 2}
    flag_out = ex.execute(call("set_flag", flag="met_clerk", value=True), state, {}, 1, "p2")
    assert state["flag_met_clerk"] is True
    assert flag_out.changes["flag_met_clerk"]["after"] is True
