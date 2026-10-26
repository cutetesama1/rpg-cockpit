import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(fs.readFileSync(new URL("../src/chatHistory.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { buildChatHistory: history, actionMessage } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const e=(seq,turn,kind,payload)=>({seq,turn,kind,payload});
test("ledger restores both sides in sequence, including opening and player modes", () => {
  const ledger=[e(3,1,"narrative.generated",{narrative:"门开了。“请进。”"}),e(1,0,"narrative.generated",{opening:true,narrative:"开局"}),e(2,1,"turn.started",{action:{kind:"text",text:"我敲门，说你好",modes:["action","speech"]}})];
  const chat=history(ledger);
  assert.deepEqual(chat.map(m=>m.role),["assistant","user","assistant"]);
  assert.equal(chat[1].text,"我敲门，说你好");
  assert.deepEqual(chat[1].meta,["动作","话语"]);
  assert.deepEqual(history(JSON.parse(JSON.stringify(ledger))),chat);
});
test("undo removes both sides; failed input and failure notice remain visible", () => {
  const ledger=[e(1,0,"narrative.generated",{narrative:"开局"}),e(2,1,"turn.started",{action:{kind:"text",text:"撤销我"}}),e(3,1,"narrative.generated",{narrative:"旧回复"}),e(4,1,"turn.rolled_back",{reason:"undo"}),e(5,2,"turn.started",{action:{kind:"text",text:"失败输入"}}),e(6,2,"turn.rolled_back",{reason:"guardrail_or_llm_failure",errors:["超时"]})];
  const chat=history(ledger);
  assert.equal(chat.length,3);assert.equal(chat[1].text,"失败输入");assert.equal(chat[1].failed,true);
  assert.equal(chat[2].role,"notice");assert.ok(chat[2].text.includes("超时"));
});
test("skill-only, extras-only and historical options have readable labels", () => {
  assert.equal(actionMessage({kind:"skill",skill_id:"focus_step"},{focus_step:"专注步法"}).text,"使用技能：专注步法");
  assert.equal(actionMessage({kind:"text",text:"",extras:["inspect"]}).text,"附加请求：审视");
  assert.equal(history([e(1,1,"turn.started",{action:{kind:"option",option_id:"old"},display_text:"我推开大门。"})])[0].text,"我推开大门。");
  assert.equal(actionMessage({kind:"option",option_id:"unknown"}).text,"选择选项：unknown");
});
test("segments override whole-message modes and invalid legacy values do not crash", () => {
  assert.deepEqual(actionMessage({kind:"text",text:"你好",segments:[{mode:"speech",text:"你好"}],modes:["thought"]}).meta,["话语"]);
  assert.deepEqual(actionMessage({kind:"text",text:null,modes:["constructor","bad"]}).meta,[]);
  assert.equal(history([e(1,1,"turn.started",{debug:true})]).length,0);
});
test("untrusted prose stays plain text and AI-only legacy saves do not invent user input", () => {
  const text='<img src=x onerror=alert(1)>';
  const chat=history([e(1,0,"narrative.generated",{narrative:text})]);
  assert.equal(chat.length,1);assert.equal(chat[0].role,"assistant");assert.equal(chat[0].text,text);
});

test("uncertain settlement is visible and survives reload; undo and failed turns hide it", () => {
  const ledger=[e(1,1,"turn.started",{action:{kind:"text",text:"继续"}}),e(2,1,"settlement.warning",{uncertain:["新披风没有目录映射"]}),e(3,1,"narrative.generated",{narrative:"你擦伤了手臂。"}),e(4,1,"turn.committed",{})];
  const chat=history(ledger);
  assert.equal(chat.length,2);assert.equal(chat[1].role,"assistant");assert.match(chat[1].backendNotes[0],/新披风/);
  assert.deepEqual(history(JSON.parse(JSON.stringify(ledger))),chat);
  assert.equal(history([...ledger,e(5,1,"turn.rolled_back",{reason:"undo"})]).length,0);
  assert.ok(!history([...ledger,e(5,1,"turn.rolled_back",{reason:"guardrail_or_llm_failure"})]).some(m=>m.text.includes("待确认")));
});

test("correction inputs and revised replies remain chronological and auxiliary undo hides them", () => {
  const ledger=[e(1,0,"narrative.generated",{narrative:"原文"}),e(2,-1,"correction.applied",{mode:"narrative",anchor:0,instruction:"改为第一人称",narrative:"修订稿"})];
  assert.deepEqual(history(ledger).map(m=>m.text),["原文","改为第一人称","修订稿"]);
  assert.deepEqual(history([...ledger,e(3,-1,"turn.rolled_back",{reason:"correction_undo"})]).map(m=>m.text),["原文"]);
  const stats=[e(4,-2,"correction.applied",{mode:"state",anchor:1,instruction:"恢复体力",changes:{hp:{}},explanation:"已恢复"})];
  assert.deepEqual(history(stats).map(m=>m.role),["user","notice"]);
  assert.equal(history([...stats,e(5,1,"turn.rolled_back",{reason:"undo"})]).length,0);
});
