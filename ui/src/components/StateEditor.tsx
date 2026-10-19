import type { FieldDef, Scalar, StateConfig } from '../types';
const ROLES: Record<string,string> = {health:'生命资源',mana:'施法资源',effort:'武技／体力资源',currency:'货币'};
export default function StateEditor({value,onChange,disabled=false,current,onCurrent}:{value:StateConfig;onChange:(v:StateConfig)=>void;disabled?:boolean;current?:Record<string,Scalar>;onCurrent?:(v:Record<string,Scalar>)=>void}) {
  const numeric=value.fields.filter(f=>f.type==='int'||f.type==='float');
  const patch=(id:string,data:Partial<FieldDef>)=>onChange({...value,fields:value.fields.map(f=>f.id===id?{...f,...data}:f)});
  const add=()=>{let n=1;while(value.fields.some(f=>f.id===`resource_${n}`))n++;onChange({...value,fields:[...value.fields,{id:`resource_${n}`,label:'自定义资源',type:'int',default:100,min:0,max:100,step:1,display:'bar',group:'vitals',color:'#91d6b9'}]});};
  return <section className="state-editor" aria-label="基础数值编辑">
    <p className="hint">按世界观自定义名称、初始值、上下限和单位。初始值用于新开局；已有进度保留当前值，提高上限不会自动回满。上限留空表示不限制。</p>
    <div className="state-resource-bindings">{Object.entries(ROLES).map(([role,label])=><label key={role}>{label}<select disabled={disabled} aria-label={label+'绑定'} value={value.resource_bindings[role]??''} onChange={e=>onChange({...value,resource_bindings:{...value.resource_bindings,[role]:e.target.value}})}><option value="">不使用此用途</option>{numeric.map(f=><option key={f.id} value={f.id}>{f.label}（{f.id}）</option>)}</select></label>)}</div>
    {numeric.map(field=><article className="edit-card state-field-card" key={field.id}>
      <div className="edit-grid">
        <label>名称<input aria-label={field.id+'名称'} value={field.label} disabled={disabled} onChange={e=>patch(field.id,{label:e.target.value})}/></label>
        <label>内部 ID<input value={field.id} readOnly title="内部 ID 保持稳定，改名不会破坏技能引用"/></label>
        <label>初始值<input aria-label={field.id+'初始值'} type="number" step={field.step??1} value={Number(field.default??0)} disabled={disabled} onChange={e=>patch(field.id,{default:Number(e.target.value)})}/></label>
        {current&&onCurrent&&<label>当前值<input aria-label={field.id+'当前值'} type="number" step={field.step??1} value={Number(current[field.id]??field.default??0)} disabled={disabled} onChange={e=>onCurrent({...current,[field.id]:Number(e.target.value)})}/></label>}
        <label>最低值<input aria-label={field.id+'最低值'} type="number" value={field.min??''} disabled={disabled} onChange={e=>patch(field.id,{min:e.target.value===''?null:Number(e.target.value)})}/></label>
        <label>上限<input aria-label={field.id+'上限'} type="number" placeholder="不限制" value={field.max??''} disabled={disabled} onChange={e=>patch(field.id,{max:e.target.value===''?null:Number(e.target.value),...(e.target.value===''?{display:'number'}:{})})}/></label>
        <label>类型<select value={field.type} disabled={disabled} onChange={e=>patch(field.id,{type:e.target.value})}><option value="int">整数</option><option value="float">小数</option></select></label>
        <label>步进<input type="number" min="0.001" step="any" value={field.step??1} disabled={disabled} onChange={e=>patch(field.id,{step:Number(e.target.value)})}/></label>
        <label>单位<input value={field.unit??''} disabled={disabled} onChange={e=>patch(field.id,{unit:e.target.value||null})}/></label>
        <label>显示<select value={field.display} disabled={disabled} onChange={e=>patch(field.id,{display:e.target.value})}><option value="bar">状态条</option><option value="number">数字</option><option value="hidden">隐藏</option></select></label>
        <label>颜色<input type="color" value={field.color??'#91d6b9'} disabled={disabled} onChange={e=>patch(field.id,{color:e.target.value})}/></label>
        <label>单回合变化限额<input type="number" min="0" placeholder="不另设限制" value={value.limits.max_delta_per_turn[field.id]??''} disabled={disabled} onChange={e=>{const limits={...value.limits.max_delta_per_turn};if(e.target.value==='')delete limits[field.id];else limits[field.id]=Number(e.target.value);onChange({...value,limits:{...value.limits,max_delta_per_turn:limits}});}}/></label>
      </div>
      <button type="button" className="ghost small" disabled={disabled} onClick={()=>{const bindings={...value.resource_bindings};for(const key in bindings)if(bindings[key]===field.id)bindings[key]='';const limits={...value.limits.max_delta_per_turn};delete limits[field.id];onChange({...value,fields:value.fields.filter(f=>f.id!==field.id),resource_bindings:bindings,limits:{...value.limits,max_delta_per_turn:limits}});}}>删除数值</button>
    </article>)}
    <button type="button" disabled={disabled} onClick={add}>添加基础数值</button>
    <p className="muted small">删除被技能、场景或立绘引用的字段会被拒绝，请先解除引用。绑定施法资源后，预设法术会扣除该资源。</p>
  </section>;
}
