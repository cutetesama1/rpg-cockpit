import { useMemo, useState } from "react";
import type { SettingsView, Status, TurnResult } from "../types";
import type { ThemeSettings } from "../theme";

interface Props {
  status: Status | null;
  last: TurnResult | null;
  settings: SettingsView | null;
  theme: ThemeSettings;
}

function Block({ title, value, open = false }: { title: string; value: unknown; open?: boolean }) {
  return (
    <details className="debug-block" open={open}>
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export default function DebugPanel({ status, last, settings, theme }: Props) {
  const [copied, setCopied] = useState(false);

  const snapshot = useMemo(
    () => ({
      pack: status?.pack,
      turn: status?.turn,
      scene: status?.scene,
      state: status?.state,
      inventory: status?.inventory,
      skills: status?.skills,
      llm: status?.llm,
      usage: status?.usage,
      replay: status?.replay,
      events: status?.events,
      last,
      settings,
      theme,
      captured_at: new Date().toISOString(),
    }),
    [status, last, settings, theme],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(snapshot, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  if (!status) {
    return <p className="muted">正在读取运行状态……</p>;
  }

  return (
    <div className="debug-panel">
      <div className="debug-grid">
        <span>pack</span>
        <b>{status.pack.id}</b>
        <span>回合</span>
        <b>{status.turn}</b>
        <span>场景</span>
        <b>
          {status.scene.id} · {status.scene.title}
        </b>
        <span>场景条件</span>
        <b>{status.scene.requires_met ? "已满足" : status.scene.blocked_reason ?? "未满足"}</b>
        <span>事件</span>
        <b>{status.events.length} 条</b>
        <span>回放</span>
        <b className={status.replay.equal ? "ok" : "bad"}>
          {status.replay.equal ? "一致" : "不一致"}
        </b>
        <span>模型</span>
        <b>
          {status.llm.roles.narrator.provider} · {status.llm.roles.narrator.model || "端点默认"}
          {status.llm.separated ? "（分离）" : "（单模型）"}
        </b>
        <span>累计调用</span>
        <b>
          {status.usage.calls} 次 · {status.usage.total_tokens} tok · $
          {status.usage.cost_usd.toFixed(4)} · {status.usage.latency_ms.toFixed(0)}ms
        </b>
        <span>壁纸</span>
        <b>
          {theme.custom ? "自定义图片" : theme.wallpaper} · dim {theme.dim.toFixed(2)} · blur{" "}
          {theme.blur}px
        </b>
      </div>

      <div className="debug-actions">
        <button className="ghost small" type="button" onClick={() => void copy()}>
          {copied ? "已复制 ✓" : "复制全部 JSON"}
        </button>
      </div>

      <Block title="状态字段 + 背包" value={{ state: status.state, inventory: status.inventory }} open />
      <Block title="当前场景（含选项可用性）" value={status.scene} open />
      <Block title="技能可用性" value={status.skills} />
      <Block title="回放报告" value={status.replay} />
      <Block title="最近回合结果" value={last ?? "（还没有行动）"} />
      <Block title="事件账本（全量）" value={status.events} />
      <Block title="模型设置（api_key 已打码）" value={settings ?? "（未读取）"} />
      <Block title="外观设置" value={theme} />
    </div>
  );
}
