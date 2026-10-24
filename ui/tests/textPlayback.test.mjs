import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const js=ts.transpileModule(fs.readFileSync(new URL('../src/textPlayback.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {advanceCharacters,commonPrefixLength,normalizeTextSpeed}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
test('display pacing has stable fractional budget across small frames',()=>{
  let credit=0,total=0;
  for(let i=0;i<100;i++){const step=advanceCharacters(credit,10,25,1000);credit=step.credit;total+=step.count;}
  assert.equal(total,25);
  assert.equal(advanceCharacters(0,16,0,800).count,800);
});
test('rate changes and background gaps are bounded',()=>{
  assert.equal(normalizeTextSpeed(-10),0);assert.equal(normalizeTextSpeed('bad'),60);
  assert.equal(normalizeTextSpeed(999),200);assert.equal(normalizeTextSpeed(1),5);
  assert.equal(advanceCharacters(0,10000,20,1000).count,5);
  assert.equal(advanceCharacters(.75,20,50,0).count,0);
});
test('revised final text and non-BMP characters keep a valid prefix',()=>{
  assert.equal(commonPrefixLength('你好🌟旧句','你好🌟新句'),3);
  assert.equal(Array.from('你好🌟').slice(0,3).join(''),'你好🌟');
  assert.equal(commonPrefixLength('a longer preview','a final result'),2);
});
