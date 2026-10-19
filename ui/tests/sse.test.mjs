import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(fs.readFileSync(new URL("../src/sse.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {consumeEventStream}=await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const response=(text)=>new Response(new ReadableStream({start(c){for(const b of new TextEncoder().encode(text))c.enqueue(new Uint8Array([b]));c.close();}}));
test("SSE handles byte-split UTF-8, split CRLF, heartbeats and an unframed tail",async()=>{
  const events=[];
  await consumeEventStream(response(': ping\r\n\r\nevent: narrative\r\ndata: {"text":"风声🌙"}\r\n\r\nevent: result\ndata: {"ok":true}'),(kind,data)=>events.push([kind,data]));
  assert.deepEqual(events,[["narrative",{text:"风声🌙"}],["result",{ok:true}]]);
});
test("first text is delivered while the response remains open",async()=>{
  let controller;let seen=false;
  const stream=new ReadableStream({start(c){controller=c;c.enqueue(new TextEncoder().encode('event: narrative\ndata: {"text":"第一段"}\n\n'));}});
  const reading=consumeEventStream(new Response(stream),(kind,data)=>{if(kind==='narrative'){seen=true;assert.equal(data.text,'第一段');}});
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(seen,true);
  controller.enqueue(new TextEncoder().encode('event: result\ndata: {"ok":true}\n\n'));controller.close();
  await reading;
});
test("SSE propagates malformed/error frames and rejects HTTP errors",async()=>{
  await assert.rejects(()=>consumeEventStream(response('data: nope\n\n'),()=>{}));
  await assert.rejects(()=>consumeEventStream(new Response('oops',{status:503}),()=>{}),/HTTP 503/);
  await assert.rejects(()=>consumeEventStream(response('event: error\ndata: {"error":"断线"}\n\n'),()=>{throw new Error('断线')}),/断线/);
});
