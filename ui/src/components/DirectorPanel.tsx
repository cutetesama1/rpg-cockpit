import { useEffect, useState } from "react";
import { getDirector, saveDirector, requestDirector, putDirectorClue, rollDice } from "../api";
import type { CheckResult, DirectorConfig, DirectorView, PlotClue, Status } from "../types";

const uuid = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const reasonLabels: Record<string, string> = { npc_entrance_review: "人物出场复查", manual: "手动请求", scene_change: "场景变化", milestone: "重要事件", clue_change: "线索变化" };

export default function DirectorPanel({ status, onChanged, independentDirector = false }: { status: Status | null; onChanged: () => Promise<void> | void; independentDirector?: boolean }) {
  const packId = status?.pack.id ?? "";
  const [data, setData] = useState<DirectorView | null>(status?.director ?? null);
  const [draft, setDraft] = useState<DirectorConfig | null>(status?.director?.config ?? null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [auditOpen, setAuditOpen] = useState(false);
  const [expression, setExpression] = useState("1d20");
  const [probability, setProbability] = useState(false);
  const [chance, setChance] = useState("50");
  const [target, setTarget] = useState("");
  const [rollId, setRollId] = useState<string | null>(null);
  const [lastRoll, setLastRoll] = useState<CheckResult | null>(null);
  const [clueId, setClueId] = useState<string | null>(null);
  const [clueTitle, setClueTitle] = useState("");
  const [clueSummary, setClueSummary] = useState("");
  const [clueInternal, setClueInternal] = useState(false);

  useEffect(() => {
    let active = true;
    if (packId) getDirector().then(next => {
      if (active && next.pack_id === packId) { setData(next); setDraft(next.config); }
    }).catch(err => { if (active) setMessage(String(err)); });
    return () => { active = false; };
  }, [packId]);

  const run = async (task: () => Promise<void>) => {
    setBusy(true); setMessage("");
    try { await task(); } catch (err) { setMessage(String(err)); }
    finally { setBusy(false); }
  };
  const apply = (next: DirectorView) => { setData(next); setAuditOpen(false); };
  const patch = (changes: Partial<DirectorConfig>) => setDraft(old => old ? { ...old, ...changes } : old);
  const save = () => run(async () => {
    if (!draft) return;
    const next = await saveDirector(packId, draft); apply(next); setDraft(next.config);
    setMessage("已保存到当前游戏；不启用时不会增加导演模型调用。"); await onChanged();
  });
  const ask = () => run(async () => {
    apply(await requestDirector(packId)); setMessage("已排队：下次提交玩家行动时调用一次导演。"); await onChanged();
  });
  const roll = () => run(async () => {
    const id = rollId ?? uuid(); setRollId(id);
    const check = probability ? { kind: "probability" as const, chance: Number(chance) / 100 }
      : { kind: "dice" as const, dice: expression, ...(target.trim() ? { target: Number(target) } : {}) };
    const response = await rollDice(packId, id, check);
    setLastRoll(response.result); setRollId(null);
    setMessage(response.reused ? "已恢复上次检定结果，没有重新掷骰。" : "检定已记录，不消耗模型调用，也不会直接修改角色数值。");
    await onChanged();
  });
  const addClue = () => run(async () => {
    const id = clueId ?? `clue_${uuid().replace(/[^a-z0-9]/gi, "").slice(0, 40).toLowerCase()}`;
    setClueId(id);
    const clue: PlotClue = { id, title: clueTitle.trim(), summary: clueSummary.trim(), status: "open", visibility: clueInternal ? "internal" : "public" };
    apply(await putDirectorClue(packId, clue)); setClueId(null); setClueTitle(""); setClueSummary("");
    setMessage("线索已保存。导演只读取未解决线索，不会自行改写线索状态。"); await onChanged();
  });
  const setClueStatus = (clue: PlotClue, value: PlotClue["status"]) => run(async () => {
    apply(await putDirectorClue(packId, { ...clue, status: value })); await onChanged();
  });

  if (!packId || !draft || !data) return <section className="settings-section"><h3>剧情导演与骰子</h3><p className="muted">{message || "正在读取当前游戏的导演设置…"}</p></section>;
  return <section className="settings-section director-settings">
    <h3>剧情导演与骰子</h3>
    <p className="muted small">当前游戏：{status?.pack.title}。候选剧情先经后端检定，只有已触发且结果确定的公开事件才交给叙事模型。</p>
    <label className="checkbox-row"><input type="checkbox" checked={draft.enabled} onChange={e => patch({ enabled: e.target.checked })} /><span>启用可选剧情导演</span></label>
    {independentDirector ? <p className="muted small">使用上方“剧情导演 AI”的独立 URL、API Key 与模型；不会被旧版复用选项覆盖。</p> : <label className="checkbox-row"><input type="checkbox" checked={draft.use_narrator_model} onChange={e => patch({ use_narrator_model: e.target.checked })} /><span>复用叙事模型连接（关闭后使用模型设置中的剧情导演）</span></label>}
    <div className="field-row">
      <label><span>最少间隔回合</span><input type="number" min="1" max="100" value={draft.min_turn_gap} onChange={e => patch({ min_turn_gap: Number(e.target.value) })} /></label>
      <label><span>每次最多候选事件</span><input type="number" min="1" max="5" value={draft.max_candidates} onChange={e => patch({ max_candidates: Number(e.target.value) })} /></label>
    </div>
    <div className="field-row">
      <label className="checkbox-row"><input type="checkbox" checked={draft.on_scene_change} onChange={e => patch({ on_scene_change: e.target.checked })} /><span>场景变化</span></label>
      <label className="checkbox-row"><input type="checkbox" checked={draft.on_milestone} onChange={e => patch({ on_milestone: e.target.checked })} /><span>重要事件</span></label>
      <label className="checkbox-row"><input type="checkbox" checked={draft.on_clue_change} onChange={e => patch({ on_clue_change: e.target.checked })} /><span>线索更新</span></label>
    </div>
    <div className="drawer-actions"><button type="button" disabled={busy} onClick={() => void save()}>保存导演选项</button><button type="button" disabled={busy || !data.config.enabled || data.pending_manual} onClick={() => void ask()}>{data.pending_manual ? "已排队等待下次行动" : "下回合请求一次导演"}</button></div>
    {data.last_run && <p className="muted small">最近调用：第 {data.last_run.turn} 回合 · {reasonLabels[data.last_run.reason] ?? data.last_run.reason}{data.last_run.failed ? " · 未生成有效候选，已继续普通叙事" : ""}</p>}
    <details><summary>骰子工具 · 不调用 AI</summary>
      <label className="checkbox-row"><input type="checkbox" checked={probability} onChange={e => { setProbability(e.target.checked); setRollId(null); }} /><span>使用概率检定</span></label>
      {probability ? <label><span>成功概率（%）</span><input type="number" min="0" max="100" step="0.1" value={chance} onChange={e => { setChance(e.target.value); setRollId(null); }} /></label>
        : <div className="field-row"><label><span>骰式</span><input value={expression} onChange={e => { setExpression(e.target.value); setRollId(null); }} placeholder="2d6+3 / 2d20kh1 / d% / 4dF" /></label><label><span>成功阈值（可留空）</span><input type="number" value={target} onChange={e => { setTarget(e.target.value); setRollId(null); }} /></label></div>}
      <button type="button" disabled={busy} onClick={() => void roll()}>{rollId ? "重试本次检定" : "执行检定"}</button>
      {lastRoll && <p role="status">{lastRoll.kind === "probability" ? "概率检定" : lastRoll.dice}：{lastRoll.total ?? (lastRoll.passed ? "成功" : "失败")}{lastRoll.total != null && lastRoll.passed != null ? ` · ${lastRoll.passed ? "成功" : "失败"}` : ""}{lastRoll.rolls ? `（各骰：${lastRoll.rolls.join("、")}）` : ""}</p>}
    </details>
    <details><summary>供导演参考的线索</summary>
      <p className="muted small">这里只维护线索摘要，不作为生命、资源、技能或库存的替代品。自动动态世界书留到后续阶段。</p>
      {data.clues.map(clue => <div key={clue.id} className="settings-section"><strong>{clue.title}</strong><p className="small">{clue.summary}</p><label><span>{clue.visibility === "internal" ? "内部秘密" : "公开线索"}</span><select disabled={busy} value={clue.status} onChange={e => void setClueStatus(clue, e.target.value as PlotClue["status"])}><option value="open">未解决</option><option value="resolved">已解决</option><option value="paused">搁置</option></select></label></div>)}
      <label><span>新线索标题</span><input maxLength={100} value={clueTitle} onChange={e => { setClueTitle(e.target.value); setClueId(null); }} /></label>
      <label><span>线索摘要</span><textarea maxLength={1200} rows={3} value={clueSummary} onChange={e => { setClueSummary(e.target.value); setClueId(null); }} /></label>
      <label className="checkbox-row"><input type="checkbox" checked={clueInternal} onChange={e => setClueInternal(e.target.checked)} /><span>内部秘密（默认不显示在公开记录）</span></label>
      <button type="button" disabled={busy || !clueTitle.trim() || !clueSummary.trim()} onClick={() => void addClue()}>保存线索</button>
    </details>
    <details><summary>导演记录</summary>
      {data.events.length ? data.events.map(event => <p className="small" key={event.id}><strong>{event.title}</strong>：{event.outcome}</p>) : <p className="muted small">暂无已确定的公开事件。</p>}
      <button type="button" disabled={busy} onClick={() => void run(async () => { const next = await getDirector(!auditOpen); setData(next); setAuditOpen(!auditOpen); })}>{auditOpen ? "隐藏内部记录" : "查看内部记录（含未触发候选与幕后秘密）"}</button>
      {auditOpen && <pre className="small" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto" }}>{JSON.stringify(data.audit ?? [], null, 2)}</pre>}
    </details>
    {message && <p className="muted small" role="status">{message}</p>}
  </section>;
}
