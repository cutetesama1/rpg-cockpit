import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const source=fs.readFileSync(new URL('../src/spriteMotion.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {portraitMotion,portraitContext}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
test('body and sleeves receive one effective arm posture without mutating state',()=>{
 const state={pose:'guard',left_arm:'auto',right_arm:'auto'};
 const ctx=portraitContext(state);
 assert.equal(ctx.portrait_left_arm,'cover');assert.equal(ctx.portrait_right_arm,'cover');assert.deepEqual(state,{pose:'guard',left_arm:'auto',right_arm:'auto'});
 assert.equal(portraitContext({pose:'stand',handheld:'umbrella'}).portrait_right_arm,'hold');
 assert.equal(portraitContext({pose:'cast',right_arm:'idle'}).portrait_right_arm,'idle');
 assert.equal(portraitContext({pose:'cast',handheld:'sword cane'},0,false,{'sword cane':'idle'},{'sword cane':['idle']}).portrait_right_arm,'idle');
 assert.equal(portraitContext({pose:'talk',mouth_shape:'auto'}).portrait_mouth,'chew');
});
test('motion transforms stay within the portrait padding and are deterministic',()=>{
 for(const kind of ['none','sway','walk','run','jump','attack','cast','hurt']) for(let t=0;t<5;t+=.073){
  const m=portraitMotion(kind,t);assert.ok(Object.values(m).every(Number.isFinite));assert.ok(Math.abs(m.x)<=6&&Math.abs(m.y)<=13&&Math.abs(m.angle)<=.07);assert.deepEqual(m,portraitMotion(kind,t));
 }
 assert.deepEqual(portraitMotion('none',3),{x:0,y:0,angle:0,scaleX:1,scaleY:1});
});
