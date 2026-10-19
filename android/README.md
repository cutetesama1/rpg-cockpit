# RPG 驾驶舱 · Android 端

手机端 App：Kotlin 壳 + Chaquopy 内嵌 CPython，Python 在 App 私有目录里跑本地引擎，
WebView 通过 `http://127.0.0.1:<port>` 加载界面。目标是手机上完全不依赖电脑。

## 当前进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 环境（cmdline-tools、NDK 27.2、CMake 3.22、platform 36、JDK 22、模拟器） | ✅ |
| P1 | 最小 APK：Chaquopy + Python 3.13 + 本地 HTTP + WebView + 健康检查 | ✅ 模拟器验收通过 |
| P2 | pydantic-core 在 Android 上编译（高风险） | ✅ 两个 ABI 的 wheel 已产出并在模拟器导入成功 |
| P3 | 换成真正的 FastAPI 后端 + 内容包 + 存档 + 真 UI | ✅ 模拟器验收通过 |
| P4 | UI 手机适配（竖屏单栏/抽屉/吸底 + 横屏双栏） | ✅ 竖屏 ≤640px 单列；**横屏手机（高 ≤560px）为主要场景**，叙事/输入 + 状态/技能双栏一屏 |
| P5 | API Key 安全、真模型、内容包导入 | ✅ 真模型出叙事；zip 导入走系统文件选择器 |
| P6 | release 签名、按 ABI 拆分、图标/启动图、发布文档 | ✅ 签名 APK 产物 + 模拟器验收（真机 arm64 仍待有设备时回归） |

验收环境：Android 17 / API 37，x86_64 模拟器（`emulator-5554`），minSdk 29。
APK：debug 通用包约 47 MB；release 产物见 `android/app/build/outputs/apk/release/`
（`app-universal-release.apk` 47.4 MB、`app-arm64-v8a-release.apk` 36.3 MB、`app-x86_64-release.apk` 36.3 MB）。

## P3 验收（模拟器实测）

- 冷启动日志：
  ```
  RpgCockpit: assets extracted: backend -> /data/user/0/com.rpgframework.cockpit/files/runtime/backend in 288ms
  RpgCockpit: python probe: {'ok': True, 'api_py': True, 'ui_index': True, 'packs': ['night-convenience-store']}
  python.stdout: [rpg-android] fastapi app loaded: 0.6.0-builder
  python.stdout: [rpg-android] uvicorn listening on http://127.0.0.1:8710
  ```
  随后 `/api/health` 返回 200、WebView 加载真界面（免责声明 → 新手指引 → 叙事驾驶舱）。
- `/api/library`、`/api/state`、`/api/action`、`/api/settings`、`/api/saves` 全部可用；
  存档/设置/内容包都在 App 私有目录 `/data/user/0/com.rpgframework.cockpit/files/rpg/`。

## P4 验收（≤640px）

- 单列纵向布局：叙事区 → 输入区 → 右栏（状态/技能）→ 小票；发送条 `position: sticky` 吸底。
- 左上角 ☰ 打开左侧导航抽屉（遮罩/✕/点导航项/Esc/转桌面宽度 都会关闭），抽屉内按钮 44px 触控。
- **横屏（现在的首要场景）**：`@media (max-width: 640px), (orientation: landscape) and (max-height: 560px)`
  让横屏手机先拿到竖屏的手机行为，再叠一档精修块：`.layout` 双栏（叙事列 + `clamp(240px,30vw,340px)`
  右栏，右栏自身滚动）；顶栏压成单行、隐藏副标题与模型条；叙事区限高 `calc(100dvh - 332px)`；
  发送条紧跟输入框（不再吸底），「附加 / 接下来」各压成单行横滚。
  2400×1080 横屏（411dp 高）实测：叙事、输入、发送、附加、选项五块都在首屏。
- 桌面端规则一行未改：移动端覆盖收在 `ui/src/styles.css` 的
  `@media (max-width: 640px), (orientation: landscape) and (max-height: 560px)` 与末尾横屏精修块里。

## P5 验收（模拟器实测）

- **真模型**：把桌面 `~/.rpg-framework/settings.json` 推进
  `files/rpg/config/settings.json` 后重启，`/api/settings` 显示 narrator = `deepseek/deepseek-flash`、
  `max_tokens=0`；`/api/settings/test` 返回 `ok=True model=deepseek-flash latency≈1.0s`；
  `/api/opening` 4.6s 生成 664 字 / 11 段 / 4 个选项的真实开场。
