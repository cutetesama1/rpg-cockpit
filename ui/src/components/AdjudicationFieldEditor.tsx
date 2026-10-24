import { useEffect, useState } from "react";
import { getAdjudicationEditor } from "../api";
import { fieldDraft, hex, rgb, type EditorCatalog, type DraftOp } from "../adjudicationFields";

export default function AdjudicationFieldEditor({ packId, operations, disabled, onChange, onMessage }: {
  packId: string; operations: string; disabled: boolean; onChange: (value: string) => void; onMessage: (value: string) => void;
}) {
  const [catalog,setCatalog]=useState<EditorCatalog|null>(null);
  const [fieldId,setFieldId]=useState("");const [value,setValue]=useState("");
  const [error,setError]=useState("");
  useEffect(()=>{ let alive=true;getAdjudicationEditor().then(data=>{if(alive && data.pack_id===packId)setCatalog(data);}).catch(err=>{if(alive)setError(String(err));});return()=>{alive=false;}; },[packId]);
  const field=catalog?.fields.find(f=>f.id===fieldId);
  const choose=(id:string)=>{const f=catalog?.fields.find(row=>row.id===id);setFieldId(id);setValue(f?.input==='color'?hex(rgb(String(f.value))):String(f?.value??""));};
  const add=()=>{
    if(!field||!catalog)return;
    try {
      const ops=JSON.parse(operations);if(!Array.isArray(ops))throw new Error("操作草案须为数组");
      const v=field.type==='int'||field.type==='float'?Number(value):field.type==='bool'?value==='true':value;
      if(typeof v==='number' && (!Number.isFinite(v)||field.type==='int'&&!Number.isInteger(v)))throw new Error("请输入合法数字，整数字段不能含小数");
      if(field.input==='color'&&!/^#[\da-f]{6}$/i.test(value))throw new Error("请选择有效颜色");
      onChange(JSON.stringify(fieldDraft(ops as DraftOp[],field,v,catalog.health_field),null,2));onMessage(`已更新「${field.label}」草案，请填写依据并预览。`);
    }catch(err){onMessage(String(err));}
  };
  return <div className="adjudication-field-editor">
    {error&&<p role="alert">{error}</p>}
    <label>要裁定的内容<select aria-label="裁定状态字段" disabled={disabled||!catalog} value={fieldId} onChange={e=>choose(e.target.value)}><option value="">{catalog?"选择状态、衣物、饰品或颜色":"正在读取当前游戏目录…"}</option>{catalog?.fields.map(f=><option key={f.id} value={f.id}>{f.label} · 当前 {f.options[String(f.value)]??String(f.value??"未设置")}</option>)}</select></label>
    {field && <div className="adjudication-field-value"><span>{field.label}</span>
      {field.input==='select'?<select aria-label="裁定字段值" disabled={disabled} value={value} onChange={e=>setValue(e.target.value)}>{field.type==='bool'?<><option value="true">是</option><option value="false">否</option></>:Object.entries(field.options).map(([id,label])=><option value={id} key={id}>{label}</option>)}</select>
      :field.input==='color'?<div className="adjudication-color"><input type="color" aria-label="裁定颜色选择" disabled={disabled} value={hex(rgb(value))} onChange={e=>setValue(e.target.value)}/>{['R','G','B'].map((channel,i)=><label key={channel}>{channel}<input type="number" aria-label={`裁定颜色${channel}`} min={0} max={255} step={1} disabled={disabled} value={rgb(value)[i]} onChange={e=>{const channels=rgb(value);channels[i]=Number(e.target.value);setValue(hex(channels));}}/></label>)}<output>{value}</output></div>
      :<input aria-label="裁定字段值" disabled={disabled} type={field.input==='number'?'number':'text'} min={field.min??undefined} max={field.max??undefined} step={field.type==='int'?1:field.step??'any'} value={value} onChange={e=>setValue(e.target.value)}/>}
      {field.input==='number'&&<small>填写裁定后的最终值{field.min!=null?`，最低 ${field.min}`:''}{field.max!=null?`，最高 ${field.max}`:''}。</small>}
      {field.slot&&<small>已连接当前游戏的衣物目录，会通过换装工具修改。</small>}
    </div>}
    <button disabled={disabled||!field||!value.trim()} onClick={add}>添加状态草案</button>
  </div>;
}
