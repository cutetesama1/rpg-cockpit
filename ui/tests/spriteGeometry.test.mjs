import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const source = fs.readFileSync(new URL("../src/spriteGeometry.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { spriteFrameOffset } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
test("portrait source stride survives full, bust and face crops", () => {
  assert.equal(spriteFrameOffset(512, 256, 2, 1), 256);
  assert.equal(spriteFrameOffset(256, 256, 2, 1), 0);
});
test("six frame small strips use their source stride", () => {
  assert.deepEqual(Array.from({ length: 6 }, (_, f) => spriteFrameOffset(192, 32, 6, f)), [0, 32, 64, 96, 128, 160]);
  assert.equal(spriteFrameOffset(32, 32, 6, 5), 0);
  assert.equal(spriteFrameOffset(33, 32, 1, 0), 0);
});
