import { Fragment } from "react";
import { formatNarrativeDialogue } from "../narrativeFormatting";
import type { ChatEntry } from "../chatHistory";
import NpcSpeech from "./NpcSpeech";
export default function ChatMessage({ entry, packId, automatic }: { entry: ChatEntry; packId: string; automatic?: boolean }) {
  return <article className={`chat-message chat-message--${entry.role}${entry.failed ? " chat-message--failed" : ""}${entry.streaming ? " narrative-preview" : ""}`} data-role={entry.role}>
    {entry.role !== "notice" && <div className="chat-message-meta"><span>{entry.role === "user" ? "你" : entry.turn === 0 ? "开端" : `叙述 · 第 ${entry.turn} 回合`}</span>{entry.meta.map((item, i) => <span key={i}>{item}</span>)}{entry.failed && <span>未完成</span>}</div>}
    <p>{entry.role === "assistant" ? formatNarrativeDialogue(entry.text).split("\n").map((line, index, all) => <Fragment key={index}><span className={/^[\s]*[“「『"]/.test(line) ? "chat-dialogue-line" : undefined}>{line}</span>{index < all.length - 1 ? "\n" : ""}</Fragment>) : entry.text}</p>
    <NpcSpeech entry={entry} packId={packId} automatic={automatic}/>
  </article>;
}
