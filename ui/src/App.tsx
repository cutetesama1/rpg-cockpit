import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
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
import OptionsList from "./components/OptionsList";
import QuickCreateDialog from "./components/QuickCreateDialog";
import ReceiptLog from "./components/ReceiptLog";
import SaveDialog from "./components/SaveDialog";
import SettingsDrawer from "./components/SettingsDrawer";
import AdjudicationCenter from "./components/AdjudicationCenter";
import DebugConsole from "./components/DebugConsole";
import UiIcon from "./components/UiIcon";
import Sidebar from "./components/Sidebar";
import SpriteCanvas from "./components/SpriteCanvas";
import SkillCards from "./components/SkillCards";
import StatusBars from "./components/StatusBars";
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
import ChatMessage from "./components/ChatMessage";
import { lastNarrativeIds } from "./narrativeReview";
import InventoryPanel from "./components/InventoryPanel";
import CorrectionPanel, { CorrectionIcon } from "./components/CorrectionPanel";
import { useTextPlayback } from "./useTextPlayback";
import { streamCorrection, undoCorrection } from "./api";
import type { CorrectionMode, CorrectionRequest, CorrectionResult } from "./api";
import MobileGameDrawer from "./components/MobileGameDrawer";
import { useMobileLayout, MOBILE_LAYOUT_QUERY } from "./useMobileLayout";
import { actionMessage, buildChatHistory } from "./chatHistory";
import { formatNarrativeDialogue } from "./narrativeFormatting";

const NAV_COLLAPSED_KEY = "rpg-nav-collapsed";

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

