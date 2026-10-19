# 异世界

内容包 id：`new-game`，由 `rpg-framework` 的 `rpg pack new` 生成。

## 目录

| 路径 | 作用 |
| --- | --- |
| `manifest.json` | 包身份、版本、年龄分级 |
| `state.json` | 状态字段（类型/范围/显示）+ 回合限额 |
| `vocab/` | 技能、物品、NPC、任务、标记、世界书 |
| `vocab/worldbook.json` | 世界书：常驻/关键词触发的世界观设定 |
| `prompts/pre.md` | 前置提示词（每回合拼在最前面的世界基调） |
| `prompts/narrator.md` | 叙事者提示词（玩家看到的文字） |
| `prompts/settler.md` | 结算器提示词（把叙事翻译成工具调用） |
| `ui/layout.json` | 驾驶舱里显示哪些字段 |
| `scenes/` | 场景与开场 |
| `tests/scenarios.json` | 金样场景（`pytest tests/test_golden.py` 会跑） |

## 下一步

1. 改 `scenes/opening.json` 写你的开场。
2. 在 `vocab/skills.json` 加技能；效果不要写公式，写在 `prompts/settler.md` 里。
3. 在 `state.json` 加你自己的数值字段，并在 `ui/layout.json` 里决定怎么显示。
4. 跑校验：`python -m rpg_content.cli lint <本目录>`。
5. 把第一个可玩场景写进 `tests/scenarios.json`，让它成为回归测试。
