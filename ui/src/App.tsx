import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getSprite,
  getState,
  getVerify,
  getWorld,
  streamOpening,
  postReset,
  postUndo,
  streamAction,
} from "./api";
import { loadDebug, loadTheme, saveDebug, saveTheme, wallpaperCss } from "./theme";
import type { ThemeSettings } from "./theme";
import LibraryDialog from "./components/LibraryDialog";
import QuickCreateDialog from "./components/QuickCreateDialog";
import SaveDialog from "./components/SaveDialog";
import SettingsDrawer from "./components/SettingsDrawer";
import AdjudicationCenter from "./components/AdjudicationCenter";
import DebugConsole from "./components/DebugConsole";
import WelcomeDialog, { welcomeSeen } from "./components/WelcomeDialog";
import WorldDialog from "./components/WorldDialog";
import type {
  Action,
  EventRecord,
  NarrativeUpdate,
  ExtraAction,
  InputMode,
  InputSegment,
  Option,
  PickedSkill,
  SpriteSheet,
  Status,
  TurnResult,
  WorldView,
} from "./types";

import MobileChat from "./components/MobileChat";
import CorrectionPanel from "./components/CorrectionPanel";
import { useTextPlayback } from "./useTextPlayback";
import { streamCorrection, undoCorrection } from "./api";
import type { CorrectionMode, CorrectionRequest, CorrectionResult } from "./api";
import MobileGameDrawer from "./components/MobileGameDrawer";
import { useMobileLayout } from "./useMobileLayout";
import { actionMessage, buildChatHistory } from "./chatHistory";


/** 文字分段标记：选中一段文字再点按钮，同一句话里可以混着话语/动作/心理。 */
const TAG_MODES: { id: InputMode; icon: string; label: string; hint: string }[] = [
  {
    id: "speech",
    icon: "💬",
    label: "话语",
    hint: "选中部分 = 说出口的话",
  },
  {
    id: "action",
    icon: "🏃",
    label: "动作",
    hint: "选中部分 = 实际执行的行为",
  },
  {
    id: "thought",
    icon: "💭",
    label: "心理",
    hint: "选中部分 = 只在心里想",
  },
];

const EXTRA_ACTIONS: { id: ExtraAction; icon: string; label: string; hint: string }[] = [
  { id: "inspect", icon: "👁", label: "审视", hint: "细写身体、衣着与身边细节" },
  { id: "status", icon: "📊", label: "详情", hint: "完整回顾当前状态与处境" },
  { id: "task", icon: "📋", label: "任务", hint: "梳理主线目标与支线线索" },
];

interface TextTag {
  start: number;
  end: number;
  mode: InputMode;
}

/** 把标记区间还原成按顺序的分段；未标记的空隙按「未标注」处理。 */
function buildSegments(text: string, tags: TextTag[]): InputSegment[] {
  if (tags.length === 0) return [];
  const sorted = [...tags].sort((a, b) => a.start - b.start);
  const out: InputSegment[] = [];
  let cursor = 0;
  for (const tag of sorted) {
    if (tag.start > cursor) {
      out.push({ mode: "plain", text: text.slice(cursor, tag.start).trim() });
    }
    out.push({ mode: tag.mode, text: text.slice(tag.start, tag.end).trim() });
    cursor = Math.max(cursor, tag.end);
  }
  if (cursor < text.length) {
    out.push({ mode: "plain", text: text.slice(cursor).trim() });
  }
  return out.filter((segment) => segment.text.length > 0);
}

