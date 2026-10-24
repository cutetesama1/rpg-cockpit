import { useEffect, useRef, useState } from "react";
import { getCurrentCharacterCard, importCharacterCard, previewCharacterCard } from "../api";
import type { CardOptions, CardPreview, CardUpload, CurrentCard } from "../types";
import "../characterCards.css";

const labels: Record<string,string>={description:'角色描述',personality:'人物性格',scenario:'场景',examples:'示例对话',worldbook:'嵌入式世界书',system_prompt:'卡内叙事提示',post_history_instructions:'卡内末尾提示'};
const defaults:CardOptions={title:'',id:'',user_name:'你',role:'npc',greeting:0,include:Object.keys(labels)};
const uuid=()=>globalThis.crypto?.randomUUID?.()??`${Date.now()}-${Math.random().toString(16).slice(2)}`;
const download=(value:unknown,name:string)=>{
  const content=JSON.stringify(value);
  const nativeAndroid=/Android/.test(navigator.userAgent)&&/\bwv\b/.test(navigator.userAgent);
  let url:string;
  if(nativeAndroid){const bytes=new TextEncoder().encode(content);let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));url='data:application/json;base64,'+btoa(binary);}
  else url=URL.createObjectURL(new Blob([content],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=name;link.click();if(!nativeAndroid)setTimeout(()=>URL.revokeObjectURL(url),1000);
};

export default function CharacterCardImporter({onCreated}:{onCreated:()=>void}) {
  const [options,setOptions]=useState<CardOptions>(defaults);
  const [upload,setUpload]=useState<CardUpload|null>(null);
  const [preview,setPreview]=useState<CardPreview|null>(null);
  const [valid,setValid]=useState(false);
  const [current,setCurrent]=useState<CurrentCard|null>(null);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [message,setMessage]=useState('');
  const [retry,setRetry]=useState<Parameters<typeof importCharacterCard>[0]|null>(null);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;getCurrentCharacterCard().then(setCurrent).catch(err=>{if(alive.current)setError(String(err));});return()=>{alive.current=false;};},[]);
  const update=(changes:Partial<CardOptions>)=>{setOptions(old=>({...old,...changes}));setValid(false);setRetry(null);setMessage('映射选项已变化，请重新预览。');};
  const pick=async(file:File|undefined)=>{
    if(!file)return;setError('');setMessage('');setPreview(null);setValid(false);setRetry(null);setUpload(null);setBusy(true);
    try {
      if(file.size>20*1024*1024)throw new Error('角色卡文件不能超过 20 MB');
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
      for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
      if(alive.current){setUpload({filename:file.name,data_base64:btoa(binary)});setOptions({...defaults,include:[...defaults.include]});}
    }catch(err){if(alive.current)setError(String(err));}finally{if(alive.current)setBusy(false);}
  };
  const inspect=async()=>{
    if(!upload)return;setBusy(true);setError('');setRetry(null);
    try {const data=await previewCharacterCard({...upload,options});if(alive.current){setPreview(data);setValid(true);setMessage('预览完成。确认字段映射和开场白后，可创建为新游戏。');}}
    catch(err){if(alive.current){setError(String(err));setValid(false);}}finally{if(alive.current)setBusy(false);}
  };
  const apply=async(body:Parameters<typeof importCharacterCard>[0])=>{
    setBusy(true);setError('');setRetry(body);
    try {
      const result=await importCharacterCard(body);onCreated();
      if(alive.current){setRetry(null);setMessage(result.reused?'该导入已经完成，没有重复创建或重置游戏。':'角色卡已创建为新游戏，开场白和世界书已接入。');setValid(false);setCurrent(await getCurrentCharacterCard());}
    }catch(err){if(alive.current)setError(String(err));}finally{if(alive.current)setBusy(false);}
  };
  return <section className="character-card-importer" aria-label="角色卡导入">
    <h3>SillyTavern 角色卡 V2 / V3</h3>
    <p className="muted">选择 JSON、带角色卡数据的 PNG/APNG 或 CHARX。先预览，再创建新游戏；原始文件与不支持字段会保留。导入本身不调用 AI。</p>
    <label>选择角色卡文件<input aria-label="角色卡文件" type="file" accept=".json,.png,.apng,.charx" disabled={busy} onChange={e=>void pick(e.target.files?.[0])}/></label>
    {upload&&<>
      <p className="small">已读取：{upload.filename}</p>
      <div className="card-import-grid">
        <label>游戏标题<input aria-label="角色卡游戏标题" value={options.title} disabled={busy} maxLength={200} placeholder="留空使用角色名" onChange={e=>update({title:e.target.value})}/></label>
        <label>游戏 ID<input aria-label="角色卡游戏ID" value={options.id} disabled={busy} maxLength={64} placeholder="留空自动生成，已有 ID 不会覆盖" onChange={e=>update({id:e.target.value})}/></label>
        <label>玩家称呼<input aria-label="角色卡玩家称呼" value={options.user_name} maxLength={80} disabled={busy} onChange={e=>update({user_name:e.target.value})}/></label>
        <label>卡片角色身份<select aria-label="角色卡身份" value={options.role} disabled={busy} onChange={e=>update({role:e.target.value as CardOptions['role']})}><option value="npc">与你互动的角色（NPC）</option><option value="player">玩家扮演的角色</option></select></label>
      </div>
      <fieldset disabled={busy}><legend>导入哪些内容</legend><div className="card-mapping-options">{Object.entries(labels).map(([id,label])=><label key={id}><input type="checkbox" checked={options.include.includes(id)} onChange={e=>update({include:e.target.checked?[...options.include,id]:options.include.filter(key=>key!==id)})}/>{label}</label>)}</div></fieldset>
      <p className="muted small">NPC 的能力不会直接变成玩家技能。资源上限和技能库可在创建后的“世界构筑”中调整。卡内提示作为叙事参考，状态仍由后端结算。</p>
      <button disabled={busy} onClick={()=>void inspect()}>{busy?'正在处理…':preview?'重新预览角色卡':'预览角色卡'}</button>
    </>}
    {error&&<p className="modal-message bad" role="alert">{error}</p>}
    {message&&<p className="modal-message ok" role="status">{message}</p>}
    {retry&&<button disabled={busy} onClick={()=>void apply(retry)}>重试本次导入</button>}
    {preview&&<section className="card-preview">
      <h4>{preview.title} <small>{preview.spec} · {preview.format.toUpperCase()}</small></h4>
      <p>作者：{preview.creator||'未注明'} · 卡片版本：{preview.character_version||'未注明'} · 世界书 {preview.worldbook_count} 条</p>
      {preview.creator_notes&&<details open><summary>作者备注（不发送给模型）</summary><p className="card-source-text">{preview.creator_notes}</p></details>}
      <label>开场白<select aria-label="角色卡开场白" disabled={busy} value={options.greeting} onChange={e=>update({greeting:Number(e.target.value)})}>{preview.greetings.map(g=><option value={g.index} key={g.index}>{g.label}{g.text?'':'（空白，将使用开场生成）'}</option>)}</select></label>
      <blockquote className="card-source-text">{preview.greetings.find(g=>g.index===options.greeting)?.text||'未提供开场白。'}</blockquote>
      <details><summary>字段映射与提示词预览</summary><ul>{preview.mappings.map(row=><li key={row.source}>{row.source} → {row.target} · {row.enabled?'参与游戏':'仅保留原始数据'}</li>)}</ul>{Object.entries(preview.prompts).map(([key,value])=><details key={key}><summary>{key==='pre'?'前置设定':key==='narrator'?'叙事提示':'结算语义'}</summary><pre>{value}</pre></details>)}</details>
      <details open={preview.warnings.length>0}><summary>兼容提示 · {preview.warnings.length} 项</summary>{preview.warnings.length?<><ul>{preview.warnings.slice(0,50).map((warning,i)=><li key={i}>{warning}</li>)}</ul>{preview.warnings.length>50&&<p>其余提示可下载完整兼容报告查看。</p>}</>:<p>已映射已知字段。原始 JSON 将一并保存。</p>}<button onClick={()=>download({warnings:preview.warnings,unsupported:preview.unsupported,entry_mapping:preview.entry_mapping},'character-card-report.json')}>下载兼容报告</button></details>
      <div className="modal-actions"><button className="primary" disabled={busy||!valid||!upload} onClick={()=>upload&&void apply({...upload,options,request_id:uuid(),preview_token:preview.preview_token,expected_pack_id:preview.active_pack_id})}>按预览创建并进入</button><button disabled={busy} onClick={()=>download(preview.raw,'character-card-original.json')}>下载保留的原始 JSON</button></div>
      {!valid&&<p className="muted small">选项改变后需要重新预览，避免导入过期映射。</p>}
    </section>}
    {current?.card&&<details className="current-card"><summary>当前游戏的角色卡 · {current.card.name}</summary><p>{current.card.spec} · {current.card.creator||'未注明作者'}</p><p className="card-source-text">{current.card.creator_notes}</p><div className="modal-actions"><a href={`/api/character-cards/source?pack_id=${encodeURIComponent(current.pack_id)}`} download>导出原始 JSON</a><a href={`/api/character-cards/source-file?pack_id=${encodeURIComponent(current.pack_id)}`} download>导出原始文件</a><button onClick={()=>download(current.card,'character-card-compatibility.json')}>导出兼容报告</button></div></details>}
  </section>;
}
