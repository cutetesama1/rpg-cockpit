import { useEffect, useRef, useState } from "react";
import type { CorrectionMode, CorrectionResult } from "../api";
export function CorrectionIcon({ mode = "narrative" }: { mode?: CorrectionMode }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{mode === "narrative" ? <><path d="m14 5 5 5M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z"/><path d="M13 20h7"/></> : <><rect x="4" y="3" width="16" height="18" rx="4"/><path d="M8 8h8M8 13h3m-1.5-1.5v3M14 14h2M8 18h3m3 0h2"/></>}</svg>;
}
interface Props {
  open: boolean;
  busy: boolean;
  packId: string;
  result: CorrectionResult | null;
  error: string | null;
  onClose: () => void;
  onSubmit: (mode: CorrectionMode, text: string, persist: boolean) => void;
  onUndo: () => void;
}
export default function CorrectionPanel(props: Props) {
  const [mode, setMode] = useState<CorrectionMode>("narrative");
  const [drafts, setDrafts] = useState({ narrative: "", state: "" });
  const [persist, setPersist] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { setDrafts({ narrative: "", state: "" }); setPersist(false); }, [props.packId]);
  useEffect(() => { if (props.open) input.current?.focus(); }, [props.open, mode]);
  useEffect(() => {
    if (!props.open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && !props.busy) { event.preventDefault(); props.onClose(); } };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [props.open, props.busy, props.onClose]);
  if (!props.open) return null;
  const text = drafts[mode];
  const submit = () => { if (!props.busy && text.trim()) props.onSubmit(mode, text.trim(), mode === "narrative" && persist); };
  return <section className="correction-panel" aria-label="纠正 AI">
    <header><div><CorrectionIcon mode={mode}/><strong>纠正 AI</strong></div><button type="button" className="ghost" aria-label="关闭纠正框" disabled={props.busy} onClick={props.onClose}>✕</button></header>
    <div className="correction-switch" role="group" aria-label="纠正模式">
      {([['narrative','更改叙述'],['state','更改数值']] as const).map(([id,label]) => <button key={id} type="button" aria-pressed={mode === id} className={mode === id ? "on" : ""} disabled={props.busy} onClick={() => setMode(id)}><CorrectionIcon mode={id}/>{label}</button>)}
    </div>
    <p className="correction-hint">{mode === "narrative" ? "修订最近一段正文，可更改视角、语气和表述。不会再次结算或推进回合。" : "独立 AI 只读取本次说明和当前数值。写清要调整的资源和结果，例如“体力恢复至上限，金币减少 5”。"}</p>
    <textarea ref={input} rows={3} maxLength={6000} aria-label={mode === "narrative" ? "叙述纠正内容" : "数值纠正说明"} placeholder={mode === "narrative" ? "例如：改为第一人称，让人物话语单独分行…" : "例如：刚才已完成休息，将体力恢复至上限…"} value={text} disabled={props.busy} onChange={e => setDrafts(prev => ({...prev,[mode]:e.target.value}))} onKeyDown={event => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
    }}/>
    {mode === "narrative" && <label className="correction-persist"><input type="checkbox" checked={persist} disabled={props.busy} onChange={e => setPersist(e.target.checked)}/>后续叙述也遵循本次视角、文风要求</label>}
    {props.error && <p className="correction-error" role="alert">{props.error}</p>}
    {props.result && <div className="correction-result" role="status"><p>{props.result.explanation}</p>{Object.values(props.result.changes).map(change => <span key={change.field}>{props.result?.status.fields.find(f => f.id === change.field)?.label ?? change.field}：{String(change.before)} → {String(change.after)}</span>)}<button className="ghost small" type="button" disabled={props.busy} onClick={props.onUndo}>撤销本次纠正</button></div>}
    <footer><span>Ctrl / ⌘ + Enter 提交</span><button type="button" className="primary" disabled={props.busy || !text.trim()} onClick={submit}>{props.busy ? "正在纠正…" : mode === "narrative" ? "修订叙述" : "应用数值"}</button></footer>
  </section>;
}