export default function App() {
  const mobileLayout = useMobileLayout();
  const [inputModes, setInputModes] = useState<InputMode[]>(["action"]);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);
  const [sendSerial, setSendSerial] = useState(0);
  const [status, setStatus] = useState<Status | null>(null);
  const [last, setLast] = useState<TurnResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replayEqual, setReplayEqual] = useState<boolean | null>(null);
  const [draft, setDraft] = useState("");
  const [tags, setTags] = useState<TextTag[]>([]);
  const [tagHint, setTagHint] = useState<string>("");
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [extras, setExtras] = useState<Record<ExtraAction, boolean>>({
    inspect: false,
    status: false,
    task: false,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [correctionResult, setCorrectionResult] = useState<CorrectionResult | null>(null);
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  const correctionRequest = useRef<CorrectionRequest | null>(null);
  const playbackSerial = useRef(0);
  const [playback, setPlayback] = useState<{key:string;turn:number;text:string;mode:"normal"|"correction";receipt?:number} | null>(null);
  const [adjudicationOpen, setAdjudicationOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(
    () => new URLSearchParams(window.location.search).get("debug") === "1",
  );
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [worldOpen, setWorldOpen] = useState(false);
  const [savesOpen, setSavesOpen] = useState(false);
  const [quickOpen, setQuickOpen] = useState(false);
  // 截图/自动化验收用：?skipDisclaimer=1 直接跳过首次提示（不影响普通打开）
  const [welcomeOpen, setWelcomeOpen] = useState<boolean>(() => {
    if (new URLSearchParams(window.location.search).has("skipDisclaimer")) return false;
    return !welcomeSeen();
  });
  const [world, setWorld] = useState<WorldView | null>(null);
  const [liveEvents, setLiveEvents] = useState<EventRecord[]>([]);
  const [liveNarrative, setLiveNarrative] = useState<NarrativeUpdate | null>(null);
  const [theme, setTheme] = useState<ThemeSettings>(() => loadTheme());
  const paced = useTextPlayback(playback?.text ?? "", playback?.key ?? "idle", theme.textSpeed);
  const captureNarrative = useCallback((update: NarrativeUpdate, key: string, mode: "normal" | "correction" = "normal") => {
    setLiveNarrative(update);
    setPlayback({key,turn:update.turn,text:update.text,mode});
  }, []);
  const [spriteReload,setSpriteReload] = useState(0);
  const [spriteError,setSpriteError] = useState<string|null>(null);
  const [sprite, setSprite] = useState<{ pack: string; sheet: SpriteSheet | null } | null>(
    null,
  );
  const [debug, setDebug] = useState<boolean>(() => loadDebug());
  /** Desktop docks the same character sidebar that phones show as a drawer. */
  const [navOpen, setNavOpen] = useState<boolean>(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [openingBusy, setOpeningBusy] = useState(false);
  const [openingError, setOpeningError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getState());
      const report = await getVerify();
      setReplayEqual(report.equal);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const generateOpening = useCallback(async () => {
    const key = `opening-${++playbackSerial.current}`;
    setPlayback(null);
    setOpeningBusy(true);
    setOpeningError(null);
    setLiveNarrative(null);
    try {
      const result = await streamOpening({ onNarrative: update => captureNarrative(update,key) });
      if (result.ok) setPlayback({key,turn:0,text:result.narrative || "",mode:"normal"});
      else setPlayback(null);
      if (!result.ok) {
        setOpeningError(result.error || "开局生成失败，点「重试」再来一次");
      }
      await refresh();
    } catch (err) {
      setOpeningError(String(err));
    } finally {
      setOpeningBusy(false);
      setLiveNarrative(null);
    }
  }, [refresh, captureNarrative]);

  // 创建、切换和恢复世界不自动调用开场模型。

  // 立绘配置随当前内容包变化（没有配置的包返回 null，不显示立绘）
  useEffect(() => {
    const activePack = status?.pack.id;
    if (!activePack) return;
    let alive = true;
    setSpriteError(null);
    void getSprite()
      .then((view) => {
        if (alive) setSprite(view);
      })
      .catch((err) => {
        if (alive) {setSprite(null);setSpriteError(String(err));}
      });
    return () => {
      alive = false;
    };
  }, [status?.pack.id,status?.appearance_revision,spriteReload]);

  useEffect(() => saveTheme(theme), [theme]);
  useEffect(() => {
    document.documentElement.dataset.uiTheme = theme.uiTheme;
  }, [theme.uiTheme]);
  useEffect(() => saveDebug(debug), [debug]);
  // 字号：只改写 CSS 变量，桌面与手机同一套；默认 100% 时与原样式完全一致
  useEffect(() => {
    const root = document.documentElement;
    const scale = String(theme.fontScale / 100);
    root.style.setProperty(
      "--ui-font-scale",
      theme.fontTarget === "all" ? scale : "1",
    );
    root.style.setProperty(
      "--narrative-font-scale",
      theme.fontTarget === "narrative" ? scale : "1",
    );
  }, [theme.fontTarget, theme.fontScale]);
  const act = useCallback(
    async (action: Action) => {
      const key = `action-${++playbackSerial.current}`;
      setPlayback(null);
      setBusy(true);
      setError(null);
      setLiveEvents([]);
      setLiveNarrative(null);
        setPendingAction(action);
      setSendSerial(value => value + 1);
      try {
        // SSE：回合内事件实时追加到小票，最终结果再统一刷新状态
        const result = await streamAction(action, {
          onNarrative: update => captureNarrative(update,key),
          onEvent: (event) =>
            setLiveEvents((prev) =>
              prev.some((item) => item.seq === event.seq) ? prev : [...prev, event],
            ),
        });
        setLast(result);
        setPlayback(result.ok ? {key,turn:result.turn,text:result.narrative,mode:"normal"} : null);
        if(result.ok && result.status) setStatus(result.status);
        if (!result.ok) {
          setError(result.errors.join("；") || "本回合失败");
        }
        if(!result.ok || !result.status) await refresh();
        return result.ok;
      } catch (err) {
        setError(String(err));
        setPlayback(null);
        await refresh();
        return false;
      } finally {
        setBusy(false);
        setLiveEvents([]);
        setLiveNarrative(null);
        setPendingAction(null);
      }
    },
    [refresh, captureNarrative],
  );

  useEffect(() => {
    const resume=()=>{if(!busy&&document.visibilityState==='visible')void refresh();};
    document.addEventListener('visibilitychange',resume);
    window.addEventListener('focus',resume);
    return()=>{document.removeEventListener('visibilitychange',resume);window.removeEventListener('focus',resume);};
  },[busy,refresh]);

  const selectedExtras = EXTRA_ACTIONS.filter((item) => extras[item.id]).map(
    (item) => item.id,
  );
  const pickedSkillList: PickedSkill[] = useMemo(
    () =>
      selectedSkills.map((id) => ({
        skill_id: id,
        name: status?.skills.find((skill) => skill.id === id)?.name,
      })),
    [selectedSkills, status],
  );
  const costPreview = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const id of selectedSkills) {
      const skill = status?.skills.find((item) => item.id === id);
      if (!skill) continue;
      for (const [field, amount] of Object.entries(skill.cost ?? {})) {
        totals[field] = (totals[field] ?? 0) + Number(amount);
      }
    }
    return totals;
  }, [selectedSkills, status]);
  const previewRows = useMemo(() => {
    if (!status) return [];
    return Object.entries(costPreview).map(([fieldId, amount]) => {
      const def = status.fields.find((field) => field.id === fieldId);
      const before = Number(status.state[fieldId] ?? 0);
      return {
        id: fieldId,
        label: def?.label ?? fieldId,
        amount,
        before,
        after: before - amount,
      };
    });
  }, [costPreview, status]);
  /** 开局叙述就绪后才允许行动（旧存档 turn>0 视为已就绪） */
  const ready = Boolean(status?.opening_generated) || (status?.turn ?? 0) > 0;


  const canSend =
    !busy &&
    ready &&
    (draft.trim().length > 0 ||
      selectedExtras.length > 0 ||
      selectedSkills.length > 0);

  const applyTag = useCallback((mode: InputMode) => {
    const element = inputRef.current;
    if (!element) return;
    const start = element.selectionStart ?? 0;
    const end = element.selectionEnd ?? 0;
    if (end <= start) {
      setTagHint("先在输入框里选中一段文字，再点标记");
      return;
    }
    setTagHint("");
    setTags((prev) => {
      const kept = prev.filter((tag) => tag.end <= start || tag.start >= end);
      return [...kept, { start, end, mode }].sort((a, b) => a.start - b.start);
    });
  }, []);

  const removeTag = useCallback((index: number) => {
    setTags((prev) => prev.filter((_, item) => item !== index));
  }, []);

  const send = useCallback(async () => {
    if (!ready) return;
    let text = draft.trim();
    if (!text && selectedSkills.length === 0 && selectedExtras.length === 0) return;
    if (busy) return;
    let segments = buildSegments(draft, tags);
    // 兼容旧习惯：「， 」开头=动作、「。 」开头=心理（没有手动标记时整段生效）
    if (segments.length === 0) {
      if (text.startsWith("， ")) {
        text = text.slice(2).trim();
        segments = [{ mode: "action", text }];
      } else if (text.startsWith("。 ")) {
        text = text.slice(2).trim();
        segments = [{ mode: "thought", text }];
      }
    }
    const picked = EXTRA_ACTIONS.filter((item) => extras[item.id]).map(
      (item) => item.id,
    );
    setDraft("");
    setTags([]);
    setTagHint("");
    setSelectedSkills([]);
    setExtras({ inspect: false, status: false, task: false });
    const ok = await act({
      kind: "text",
      text,
      mode: segments.length === 0 && inputModes.length === 1 ? inputModes[0] : undefined,
      modes: segments.length === 0 && inputModes.length > 0 ? inputModes : undefined,
      segments: segments.length > 0 ? segments : undefined,
      skills: pickedSkillList.length > 0 ? pickedSkillList : undefined,
      extras: picked,
    });
    if (!ok) {
      setDraft(text);
      setSelectedSkills([...selectedSkills]);
      setExtras({ ...extras });
      setTags(tags);
    }
  }, [act, busy, draft, extras, pickedSkillList, ready, selectedExtras.length, selectedSkills, tags, mobileLayout, inputModes]);

  const undo = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await postUndo();
      if (!result.ok) setError(String(result.error ?? "没有可撤销的回合"));
      setLast(null);
      setPlayback(null);
      setCorrectionResult(null);
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const reset = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await postReset();
      setOpeningError(null);
      setLast(null);
      setPlayback(null);
      setCorrectionResult(null);
      setDraft("");
      setTags([]);
      setTagHint("");
      setSelectedSkills([]);
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const openLibrary = useCallback(() => {
    setLibraryOpen(true);
    setWorldOpen(false);
  }, []);

  const reloadWorld = useCallback(async () => {
    try {
      setWorld(await getWorld());
    } catch (err) {
      setError(String(err));
    }
  }, []);

  const openWorld = useCallback(async () => {
    await reloadWorld();
    setLibraryOpen(false);
    setWorldOpen(true);
  }, [reloadWorld]);

  const onGameChanged = useCallback(async () => {
    setOpeningError(null);
    setLast(null);
    setPlayback(null);
    setCorrectionResult(null);
    setCorrectionOpen(false);
    setDraft("");
    await refresh();
    await reloadWorld();
  }, [refresh, reloadWorld]);

  const onSaveLoaded = useCallback(
    async (loaded: Status) => {
      setOpeningError(null);
      setStatus(loaded);
      setLast(null);
      setPlayback(null);
      setCorrectionResult(null);
      setDraft("");
      setError(null);
      try {
        const report = await getVerify();
        setReplayEqual(report.equal);
      } catch (err) {
        setError(String(err));
      }
    },
    [],
  );

  const pickSuggestion = useCallback((option: Option) => {
    setDraft(option.action_text);
    inputRef.current?.focus();
  }, []);


  const correct = async (mode: CorrectionMode, instruction: string, persist: boolean) => {
    if (!status || busy || openingBusy) return;
    setBusy(true); setCorrectionError(null); setCorrectionResult(null);
    const key = `correction-${++playbackSerial.current}`;
    if (mode === "narrative") { setPlayback(null); setLiveNarrative(null); }
    const old = correctionRequest.current;
    const request: CorrectionRequest = old && old.pack_id === status.pack.id && old.mode === mode && old.instruction === instruction && old.persist === persist ? old : {
      pack_id:status.pack.id, revision:status.correction_revision || "", request_id:globalThis.crypto?.randomUUID?.() ?? `correct-${Date.now()}-${Math.random()}`, mode, instruction, persist,
    };
    correctionRequest.current = request;
    try {
      const result = await streamCorrection(request, {onNarrative:update => captureNarrative(update,key,"correction")});
      setStatus(result.status); setLast(null); setCorrectionResult(result); correctionRequest.current = null;
      if (mode === "narrative") setPlayback({key,turn:result.status.turn,text:result.narrative,mode:"correction",receipt:result.receipt_id});
    } catch (err) {
      setCorrectionError(String(err));
      if (mode === "narrative") setPlayback(null);
      if (!(err instanceof TypeError) && !/流式响应没有返回最终结果|network|fetch/i.test(String(err))) correctionRequest.current = null;
      await refresh();
    } finally { setBusy(false); setLiveNarrative(null); }
  };
  const reverseCorrection = async () => {
    if (!status || !correctionResult || busy) return;
    setBusy(true); setCorrectionError(null);
    try { const result = await undoCorrection(status.pack.id,correctionResult.receipt_id); setStatus(result.status); setLast(null); setPlayback(null); setCorrectionResult(null); }
    catch (err) { setCorrectionError(String(err)); await refresh(); }
    finally { setBusy(false); }
  };
  const chatEntries = useMemo(() => {
    const seen = new Set(status?.events.map(event => event.seq) ?? []);
    const events = [...(status?.events ?? []), ...liveEvents.filter(event => !seen.has(event.seq))];
    const names = Object.fromEntries((status?.skills ?? []).map(skill => [skill.id, skill.name]));
    const entries = buildChatHistory(events, names);
    if (pendingAction && !liveEvents.some(event => event.kind === "turn.started")) {
      entries.push({ id: "pending-action", turn: (status?.turn ?? 0) + 1, role: "user", ...actionMessage(pendingAction, names) });
    }
    if (!entries.length && (status?.opening_generated || (status?.turn ?? 0) > 0)) {
      const text = last?.narrative || status?.scene?.text || status?.opening.text;
      if (text) entries.push({ id: "legacy-narrative", turn: status?.turn ?? 0, role: "assistant", text, meta: [] });
    }
    if (playback?.mode !== "correction" && liveNarrative?.text && !entries.some(entry => entry.role === "assistant" && entry.turn === liveNarrative.turn)) {
      entries.push({ id: `live-narrative-${liveNarrative.turn}`, turn: liveNarrative.turn, role: "assistant", text: liveNarrative.text,
        meta: [liveNarrative.phase === "settling" ? "正在结算…" : "正在生成…"], streaming: true });
    }
    if (playback?.mode === "correction" && !playback.receipt && playback.text) entries.push({id:"correction-live",turn:playback.turn,role:"assistant",text:playback.text,meta:["正在修订…"],streaming:true});
    return entries.map(entry => {
      const target = playback?.mode === "correction" ? entry.id === (playback.receipt ? `correction-ai-${playback.receipt}` : "correction-live") : entry.role === "assistant" && entry.turn === playback?.turn && !entry.id.startsWith("correction-ai-");
      return target && playback ? {...entry,text:paced.text,streaming:entry.streaming || paced.playing} : entry;
    });
  }, [status, liveEvents, pendingAction, last, liveNarrative, playback, paced.text, paced.playing]);

  if (!status) {
    return (
      <div className="loading">
        <p>正在连接框架…</p>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  const scene = status.scene;
  const sceneTitle = scene?.title || scene?.id || "";
  const options = last?.options?.length ? last.options : status.options;
  const narrator = status.llm?.roles?.narrator;
  const presetLabel = narrator?.preset_label || narrator?.provider || "未知";
  const modelName = narrator?.model || "端点默认";
  const modelLabel = !narrator
    ? "模型"
    : narrator.provider === "scripted"
      ? "脚本假模型"
      : `${presetLabel} · ${modelName}`;
  const wallpaper = wallpaperCss(theme);
  const correctionPanel = <CorrectionPanel open={correctionOpen} busy={busy || openingBusy} packId={status.pack.id} result={correctionResult} error={correctionError} onClose={() => setCorrectionOpen(false)} onSubmit={(mode,text,persist) => void correct(mode,text,persist)} onUndo={() => void reverseCorrection()}/>;
  const playbackControls = paced.playing && playback ? <div className="playback-toolbar"><button className="ghost small" type="button" onClick={paced.finish}>立即显示</button></div> : null;

  return (
    <div className={`app compact-cockpit${navOpen ? " cockpit-sidebar-open" : ""}${wallpaper ? " has-wallpaper" : ""}${correctionOpen ? " correcting" : ""}`}>
      {wallpaper && (
        <div
          className="wallpaper"
          style={{ backgroundImage: wallpaper, filter: `blur(${theme.blur}px)` }}
        />
      )}
      {wallpaper && (
        <div
          className="wallpaper-dim"
          style={{ background: `rgba(4, 7, 11, ${theme.dim})` }}
        />
      )}

      <>
        <MobileChat title={status.pack.title} scene={sceneTitle} turn={status.turn} modelLabel={modelLabel}
          scrollStyle={theme.narrativeScroll} inputRef={inputRef} onSettings={() => setSettingsOpen(true)} onCorrect={() => setCorrectionOpen(true)}
          advancedInput={<><div className="tag-tools"><span className="tag-tools-hint">选中文字，再标记其中的动作、话语或心理。</span>{TAG_MODES.map(item => <button key={item.id} type="button" disabled={busy} onMouseDown={e => e.preventDefault()} onClick={() => applyTag(item.id)}>{item.label}</button>)}</div>{tagHint && <p>{tagHint}</p>}{tags.length > 0 && <div className="tag-chips">{tags.map((tag,index) => <span className={`tag-chip tag-${tag.mode}`} key={`${tag.start}-${tag.end}`}><span>{TAG_MODES.find(item => item.id === tag.mode)?.label}：{draft.slice(tag.start,tag.end).trim().slice(0,24)}</span><button type="button" aria-label="取消分段标记" disabled={busy} onClick={() => removeTag(index)}>✕</button></span>)}</div>}</>}
          selectionSummary={previewRows.map(row => <span key={row.id} className={row.after < 0 ? "short" : ""}>{row.label} −{row.amount}（{row.before} → {row.after}）</span>)} adjudication={status.adjudication} fields={status.fields} onReviewChanged={refresh} correctionPanel={correctionPanel} correcting={correctionOpen} playbackControls={playbackControls} sendSerial={sendSerial} packId={status.pack.id} entries={chatEntries} draft={draft} modes={inputModes}
          busy={busy} ready={ready} openingBusy={openingBusy} openingError={openingError}
          error={error} canSend={canSend} options={options} pickedCount={selectedSkills.length}
          extrasCount={selectedExtras.length} menuOpen={navOpen} onOpenMenu={() => setNavOpen(value => !value)}
          onDraft={text => { setDraft(text); if (tags.length) { setTags([]); setTagHint("内容已修改，请重新标记分段。"); } }} onModes={setInputModes}
          onSend={() => void send()} onRetryOpening={() => void generateOpening()} onPickSuggestion={pickSuggestion} />
        <MobileGameDrawer docked={!mobileLayout} spriteError={spriteError} onRetrySprite={()=>setSpriteReload(v=>v+1)} open={navOpen} status={status} theme={theme} sheet={sprite?.sheet ?? null}
          busy={busy} picked={selectedSkills} preview={costPreview} extras={extras}
          onClose={() => setNavOpen(false)}
          onPickSkill={id => setSelectedSkills(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id])}
          onExtra={id => setExtras(prev => ({ ...prev, [id]: !prev[id] }))}
          onAdjudication={() => setAdjudicationOpen(true)} onSettings={() => setSettingsOpen(true)} onLibrary={openLibrary} onWorld={() => void openWorld()}
          onCreate={() => setQuickOpen(true)} onSaves={() => setSavesOpen(true)} onDebug={() => setDebugOpen(true)}
          onWelcome={() => setWelcomeOpen(true)} onUndo={() => void undo()} onReset={() => void reset()} />
      </>

      <LibraryDialog
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        onGameChanged={() => void onGameChanged()}
        onOpenWorld={() => void openWorld()}
        onOpenQuickCreate={() => {
          setLibraryOpen(false);
          setQuickOpen(true);
        }}
      />

      <QuickCreateDialog
        open={quickOpen}
        onClose={() => setQuickOpen(false)}
        onCreated={() => void onGameChanged()}
        modelLabel={modelLabel}
      />

      <WorldDialog
        open={worldOpen}
        onClose={() => setWorldOpen(false)}
        world={world}
        onReload={reloadWorld}
        onGameChanged={() => void onGameChanged()}
      />

      <SaveDialog
        open={savesOpen}
        busy={busy}
        turn={status.turn}
        onClose={() => setSavesOpen(false)}
        onLoaded={(loaded) => void onSaveLoaded(loaded)}
      />

      <WelcomeDialog
        open={welcomeOpen}
        onClose={() => setWelcomeOpen(false)}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <DebugConsole
        open={debugOpen}
        onClose={() => setDebugOpen(false)}
        sheet={sprite?.sheet}
        onChanged={async (next) => {
          if (next) setStatus(next);
          else await refresh();
        }}
        theme={theme}
        onThemeChange={setTheme}
        status={status}
      />

      <AdjudicationCenter open={adjudicationOpen} onClose={() => setAdjudicationOpen(false)} status={status} busy={busy || openingBusy} onChanged={refresh} />

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onChanged={refresh}
        status={status}
        last={last}
        theme={theme}
        onThemeChange={setTheme}
        debug={debug}
        onDebugChange={setDebug}
      />
    </div>
  );
}
