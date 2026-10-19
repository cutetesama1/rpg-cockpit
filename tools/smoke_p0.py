"""P0 端到端冒烟：加载示例包 → 跑一回合 → 撤销 → 回放校验。

用法：python tools/smoke_p0.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("core", "gateway", "content"):
    sys.path.insert(0, str(ROOT / sub))

from rpg_content import load_pack  # noqa: E402
from rpg_core.contracts import LlmRolesConfig  # noqa: E402
from rpg_core.runtime import GameSession  # noqa: E402
from rpg_gateway import LlmRouter, ScriptedProvider  # noqa: E402


def main() -> int:
    pack = load_pack(ROOT / "packs" / "night-convenience-store")
    router = LlmRouter(LlmRolesConfig(), {"scripted": ScriptedProvider()})
    session = GameSession(pack, router)

    result = session.submit_action({"kind": "skill", "skill_id": "smash"})
    print("turn:", result.turn, "ok:", result.ok)
    print("narrative:", result.narrative)
    print("state:", result.state)
    print("events:", [e["kind"] for e in result.events])
    print("replay:", json.dumps(session.verify(), ensure_ascii=False))

    undo = session.undo()
    print("undo ok:", undo["ok"], "state after undo:", undo["state"])

    result2 = session.submit_action({"kind": "skill", "skill_id": "first_aid"})
    print("turn:", result2.turn, "ok:", result2.ok, "state:", result2.state)
    print("replay equal:", session.verify()["equal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
