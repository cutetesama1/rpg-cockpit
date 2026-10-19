# RPG 驾驶舱 · Android

Android 壳采用 Kotlin、Chaquopy CPython 3.13 与 WebView，在应用私有目录运行本地 FastAPI 引擎，手机无需连接电脑。

## 当前公开版

- 版本：0.7.1，versionCode 24。
- 最低 Android 10（API 29），target/compile SDK 36。
- ABI：arm64-v8a、x86_64，另提供通用 APK。
- APK 下载：[GitHub Releases](https://github.com/cutetesama1/rpg-cockpit/releases/tag/v0.7.1)。
- 公开包使用原创静态示意角色，不包含第三方完整立绘库。

界面为流式聊天，支持历史对话、圆角输入区、动作/话语/心理选择，以及右展菜单中的角色、状态、技能和底部设置。模型服务须由用户配置。

## 构建环境

本机已验证的工具为 JDK 22、Gradle 8.13、Android SDK 36 与 Chaquopy 16.1。配置文件中的 JDK 和 `buildPython` 路径需要按自己的电脑调整。

先按 [local-wheels/README.md](local-wheels/README.md) 准备 pydantic-core 的两个 Android wheel；它们不随公开源码分发。先在项目根目录构建前端：

```powershell
npm --prefix ui ci
npm --prefix ui run build
```

然后在 android 目录执行：

```powershell
gradle assembleRelease --no-daemon
```

没有发布签名配置时自动使用 debug 签名。正式发布可以使用仓库外的现有配置：

```powershell
gradle assembleRelease --no-daemon -PrpgSigningProperties=C:/private/rpg-signing/keystore/keystore.properties
```

`storeFile` 可以是绝对路径，或相对于该 properties 文件父目录的上一级目录。密码和私钥只保存在你自己的签名目录中，不要提交到仓库。

输出目录为 `app/build/outputs/apk/release/`，其中有 arm64、x86_64 和 universal 三个 APK。

若本机 JDK 22 出现 `WEPollSelector` / `Unable to establish loopback connection`，本次构建通过给 Gradle JVM 及子进程设置 `-Djava.nio.channels.spi.SelectorProvider=sun.nio.ch.WindowsSelectorProvider` 后完成；该设置仅用于构建进程，不写入系统配置。

## 运行方式

`syncBackend` 将后端、内容包、技能库和构建后的 Web UI 写入 APK assets。启动时 `AssetInstaller` 按版本戳解压到私有目录，随后 Python 引擎监听本地端口8710，WebView 加载本地界面。

应用配置、模型 Key、用户内容与存档放在 App 私有目录，`allowBackup=false`。只有 localhost 可使用明文 HTTP；远程模型端点使用 HTTPS。

## 本次验证范围

三个 APK 均构建通过，签名、版本、资源引用、Kotlin 程序入口和 ZIP 完整性已核对。本次没有已连接的 Android 真机或模拟器，因此没有进行设备安装与输入法回归。详见 [发布验证记录](../docs/releases/v0.7.1-verification.json)。
