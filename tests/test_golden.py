"""金样回放：内容包自带的黄金场景逐条跑假 LLM，断言状态与事件契约。"""
from __future__ import annotations

import json

from conftest import PACK_DIR, make_session

from rpg_core.narrative import find_leaks
from rpg_gateway import ScriptedProvider


def scenarios() -> list[dict]:
    data = json.loads((PACK_DIR / "tests" / "scenarios.json").read_text(encoding="utf-8"))
    return data["scenarios"]


def test_golden_scenarios():
    for scenario in scenarios():
        session = make_session(ScriptedProvider())
        result = session.submit_action(scenario["action"])
        expected = scenario["expect"]

        assert result.ok is True, scenario["id"]
        for field, value in expected.get("state", {}).items():
            assert result.state[field] == value, f"{scenario['id']}.{field}"
        kinds = [event["kind"] for event in result.events]
        for kind in expected.get("events_include", []):
            assert kind in kinds, f"{scenario['id']} 缺少 {kind}"
        if expected.get("narrative_no_leaks"):
            assert find_leaks(result.narrative, session.pack.state) == [], scenario["id"]
        assert session.verify()["equal"] is True, f"{scenario['id']} 回放不一致"
