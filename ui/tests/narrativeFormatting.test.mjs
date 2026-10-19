import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
async function load(name) {
  const source = fs.readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}
const { formatNarrativeDialogue: format } = await load("narrativeFormatting");
test("Chinese dialogue is isolated, with punctuation and existing paragraphs preserved", () => {
  assert.equal(format('他停下脚步，说：“你好。”她挥手：“请进！”门开了。'), '他停下脚步，说：\n“你好。”\n她挥手：\n“请进！”\n门开了。');
  assert.equal(format('第一段。\n\n“你好。”\n第二段。'), '第一段。\n\n“你好。”\n第二段。');
  assert.equal(format('他说：「她说『明天见』。」然后离开。'), '他说：\n「她说『明天见』。」\n然后离开。');
  assert.equal(format('他说“可以”，随后点头。'), '他说\n“可以”，\n随后点头。');
});
test("English quotes, apostrophes, unmatched quotes and untrusted text stay plain text", () => {
  assert.equal(format(`He said, "Don't go." Then waited.`), `He said,\n"Don't go."\nThen waited.`);
  assert.equal(format('半句“没有结束'), '半句“没有结束');
  assert.equal(format("It's a quiet day."), "It's a quiet day.");
  assert.equal(format('<script>alert(1)</script>'), '<script>alert(1)</script>');
  assert.equal(format('无对白的长叙述。\r\n保留分段。'), '无对白的长叙述。\n保留分段。');
});
test("formatting does not accumulate newlines on repeated render", () => {
  for (const input of ['他说：“好。”“再见。”她走了。', '他说：  “你好。”  然后点头。', '“他答：\"好\"。”']) {
    assert.equal(format(format(input)), format(input));
  }
});
const { loadTheme, saveTheme, DEFAULT_THEME } = await load("theme");
test("font scales 50–160 survive storage and out-of-range values clamp", () => {
  const values = new Map();
  globalThis.localStorage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  for (const scale of [50, 55, 90, 100, 160]) {
    saveTheme({ ...DEFAULT_THEME, fontScale: scale });
    assert.equal(loadTheme().fontScale, scale);
  }
  saveTheme({ ...DEFAULT_THEME, fontScale: 20 });
  assert.equal(loadTheme().fontScale, 50);
  saveTheme({ ...DEFAULT_THEME, fontScale: 200 });
  assert.equal(loadTheme().fontScale, 160);
  delete globalThis.localStorage;
});