function loadNavCollapsed(): boolean {
  try {
    const raw = localStorage.getItem(NAV_COLLAPSED_KEY);
    if (raw !== null) return raw === "1";
    return window.innerWidth < 1024;
  } catch {
    return false;
  }
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
  const [navCollapsed, setNavCollapsed] = useState<boolean>(() => loadNavCollapsed());
  /** 手机端左侧导航抽屉；桌面端这个按钮被 CSS 隐藏，所以始终为 false。 */
  const [navOpen, setNavOpen] = useState<boolean>(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const storyRef = useRef<HTMLDivElement | null>(null);
  const storyFollow = useRef(true);
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
    storyFollow.current = true;
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
  useEffect(() => {
    try {
      localStorage.setItem(NAV_COLLAPSED_KEY, navCollapsed ? "1" : "0");
    } catch {
      /* 忽略隐私模式下的存储失败 */
    }
  }, [navCollapsed]);

  // 手机端抽屉打开时锁住背景滚动；Esc 也能关掉，点导航项由 closeNavOnItem 负责
  useEffect(() => {
    if (!navOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    // 转屏/改成桌面宽度时抽屉按钮会被隐藏，必须顺手关掉，否则滚动锁会卡住页面
    const wideScreen = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const onWideScreen = () => {
      if (!wideScreen.matches) setNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    wideScreen.addEventListener("change", onWideScreen);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
      wideScreen.removeEventListener("change", onWideScreen);
    };
  }, [navOpen]);

  /** 手机抽屉里点任意导航按钮后自动收起；桌面端 navOpen 恒为 false，不产生影响。 */
  const closeNavOnItem = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (!navOpen) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest(".sidebar button")) setNavOpen(false);
    },
    [navOpen],
  );

  const act = useCallback(
    async (action: Action) => {
      const key = `action-${++playbackSerial.current}`;
      setPlayback(null);
      setBusy(true);
      setError(null);
      setLiveEvents([]);
      setLiveNarrative(null);
      storyFollow.current = true;
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
    let segments = mobileLayout ? [] : buildSegments(draft, tags);
    // 兼容旧习惯：「， 」开头=动作、「。 」开头=心理（没有手动标记时整段生效）
    if (!mobileLayout && segments.length === 0) {
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
      mode: mobileLayout && inputModes.length === 1 ? inputModes[0] : undefined,
      modes: mobileLayout && inputModes.length > 0 ? inputModes : undefined,
      segments: segments.length > 0 ? segments : undefined,
      skills: pickedSkillList.length > 0 ? pickedSkillList : undefined,
      extras: picked,
    });
    if (!ok) {
      setDraft(text);
      setSelectedSkills([...selectedSkills]);
      setExtras({ ...extras });
      if (!mobileLayout) setTags(tags);
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

  useEffect(() => {
    if (theme.narrativeScroll === "page") return;
    const element = storyRef.current;
    if (element && storyFollow.current) element.scrollTop = element.scrollHeight;
  }, [chatEntries, theme.narrativeScroll, openingBusy]);

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
  const effortLabel: Record<string, string> = {
    low: "低",
    medium: "中",
    high: "高",
  };
  const presetLabel = narrator?.preset_label || narrator?.provider || "未知";
  const modelName = narrator?.model || "端点默认";
  const effortName = narrator?.reasoning_effort
    ? effortLabel[narrator.reasoning_effort] || narrator.reasoning_effort
    : "自动";
  const modelLabel = !narrator
    ? "模型"
    : narrator.provider === "scripted"
      ? "脚本假模型"
      : `${presetLabel} · ${modelName}`;
  // 流式事件可能比 status.events 新（refresh 尚未回来），按 seq 合并去重
  const knownSeqs = new Set(status.events.map((event) => event.seq));
  const receiptEvents = status.events.concat(
    liveEvents.filter((event) => !knownSeqs.has(event.seq)),
  );
  const usage = status.usage ?? {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    cost_usd: 0,
    calls: 0,
    latency_ms: 0,
  };

  const decisionOwners = lastNarrativeIds(chatEntries);
  const wallpaper = wallpaperCss(theme);
  const correctionPanel = <CorrectionPanel open={correctionOpen} busy={busy || openingBusy} packId={status.pack.id} result={correctionResult} error={correctionError} onClose={() => setCorrectionOpen(false)} onSubmit={(mode,text,persist) => void correct(mode,text,persist)} onUndo={() => void reverseCorrection()}/>;
  const playbackControls = paced.playing && playback ? <div className="playback-toolbar"><button className="ghost small" type="button" onClick={paced.finish}>立即显示</button></div> : null;

  return (
    <div className={`app${wallpaper ? " has-wallpaper" : ""}${correctionOpen ? " correcting" : ""}`}>
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

      {mobileLayout ? <>
        <MobileChat adjudication={status.adjudication} fields={status.fields} onReviewChanged={refresh} correctionPanel={correctionPanel} correcting={correctionOpen} playbackControls={playbackControls} sendSerial={sendSerial} packId={status.pack.id} entries={chatEntries} draft={draft} modes={inputModes}
          busy={busy} ready={ready} openingBusy={openingBusy} openingError={openingError}
          error={error} canSend={canSend} options={options} pickedCount={selectedSkills.length}
          extrasCount={selectedExtras.length} menuOpen={navOpen} onOpenMenu={() => setNavOpen(true)}
          onDraft={text => { setDraft(text); setTags([]); }} onModes={setInputModes}
          onSend={() => void send()} onRetryOpening={() => void generateOpening()} onPickSuggestion={pickSuggestion} />
        <MobileGameDrawer spriteError={spriteError} onRetrySprite={()=>setSpriteReload(v=>v+1)} open={navOpen} status={status} theme={theme} sheet={sprite?.sheet ?? null}
          busy={busy} picked={selectedSkills} preview={costPreview} extras={extras}
          onClose={() => setNavOpen(false)}
          onPickSkill={id => setSelectedSkills(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id])}
          onExtra={id => setExtras(prev => ({ ...prev, [id]: !prev[id] }))}
          onAdjudication={() => setAdjudicationOpen(true)} onSettings={() => setSettingsOpen(true)} onLibrary={openLibrary} onWorld={() => void openWorld()}
          onCreate={() => setQuickOpen(true)} onSaves={() => setSavesOpen(true)} onDebug={() => setDebugOpen(true)}
          onWelcome={() => setWelcomeOpen(true)} onUndo={() => void undo()} onReset={() => void reset()} />
      </> : (
      <div className={`app-shell${navOpen ? " nav-open" : ""}`} onClickCapture={closeNavOnItem}>
        {/* 手机端左上角导航开关：桌面被 .mobile-nav-btn 的 display:none 隐藏 */}
        <button
          type="button"
          className="mobile-nav-btn"
          aria-label={navOpen ? "关闭导航菜单" : "打开导航菜单"}
          aria-expanded={navOpen}
          aria-haspopup="menu"
          onClick={() => setNavOpen((value) => !value)}
        >
          {navOpen ? "✕" : "☰"}
        </button>

        <Sidebar
          status={status}
          collapsed={navCollapsed}
          busy={busy}
          modelLabel={modelLabel}
          onToggle={() => setNavCollapsed((value) => !value)}
          onOpenLibrary={openLibrary}
          onOpenWorld={() => void openWorld()}
          onOpenAdjudication={() => setAdjudicationOpen(true)}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenDebug={() => setDebugOpen(true)}
          onOpenSaves={() => setSavesOpen(true)}
          onOpenWelcome={() => setWelcomeOpen(true)}
          onOpenQuickCreate={() => setQuickOpen(true)}
          onUndo={() => void undo()}
          onReset={() => void reset()}
        />

        {/* 手机抽屉的遮罩层：只在抽屉打开时渲染，桌面宽度下被 CSS 隐藏 */}
        {navOpen && <div className="nav-mask" aria-hidden="true" onClick={() => setNavOpen(false)} />}

        <div className="app-main">
          <header className="gamebar">
            <div className="gamebar-identity">
              <img className="gamebar-crest" src="/art/ui-v1/compass-crest.png" alt="" aria-hidden="true" />
              <div className="gamebar-main">
                <h1>{status.pack.title}</h1>
                <p className="subtitle">
                  {status.pack.id} · v{status.pack.version} · {status.pack.rating}
                </p>
              </div>
            </div>
            <div className="gamebar-chips">
              <span className="turn-chip" title="本局第几回合">
                回合 {status.turn}
              </span>
              <span className="scene-chip" title={`场景 ${scene?.id ?? ""}`}>
                {sceneTitle}
              </span>
              <span
                className="usage-chip"
                title={`累计 ${usage.calls} 次模型调用 · ${usage.total_tokens} tokens · ${usage.latency_ms.toFixed(0)}ms`}
              >
                ${usage.cost_usd.toFixed(4)} · {usage.total_tokens} tok
              </span>
              <span className={`replay-chip ${replayEqual ? "ok" : "bad"}`}>
                回放 {replayEqual ? "一致" : "不一致"}
              </span>
              <button
                className="ghost"
                disabled={busy || status.turn === 0}
                title="撤销上一回合"
                onClick={() => void undo()}
              >
                撤销上一回合
              </button>
              <button className="ghost" disabled={busy} title="重开本局" onClick={() => void reset()}>
                重开
              </button>
            </div>
          </header>

          {debug && (
            <div className="debug-strip">
              DEBUG · turn {status.turn} · scene {status.scene.id} · events{" "}
              {status.events.length} · replay {status.replay.equal ? "✓" : "✗"} ·{" "}
              {status.llm.roles.narrator.provider} · {status.usage.calls} calls ·{" "}
              {status.usage.total_tokens} tok · ${status.usage.cost_usd.toFixed(4)}
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          <main className="layout">
            <div className="column left">
              <div
                className={`model-strip${narrator?.provider === "scripted" ? " offline" : ""}`}
                title={`当前叙事模型：${presetLabel} · ${modelName}；思考强度：${effortName}`}
              >
                <span className="model-strip-icon"><UiIcon name="spark" /></span>
                <span className="model-strip-name">
                  {presetLabel} · {modelName}
                </span>
                <span className="model-strip-effort">思考强度 · {effortName}</span>
                <button
                  className="ghost small model-strip-swap"
                  onClick={() => setSettingsOpen(true)}
                >
                  切换
                </button>
              </div>
              <section className={`panel narrative${scene?.ending ? " ending" : ""}`}>
                <h2>
                  叙事
                  {sceneTitle && <span className="scene-label">· {sceneTitle}</span>}
                  {scene?.ending && (
                    <span className="ending-chip" title="作者标记的结局；仍可继续行动">
                      结局 · {scene.ending_title || "落幕"}
                    </span>
                  )}
                </h2>
                {playbackControls}
                <div
                  ref={storyRef}
                  className={`story-log desktop-history story-scroll-${theme.narrativeScroll}`}
                  onScroll={() => { const node = storyRef.current; if (node) storyFollow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 72; }}
                >
                  {!ready && !liveNarrative?.text ? (
                    <div className="story-pending">
                      <p className="story-pending-title">
                        {openingBusy
                          ? "正在生成开局…"
                          : openingError
                            ? "开局没有生成成功"
                            : "世界已创建，等待开始"}
                      </p>
                      {openingError ? (
                        <>
                          <p className="muted">{openingError}</p>
                          <button
                            className="ghost small"
                            disabled={openingBusy}
                            onClick={() => void generateOpening()}
                          >
                            重试
                          </button>
                        </>
                      ) : (
                        <p className="muted">
                          {openingBusy ? "正在生成，请稍候。" : "点击下方按钮生成开场叙述。"}
                        </p>
                      )}
                      {!openingBusy && !openingError && <button type="button" className="primary generate-world" onClick={() => void generateOpening()}>生成世界</button>}
                    </div>
                  ) : (
                    chatEntries.map(entry => <ChatMessage key={entry.id} entry={entry} packId={status.pack.id} adjudication={decisionOwners.get(entry.turn) === entry.id ? status.adjudication : undefined} fields={status.fields} busy={busy || openingBusy} onChanged={refresh} automatic={entry.id === chatEntries.filter(e => e.role === "assistant").slice(-1)[0]?.id}/>)
                  )}
                  {last && !last.ok && (
                    <p className="muted">本回合已回滚，状态未改变。</p>
                  )}
                </div>

                {correctionPanel}
                {ready && !correctionOpen && (
                <div className="action-dock composer">
                <h2>你的行动</h2>
                <div className="tag-tools" role="group" aria-label="文字分段标记">
                  <span className="tag-tools-hint">
                    选中一段文字，再点类型标记
                    <span className="muted">（一句话里可以同时有话语、动作、心理）</span>
                  </span>
                  {TAG_MODES.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="input-mode"
                      disabled={busy}
                      title={item.hint}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => applyTag(item.id)}
                    >
                      <span className="input-mode-icon">{item.icon}</span>
                      {item.label}
                    </button>
                  ))}
                </div>
                {tagHint && <p className="tag-hint">{tagHint}</p>}
                <textarea
                  ref={inputRef}
                  className="composer-input"
                  rows={5}
                  value={draft}
                  disabled={busy}
                  autoFocus
                  placeholder="想说什么、做什么、想什么，都写在这里；写完可以选中一段标成话语/动作/心理"
                  onChange={(event) => {
                    setDraft(event.target.value);
                    if (tags.length > 0) {
                      setTags([]);
                      setTagHint("内容改过了，分段标记已清空，请重新标记");
                    }
                  }}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      void send();
                    }
                  }}
                />
                {tags.length > 0 && (
                  <div className="tag-chips">
                    {tags.map((tag, index) => {
                      const mode = TAG_MODES.find((item) => item.id === tag.mode);
                      return (
                        <span className={`tag-chip tag-${tag.mode}`} key={`${tag.start}-${tag.end}-${index}`}>
                          <span className="tag-chip-mode">
                            {mode?.icon} {mode?.label}
                          </span>
                          <span className="tag-chip-text">
                            {draft.slice(tag.start, tag.end).trim().slice(0, 24) || "…"}
                          </span>
                          <button
                            type="button"
                            className="tag-chip-remove"
                            title="取消这段标记"
                            disabled={busy}
                            onClick={() => removeTag(index)}
                          >
                            ✕
                          </button>
                        </span>
                      );
                    })}
                  </div>
                )}
                {selectedSkills.length > 0 && (
                  <div className="cost-preview">
                    <span className="cost-preview-title">
                      勾选 {selectedSkills.length} 个技能，本回合一起结算
                    </span>
                    {previewRows.length === 0 ? (
                      <span className="muted">无消耗</span>
                    ) : (
                      previewRows.map((row) => (
                        <span
                          className={`cost-item${row.after < 0 ? " short" : ""}`}
                          key={row.id}
                        >
                          {row.label} -{row.amount}（{row.before} → {row.after}）
                        </span>
                      ))
                    )}
                    <span className="muted">取消勾选就不再扣除</span>
                    {previewRows.some((row) => row.after < 0) && (
                      <span className="cost-short">数值不够，发送会被拒绝</span>
                    )}
                  </div>
                )}
                <div className="composer-bar">
                  <span className="composer-hint">
                    Enter 发送 · Shift+Enter 换行
                    {selectedExtras.length > 0 && ` · 附加 ${selectedExtras.length} 项`}
                    {selectedSkills.length > 0 && ` · 技能 ${selectedSkills.length} 个`}
                  </span>
                  <button
                    className="primary"
                    disabled={!canSend}
                    onClick={() => void send()}
                  >
                    {busy ? "结算中…" : "发送"}
                  </button>
                </div>
                <div className="extras-row" role="group" aria-label="附加请求">
                  <span className="extras-label">
                    附加 <span className="muted">（可多选，只随本次发送）</span>
                  </span>
                  {EXTRA_ACTIONS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`extra-chip${extras[item.id] ? " on" : ""}`}
                      aria-pressed={extras[item.id]}
                      disabled={busy}
                      title={item.hint}
                      onClick={() =>
                        setExtras((prev) => ({ ...prev, [item.id]: !prev[item.id] }))
                      }
                    >
                      <span className="input-mode-icon">{item.icon}</span>
                      {item.label}
                    </button>
                  ))}
                </div>
                <OptionsList
                  title={status.layout.options_section}
                  options={options}
                  busy={busy}
                  onPick={pickSuggestion}
                />
                </div>
              )}
              </section>

              <ReceiptLog events={receiptEvents} turn={status.turn} live={busy} />
            </div>
            <div className="column right">
              {theme.showSprite && sprite?.sheet && (
                <SpriteCanvas
                  sheet={sprite.sheet}
                  state={status.state}
                  explicit={theme.explicitLayers}
                  view={theme.spriteView}
                  forcedPose={
                    theme.spriteView.startsWith("closeup_") ? theme.spriteView : undefined
                  }
                  animated={theme.spriteAnimated}
                  fields={status.fields}
                />
              )}
              <InventoryPanel status={status} />
              <StatusBars
                fields={status.fields}
                state={status.state}
                layout={status.layout}
                narrativeStatus={status.narrative_status}
                preview={costPreview}
              />
              {ready && (
              <SkillCards
                title={status.layout.skills_section}
                skills={status.skills}
                busy={busy}
                picked={selectedSkills}
                onToggle={(skillId) =>
                  setSelectedSkills((prev) =>
                    prev.includes(skillId)
                      ? prev.filter((item) => item !== skillId)
                      : [...prev, skillId],
                  )
                }
              />
              )}
            </div>
          </main>
        </div>
      </div>
      )}

      {!adjudicationOpen && !correctionOpen && !settingsOpen && !!status.adjudication?.pending_count && <button type="button" className="adjudication-orb" aria-label={`待裁定问题 ${status.adjudication.pending_count} 项`} title="回答后端 AI 的问题" disabled={busy || openingBusy} onClick={() => {setNavOpen(false);setAdjudicationOpen(true);}}><span aria-hidden="true">?</span><small>{status.adjudication.pending_count}</small></button>}
      {!correctionOpen && <button type="button" className="correction-orb" aria-label="打开 AI 纠正框" title="纠正 AI" disabled={busy || openingBusy || !ready} onClick={() => {setNavOpen(false);setCorrectionOpen(true);}}><CorrectionIcon/></button>}

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
