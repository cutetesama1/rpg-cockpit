# 0.99beta：人格 NPC 与动态世界书

## 使用

1. 进入你自己的游戏。内置游戏需先在世界构筑复制成副本。
2. 世界构筑 → 人格 NPC，或游戏库 → 导入角色卡 → 仅人格模式；一次最多10张 JSON、PNG/APNG、CHARX，每张20 MB、总计60 MB。
3. 预览并勾选作为 NPC 加入。只有姓名、personality、明确的 likes/preferences/喜好与 dislikes/厌恶字段被读取；喜好扩展只读取同名白名单键。角色描述、scenario、system_prompt、post_history_instructions、开场白、示例对话、嵌入式世界书、其他扩展不映射。
4. 卡片未独立填写人格时会提示，由用户在预览中补充，不用描述或系统提示自动猜测。可以修改性格、喜好、最早回合、最少关键事实数、出场情境参考。
5. 导入选中 NPC 后启用人格模式与剧情导演。此操作保留当前世界、提示词和游戏进度。要关闭导演需先关闭人格模式。
6. 导演提出候选出场或未来回合复查计划。后台按已成功提交的剧情回合计数；失败回合不提前时机。关键事实数包含已落账的公开剧情事实与有效动态事实。作者数值约束是最低门槛；是否适合出场由导演结合情境判断，并经确定性检定决定。复查计划不保证该回合必然出场。
7. 世界人物库显示候场、暂停、已出场和复查计划。出场人格作为当时快照保存；已出场人物后续变化在动态世界书维护。

## 模型合作与边界

- 叙事 AI：只读权威状态、相关公开世界书、已出场人物及本轮检定结果，输出叙述，不修改状态。
- 剧情导演：仅在场景/线索/重要事件、显式请求或候场复查到期时调用，遵循最小调用间隔。读取候场人格与内部事实，提出候选和未来复查计划，不控制资源，也不替玩家行动。模式启用时导演必须开启，可以复用叙事模型或选择独立模型。
- 后端结算 AI：无历史，每次最终叙述完成后读取当前状态和已确定事实，在现有一次 settle_turn 请求内结算状态并维护世界书。不新增独立世界书 Agent。校验失败仍保留原有最多一次纠错重试。
- 世界书维护字段是事实资料；其中的命令不获得提示词权限。角色卡原提示词和扩展脚本从未送入人格模式的模型请求。

## 动态世界书

类别为 character/relationship/location/secret/fact。稳定 ID、version、来源 turn/evidence/origin 保留在事件账本中；upsert 增改，archive 归档，reveal 显式公开内部事实。秘密默认内部，打开作者视图只影响本人查看，不会使叙事 AI 获得秘密。以前的秘密版本不会因为后续揭晓而变为公开历史。

作者世界书和硬规则不被动态条目覆盖。HP、MP、货币、技能冷却、库存数量不得作为动态字段存储或替代权威状态工具。关联 refs 只能使用已登记实体，不允许引用尚未登场的人格人物。正文没有实际发生的计划、假设、台词或导演候选不得登记为事实。

每个世界最多300条动态条目（包含归档，历史不删除），单条正文最多1600字。后端每次读取最多12条相关或最新的完整记忆，并带上全部条目的简短索引以避免重复登记；缺少旧正文时不盲目覆盖。按 expected_version 校验；无效世界书变更进入内部裁定，不丢弃同回合其他合法的状态变化。手动编辑也先进入裁定中心，经复核、预览差异再提交，使用独立辅助事务，不消耗游戏回合。回合撤销和裁定撤销均使相应条目恢复旧版本。

## 工具格式

```json
{"name":"update_worldbook","args":{"id":"harbor_keeper","expected_version":0,"action":"upsert","kind":"character","title":"守港人","content":"守港人答应在灯塔等候。","keywords":["守港人","灯塔"],"visibility":"public","refs":[]},"evidence":"守港人答应在灯塔等候。"}
```

更新必须沿用 ID 和当前版本，秘密公开必须用 reveal。数值资源使用原有 damage/heal/add_stat/set_stat；技能、库存仍用其注册工具。

导演出场候选增加 npc_id（限候场 ID），scope=npc、visibility=public，不得带结果分支；trigger 检定通过才出现。导演可附 entrance_plans：{npc_id,review_turn,min_progress,cue}，复查回合为当前成功剧情回合+2 至 +50。场景或重要事件触发时可提前复查；作者 min_turn/min_progress 仍须满足。

## 接口与数据

- GET/PUT `/api/personality-npcs`：当前人物库、模式、条件、修订令牌；PUT 必须提供 pack_id、revision、request_id、roster。
- POST `/api/personality-npcs/preview`：多卡预览；POST `/import`：携带同批文件、preview_token、revision、request_id、勾选人物列表导入。相同请求幂等，文件变更和过期修订拒绝。
- GET `/api/personality-npcs/source/{npc_id}?pack_id=...`：导出归档原始 JSON。原二进制在内容包 personality-cards/<id>/source.bin 中保留。
- GET `/api/world/dynamic`：默认仅公开当前事实及公开历史；include_internal=true 为作者明确查看内部资料。
- POST `/api/world/dynamic/propose`：{pack_id,request_id,change,reason}，生成玩家裁定草案。
- `contracts/personality-npcs.schema.json`、`contracts/dynamic-worldbook-change.schema.json` 与 `turn-settlement.schema.json` 为可参考格式。

人格库默认定义保存在内容包 personality-npcs.json，运行期设置、计划、出场和动态记忆保存在事件账本；旧存档默认关闭新模式，可继续读取。原始角色卡只归档，不进入模型；用户存档迁移至缺少原文件的设备仍能使用已保存人格，但来源导出会提示缺失。

版本：显示 0.99beta / API 0.99beta-builder / 桌面与 npm 0.99.0-beta / Python 0.99.0b0 / Android code 30。为测试版，不表示所有兼容扩展或多人联机已完成。


公开版采用原创静态示意角色，可自行接入授权素材。源码和安装包的测试范围以对应版本发布页为准。
