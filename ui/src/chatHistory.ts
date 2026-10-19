import type { Action, EventRecord, InputMode } from "./types";
export interface ChatEntry {
  streaming?: boolean;
  id: string;
  turn: number;
  role: "user" | "assistant" | "notice";
  text: string;
  meta: string[];
  failed?: boolean;
}
const MODES: Record<InputMode, string> = { action: "动作", speech: "话语", thought: "心理" };
const EXTRAS: Record<string, string> = { inspect: "审视", status: "详情", task: "任务" };
export function actionMessage(action: Action, names: Record<string, string> = {}): { text: string; meta: string[] } {
  if (action.kind === "skill") return { text: `使用技能：${names[action.skill_id] ?? action.skill_id}`, meta: ["技能"] };
  if (action.kind === "option") return { text: `选择选项：${action.option_id}`, meta: [] };
  const modes = Array.isArray(action.segments) && action.segments.length ? action.segments.map(s => s.mode) : Array.isArray(action.modes) ? action.modes : action.mode ? [action.mode] : [];
  const meta = Array.from(new Set(modes.filter((m): m is InputMode => Object.prototype.hasOwnProperty.call(MODES, m)).map(m => MODES[m])));
  const skills = (action.skills ?? []).map(s => s.name || names[s.skill_id] || s.skill_id);
  if (skills.length) meta.push(`技能：${skills.join("、")}`);
  const extras = (action.extras ?? []).map(e => EXTRAS[e] ?? e);
  if (extras.length) meta.push(`附加：${extras.join("、")}`);
  const text = (typeof action.text === "string" ? action.text.trim() : "") || (skills.length ? `使用技能：${skills.join("、")}` : `附加请求：${extras.join("、")}`);
  return { text, meta };
}
/** Read the ledger once: saved player actions and AI replies share the same timeline. */
export function buildChatHistory(events: EventRecord[], names: Record<string, string> = {}): ChatEntry[] {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const undone = new Set(sorted.filter(e => e.kind === "turn.rolled_back" && e.payload.reason === "undo").map(e => e.turn));
  const failed = new Set(sorted.filter(e => e.kind === "turn.rolled_back" && e.payload.reason !== "undo").map(e => e.turn));
  const entries: ChatEntry[] = [];
  for (const event of sorted) {
    if (undone.has(event.turn)) continue;
    if (event.kind === "turn.started") {
      const action = event.payload.action as Action | undefined;
      if (!action || !["text", "skill", "option"].includes(action.kind)) continue;
      const message = actionMessage(action, names);
      const display = event.payload.display_text;
      entries.push({ id: `user-${event.seq}`, turn: event.turn, role: "user", ...message,
        text: typeof display === "string" && display.trim() ? display : message.text, failed: failed.has(event.turn) });
    } else if (event.kind === "narrative.generated" && !failed.has(event.turn)) {
      const text = event.payload.narrative;
      if (typeof text === "string" && text.trim()) entries.push({ id: `ai-${event.seq}`, turn: event.turn, role: "assistant", text, meta: [] });
    } else if (event.kind === "turn.rolled_back" && failed.has(event.turn)) {
      const errors = event.payload.errors;
      entries.push({ id: `error-${event.seq}`, turn: event.turn, role: "notice", text: `本回合未完成，状态已回滚。${Array.isArray(errors) ? errors.join("；") : ""}`, meta: [] });
    }
  }
  return entries;
}
