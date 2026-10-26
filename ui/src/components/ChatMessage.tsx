import { Fragment } from "react";
import { formatNarrativeDialogue } from "../narrativeFormatting";
import type { ChatEntry } from "../chatHistory";
import type { AdjudicationView, FieldDef } from "../types";
import NpcSpeech from "./NpcSpeech";
import InlineAnswers from "./InlineAnswers";
export default function ChatMessage({ entry, packId, automatic, adjudication, fields, busy, onChanged }: {
  entry: ChatEntry; packId: string; automatic?: boolean; adjudication?: AdjudicationView; fields?: FieldDef[];
  busy?: boolean; onChanged?: () => Promise<void>;
}) {
  return <article className={`chat-message chat-message--${entry.role}${entry.failed ? " chat-message--failed" : ""}${entry.streaming ? " narrative-preview" : ""}`} data-role={entry.role} data-turn={entry.turn}>
    {entry.role !== "notice" && <div className="chat-message-meta"><span>{entry.role === "user" ? "你" : entry.turn === 0 ? "开端" : `叙述 · 第 ${entry.turn} 回合`}</span>{entry.meta.map((item, i) => <span key={i}>{item}</span>)}{entry.failed && <span>未完成</span>}</div>}
    {!!entry.backendNotes?.length && <details className="backend-notes"><summary>本轮结算说明 · {entry.backendNotes.length} 项<span aria-hidden="true">⌄</span></summary><ul>{entry.backendNotes.map((note, i) => <li key={i}>{note}</li>)}</ul></details>}
    <p>{entry.role === "assistant" ? formatNarrativeDialogue(entry.text).split("\n").map((line, index, all) => <Fragment key={index}><span className={/^[\s]*[“「『"]/.test(line) ? "chat-dialogue-line" : undefined}>{line}</span>{index < all.length - 1 ? "\n" : ""}</Fragment>) : entry.text}</p>
    <NpcSpeech entry={entry} packId={packId} automatic={automatic}/>
    {entry.role === "assistant" && !entry.streaming && adjudication && onChanged && <InlineAnswers packId={packId} turn={entry.turn} view={adjudication} fields={fields} busy={busy} onChanged={onChanged}/>}
  </article>;
}
