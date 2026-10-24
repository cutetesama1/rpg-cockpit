<p align="center">
  <img src="docs/assets/app-icon.png" width="100" alt="RPG 驾驶舱图标" />
</p>

<h1 align="center">RPG 驾驶舱 · RPG Cockpit</h1>

<p align="center"><strong>把想象，写成世界。</strong></p>
<p align="center">可自定义、可扩展的开源 AI 文字冒险 RPG 框架。</p>

![项目展示封面](docs/assets/video-cover.png)

从一段世界观、人物背景或故事素材出发，构筑属于自己的文字冒险。

RPG 驾驶舱将自由叙事与游戏状态管理结合：叙事模型负责推进故事，独立后端在每次完整叙述后读取本回合正文与当前状态，结算实际发生的变化。世界书、提示词、基础数值、技能与界面都能调整，让不同题材拥有自己的玩法。

适合单人文字冒险、角色扮演、原创剧情试演、世界设定验证，以及轻量 RPG 原型开发。

## 下载与安装

当前公开版：**[v0.7.3 · Windows / Android](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.7.3)**。

| 平台 | 下载 |
| --- | --- |
| Android 10+，多数手机 | [arm64 APK](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.7.3/RPG-Cockpit-v0.7.3-arm64.apk) |
| Android 通用包 | [通用 APK](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.7.3/RPG-Cockpit-v0.7.3.apk) |
| Windows 10/11 64位 | [桌面安装包](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.7.3/RPG-Cockpit-v0.7.3-Windows-x64-Setup.exe) · [便携 ZIP](https://github.com/cutetesama1/rpg-cockpit/releases/download/v0.7.3/RPG-Cockpit-v0.7.3-Windows-x64-Portable.zip) |

便携版请完整解压，运行 `rpg-cockpit.exe`；桌面窗口需要 WebView2 Runtime。进入设置后配置自己的模型 API。公开下载版默认使用原创静态示意角色，素材范围与本仓库一致；完整分层立绘库未附带。校验值和本次验证范围见 Release 说明。

本次更新重点修复回滚与结算遗漏，详见 [更新日志](CHANGELOG.md) 和 [v0.7.3 说明](docs/releases/v0.7.3.md)。

## 你可以自定义什么

| 内容 | 能力 |
| --- | --- |
| 世界与故事 | AI 快速创建世界、导入 JSON 草稿、编辑人物与地点、管理多个游戏 |
| 世界书与提示词 | 常驻和关键词设定条目，分别编辑前置、叙事与后端结算提示词 |
| 基础数值 | 修改名称、初始值、当前值、上下限、单位和显示方式，并绑定生命、施法、体力及货币用途 |
| 技能与学习 | 标准库含300项技能，武技/魔法各150项，分低、中、高三级；按世界和人物背景匹配可学与初始技能 |
| 技能包 | 使用固定技能定义、行动指令、消耗和冷却；通过 ZIP 导入第三方技能库，按作者模板扩展 |
| 模型连接 | 接入兼容的模型 API，分别配置叙事与后端角色，查看用量与结算记录 |
| 外观与阅读 | 四套主题、自选壁纸、50%—160%字号，桌面驾驶舱与手机聊天布局 |

## 游玩体验

- 自由输入行动、话语与心理，也可以从 AI 建议获得灵感，修改后再发送。
- 模型正文流式显示，对白单独分行，向上查看自己与 AI 的历史对话。
- 状态、物品、技能、衣物和剧情事实通过受约束的后端操作更新。
- 技能消耗与冷却由框架处理，选用前可以查看费用反馈。
- 自动保存与手动存读档、撤销、事件记录和回放检查，便于继续游玩或验证规则。

## 叙事与结算如何合作

```text
玩家输入 / 选用技能
        ↓
叙事模型生成正文与选项
        ↓
独立后端读取本回合正文 + 当前状态 + 规则定义
        ↓
校验变化并记录事件
        ↓
刷新状态、技能、物品与外观
```

叙事阶段不提供状态修改工具。结算阶段使用独立请求，不携带历史聊天；当前状态、本回合正文及必要目录仍会发送。可以为两个角色选择不同模型，也可以复用同一连接。

语义判断仍取决于所选模型，程序校验不能保证模型永不漏判。失败的结算不会提交半个回合。

## 支持形态

- **Web 界面**：React 前端配合本地 Python API。
- **Windows**：提供桌面包装与打包脚本。
- **Android**：提供 Kotlin + Chaquopy + WebView 的 APK 构建源码。

应用不内置大语言模型。使用外部服务需要配置相应 API；连接本地推理服务需要自行部署。桌面与手机没有自动云同步功能。

## 开发运行

准备 Python 3.11+、Node.js 和 npm。在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
npm --prefix ui ci
npm --prefix ui run build
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
```

开发前端：`http://127.0.0.1:5173`；API：`http://127.0.0.1:8787`。

默认脚本模型用于开发流程。进入设置后，配置自己的模型端点与 API Key，再开始真实模型游玩。

标准技能库源码与作者模板位于 `skill-libraries/`，可执行下列命令重新生成技能 ZIP：

```powershell
python tools/build_skill_library.py
```

## 项目结构

```text
core/             规则、状态、事件与结算
gateway/          模型连接与角色路由
content/          世界、内容包与技能库加载
api/              FastAPI 接口
ui/               React + TypeScript 界面
packs/            示例世界与配置
skill-libraries/  标准技能与作者模板
src-tauri/        Windows 桌面包装
android/          Android 构建源码
tests/            测试
```

## 素材与当前范围

此公开源码导出包使用**原创静态示意角色**，没有包含开发演示中使用的第三方完整立绘库。

后端衣物、表情与姿势字段接口保留；完整换装、表情及动作画面需要开发者提供对应素材和配置。当前默认姿势为站立，不宣称具备完整行走、攻击或施法动画。

Android 的预编译依赖 wheel、发布签名、安装包、模型密钥、个人配置、存档和私有 Git 历史均未随此源码包分发。Android 构建依赖说明见 [android/local-wheels/README.md](android/local-wheels/README.md)。

本源码包完成了 Python 语法检查、资源引用检查和敏感凭据模式扫描；完整私有素材测试环境未复制，因此不将原开发环境的全套测试结果当作本导出包的验收结论。记录见 [EXPORT_REPORT.json](EXPORT_REPORT.json)。

## 参与开发

欢迎提交功能建议、问题复现和 Pull Request。反馈模型相关问题时，请注明端点类型、模型名称、操作步骤和实际结果；提供日志前移除 API Key 与个人信息。

## 许可证

本导出包的一方代码与原创示例图形采用 [Apache License 2.0](LICENSE)。第三方依赖和素材保留各自许可，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。


## v0.99beta
新增剧情导演、骰子、裁定、角色卡、人格NPC和动态世界书。详见[更新日志](docs/CHANGELOG-v0.99beta.md)。公开版继续使用原创示意角色，可自行接入授权素材。


## v0.991beta
新增文字展示速度、独立数值纠正、双模式浮动纠正入口和桌面双方历史。详见[更新日志](docs/CHANGELOG-v0.991beta.md)。公开版继续使用原创示意角色，可自行接入授权素材。
