# v0.991beta-api-fix · 自建 API 网关兼容修复

本版基于公开 v0.991beta，修复默认 Python 网络库 User-Agent 可能导致自建网关及 Cloudflare 1010 拦截的问题。

## 修复内容

- 普通模型请求、SSE 流式请求、流式回退及模型列表统一发送 `User-Agent: RPG-Cockpit/0.991beta-api-fix`。
- 叙事、后端结算、剧情导演、世界构筑、裁定及数值纠正共用的模型网关均采用该应用标识。
- 网关明确返回 Cloudflare 1010 时，显示对应原因、当前 UA 及可用的 CF-Ray，不再仅提示可能是 API Key 错误。
- 检测完整错误页中的 1010 标识，避免旧版只看前 300 字节时遗漏；提示不回显网关页面中可能包含的密钥。
- Bearer Key、模型请求体以及 JSON / SSE 的 Accept 设置保持兼容。

Cloudflare 官方建议客户端发送能标识应用的 UA，而不是网络库默认值：[Error 1010 官方说明](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)。若仍被网关策略拒绝，需要由网关管理员检查对应 API 路径的规则。

## 下载与升级

- 多数 Android 手机选 arm64；通用 APK 支持 arm64 与 x86_64，另提供独立 x86_64 包。
- Android 版本名 `0.991beta-api-fix`，versionCode **32**；沿用原公开版签名，可覆盖旧版。
- Windows 提供安装包与便携 ZIP，桌面内部版本为 `0.99.1-beta.1`。升级前关闭旧版，便携版完整解压后运行 `rpg-cockpit.exe`。
- 保留公开 v0.991beta 的功能和原创静态示意立绘，旧版发布页保留供回退。
- 网关 URL 请填写 API 根地址，例如 `https://你的网关/v1`，并使用该网关的 Key 与模型名称。

## 验证范围

- 公开源码后端：**616 项通过，12 项跳过，0 失败**。
- UA 与网关兼容专项：8 项通过；覆盖模型列表、普通调用、流式、回退、全部六个模型角色、1010 及密钥保护。
- 前端：**28 项通过**；TypeScript 与生产构建通过。
- Windows 打包引擎通过本地 UA 拦截网关验证，模型列表、设置连接测试和流式开场均使用应用 UA；原有公开功能接口和原创立绘可读取。
- 三种 APK 均验证签名、版本和包内源代码 / 网页资源一致性；安装包不包含私有完整立绘库或签名材料。

未连接反馈者的实际网关，未使用真实付费模型，未在实体 Android 设备安装测试。校验值见 `SHA256SUMS.txt`。
