"""Opt-in, bounded live-model probes. Never saves settings, packs or game sessions.
Run: python tools/verify_llm_capabilities.py --live
Only sanitized training-room prompts are sent. Report excludes credentials/endpoints.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for part in ("core", "gateway", "content"):
    sys.path.insert(0, str(ROOT / part))
from rpg_content import load_pack
from rpg_core.contracts import OpeningScene, StateField
from rpg_core.runtime import GameSession
from rpg_gateway.factory import build_router
from rpg_gateway.settings import load_settings

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/previews/p13-live-model-verification.json")
    args = parser.parse_args()
    settings = load_settings().model_copy(deep=True)
    original_separated = settings.roles.separated
    profile = settings.roles.narrator
    cfg = settings.providers.get(profile.provider)
    if not cfg or not cfg.api_key:
        raise SystemExit("No configured authenticated narrator provider; no network calls made.")
    # Preserve provider/model selection; bound time, retries and output in memory only.
    cfg.timeout = 45
    cfg.max_retries = 0
    profile.temperature = 0
    profile.max_tokens = 2048
    settings.roles.separated = False
    router = build_router(settings)
    secrets = [p.api_key for p in settings.providers.values() if p.api_key]
    def safe(value):
        text = str(value)
        for secret in secrets:
            text = text.replace(secret, "[redacted]")
        return re.sub(r"https?://[^\s]+", "[endpoint]", text)[:400]
    def game(mp=False):
        pack = load_pack(ROOT / "packs/new-game")
        pack.prompts = {
            "pre": "普通冒险游戏测试场。场景是明亮的训练室。只测试明确指定的事件，不添加随机伤害、花费或奖励。",
            "narrator": "你是普通冒险游戏的叙事者。遵循工具协议，叙述和实际工具结果一致。不引入测试事件以外的状态变化。",
            "settler": "需要修改状态时先调用已提供的工具。严格按本次指定的数值和技能定义结算。工具执行后不要重复调用。不存在的字段和工具不可编造，无法执行的操作如实说明。",
        }
        pack.prompt_versions = {}
        pack.worldbook = []
        pack.npcs = []
        pack.items = []
        pack.quests = []
        pack.skills = []
        pack.opening = OpeningScene(id="opening", text="你站在明亮的训练室里，旁边有教练、衣架和练习木桩。")
        pack.scenes = [pack.opening]
        pack.state.limits.max_tool_rounds = 3
        if mp:
            pack.state.fields.append(StateField(id="mp", label="魔力", default=10, min=0, max=10))
        return GameSession(pack, router)
    results = []
    def turn(label, session, text, expected, skills=None):
        before = dict(session.state)
        action = {"kind": "text", "text": text}
        if skills:
            action["skills"] = [{"skill_id": skill} for skill in skills]
        result = session.submit_action(action)
        select = lambda state: {key: state[key] for key in ("hp", "focus", "mp", "upper", "pose") if key in state}
        events = result.events
        record = {
            "scenario": label, "turn_ok": result.ok,
            "expectation_kind": "unsupported_boundary" if label == "action_state_unavailable" else "supported_feature",
            "before": select(before), "after": select(session.state),
            "applied_tools": [e["payload"].get("tool") for e in events if e["kind"] == "tool.applied"],
            "rejected_tools": [{"tool": e["payload"].get("tool"), "code": e["payload"].get("error_code")} for e in events if e["kind"] == "tool.rejected"],
            "learned_skills": [s.model_dump() for s in session._learned_skills()],
            "skill_uses": [e["payload"].get("skill_id") for e in events if e["kind"] == "skill.used"],
            "model_calls": sum(e["kind"] == "llm.usage" for e in events),
            "tokens": sum(e["payload"].get("usage", {}).get("total_tokens", 0) for e in events if e["kind"] == "llm.usage"),
            "narrative_preview": safe(result.narrative[:180]),
            "errors": [safe(e) for e in result.errors],
            "replay_equal": session.verify()["equal"],
            "expectation_met": bool(expected(result, session)),
        }
        results.append(record)
        print(json.dumps({k: record[k] for k in ("scenario", "turn_ok", "applied_tools", "expectation_met", "model_calls")}, ensure_ascii=False), flush=True)
        return record
    hp = game()
    turn("hp_damage", hp, "这是确定已发生的测试事件：练习时手臂被木桩擦伤，HP 应扣除 3 点。请用伤害工具准确结算一次，然后叙述，正文不要报数。", lambda r,g: r.ok and g.state["hp"] == 17)
    turn("hp_heal", hp, "教练已经完成包扎，确定恢复 HP 1 点。请用恢复工具准确结算一次，然后叙述，不要添加其他事件。", lambda r,g: r.ok and g.state["hp"] == 18)
    skills = game()
    turn("learn_skill", skills, '训练完成，你已经学会技能「专注步法」。请调用 learn_skill：id=focus_step，name=专注步法，cost={"focus":2}，cooldown=2。之后叙述学会的经过。', lambda r,g: r.ok and any(s.id == "focus_step" and s.cost == {"focus": 2} and s.cooldown == 2 for s in g._learned_skills()))
    turn("use_learned_skill", skills, "我使用勾选的专注步法绕过木桩，不发生其他资源变化。", lambda r,g: r.ok and g.state["focus"] == 8, skills=["focus_step"])
    appearance = game()
    turn("wardrobe_supported_action_unavailable", appearance, "已经发生的事件：我换上连帽卫衣（hoodie），然后举剑做了一个攻击动作。请叙述事件；衣物将由后端读取叙述结算，不要声称拥有尚未接入的攻击动画状态。", lambda r,g: r.ok and g.state["upper"] == "hoodie" and g.state["pose"] == appearance.pack.state.defaults()["pose"])
    mp = game(mp=True)
    turn("declared_mp", mp, "确定已发生的练习事件：小型照明法术消耗 MP（字段 mp）2 点。请准确结算一次，不改变 HP，不额外学技能。", lambda r,g: r.ok and g.state["mp"] == 8 and g.state["hp"] == 20)
    report = {
        "test_kind": "live_authenticated_provider", "tested_at": datetime.now(timezone.utc).isoformat(), "provider": profile.provider,
        "model": profile.model or cfg.model, "user_config_separated": original_separated,
        "test_separated": False, "isolated_in_memory": True,
        "sanitized_training_pack": True, "configured_state_has_mp": "mp" in load_pack(ROOT / "packs/new-game").state.by_id(),
        "note": "MP added only to isolated MP probe. Wardrobe post-processing is enabled; changing pose remains unsupported. Full clothing probes are in verify_clothing_live.py. Split-role routing tested separately with stubs.",
        "scenarios": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scenarios": len(results), "expectations_met": sum(r["expectation_met"] for r in results), "calls": sum(r["model_calls"] for r in results), "report": str(args.output)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