- **Key 安全**：`/api/settings` 只回 `has_key` 与 `key_hint: "***5b91"`，不回明文；
  `api_key` 只写在 App 私有目录的 `settings.json`；`AndroidManifest.xml` 里 `allowBackup=false`
  （不参与云备份/换机迁移）；明文 HTTP 只允许 `127.0.0.1` / `localhost`（`network_security_config.xml`）。
- **内容包导入**：设置抽屉「内容包 · 导入 zip」→ 系统文件选择器（`onShowFileChooser`）→
  Web 侧 base64 上传 → `POST /api/library/import` → Python 校验（manifest / zip-slip / 20 MB 上限 /
  `load_pack` 全量校验）后落到用户包目录；模拟器实测导入「异世界」包成功，
  `/api/library` 出现 `new-game`（`builtin=False, valid=True`）并成功切换。

## P6 验收（release 产物，模拟器实测）

- **签名**：`android/keystore/rpg-release.jks`（PKCS12、RSA 4096、10000 天）+ `android/keystore/keystore.properties`；
  两者都被 `.gitignore` 的 `keystore/` 挡住，不入库。`app/build.gradle.kts` 在 properties 缺失时回落到
  debug 签名，保证别人 clone 后也能构建。`apksigner verify` 实测签名者 `CN=RPG Cockpit`。
- **按 ABI 拆分**：`splits.abi` + `isUniversalApk = true`，一次 `assembleRelease` 出三个包：
  通用 47.4 MB / `arm64-v8a` 36.3 MB / `x86_64` 36.3 MB（`output-metadata.json`：versionCode 6、
  versionName 0.6.0、各自 `filterType: ABI`）；瘦包 `lib/` 里只剩对应 ABI 的 8 个 `.so`（含 `libpython3.13.so`）。
  模拟器装 x86_64 瘦包，冷启动、后端、WebView 全部正常。
- **图标 / 启动图**：自适应图标（深色底 + 青绿菱形，`res/mipmap-anydpi-v26/ic_launcher(.round).xml` +
  `res/drawable/ic_launcher_foreground.xml`）；Android 12+ 启动画面（`res/values-v31/themes.xml`，
  `windowSplashScreenBackground` + 同图标），启动不再先闪一下白屏。
- **横屏 + 真模型整体验收**：release 包在 2400×1080 横屏加载「异世界」包，narrator=`deepseek-flash`、
  `max_tokens=0`，`/api/opening` 705 字真实开场；右栏状态四条评分条带小字描述；
  叙事/输入/发送/附加/接下来选项都在一屏内（截图 `android-previews/04-landscape-real-model.png`）。
- **顺手修的真机问题**：启动器原来 `setdefault("RPG_PACK", "night-convenience-store")`，
  它比 `library.json` 的 `active_pack` 优先级高，导致用户选过的包重启后被拽回样例包；
  已删掉该默认值（未选包时由 api 侧回落到样例包）。

## 设计要点

- **固定端口**：`android/app/src/main/python/main.py` 里 `PREFERRED_PORT = 8710`（被占用才回落随机端口）。
  WebView 的 `localStorage`（主题、叙事滚动、「不再提示」）按 origin 隔离，端口一变就全丢，所以固定端口。
- **后端资源打包**：Gradle 的 `syncBackend` 任务把仓库里的
  `api/ core/ gateway/ content/ packs/night-convenience-store/ ui/dist/` 同步到
  `app/src/main/assets/backend/` 并写 `version.txt`；`AssetInstaller.kt` 在启动时按版本号
  解压到 `files/runtime/backend/`（版本相同就跳过）。
- **启动顺序**：`AssetInstaller.install()` → `Python.start()` → `main.start_server(filesDir)`（幂等）
  → 轮询 `/api/health`（30s 超时）→ WebView 加载 `http://127.0.0.1:<port>/`。
- **环境重定向**：启动器设置 `RPG_SAVES / RPG_USER_PACKS / RPG_CONFIG_DIR / RPG_LIBRARY / RPG_SETTINGS /
  RPG_DATA_DIR / RPG_HOST`，后端代码本身不需要知道自己在手机上。**不要设 `RPG_PACK`**：它优先级高于
  `library.json` 的 active_pack，会把用户选过的包冲掉（P6 踩过）。
