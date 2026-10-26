import AdjudicationFieldEditor from "./AdjudicationFieldEditor";
import { useEffect, useRef, useState } from "react";
import { getAdjudications, previewAdjudication, decideAdjudication } from "../api";
import type { AdjudicationItem, AdjudicationView, DecisionDraft, DecisionPreview, Status } from "../types";
import "../adjudication.css";

const uuid = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const states: Record<string, string> = { pending: "待裁定", deferred: "已搁置", confirmed: "已确认", rejected: "已否决" };
const actions: Record<string, string> = { confirm: "确认", modify: "修改草案", reject: "否决", defer: "搁置", resume: "恢复", undo: "撤销裁定" };
const domains: Record<string, string> = { state: "状态", inventory: "物品", status: "角色信息", skills: "技能", facts: "剧情事实", worldbook: "动态世界书", npcs: "人物出场", items: "物品登记", scene: "场景" };
const text = (value: unknown) => value === null || value === undefined ? "未设置" : typeof value === "object" ? JSON.stringify(value) : String(value);

export default function AdjudicationCenter({ open, onClose, status, busy: gameBusy, onChanged }: {
  open: boolean; onClose: () => void; status: Status; busy: boolean; onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<AdjudicationView | null>(null);
  const [internal, setInternal] = useState(false);
  const [tab, setTab] = useState("pending");
  const [selected, setSelected] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [operations, setOperations] = useState("[]");
  const [patch, setPatch] = useState("{}");
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<(DecisionPreview & { decision: DecisionDraft }) | null>(null);
  const [retry, setRetry] = useState<{ id: string; decision: DecisionDraft; internal: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pane = useRef<HTMLElement>(null);
  const previewPane = useRef<HTMLElement>(null);
  useEffect(() => { if (preview) previewPane.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [preview]);
  const scope = useRef(0);
  const packId = status.pack.id;
  const disabled = busy || gameBusy;
  const item = data?.items.find(row => row.id === selected);

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    pane.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const items = Array.from(pane.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),summary') ?? []).filter(el => el.getClientRects().length);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", keys);
    return () => { window.removeEventListener("keydown", keys); before?.focus({ preventScroll: true }); };
  }, [open, onClose]);

  useEffect(() => {
    const current = ++scope.current;
    setData(null); setSelected(null); setPreview(null); setRetry(null); setEditing(false); setMessage("");
    if (open) getAdjudications(internal).then(next => {
      if (scope.current === current && next.pack_id === packId) {
        setData(next);
        const first = next.items.find(row => row.state === "pending");
        if (first) choose(first);
      }
    }).catch(err => { if (scope.current === current) setMessage(String(err)); });
    return () => { ++scope.current; };
  }, [open, internal, packId]);

  const choose = (row: AdjudicationItem) => {
    setSelected(row.id); setReason(""); setOperations(JSON.stringify(row.operations, null, 2));
    setPatch(JSON.stringify(row.status_patch, null, 2)); setEditing(false); setPreview(null); setMessage("");
  };
  const change = () => { setEditing(true); setPreview(null); };
  const run = async (task: (current: number) => Promise<void>) => {
    const current = scope.current; setBusy(true); setMessage("");
    try { await task(current); }
    catch (err) { if (scope.current === current) setMessage(String(err)); }
    finally { setBusy(false); }
  };
  const refresh = () => run(async current => {
    const next = await getAdjudications(internal);
    if (scope.current !== current || next.pack_id !== packId) return;
    setData(next); setPreview(null); setRetry(null); setMessage("已读取最新状态，请重新选择事项并预览。");
  });
  const inspect = (action: "confirm" | "modify") => run(async current => {
    if (!data || !item) return;
    const decision: DecisionDraft = { request_id: uuid(), revision: data.revision, action, reason,
      ...(action === "modify" ? { operations: JSON.parse(operations), status_patch: JSON.parse(patch) } : {}) };
    const result = await previewAdjudication(packId, item.id, decision, internal);
    if (scope.current === current && result.pack_id === packId) setPreview({ ...result, decision: { ...decision, preview_token: result.preview_token } });
  });
  const submit = (request: { id: string; decision: DecisionDraft; internal: boolean }) => run(async current => {
    setRetry(request);
    const next = await decideAdjudication(packId, request.id, request.decision, request.internal);
    await onChanged();
    if (scope.current !== current || next.pack_id !== packId) return;
    setData(next); setPreview(null); setRetry(null); setEditing(false);
    const updated = next.items.find(row => row.id === request.id);
    if (updated) { setOperations(JSON.stringify(updated.operations, null, 2)); setPatch(JSON.stringify(updated.status_patch, null, 2)); }
    setMessage(next.reused ? "已恢复上次提交回执，没有重复执行。" : request.decision.action === "modify" ? "草案修改已保存，尚未改变游戏状态；请重新预览并确认。" : "裁定已记录并保存。");
  });
  const simple = (action: DecisionDraft["action"]) => {
    if (data && item) void submit({ id: item.id, internal, decision: { request_id: uuid(), revision: data.revision, action, reason } });
  };
  const diffs = (changes: DecisionPreview["changes"]) => <div className="adjudication-diffs">{changes.map((entry, i) => <div key={i}>
    <strong>{domains[entry.domain] ?? entry.domain} · {status.fields.find(f => f.id === entry.field)?.label ?? entry.field}</strong>
    <span>{text(entry.before)} → {text(entry.after)}</span>
  </div>)}</div>;
  if (!open) return null;
  return <div className="drawer-mask" onClick={onClose}>
    <aside ref={pane} className="drawer adjudication-drawer" role="dialog" aria-modal="true" aria-labelledby="adjudication-title" onClick={e => e.stopPropagation()}>
      <header className="drawer-head"><div><small>PLAYER ADJUDICATION</small><h2 id="adjudication-title">玩家裁定中心</h2></div><button onClick={onClose}>关闭</button></header>
      <div className="drawer-body">
        <p className="muted">不确定事项由你决定。确认和修改前先检查差异，裁定不额外调用 AI，也不消耗回合。</p>
        <details className="adjudication-guide"><summary>裁定是什么？如何使用</summary>
          <p>这里用来回答后端 AI 提出的疑问，也可以确认新获得的物品是否入包。新物品先有临时 ID，只有你确认后才会正式登记。例如叙述中发生擦伤，但伤害程度不明确；在你裁定前，对应状态保持原值。</p>
          <ol><li>选择一条“待裁定”，查看本轮叙述依据和拟修改内容。</li><li>建议正确：点“预览确认”，检查前后数值，再“确认并提交”。</li><li>需要调整：填写玩家裁定依据，选择状态、衣物、饰品或颜色并添加草案；先“预览修改草案 → 保存修改草案”，再预览确认。</li></ol>
          <p>数字填写修改后的最终值；衣物、损坏程度、动作与表情从当前游戏目录选择；颜色可用色板或 R/G/B（0—255）调整。</p>
          <p>“否决”表示不执行；“搁置”留到以后，可在已搁置中恢复。“清空变更”只保留文字说明，不会改状态。历史记录可查看每次差异；有后续有效进度时需先撤销后续回合，才能撤销先前裁定。</p>
          <p>显示“需重新校对”时，核对当前状态并保存修改后再确认。“内部事项”包含幕后秘密，打开会剧透。裁定不会增加 AI 调用或消耗回合。</p>
        </details>
        <div className="adjudication-toolbar"><button disabled={disabled} onClick={() => void refresh()}>刷新</button><label><input type="checkbox" disabled={disabled} checked={internal} onChange={e => setInternal(e.target.checked)} />查看内部事项（含剧透）</label></div>
        <nav className="adjudication-tabs" aria-label="裁定分类">{[["pending", `待裁定 ${data?.pending_count ?? 0}`], ["deferred", `已搁置 ${data?.deferred_count ?? 0}`], ["all", "全部事项"], ["history", "历史记录"]].map(([id, title]) => <button key={id} aria-pressed={tab === id} onClick={() => { setTab(id); setPreview(null); }}>{title}</button>)}</nav>
        {message && <p className="adjudication-message" role="status">{message}</p>}
        {retry && <div className="adjudication-message"><p>上次提交尚未收到确认；可用同一编号重试，后端会防止重复执行。</p><button disabled={disabled} onClick={() => void submit(retry)}>重试上次提交</button></div>}
        {!data ? <p className="muted">正在读取当前游戏的裁定事项…</p> : tab === "history" ? <div className="adjudication-history">
          {data.history.length === 0 && <p className="muted">暂无裁定记录。</p>}
          {[...data.history].reverse().map(receipt => <article className="adjudication-card" key={receipt.seq}><strong>{actions[receipt.action]} · {receipt.title}</strong><small>{new Date(receipt.ts).toLocaleString()}{receipt.source_withdrawn ? " · 来源回合已撤销" : ""}</small><p>{receipt.reason || "未附加说明"}</p>{diffs(receipt.changes)}{receipt.changes.length === 0 && <p className="muted small">未改变游戏状态。</p>}</article>)}
        </div> : <>
          <div className="adjudication-list">{data.items.filter(row => tab === "all" || row.state === tab).map(row => <button key={row.id} className={`adjudication-card ${selected === row.id ? "selected" : ""}`} onClick={() => choose(row)}><span>{row.title}</span><small>{states[row.state]} · 第 {row.source_turn} 回合{row.visibility === "internal" ? " · 内部" : ""}{row.stale && row.state === "pending" ? " · 需重新校对" : ""}</small></button>)}
            {!data.items.some(row => tab === "all" || row.state === tab) && <p className="muted">这里没有待处理事项。</p>}</div>
          {item && <section className="adjudication-editor" key={item.id}><h3>{item.title}</h3><p className="adjudication-question">{item.question || "是否采用这项游戏变化？"}</p><p>{item.reason}</p>
            {item.operations.filter(op => op.name === "acquire_item").map((op, i) => <div className="adjudication-item-preview" key={i}><strong>{String((op.args as Record<string, unknown>).name)} × {String((op.args as Record<string, unknown>).count)}</strong><small>临时 ID：{String((op.args as Record<string, unknown>).item_id || "确认时生成")}</small><span>选择“是”后登记并加入背包；否决或搁置不会入包。</span></div>)}
            <details><summary>本轮叙述依据</summary><p className="adjudication-evidence">{item.evidence || "旧版记录未保存证据，需要先修改并填写裁定依据。"}</p></details>
            {item.stale && item.state === "pending" && <p className="adjudication-message">游戏进度已变化。请核对当前状态，填写依据后保存修改，再确认。</p>}
            <label>玩家裁定依据<textarea aria-label="玩家裁定依据" maxLength={500} value={reason} disabled={disabled} onChange={e => { setReason(e.target.value); setPreview(null); }} placeholder="例如：这次只是轻微擦伤，当前体力应为 19。" /></label>
            {item.state === "pending" && <>
              <details><summary>需要调整？修改状态草案</summary><AdjudicationFieldEditor packId={packId} operations={operations} disabled={disabled} onChange={value=>{setOperations(value);change();}} onMessage={setMessage}/><button disabled={disabled} onClick={()=>{setOperations("[]");setPatch("{}");change();}}>清空变更，仅确认说明</button></details>
              <details><summary>查看或编辑完整操作草案</summary><p className="muted small">物品、衣物、技能等沿用现有工具格式和目录；后端统一校验，新物品可通过 acquire_item 草案生成临时 ID，确认后登记；衣物与动作仍从真实目录选择。</p><label>操作数组<textarea className="adjudication-json" aria-label="操作草案" value={operations} disabled={disabled} onChange={e => { setOperations(e.target.value); change(); }} /></label><label>角色信息补丁<textarea className="adjudication-json" aria-label="角色信息补丁" value={patch} disabled={disabled} onChange={e => { setPatch(e.target.value); change(); }} /></label></details>
              <div className="drawer-actions"><button disabled={disabled || editing || item.stale} onClick={() => void inspect("confirm")}>是 · 预览变化</button><button disabled={disabled || !reason.trim()} onClick={() => void inspect("modify")}>{item.stale ? "按当前状态重新校对" : "预览修改草案"}</button><button disabled={disabled} onClick={() => simple("reject")}>否 · 不采用</button><button disabled={disabled} onClick={() => simple("defer")}>搁置</button></div>
            </>}
            {item.state === "deferred" && <div className="drawer-actions"><button disabled={disabled} onClick={() => simple("resume")}>恢复待裁定</button><button disabled={disabled} onClick={() => simple("reject")}>否 · 不采用</button></div>}
            {(item.state === "confirmed" || item.state === "rejected") && <><button disabled={disabled || !item.can_undo} onClick={() => simple("undo")}>撤销这次裁定</button>{!item.can_undo && <p className="muted small">后续已有进度，不能直接撤销。可以先撤销后续回合，或在调试台修正当前状态。</p>}</>}
            {preview && <section ref={previewPane} className="adjudication-preview"><h4>{preview.decision.action === "modify" ? "草案预览 · 保存后仍需确认" : "确认后将发生的变化"}</h4>{diffs(preview.changes)}{preview.no_state_change && <p>本次不改变游戏状态，仅记录裁定。</p>}<div className="drawer-actions"><button disabled={disabled} onClick={() => void submit({ id: item.id, internal, decision: preview.decision })}>{preview.decision.action === "modify" ? "保存修改草案" : "是 · 确认并提交"}</button><button disabled={disabled} onClick={() => setPreview(null)}>返回检查</button></div></section>}
          </section>}
        </>}
      </div>
    </aside>
  </div>;
}
