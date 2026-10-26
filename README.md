<p align="center">
  <img src="docs/assets/app-icon.png" width="100" alt="RPG 驾驶舱图标" />
</p>

<h1 align="center">RPG 驾驶舱 · RPG Cockpit</h1>

<p align="center"><strong>把想象，写成世界。</strong></p>
<p align="center">从世界构筑到角色成长，让 AI 叙事成为可以游玩、修改与延续的冒险。</p>
<p align="center">开源 · Windows / Android / Web · 自选模型 · 自定义世界与规则</p>
<p align="center">
  <a href="https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.993">下载 0.993</a> ·
  <a href="docs/CHANGELOG-v0.993.md">本版更新</a> ·
  <a href="docs/CHANGELOG-v0.99beta.md">0.99beta 更新</a> ·
  <a href="LICENSE">Apache 2.0</a>
</p>

![项目展示封面](docs/assets/video-cover.png)

从一段世界观、人物背景或角色卡出发，构筑属于自己的文字冒险。

**RPG 驾驶舱是可自定义、可扩展的开源 AI 文字冒险 RPG 框架。** 叙事 AI 描绘故事，独立后端结算角色数值与游戏变化；可选剧情导演安排候选事件，后端骰子执行检定，玩家通过裁定中心审阅有争议的结果。世界书、人物、提示词、基础数值、技能和阅读界面都能按你的设定调整。

适合单人文字冒险、角色扮演、原创剧情试演、世界设定验证，以及轻量 RPG 原型开发。

## 下载与安装

**当前数字版本：[v0.993](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.993)**，包含 0.99beta 的全部更新。数字版按每次 +0.001 发布，均仍处于开发预发布阶段。

| 平台 | 0.993下载 |
| --- | --- |
| Android 10+，多数手机 | [arm64 APK](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Cockpit-v0.993-arm64.apk) |
| Android 通用包 | [通用 APK](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Cockpit-v0.993.apk) |
| Android x86_64 设备或模拟器 | [x86_64 APK](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Cockpit-v0.993-x86_64.apk) |
| Windows 10/11 64 位 | [桌面安装包](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Cockpit-v0.993-Windows-x64-Setup.exe) · [便携 ZIP](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Cockpit-v0.993-Windows-x64-Portable.zip) |
| Web | 从源码运行 React 前端与本地 Python API，见下方开发运行说明 |

便携版请完整解压，让两个 EXE 保持在同一目录，再运行 `rpg-cockpit.exe`。Windows 窗口需要 WebView2 Runtime。升级前退出旧版，建议先备份存档；Android 沿用原公开版签名。

进入设置后配置自己的模型 API。应用不内置大语言模型；使用外部服务需自行配置，本地推理服务需自行部署。公开版附带原创静态示意角色，完整分层立绘库需自行接入授权素材。

