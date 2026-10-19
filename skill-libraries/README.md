# 技能库格式 v1

ZIP 根目录或唯一一层文件夹内放 manifest.json 和 skills.json。
manifest.type 必须为 rpg.skill-library，schema_version=1，id 使用小写字母/数字/连字符。
skills.json 为 {"skills": [条目]}；每项含 id、kind(martial/magic)、tier(low/mid/high)、school、tags、aliases、requires_world_tags、excludes_world_tags、prerequisites、resource_cost、instruction、skill。
skill 是完整技能定义：id/name/description/cost/cooldown/targets/usable_when/action_text/effect_hint/category/brief。
条目 id 与 skill.id 必须相同；skill.cost 留空，消耗由 resource_cost 声明，再依据 manifest.resources 绑定游戏状态字段。
默认 effort 优先 stamina/energy/focus；mana 优先 mp/mana/focus；资源字段缺失的技能不会变成免费技能。
魔法必须 requires_world_tags 包含 magic。prerequisites 引用同库条目 id，不能循环。
学习只引用 ref（库id:条目id），不重写预设技能；初始掌握数量由世界和角色背景决定，没有固定新手配额。
本包仅包含数据，不放 Python、JavaScript、插件或可执行指令脚本。instruction 是给叙事/结算模型的固定行动说明。
升级请采用新的库 id，旧世界保留自己的快照，不覆盖旧技能定义。

导入：设置 → 技能库 · 预设技能 → 导入技能库 ZIP。
随后新建世界会自动匹配；已有可编辑世界可点“为当前世界匹配技能池”，保留当前进度。
已掌握技能可以直接勾选使用，未掌握技能由叙述确认学习后由后端登记。
