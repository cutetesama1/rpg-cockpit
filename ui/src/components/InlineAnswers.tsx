import { useEffect, useRef, useState } from "react";
import { answerAdjudication } from "../api";
import type { AdjudicationView, FieldDef } from "../types";
import { questionEffect, turnQuestions } from "../narrativeReview";

type Request = { pack_id: string; revision: string; request_id: string; accepted: boolean };
export default function InlineAnswers({ packId, turn, view, fields, busy, onChanged }: {
  packId: string; turn: number; view: AdjudicationView; fields?: FieldDef[]; busy?: boolean; onChanged: () => Promise<void>;
}) {
  const [local, setLocal] = useState<AdjudicationView | null>(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const requests = useRef(new Map<string, Request>());
  const scope = useRef(0);
  const locked = useRef(false);
  useEffect(() => { ++scope.current; requests.current.clear(); setLocal(null); setMessage(""); }, [packId]);
  useEffect(() => { setLocal(null); }, [view.revision]);
  const data = local ?? view;
  const questions = turnQuestions(data.items, turn);
  if (!questions.length) return null;
  const count = questions.filter(item => item.state === "pending").length;
  const answer = async (id: string, accepted: boolean) => {
    if (locked.current || busy) return;
    locked.current = true; setWorking(true); setMessage("");
    const current = scope.current;
    const previous = requests.current.get(id);
    const request = previous?.accepted === accepted ? previous : { pack_id: packId, revision: data.revision, accepted,
      request_id: globalThis.crypto?.randomUUID?.() ?? `answer-${Date.now()}-${Math.random().toString(16).slice(2)}` };
    requests.current.set(id, request);
    try {
      const next = await answerAdjudication(id, request);
      if (current !== scope.current || next.pack_id !== packId) return;
      setLocal(next); requests.current.delete(id);
      try { await onChanged(); }
      catch { if (current === scope.current) setMessage("选择已保存，页面状态同步未完成；刷新游戏即可恢复。"); }
    } catch (error) {
      if (current === scope.current) setMessage(String(error));
    } finally { locked.current = false; setWorking(false); }
  };
  return <details className="inline-answers">
    <summary>{count ? `本轮裁定 · ${count} 个问题待回答` : "本轮裁定 · 已处理"}<span aria-hidden="true">⌄</span></summary>
    <div className="inline-answer-list">{questions.map(item => <section key={item.id} className="inline-answer" aria-label={item.question || item.title}>
      <p>{item.question || `${item.title}，是否确认？`}</p>
      <small>{questionEffect(item, fields)}</small>
      {item.state === "pending" ? <div className="inline-answer-buttons">
        <button type="button" disabled={busy || working || item.stale} onClick={() => void answer(item.id, true)}>是</button>
        <button type="button" disabled={busy || working} onClick={() => void answer(item.id, false)}>否</button>
      </div> : <span className="inline-answer-result">{item.state === "confirmed" ? "已选择：是" : "已选择：否"}</span>}
      {item.state === "pending" && item.stale && <small>当前状态已变化，需要在裁定中心重新核对后才能采用。</small>}
    </section>)}</div>
    {message && <p className="inline-answer-message" role="status">{message}</p>}
  </details>;
}
