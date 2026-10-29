# ElevenLabs 原生 TTS

旧实现始终将语音根 URL 拼接为 `/audio/speech`，发送 OpenAI 的
`Authorization: Bearer …` 和 `model/voice/input/response_format/speed`。
因此填写 `https://api.elevenlabs.io/v1` 会请求不存在的
`POST https://api.elevenlabs.io/v1/audio/speech`，与 Termux 已成功的原生接口不同。

在模型设置的「NPC 语音」选择 **ElevenLabs 原生**，配置：

- URL：`https://api.elevenlabs.io/v1`（根地址，不包含音色路径）
- 模型：`eleven_multilingual_v2`（留空也使用此默认值）
- 默认音色：`cJ90yKqmDMAuUmZ3fyB4`；人物单独配置的音色会覆盖它
- API Key：通过本机设置界面填写，或在本机后端配置中配置；不要提交到仓库

后端发送 `POST /v1/text-to-speech/{voice_id}`，使用 `xi-api-key` 认证，
`Content-Type: application/json`、`Accept: audio/mpeg`，请求体仅有 `text` 和 `model_id`。
ElevenLabs 原生模式不发送 OpenAI 的 `speed`，界面禁用该选项。
切换 Provider 不会自动转换旧 Key，请填写对应服务的 Key（留空沿用后端已有 Key）。

这是 React + Python 后端架构。密钥保存在本机后端设置文件（已有保存逻辑设置权限为
0600），设置读取只返回脱敏视图；浏览器不直接请求 ElevenLabs。
用户在设置界面新输入的 Key 仅通过本地设置 API 提交，不写入前端源码或浏览器持久存储。
如将本机服务部署到公共网络，应在反向代理配置 HTTPS 和访问认证，禁止公开设置接口。

上游 MP3 以 bytes 返回，`/api/voice/audio` 使用 `audio/mpeg` 和 `Cache-Control: no-store`，
现有播放器通过 `Response.blob()`、对象 URL 和 HTML audio 播放，保留停止、取消和对象 URL 回收。
上游 HTTP 错误会在界面显示状态码；后端日志仅记录 Provider、POST、接口模板、状态码或音频字节数，
不记录实际 URL、认证头、台词、模型值或上游正文。不会跟随重定向发送密钥。

旧配置没有 `provider` 时默认为 `openai`，保留 `/audio/speech`、Bearer 和原有请求体。

## 验证

安装项目测试依赖后运行：

```sh
python -m pytest tests/test_speech_providers.py tests/test_speech.py tests/test_api_speech.py tests/test_http_identity.py tests/test_settings.py
```

测试使用模拟响应或本地服务器，不需要真实密钥，不调用付费服务。
包括原生 URL/认证/JSON、OpenAI 请求回归、MP3 二进制、错误脱敏、配置持久化和 API 音频缓存。
真实设备播放验收：保存上述配置，在已完成对话中点击 NPC 台词播放，确认能听到 MP3，
并检查停止和重播；浏览器如限制自动播放，可点击音频控件播放。
