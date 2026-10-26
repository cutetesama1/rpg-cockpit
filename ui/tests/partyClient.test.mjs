import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const compile=file=>ts.transpileModule(fs.readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const asModule=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const streamModule=asModule(compile('../src/sse.ts'));
const client=await import(asModule(compile('../src/partyClient.ts').replace(/from ["']\.\/sse["']/,`from "${streamModule}"`)));
globalThis.location=new URL('http://127.0.0.1:8787/?multiplayer=1');
function agent(value){Object.defineProperty(globalThis,'navigator',{value:{userAgent:value},configurable:true});}
test('tunnel addresses support public domains, TLS ports and IPv6',()=>{
  assert.equal(client.serverUrl('https://party.example:32451'),'https://party.example:32451');
  assert.equal(client.serverUrl('http://[2001:db8::1]:30000'),'http://[2001:db8::1]:30000');
  assert.throws(()=>client.serverUrl('https://user:secret@party.example'));
});
test('authenticated GET includes tunnel bypass header and keeps token out of URL',async()=>{
  agent('Desktop');let request;
  globalThis.fetch=async(url,options)=>{request={url,options};return Response.json({ok:true});};
  await client.jsonRequest('https://party.example/api/rooms/room_test/state','GET',undefined,'room-session');
  assert.equal(request.options.headers['ngrok-skip-browser-warning'],'true');
  assert.equal(request.options.headers.Authorization,'Bearer room-session');
  assert.ok(!request.url.includes('room-session'));assert.equal(request.options.body,undefined);
});
test('Android routes tunnel traffic through loopback while control requests stay local',()=>{
  agent('Android');
  const routed=client.transportUrl('https://party.example:30000/api/party/health');
  assert.ok(routed.startsWith('/api/multiplayer/relay?target='));
  assert.equal(new URL(routed,location.href).searchParams.get('target'),'https://party.example:30000/api/party/health');
  assert.equal(client.transportUrl('/api/multiplayer/connections'),'http://127.0.0.1:8787/api/multiplayer/connections');
});
test('room streaming survives the relay and carries room auth plus tunnel headers',async()=>{
  agent('Android');let request;const received=[];
  globalThis.fetch=async(url,options)=>{request={url,options};return new Response('event: narrative.delta\ndata: {"seq":3,"data":{"text":"山风"}}\n\n');};
  await client.subscribe({server_url:'https://party.example',room_id:'room_test',player_id:'actor_test',token:'scoped-token'},2,new AbortController().signal,(kind,row)=>received.push([kind,row]));
  assert.equal(request.options.headers.Authorization,'Bearer scoped-token');
  assert.equal(request.options.headers['ngrok-skip-browser-warning'],'true');
  assert.deepEqual(received,[['narrative.delta',{seq:3,data:{text:'山风'}}]]);
});
