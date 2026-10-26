import type { FieldDef, SpriteSheet } from './types';
import { consumeEventStream } from './sse';
export type PartySession = {server_url:string;room_id:string;player_id:string;token:string};
export type Intent = {skill_names?:string[];text:string;modes:('action'|'speech')[];skills:string[]};
export type Member = {id:string;name:string;owner:boolean;state:Record<string,unknown>;ready:boolean;submitted:boolean;intent_revision:number|null;intent:Intent|null;inventory:Record<string,number>|null;skills:{id:string;name:string;description:string;available:boolean;cooldown_remaining:number;cost:Record<string,number>}[]};
export type PartyView = {items?:{id:string;name:string}[];scene_title?:string;opening_text?:string;opening_generated:boolean;opening?:{task_id:string;narrative:string;options:{actor_id:string;label:string;action_text:string}[]}|null;id:string;title:string;capacity:number;owner_id:string;me:string;phase:string;round:number;round_token:string;revision:number;cursor:number;world:{scene:string;state:Record<string,unknown>;facts:Record<string,{title:string;value:unknown}>};players:Member[];fields:FieldDef[];history:{round:number;task_id:string;inputs:({actor_id:string;name:string}&Intent)[];narrative:string;options:{actor_id:string;label:string;action_text:string}[]}[];task:{id:string;round:number;status:string;text:string;error:string;narration_complete:boolean;kind?:string}|null;pending:{id:string;round:number;reason:string}[];pending_count:number;invite_code?:string;undo:{id:string;round:number;votes:Record<string,boolean>;eligible:string[]}|null};
const KEY='rpg-party-session-v1';
export function requestId(){return crypto.randomUUID ? crypto.randomUUID() : 'req_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2);}
export function serverUrl(input:string){const url=new URL(input);if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||url.pathname!='/')throw new Error('请填写HTTP或HTTPS房主地址，可使用穿透域名和公网端口');return url.origin;}
export function savedSession():PartySession|null{try{const raw=JSON.parse(localStorage.getItem(KEY)||'null');return raw&&raw.token&&raw.room_id?raw:null;}catch{return null;}}
export function saveSession(value:PartySession|null){try{value?localStorage.setItem(KEY,JSON.stringify(value)):localStorage.removeItem(KEY);}catch{/* Session still works until the page closes. */}}
export function transportUrl(input:string){
  const url=new URL(input,location.href);
  // Android's WebView permits local HTTP only. Bridge room requests through the
  // loopback engine, which checks the explicitly selected room-server origin.
  if(/Android/i.test(navigator.userAgent)&&['127.0.0.1','localhost'].includes(location.hostname)&&url.origin!==location.origin)return '/api/multiplayer/relay?target='+encodeURIComponent(url.href);
  return url.href;
}
export async function jsonRequest<T>(url:string,method='GET',body?:unknown,token?:string,signal?:AbortSignal):Promise<T>{
  const res=await fetch(transportUrl(url),{method,signal,headers:{'ngrok-skip-browser-warning':'true',...(body!==undefined?{'Content-Type':'application/json'}:{}),...(token?{Authorization:'Bearer '+token}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  if(!res.ok){const error=await res.json().catch(()=>null);throw new Error(typeof error?.detail==='string'?error.detail:`请求失败（${res.status}）`);}return res.json();
}
export function roomRequest<T>(session:PartySession,path:string,method='GET',body?:unknown){return jsonRequest<T>(`${session.server_url}/api/rooms/${session.room_id}/${path}`,method,body,session.token);}
export async function subscribe(session:PartySession,after:number,signal:AbortSignal,receive:(event:string,row:{seq:number;data:Record<string,unknown>})=>void){
  const response=await fetch(transportUrl(`${session.server_url}/api/rooms/${session.room_id}/events`),{method:'POST',signal,headers:{'Content-Type':'application/json','ngrok-skip-browser-warning':'true',Authorization:'Bearer '+session.token},body:JSON.stringify({after})});
  await consumeEventStream(response,(event,row)=>receive(event,row as {seq:number;data:Record<string,unknown>}));
}
export function roomImageLoader(session:PartySession){
  const cache=new Map<string,Promise<HTMLImageElement|null>>();
  return (path:string)=>{
    if(!cache.has(path))cache.set(path,(async()=>{try{
      const response=await fetch(transportUrl(`${session.server_url}/api/rooms/${session.room_id}/assets/${path.split('/').map(encodeURIComponent).join('/')}`),{headers:{'ngrok-skip-browser-warning':'true',Authorization:'Bearer '+session.token}});if(!response.ok)throw new Error('asset');
      const url=URL.createObjectURL(await response.blob());try{return await new Promise<HTMLImageElement>((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=reject;img.src=url;});}finally{URL.revokeObjectURL(url);}
    }catch{cache.delete(path);return null;}})());return cache.get(path)!;
  };
}
export type PartySheet={sheet:SpriteSheet|null;asset_revision:string};
