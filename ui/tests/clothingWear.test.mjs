import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(fs.readFileSync(new URL("../src/clothingWear.ts",import.meta.url),"utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { clothingWearPixel: wear } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
test("clothing wear distinguishes four levels and keeps idle frames aligned", () => {
  const samples = condition => Array.from({ length: 16*18 }, (_,i) => wear(i%16,Math.floor(i/16),condition));
  assert.equal(samples("intact").filter(Boolean).length,0);
  assert.notDeepEqual(samples("scuffed"), samples("damaged"));
  assert.notDeepEqual(samples("damaged"), samples("ruined"));
  for (let y=0;y<256;y+=3) for(let x=0;x<256;x+=3) {
    assert.equal(wear(x,y,"ruined"),wear(x+256,y,"ruined"));
    assert.ok(wear(x,y,"ruined")>=0 && wear(x,y,"ruined")<=1);
  }
});
