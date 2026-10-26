import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const js=ts.transpileModule(fs.readFileSync(new URL('../src/narrativeReview.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {lastNarrativeIds,turnQuestions,questionEffect}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
test('only the latest narrative/revision owns each round questions',()=>{
  const ids=lastNarrativeIds([{id:'user',turn:1,role:'user'},{id:'original',turn:1,role:'assistant'},{id:'revised',turn:1,role:'assistant'},{id:'next',turn:2,role:'assistant'}]);
  assert.equal(ids.get(1),'revised');assert.equal(ids.get(2),'next');
});
test('inline questions exclude secrets, other turns and deferred cases',()=>{
  const row={source_turn:1,visibility:'public',state:'pending'};
  const visible=turnQuestions([{...row,id:'yes'},{...row,id:'answered',state:'confirmed'},{...row,id:'no',state:'rejected'},{...row,id:'secret',visibility:'internal'},{...row,id:'later',state:'deferred'},{...row,id:'other',source_turn:2}],1);
  assert.deepEqual(visible.map(r=>r.id),['yes','answered','no']);
});
test('question effect describes changes without exposing operation JSON',()=>{
  const item={title:'钥匙入包',status_patch:{},operations:[{name:'acquire_item',args:{name:'旧钥匙',count:1}},{name:'add_stat',args:{field:'money',delta:100}}]};
  assert.equal(questionEffect(item,[{id:'money',label:'金钱'}]),'旧钥匙 × 1；金钱 +100');
  assert.match(questionEffect({...item,operations:[]}),/仅记录/);
});
