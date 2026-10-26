"""从 pydantic 模型导出 contracts/*.json（JSON Schema）。

用法：python tools/export_contracts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from rpg_core import contracts as c  # noqa: E402
from rpg_core.settlement import Proposal
from rpg_core.personality_npcs import Roster
from rpg_core.dynamic_worldbook import Change  # noqa: E402
from rpg_core.corrections import Correction, NumericCorrection

CONTRACTS = {
    "voice-settings": c.VoiceSettings,
    "llm-settings": c.LlmSettings,
    "ai-correction": Correction,
    "numeric-correction": NumericCorrection,
    "personality-npcs": Roster,
    "dynamic-worldbook-change": Change,
    "state-schema": c.StateSchema,
    "turn-settlement": Proposal,
    "mutator": c.MutatorSpec,
    "event": c.Event,
    "content-pack": c.ContentPack,
    "narrator-io": c.NarratorOutput,
    "settler-io": c.SettlerOutput,
    "llm-role": c.LlmRolesConfig,
}


def main() -> None:
    out = ROOT / "contracts"
    out.mkdir(parents=True, exist_ok=True)
    for name, model in CONTRACTS.items():
        path = out / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(ROOT)}")
    # 工具集是列表，单独导出一份给网关提示词/工具 schema 用
    tools_path = out / "mutators.tools.json"
    tools_path.write_text(
        json.dumps(
            [m.model_dump(mode="json") for m in c.MUTATORS],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {tools_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