[0.99beta 下载](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.99beta) · [此前非预发布版 v0.7.3](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.7.3) · [全部版本与校验文件](https://github.com/cutetesama1/rpg-cockpit/releases)

## 本版更新

- 叙事、结算、导演等模型角色分别配置 URL、API Key 与模型。
- NPC 对白语音：可选择仅导入 NPC，或识别本轮 NPC 后朗读；只读取人物对白。

[完整更新日志](docs/releases/v0.993.md) · [数字版本对应表](docs/NUMERICAL-RELEASES.md)

## 历史更新

### 0.991beta API 修复

统一发送应用 User-Agent，修复默认 Python 网络库标识可能导致的自建网关 / Cloudflare 1010 拦截；覆盖普通、流式及模型列表请求，明确提示 1010 与 CF-Ray。详见 [API 修复说明](docs/releases/v0.993.md)。

[原 0.991beta](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.991beta) 保留供回退。

### 0.991beta：更顺手地阅读与纠正

- **可调文字展示速度**：5—200 字符/秒或即时显示，也可一键显示已收到的内容。只改变阅读节奏，不拖慢 API 接收、模型生成和后端结算。
- **圆形 AI 纠正入口**：点击展开输入框，以带图标的按钮切换“更改叙述”和“更改数值”，两种草稿分别保留。
- **叙述修订**：修改最近一段正文，调整叙述视角或语气；修订不推进剧情回合，可保留要求供后续叙述使用。
- **独立数值纠正 AI**：根据本次纠正说明、当前数值和字段规则提出修改，经后端校验后提交；支持回执、重复请求保护与适当撤销。
- **桌面完整对话历史**：向上查看自己的行动、AI 回复、纠正说明和修订稿，随存档恢复。

详见 [0.991beta 更新日志](docs/CHANGELOG-v0.991beta.md) 与 [使用说明](docs/P28-文字展示与AI纠正.md)。

### 0.99beta：让人物与世界持续发展

| 功能 | 你可以做什么 |
| --- | --- |
| 剧情导演与骰子 | 可选导演提出候选事件；后端执行骰子与概率检定，记录已触发的结果，重复请求不会重新掷骰 |
| 玩家裁定中心 | 查看说明与修改差异，确认、否决、修改或搁置事项，回看历史并进行适当撤销 |
| 角色卡 V2/V3 | 导入 JSON、PNG/APNG、CHARX，预览并映射字段；不支持的字段保留原始数据 |
| 仅人格 NPC 模式 | 批量选择角色卡，只读取姓名、性格与明确喜好，将人物加入世界；卡内提示词不进入此模式的模型请求 |
| 人物出场安排 | 设置出场门槛，由剧情导演结合情境提出出场候选与复查计划，经检定通过后登场 |
| 动态世界书 | 持续维护人物、关系、地点、秘密与关键事实，保留来源、版本和历史，支持归档、揭晓与撤销 |

详见 [0.99beta 更新日志](docs/CHANGELOG-v0.99beta.md)。人格 NPC 模式需要开启剧情导演；动态世界书复用后端结算调用，生命、施法资源、库存和冷却仍由游戏状态系统管理。

## 你可以自定义什么

| 内容 | 能力 |
| --- | --- |
| 世界与故事 | AI 快速创建世界、导入 JSON 草稿、编辑人物与地点、管理多个游戏 |
| 世界书与提示词 | 常驻和关键词设定条目、动态剧情事实，分别配置叙事、后端与可选导演等角色 |
| 基础数值 | 自定义名称、初始值、上下限、单位与显示方式，绑定生命、施法、体力及货币用途 |
| 技能与成长 | 标准库含 300 项技能，武技/魔法各 150 项，分低、中、高三级；按世界和角色背景匹配可学与初始技能 |
| 技能包 | 固定技能定义、行动指令、消耗与冷却，通过 ZIP 导入第三方技能库，按作者模板扩展 |
| 模型连接 | 接入兼容的模型 API，不同角色可选不同模型或复用连接，查看用量与结算记录 |
| 外观与阅读 | 四套主题、自选壁纸、50%—160% 字号、文字展示速度，桌面驾驶舱与手机聊天布局 |

[下载 300 技能库](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-300-Skills-v1.zip) · [下载技能作者模板](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.993/RPG-Skill-Library-Author-Template-v1.zip)

## 游玩体验

- 自由输入行动、话语与心理，也可以参考 AI 建议，修改后再发送。
- 正文流式显示，对白单独分行，向上查看自己与 AI 的历史对话。
- 手机主界面聚焦叙述与输入，立绘、状态、技能和设置收纳到侧边栏。
- 状态、物品、技能、衣物和剧情事实通过受约束的后端操作更新。
- 技能消耗与冷却由框架处理，选用前可以查看费用反馈。
- 自动保存、手动存读档、撤销与事件记录，便于继续冒险或检查规则。

## AI 如何合作

```text
玩家输入 / 选用技能
        ↓
可选剧情导演提出候选 → 后端检定 → 已触发的确定结果
        ↓
叙事 AI 生成正文与选项
        ↓
独立结算 AI 读取本回合正文 + 当前状态 + 规则
        ↓
后端校验、提交状态与动态世界书 → 刷新界面

玩家主动纠正 → 叙述修订 / 独立数值纠正 → 校验与回执
待确认事项   → 玩家裁定中心 → 校验与提交
```

叙事 AI 不直接修改权威游戏状态。结算请求不携带历史聊天，读取本回合正文、当前状态和必要规则；导演按场景变化、重要事件等条件触发，未触发的候选不进入叙事上下文。数值纠正使用独立角色，只读取本次纠正所需资料。

动态世界书维护剧情记忆，数值、技能冷却与物品数量由专门的状态工具处理。语义判断仍取决于所选模型，程序校验不能保证模型永不漏判。

## 支持形态与当前范围

- **Web**：React + TypeScript 界面配合本地 Python API。
- **Windows**：Tauri 桌面应用，提供安装包与便携版。
- **Android**：Kotlin + Chaquopy + WebView，提供已签名 APK 与构建源码。

当前面向单人游玩；多人联机尚未实现。桌面与手机没有自动云同步功能。

## 开发运行

准备 Python 3.11+、Node.js 和 npm。在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
npm --prefix ui ci
npm --prefix ui run build
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
```

开发前端：`http://127.0.0.1:5173`；API：`http://127.0.0.1:8787`。默认脚本模型用于开发流程，真实模型游玩需在设置中配置端点与 API Key。

标准技能库源码与作者模板位于 `skill-libraries/`，可重新生成技能 ZIP：

```powershell
python tools/build_skill_library.py
```

## 项目结构

```text
core/             规则、状态、事件与结算
gateway/          模型连接与角色路由
content/          世界、内容包、角色卡与技能库加载
api/              FastAPI 接口
ui/               React + TypeScript 界面
packs/            示例世界与配置
skill-libraries/  标准技能与作者模板
src-tauri/        Windows 桌面包装
android/          Android 构建源码
tests/            测试
```

## 素材与验证

公开源码和安装包采用**原创静态示意角色**，没有包含开发演示中的第三方完整立绘库。衣物、表情与姿势字段接口保留；完整换装和动作画面需要提供对应素材和配置。

0.991beta 公开源码验证：后端 **608 项通过、12 项跳过、0 失败**，前端 **28 项通过**，TypeScript 与生产构建通过。Windows 打包程序启动与相关接口、三种 APK 的版本、签名和包内资源一致性已核对。跳过项涉及可选配置或未分发的第三方图片；未使用真实付费模型，未进行 Android 真机安装测试。详细记录见 [版本验证报告](docs/releases/v0.991beta-verification.json) 与 [发布页](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.993)。

Android 预编译依赖 wheel、发布签名、模型密钥、个人配置和存档不随源码分发。Android 构建依赖见 [说明](android/local-wheels/README.md)，公开源码导出范围见 [EXPORT_REPORT.json](EXPORT_REPORT.json)。

## 参与开发与许可证

欢迎提交功能建议、问题复现和 Pull Request。反馈模型相关问题时，请注明端点类型、模型名称、操作步骤和实际结果；提供日志前移除 API Key 与个人信息。

本项目一方代码与原创示例图形采用 [Apache License 2.0](LICENSE)。第三方依赖和素材保留各自许可，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
