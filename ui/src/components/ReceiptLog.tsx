import { useState } from "react";
import type { EventRecord } from "../types";

interface Props {
  events: EventRecord[];
  turn: number;
  /** 回合进行中：事件实时追加，显示脉冲提示。 */
  live?: boolean;
}

interface Change {
  before: unknown;
  after: unknown;
}

type Filter = "all" | "turn" | "tools" | "issues";

const TOOL_KINDS = new Set([
  "tool.applied",
  "tool.rejected",
  "roll.resolved",
  "skill.used",
  "skill.learned",
  "llm.usage",
  "scene.entered",
  "clothing.checked",
  "director.triggered",
  "director.resolved",
  "settlement.checked",
  "settlement.rejected",
  "settlement.warning",
]);
const ISSUE_KINDS = new Set(["tool.rejected", "turn.rolled_back", "narrative.checked", "settlement.rejected", "settlement.warning"]);

function describe(event: EventRecord): string {
  const payload = event.payload ?? {};
  switch (event.kind) {
    case "turn.started": {
      const action = payload.action as { kind?: string; skill_id?: string; text?: string } | undefined;
      const label = action?.skill_id ?? action?.text ?? action?.kind ?? "行动";
      return `回合 ${event.turn} 开始 · ${label}`;
    }
    case "skill.used": {
      const changes = payload.changes as Record<string, Change> | undefined;
      const spent = Object.entries(changes ?? {})
        .map(([field, change]) => `${field} ${String(change.before)}→${String(change.after)}`)
        .join("，");
      return `使用技能 ${String(payload.name ?? payload.skill_id ?? "")}${spent ? ` · 消耗 ${spent}` : ""}`;
    }
    case "skill.learned": {
      const skill = (payload.skill ?? {}) as { name?: string; id?: string; cost?: Record<string, number> };
      const cost = Object.entries(skill.cost ?? {})
        .map(([field, amount]) => `${field} ${amount}`)
        .join("，");
      return `习得技能 ${String(skill.name ?? skill.id ?? "")}${cost ? ` · 消耗 ${cost}` : ""}`;
    }
    case "roll.resolved": {
      const rolled = (event.rolls?.[0] ?? payload) as { dice?: string; total?: number; passed?: boolean; kind?: string };
      return rolled.kind === "probability" ? `概率检定 → ${rolled.passed ? "成功" : "失败"}` : `掷骰 ${rolled.dice ?? ""} → ${rolled.total ?? "?"}`;
    }
    case "director.triggered": return `导演事件触发 · ${String(payload.title ?? "")}`;
    case "director.resolved": return `导演结果确定 · ${String(payload.title ?? "")} · ${String(payload.outcome ?? "")}`;
    case "tool.applied": {
      const tool = String(payload.tool ?? "tool");
      const changes = payload.changes as Record<string, Change> | undefined;
      const changed = Object.entries(changes ?? {})
        .map(([field, change]) => `${field} ${String(change.before)}→${String(change.after)}`)
        .join("，");
      const data = payload.data as { item_id?: string; count?: number; flag?: string } | undefined;
      const extra = data?.item_id
        ? `${data.item_id}×${data.count ?? 1}`
        : data?.flag
          ? `flag ${data.flag}`
          : "";
      return `已应用 ${tool}${changed ? ` · ${changed}` : ""}${extra ? ` · ${extra}` : ""}`;
    }
    case "tool.rejected":
      return `拒绝 ${String(payload.tool ?? "")}：${String(payload.error ?? "")}`;
    case "settlement.checked":
      return `结算完成 · ${String(payload.operations ?? 0)} 项操作 · ${String(payload.attempts ?? 1)} 次尝试`;
    case "settlement.rejected":
      return `结算草案未提交 · ${String(payload.failed_at ?? "")}：${String(payload.error ?? "")}`;
    case "settlement.warning":
      return `待确认，相关状态保持原值：${Array.isArray(payload.uncertain) ? payload.uncertain.join("；") : ""}`;
    case "clothing.checked": {
      const changed = payload.changed_fields as string[] | undefined;
      return changed?.length ? `衣物结算 · 已更新 ${changed.length} 项` : "衣物结算 · 保持当前衣着";
    }
    case "narrative.generated":
      return "叙事生成";
    case "scene.entered": {
      const title = String(payload.title ?? payload.scene_id ?? "");
      const from = payload.from_scene ? `${String(payload.from_scene)} → ` : "";
      const reason = payload.reason ? `（${String(payload.reason)}）` : "";
      return `进入场景 ${from}「${title}」${reason}`;
    }
    case "narrative.checked":
      return `数值检查 · ${String(payload.action ?? "")}`;
    case "turn.committed":
      return "回合提交";
    case "turn.rolled_back":
      return "回合回滚";
    case "llm.usage": {
      const usage = (payload.usage ?? {}) as {
        total_tokens?: number;
        prompt_tokens?: number;
        completion_tokens?: number;
      };
      const cost = Number(payload.cost_usd ?? 0);
      const attempts = Number(payload.attempts ?? 1);
      const retried = attempts > 1 ? ` · 重试 ${attempts - 1} 次` : "";
      return `调用 ${String(payload.provider ?? "")} · ${usage.total_tokens ?? 0} tok · $${cost.toFixed(4)}${retried}`;
    }
    default:
      return event.kind;
  }
}

export default function ReceiptLog({ events, turn, live = false }: Props) {
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = events.filter((event) => {
    if (filter === "turn") return event.turn === turn && turn > 0;
    if (filter === "tools") return TOOL_KINDS.has(event.kind);
    if (filter === "issues") return ISSUE_KINDS.has(event.kind);
    return true;
  });
  const recent = filtered.slice(-16).reverse();

  const chips: { id: Filter; label: string }[] = [
    { id: "all", label: "全部" },
    { id: "turn", label: "本回合" },
    { id: "tools", label: "工具与技能" },
    { id: "issues", label: "异常" },
  ];

  return (
    <section className="panel receipt">
      <div className="receipt-head">
        <h2>
          小票 · 事件账本
          {live && <span className="live-dot" title="回合进行中，事件实时推送" />}
        </h2>
        <div className="filter-chips">
          {chips.map((chip) => (
            <button
              key={chip.id}
              className={`filter-chip${filter === chip.id ? " on" : ""}`}
              type="button"
              onClick={() => setFilter(chip.id)}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>
      {recent.length === 0 ? (
        <p className="muted">
          {events.length === 0 ? "还没有事件。" : "没有符合条件的事件。"}
        </p>
      ) : (
        <ol>
          {recent.map((event) => (
            <li key={event.seq} className={`event event-${event.kind.replaceAll(".", "-")}`}>
              <span className="event-seq">#{event.seq}</span>
              <span className="event-kind">{event.kind}</span>
              <span className="event-text">{describe(event)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
