import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const js=ts.transpileModule(fs.readFileSync(new URL('../src/mobileViewport.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {visibleViewport}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

test('IME resize uses innerHeight even if visualViewport is stale',()=>{
  assert.equal(visibleViewport({innerHeight:480,innerWidth:390,visualHeight:844}).height,480);
  assert.equal(visibleViewport({innerHeight:844,innerWidth:390,visualHeight:480}).height,480);
});
test('native and browser keyboard signals do not subtract the IME twice',()=>{
  assert.equal(visibleViewport({innerHeight:480,innerWidth:390,visualHeight:480,native:{widthPx:1080,heightPx:1329}}).height,480);
  assert.equal(visibleViewport({innerHeight:844,innerWidth:390,visualHeight:844,native:{widthPx:1080,heightPx:1329}}).height,480);
});
test('keyboard closure restores height, overlay keyboard and viewport panning are supported',()=>{
  assert.deepEqual(visibleViewport({innerHeight:844,innerWidth:390,visualHeight:844}),{height:844,top:0});
  assert.deepEqual(visibleViewport({innerHeight:844,innerWidth:390,keyboardTop:500,visualOffsetTop:20}),{height:480,top:20});
  assert.equal(visibleViewport({innerHeight:844,innerWidth:390,visualHeight:400,scale:2}).height,844);
});
