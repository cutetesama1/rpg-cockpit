# 插件 SDK（P0 占位）

P0 只固定边界，不实现运行时：

- 插件是**声明式扩展**：内容包覆盖（overlay）、词表追加、提示词替换、UI 槽位、主题。
- **不执行第三方代码**（无 Python/JS 插件加载器），避免越权与沙箱成本。
- 冲突规则、版本约束、启用/禁用与热更新在 P6（M7）实现。

契约占位：`plugin-manifest.schema.json`。加载器与校验器待 P6 补齐。

```json
{
  "id": "my-overlay",
  "name": "更冷的夜",
  "version": "0.1.0",
  "kind": "content-overlay",
  "targets": ["night-convenience-store"],
  "overrides": {
    "prompts/narrator.md": "覆盖后的叙事提示词……",
    "state.fields.hp.max": 30
  }
}
```
