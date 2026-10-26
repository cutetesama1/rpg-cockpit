import { useEffect, useRef } from "react";
import type { ExtraAction, SpriteSheet, Status } from "../types";
import type { ThemeSettings } from "../theme";
import SpriteCanvas from "./SpriteCanvas";
import StatusBars from "./StatusBars";
import SkillCards from "./SkillCards";
import ReceiptLog from "./ReceiptLog";
import InventoryPanel from "./InventoryPanel";
import UiIcon from "./UiIcon";
interface Props {
  open: boolean;
  docked?: boolean;
  spriteError?: string|null;
  onRetrySprite?:()=>void;
  status: Status;
  theme: ThemeSettings;
  sheet: SpriteSheet | null;
  busy: boolean;
  picked: string[];
  preview: Record<string, number>;
  extras: Record<ExtraAction, boolean>;
  onClose: () => void;
  onPickSkill: (id: string) => void;
  onExtra: (id: ExtraAction) => void;
  onSettings: () => void;
  onAdjudication: () => void;
  onLibrary: () => void;
  onWorld: () => void;
  onCreate: () => void;
  onSaves: () => void;
  onDebug: () => void;
  onWelcome: () => void;
  onUndo: () => void;
  onReset: () => void;
}
export default function MobileGameDrawer(props: Props) {
  const pane = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!props.open) return;
    const before = document.activeElement as HTMLElement | null;
    pane.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); props.onClose(); }
      if (props.docked || event.key !== "Tab") return;
      const items = Array.from(pane.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex="0"]') ?? []).filter(item => item.getClientRects().length > 0);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", keys);
    return () => { window.removeEventListener("keydown", keys); before?.focus({ preventScroll: true }); };
  }, [props.open, props.docked]);
  if (!props.open) return null;
  const navigate = (action: () => void) => { props.onClose(); action(); };
  const usage = props.status.usage;
  return <div className={`mobile-game-overlay${props.docked ? " is-docked" : ""}`}>
    <div className="mobile-game-backdrop" onClick={props.onClose} aria-hidden="true" />
    <aside ref={pane} id="mobile-game-sidebar" className="mobile-game-sidebar" role={props.docked ? "complementary" : "dialog"} aria-modal={props.docked ? undefined : true} aria-label="游戏侧栏">
      <header className="mobile-game-sidebar-head"><strong>{props.status.pack.title}</strong><button type="button" aria-label="关闭游戏侧栏" onClick={props.onClose}>✕</button></header>
      <div className="mobile-game-sidebar-content">
        {props.theme.showSprite && props.sheet && <SpriteCanvas sheet={props.sheet} state={props.status.state} explicit={props.theme.explicitLayers} view={props.theme.spriteView} forcedPose={props.theme.spriteView.startsWith("closeup_") ? props.theme.spriteView : undefined} animated={props.theme.spriteAnimated} fields={props.status.fields} />}
        {props.theme.showSprite && !props.sheet && <section className="panel panel-compact"><h2>立绘</h2><p className="muted small">{props.spriteError?'立绘配置载入失败，可重新尝试。':'正在读取立绘；没有配置的旧世界可复制为可编辑游戏以接入基础立绘。'}</p><button type="button" onClick={props.onRetrySprite}>重新载入立绘</button></section>}
        <StatusBars fields={props.status.fields} state={props.status.state} layout={props.status.layout} narrativeStatus={props.status.narrative_status} preview={props.preview} />
        <InventoryPanel status={props.status} />
        <SkillCards title={props.status.layout.skills_section} skills={props.status.skills} busy={props.busy} picked={props.picked} onToggle={props.onPickSkill} />
        <section className="panel panel-compact mobile-extra-requests"><h2>本回合附加</h2><div>{([{ id: "inspect", label: "审视" }, { id: "status", label: "详情" }, { id: "task", label: "任务" }] as const).map(item => <label key={item.id}><input type="checkbox" checked={props.extras[item.id]} disabled={props.busy} onChange={() => props.onExtra(item.id)} />{item.label}</label>)}</div></section>
        <section className="panel panel-compact mobile-session-summary"><h2>当前进度</h2><p>回合 {props.status.turn} · {props.status.scene.title || props.status.scene.id}</p><p>{usage?.calls ?? 0} 次模型调用 · ${Number(usage?.cost_usd ?? 0).toFixed(4)}</p></section>
        <nav className="mobile-game-links" aria-label="游戏功能">
          <button type="button" onClick={() => {location.href="/?multiplayer=1";}}><UiIcon name="library"/>多人联机</button>
          <details className="adjudication-menu-entry"><summary>裁定与记录</summary><button type="button" onClick={() => navigate(props.onAdjudication)}><UiIcon name="book" />玩家裁定{props.status.adjudication?.pending_count ? ` · ${props.status.adjudication.pending_count}` : ""}</button>
          </details>
          <button type="button" onClick={() => navigate(props.onSaves)}><UiIcon name="save" />存档读档</button>
          <button type="button" onClick={() => navigate(props.onLibrary)}><UiIcon name="library" />游戏库</button>
          <button type="button" onClick={() => navigate(props.onWorld)}><UiIcon name="book" />世界构筑</button>
          <button type="button" onClick={() => navigate(props.onCreate)}><UiIcon name="spark" />创建世界</button>
          <button type="button" disabled={props.busy || props.status.turn === 0} onClick={() => navigate(props.onUndo)}><UiIcon name="undo" />撤销上一回合</button>
          <button type="button" disabled={props.busy} onClick={() => navigate(props.onReset)}><UiIcon name="reset" />重开本局</button>
          <button type="button" onClick={() => navigate(props.onDebug)}><UiIcon name="flask" />调试台</button>
          <button type="button" onClick={() => navigate(props.onWelcome)}><UiIcon name="help" />使用帮助</button>
        </nav>
        <details className="mobile-ledger"><summary>事件与结算记录</summary><ReceiptLog events={props.status.events} turn={props.status.turn} /></details>
      </div>
      <footer className="mobile-game-sidebar-footer"><button className="mobile-settings-button" type="button" onClick={() => navigate(props.onSettings)}><UiIcon name="settings" />设置</button></footer>
    </aside>
  </div>;
}
