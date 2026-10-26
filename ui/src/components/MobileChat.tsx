import { lastNarrativeIds } from "../narrativeReview";
import ChatMessage from "./ChatMessage";
import { CorrectionIcon } from "./CorrectionPanel";
import UiIcon from "./UiIcon";
import type { ReactNode, MutableRefObject } from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { UiStyleId } from "../theme";
import type { ChatEntry } from "../chatHistory";
import type { AdjudicationView, FieldDef, InputMode, Option } from "../types";
const MODES: { id: InputMode; label: string }[] = [{ id: "action", label: "动作" }, { id: "speech", label: "话语" }, { id: "thought", label: "心理" }];
interface Props {
  uiStyle: UiStyleId;
  scrollStyle: "auto" | "always" | "page";
  title: string;
  scene: string;
  turn: number;
  modelLabel: string;
  onSettings: () => void;
  onCorrect: () => void;
  advancedInput?: ReactNode;
  selectionSummary?: ReactNode;
  inputRef?: MutableRefObject<HTMLTextAreaElement | null>;
  adjudication?: AdjudicationView;
  fields?: FieldDef[];
  onReviewChanged: () => Promise<void>;
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
  const decisionOwners = lastNarrativeIds(props.entries);
  const log = useRef<HTMLDivElement>(null);
  const localInput = useRef<HTMLTextAreaElement>(null);
  const input = props.inputRef ?? localInput;
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
  useLayoutEffect(() => { if (stick.current && props.scrollStyle !== "always") latest();
    else if (log.current) setAtBottom(log.current.scrollHeight - log.current.scrollTop - log.current.clientHeight < 72);
  }, [tail, props.busy, props.ready, props.scrollStyle]);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(112, Math.max(46, element.scrollHeight))}px`;
  }, [props.draft, props.correcting]);
  useEffect(() => {
    const update = () => { if (stick.current) latest(); };
    window.addEventListener("rpg-viewport-resized", update);
    return () => window.removeEventListener("rpg-viewport-resized", update);
  }, []);
  const lastAssistant = props.entries.filter(entry => entry.role === "assistant").slice(-1)[0]?.id;
  return <main className="mobile-chat cockpit-chat" aria-label="游戏对话">
    <header className="cockpit-topbar">
      <button className="chat-menu-button" type="button" aria-label={props.menuOpen ? "关闭游戏侧栏" : "打开游戏侧栏"} aria-expanded={props.menuOpen} aria-controls="mobile-game-sidebar" onClick={props.onOpenMenu}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="4"/><path d="M9 4v16M5.5 8h1M5.5 11h1"/></svg>
      </button>
      <div className="cockpit-identity"><small>RPG COCKPIT</small><h1 title={props.title}>{props.title}</h1></div>
      <span className="cockpit-turn">回合 <b>{props.turn.toString().padStart(2, "0")}</b></span>
    </header>
    <div className="chat-reading-area">
      <div className="chat-transcript" ref={log} role="log" aria-label="对话历史" aria-live="polite" onScroll={() => {
        const element = log.current;
        if (!element) return;
        stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72;
        setAtBottom(stick.current);
      }}>
{props.uiStyle !== "cockpit" && <section className={`story-scene-intro ${props.uiStyle === "journal" ? "journal-chapter" : "cinema-scene"}`} aria-label="当前场景">
          <div className="story-scene-eyebrow"><span>{props.uiStyle === "journal" ? "THE STORY JOURNAL" : "A WORLD IN MOTION"}</span><span>第 {props.turn} 回合</span></div>
          <h2>{props.scene || props.title}</h2>
          <div className="story-scene-rule" aria-hidden="true"><UiIcon name="spark"/><span/></div>
        </section>}
        <div className="cockpit-thread-label"><span className="cockpit-dot"/><span>{props.scene || "新的旅程"}</span><button type="button" onClick={props.onSettings} title={`当前叙述模型：${props.modelLabel}；点击设置`}>{props.busy || props.openingBusy ? "正在回应" : "模型设置"}<UiIcon name="spark"/></button></div>
        {!props.ready && !props.entries.some(entry => entry.streaming) && <div className="chat-opening" role="status">
          <UiIcon name="spark"/><h2>{props.openingBusy ? "故事正在展开" : "一切，从你的选择开始"}</h2>
          <p>{props.openingBusy ? "正在生成开局…" : props.openingError || "世界已就绪，准备好后开始这段旅程。"}</p>
          {!props.openingBusy && <button className="primary generate-world" type="button" onClick={props.onRetryOpening}>{props.openingError ? "重试生成世界" : "生成世界"}<span aria-hidden="true"> →</span></button>}
        </div>}
        {props.entries.map(entry => <ChatMessage key={entry.id} entry={entry} packId={props.packId} adjudication={decisionOwners.get(entry.turn) === entry.id ? props.adjudication : undefined} fields={props.fields} busy={props.busy || props.openingBusy} onChanged={props.onReviewChanged} automatic={entry.id === lastAssistant}/>)}
        {props.busy && !props.correcting && !props.entries.some(entry => entry.streaming) && <div className="chat-generating" role="status"><span className="cockpit-dot"/> 正在叙述与结算…</div>}
      </div>
      {!atBottom && <button type="button" className="chat-to-latest" onClick={latest}>回到最新 ↓</button>}
      {props.playbackControls}
    </div>
    {props.correcting ? props.correctionPanel : <section className="chat-composer" aria-label="输入行动">
      {props.error && <p className="chat-error" role="alert">{props.error}</p>}
      {props.ready ? <>
        {props.options.length > 0 && <div className="chat-suggestions" role="group" aria-label="AI 建议回答">
          {props.options.map(option => <button type="button" key={option.id} disabled={props.busy} onClick={() => { props.onPickSuggestion(option); input.current?.focus(); }} title="填入输入框，确认后发送">{option.label}<span aria-hidden="true"> ↗</span></button>)}
        </div>}
        <div className="chat-input-modes" role="group" aria-label="输入类型">
          {MODES.map(mode => <label key={mode.id}><input type="checkbox" checked={props.modes.includes(mode.id)} disabled={props.busy} onChange={event => props.onModes(event.target.checked ? [...props.modes, mode.id] : props.modes.filter(id => id !== mode.id))}/><span>{mode.label}</span></label>)}
          <button type="button" className="chat-correct-button" aria-label="打开 AI 纠正框" title="纠正叙述或数值" disabled={props.busy || props.openingBusy} onClick={props.onCorrect}><CorrectionIcon/></button>
        </div>
        {(props.pickedCount > 0 || props.extrasCount > 0) && <div className="cockpit-selection"><button className="chat-picked" type="button" onClick={props.onOpenMenu}>{props.pickedCount > 0 && `技能 ${props.pickedCount}`}{props.pickedCount > 0 && props.extrasCount > 0 && " · "}{props.extrasCount > 0 && `附加 ${props.extrasCount}`}<span aria-hidden="true"> ↗</span></button>{props.selectionSummary}</div>}
        <div className="chat-input-row">
          <textarea ref={input} aria-label="本回合输入" rows={1} value={props.draft} disabled={props.busy} placeholder={props.uiStyle === "journal" ? "故事接下来，由你书写…" : props.uiStyle === "cinema" ? "回应这段故事…" : "写下你的行动、话语或想法…"} onChange={event => props.onDraft(event.target.value)} onKeyDown={event => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); props.onSend(); }
          }}/>
          <button className="primary chat-send" type="button" aria-label={props.busy ? "等待回应" : "发送"} title="发送 · Ctrl / ⌘ + Enter" disabled={!props.canSend} onClick={props.onSend}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button>
        </div>
        {props.advancedInput && <details className="cockpit-advanced"><summary>分段标记<span>Ctrl / ⌘ + Enter 发送</span></summary>{props.advancedInput}</details>}
      </> : <p className="cockpit-composer-idle">你的世界，你来书写。</p>}
    </section>}
  </main>;
}
