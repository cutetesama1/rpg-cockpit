import UiIcon from "./UiIcon";
import type { Status } from "../types";

interface SidebarProps {
  status: Status;
  collapsed: boolean;
  busy: boolean;
  modelLabel: string;
  onToggle: () => void;
  onOpenLibrary: () => void;
  onOpenWorld: () => void;
  onOpenSettings: () => void;
  onOpenAdjudication: () => void;
  onOpenDebug: () => void;
  onOpenSaves: () => void;
  onOpenWelcome: () => void;
  onOpenQuickCreate: () => void;
  onUndo: () => void;
  onReset: () => void;
}

/** 左侧可隐藏菜单：游戏信息 + 全部设置入口 + 本局操作/统计。 */
export default function Sidebar({
  status,
  collapsed,
  busy,
  modelLabel,
  onToggle,
  onOpenLibrary,
  onOpenWorld,
  onOpenSettings,
  onOpenAdjudication,
  onOpenDebug,
  onOpenSaves,
  onOpenWelcome,
  onOpenQuickCreate,
  onUndo,
  onReset,
}: SidebarProps) {
  const usage = status.usage;
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-head">
        <div className="brand">
          <img className="brand-crest" src="/art/ui-v1/compass-crest.png" alt="" aria-hidden="true" />
          <span className="brand-text">
            <strong>叙事驾驶舱</strong>
            <small>RPG FRAMEWORK</small>
          </span>
        </div>
        <button
          className="icon-btn"
          title={collapsed ? "展开菜单" : "收起菜单"}
          onClick={onToggle}
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>

      <button
        className="sidebar-game"
        title={`当前游戏：${status.pack.title} · 点击打开游戏库`}
        onClick={onOpenLibrary}
      >
        <span className="game-icon"><UiIcon name="book" /></span>
        <span className="sidebar-game-info">
          <strong>{status.pack.title}</strong>
          <small>
            {status.pack.id} · v{status.pack.version}
          </small>
        </span>
        <span className="sidebar-game-go">›</span>
      </button>

      <div className="sidebar-group">
        <p className="sidebar-title">世界与规则</p>
        <button className="nav-item" title="游戏库：选择 / 新建 / 复制游戏" onClick={onOpenLibrary}>
          <span className="nav-icon"><UiIcon name="library" /></span>
          <span className="nav-label">游戏库</span>
        </button>
        <button className="nav-item" title="世界书 / 技能 / 前置提示词" onClick={onOpenWorld}>
          <span className="nav-icon"><UiIcon name="book" /></span>
          <span className="nav-label">世界构筑</span>
        </button>
        <button
          className="nav-item"
          title="把素材交给 AI，一次拆成提示词 + 世界书 + 技能并建成新游戏"
          onClick={onOpenQuickCreate}
        >
          <span className="nav-icon"><UiIcon name="spark" /></span>
          <span className="nav-label">快速创建世界</span>
        </button>
        <button className="nav-item" title="存档 / 读档 / 导出脱敏日志" onClick={onOpenSaves}>
          <span className="nav-icon"><UiIcon name="save" /></span>
          <span className="nav-label">存档读档</span>
        </button>
        <button className="nav-item" title="处理待确认事项、查看裁定历史" onClick={onOpenAdjudication}>
          <span className="nav-icon"><UiIcon name="book" /></span>
          <span className="nav-label">玩家裁定{status.adjudication?.pending_count ? ` · ${status.adjudication.pending_count}` : ""}</span>
        </button>
        <button className="nav-item" title="模型 / 外观壁纸 / 调试" onClick={onOpenSettings}>
          <span className="nav-icon"><UiIcon name="settings" /></span>
          <span className="nav-label">设置</span>
        </button>
        <button
          className="nav-item"
          title="改状态 / 立绘外观 / 场景 / 物品 / 技能，测 bug 用"
          onClick={onOpenDebug}
        >
          <span className="nav-icon"><UiIcon name="flask" /></span>
          <span className="nav-label">调试台</span>
        </button>
        <button className="nav-item" title="年龄提示与上手引导（随时可重看）" onClick={onOpenWelcome}>
          <span className="nav-icon"><UiIcon name="help" /></span>
          <span className="nav-label">新手上手</span>
        </button>
      </div>

      <div className="sidebar-group">
        <p className="sidebar-title">本局操作</p>
        <button
          className="nav-item"
          disabled={busy || status.turn === 0}
          title="撤销上一回合（账本按回合号回滚）"
          onClick={onUndo}
        >
          <span className="nav-icon"><UiIcon name="undo" /></span>
          <span className="nav-label">撤销上一回合</span>
        </button>
        <button className="nav-item" disabled={busy} title="重开本局：回到开场" onClick={onReset}>
          <span className="nav-icon"><UiIcon name="reset" /></span>
          <span className="nav-label">重开本局</span>
        </button>
      </div>

      <div className="sidebar-stats">
        <p className="sidebar-title">本局统计</p>
        <div className="stat-row">
          <span>回合</span>
          <strong>{status.turn}</strong>
        </div>
        <div className="stat-row">
          <span>事件</span>
          <strong>{status.events.length}</strong>
        </div>
        <div className="stat-row">
          <span>模型调用</span>
          <strong>{usage?.calls ?? 0}</strong>
        </div>
        <div className="stat-row">
          <span>tokens</span>
          <strong>{usage?.total_tokens ?? 0}</strong>
        </div>
        <div className="stat-row">
          <span>花费</span>
          <strong>${(usage?.cost_usd ?? 0).toFixed(4)}</strong>
        </div>
      </div>

      <div className="sidebar-foot">
        <button
          className="model-chip"
          title="当前叙事模型；点击打开设置"
          onClick={onOpenSettings}
        >
          {modelLabel}
        </button>
        <p className="sidebar-tip">Enter 发送 · Shift+Enter 换行</p>
      </div>
    </aside>
  );
}
