import ChatMessage from "./ChatMessage";
import type { ReactNode } from "react";
import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { formatNarrativeDialogue } from "../narrativeFormatting";
import type { ChatEntry } from "../chatHistory";
import type { InputMode, Option } from "../types";
const MODES: { id: InputMode; label: string }[] = [{ id: "action", label: "动作" }, { id: "speech", label: "话语" }, { id: "thought", label: "心理" }];
interface Props {
  correctionPanel?: ReactNode;
  correcting?: boolean;
  playbackControls?: ReactNode;
  packId: string;
  sendSerial: number;
  entries: ChatEntry[];
  draft: string;
  modes: InputMode[];
  busy: boolean;
  ready: boolean;
  openingBusy: boolean;
  openingError: string | null;
  error: string | null;
  canSend: boolean;
  options: Option[];
  pickedCount: number;
  extrasCount: number;
  menuOpen: boolean;
  onOpenMenu: () => void;
  onDraft: (text: string) => void;
  onModes: (modes: InputMode[]) => void;
  onSend: () => void;
  onRetryOpening: () => void;
  onPickSuggestion: (option: Option) => void;
}
export default function MobileChat(props: Props) {
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const last = props.entries[props.entries.length - 1];
  const tail = last ? `${last.id}:${last.text.length}` : "";
  const latest = () => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
    stick.current = true; setAtBottom(true);
  };
  useLayoutEffect(() => { stick.current = true; latest(); }, [props.packId]);
  useLayoutEffect(() => { latest(); }, [props.sendSerial]);
  useLayoutEffect(() => {
    if (stick.current) latest();
  }, [tail, props.busy, props.ready]);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(112, Math.max(46, element.scrollHeight))}px`;
  }, [props.draft]);
  // Resizing the keyboard keeps the latest reply visible only when already following it.
  useEffect(() => {
    const update = () => { if (stick.current) latest(); };
    window.addEventListener("rpg-viewport-resized", update);
    return () => window.removeEventListener("rpg-viewport-resized", update);
  }, []);
  return (
    <main className="mobile-chat" aria-label="游戏对话">
      <button className="chat-menu-button" type="button" aria-label="打开游戏侧栏" aria-expanded={props.menuOpen} aria-controls="mobile-game-sidebar" onClick={props.onOpenMenu}>☰</button>
      <div className="chat-transcript" ref={log} role="log" aria-label="对话历史" aria-live="polite" onScroll={() => {
        const element = log.current;
        if (!element) return;
        stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72;
        setAtBottom(stick.current);
      }}>
        {!props.ready && !props.entries.some(entry => entry.streaming) && <div className="chat-opening" role="status">
          <p>{props.openingBusy ? "正在生成开局…" : props.openingError || "世界已创建，点击按钮生成开场"}</p>
          {!props.openingBusy && <button className="primary generate-world" type="button" onClick={props.onRetryOpening}>{props.openingError ? "重试生成世界" : "生成世界"}</button>}
        </div>}
        {props.entries.map(entry => <ChatMessage key={entry.id} entry={entry} packId={props.packId} automatic={entry.id === props.entries.filter(e => e.role === 'assistant').slice(-1)[0]?.id}/>)}
        {props.busy && !props.correcting && !props.entries.some(entry => entry.streaming) && <div className="chat-generating" role="status">正在叙述与结算…</div>}
      </div>
      {!atBottom && <button type="button" className="chat-to-latest" onClick={latest}>回到最新 ↓</button>}
      {props.playbackControls}
      {props.correcting ? props.correctionPanel : <section className="chat-composer" aria-label="输入行动">
        {props.error && <p className="chat-error" role="alert">{props.error}</p>}
        {props.ready && <>
          {props.options.length > 0 && <div className="chat-suggestions" role="group" aria-label="AI 建议回答">
            {props.options.map(option => <button type="button" key={option.id} disabled={props.busy} onClick={() => { props.onPickSuggestion(option); input.current?.focus(); }} title="填入输入框，确认后发送">{option.label}</button>)}
          </div>}
          <div className="chat-input-modes" role="group" aria-label="输入类型">
            {MODES.map(mode => <label key={mode.id}><input type="checkbox" checked={props.modes.includes(mode.id)} disabled={props.busy} onChange={event => props.onModes(event.target.checked ? [...props.modes, mode.id] : props.modes.filter(id => id !== mode.id))} /><span>{mode.label}</span></label>)}
            {(props.pickedCount > 0 || props.extrasCount > 0) && <button className="chat-picked" type="button" onClick={props.onOpenMenu}>{props.pickedCount > 0 && `技能 ${props.pickedCount}`}{props.pickedCount > 0 && props.extrasCount > 0 && " · "}{props.extrasCount > 0 && `附加 ${props.extrasCount}`}</button>}
          </div>
          <div className="chat-input-row">
            <textarea ref={input} aria-label="本回合输入" rows={1} value={props.draft} disabled={props.busy} placeholder="写下这一回合…" onChange={event => props.onDraft(event.target.value)} onKeyDown={event => {
              // Enter keeps a newline on phone keyboards; Ctrl/Cmd+Enter submits.
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); props.onSend(); }
            }} />
            <button className="primary chat-send" type="button" disabled={!props.canSend} onClick={props.onSend}>{props.busy ? "等待" : "发送"}</button>
          </div>
        </>}
      </section>}
    </main>
  );
}