- **原生依赖**：Chaquopy 官方仓库没有 pydantic-core，`android/local-wheels/` 放了两份手工交叉编译的
  wheel（Rust 1.99 + NDK 27.2 + `--features pyo3/extension-module`，步骤见该目录 README）；
  `fastapi` / `uvicorn`（不带 `[standard]`，避开 uvloop/httptools 原生库）走 pip。

## 环境要求

- Android SDK：platform `android-36`、build-tools 35+、platform-tools、cmdline-tools
- NDK（仅重新编译 pydantic-core 时需要）：`27.2.12479018`；CMake：`3.22.1`
- JDK 17–22（本项目 `gradle.properties` 指向 `C:\Program Files\Java\jdk-22`）
- Gradle 8.13（`C:\Tools\gradle-8.13`）
- 本机 Python 3.13（Chaquopy 的 `buildPython`，见 `app/build.gradle.kts`）

## 构建 / 安装

```bash
# 1) 构建 debug APK（自动同步后端与 UI 资源进 assets）
cd android
JAVA_HOME="C:/Program Files/Java/jdk-22" \
ANDROID_HOME="$LOCALAPPDATA/Android/Sdk" \
"C:/Tools/gradle-8.13/bin/gradle.bat" assembleDebug --no-daemon

# 2) 装到已连接的设备/模拟器
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.rpgframework.cockpit/.MainActivity

# 3) 调试：把 WebView 控制台与 Python 输出接到 logcat
adb logcat -s RpgCockpit RpgWeb python.stdout

# 4) release（需要 android/keystore/keystore.properties；缺失时自动回落 debug 签名）
JAVA_HOME="C:/Program Files/Java/jdk-22" ANDROID_HOME="$LOCALAPPDATA/Android/Sdk" "C:/Tools/gradle-8.13/bin/gradle.bat" assembleRelease --no-daemon
# 产物：app/build/outputs/apk/release/{app-universal,app-arm64-v8a,app-x86_64}-release.apk
```

首次构建约 3–4 分钟（Chaquopy 会下载 Android 版 Python 运行时）；之后改 UI 只跑 `npm run build`
再 `assembleDebug`，增量约 20–60 秒。

## 结构

```
android/
├── app/src/main/java/com/rpgframework/cockpit/MainActivity.kt   # Kotlin 壳：启动 Python、健康检查、WebView、文件选择器
├── app/src/main/java/com/rpgframework/cockpit/AssetInstaller.kt # 把 assets/backend 解压到私有目录（带版本号）
├── app/src/main/python/main.py                                  # Python 启动器：env 重定向 + uvicorn（固定端口）
├── app/src/main/AndroidManifest.xml                             # INTERNET、allowBackup=false、仅 127.0.0.1 明文
├── app/src/main/res/xml/network_security_config.xml
├── app/src/main/res/mipmap-anydpi-v26/                         # 自适应图标
├── app/src/main/res/values-v31/themes.xml                       # Android 12+ 启动画面
├── keystore/                                                    # release 签名材料（.gitignore，不入库）
├── app/build.gradle.kts                                         # AGP 8.13 + Kotlin + Chaquopy 16.1 + syncBackend
├── app/src/main/assets/backend/                                 # 构建产物（.gitignore 忽略，由 syncBackend 生成）
├── local-wheels/                                                # 手工交叉编译的 pydantic_core wheel（已入库）
└── scripts/assemble_pydantic_wheel.py                           # 从 Rust 产物组装 wheel
```

## 已知限制

- 只支持 arm64-v8a 与 x86_64；目前完整验收只在 x86_64 模拟器做过，arm64 真机还没有可用设备回归
  （瘦包已产出、`lib/` 里只有 arm64 的 8 个 `.so`，但没有真机跑过）。
- release 用的是本机自签名 keystore，只适合自用/侧载；要上架应用商店需另建密钥并长期保管。
- 真模型偶尔会调用内容包没有声明的 `set_flag` / 场景，被护栏拒绝两次会整回合回滚（内容提示词问题，与 Android 无关）。
- `gradle.properties`、`app/build.gradle.kts` 里写死了本机 JDK / Python 路径，换机器需要改。
- P6 之后仍缺：应用商店上架流程、崩溃上报、arm64 真机回归、进一步压体积。
