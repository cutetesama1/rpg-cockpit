import type { AdjudicationItem, FieldDef } from "./types";
import type { ChatEntry } from "./chatHistory";

export function lastNarrativeIds(entries: ChatEntry[]): Map<number, string> {
  const result = new Map<number, string>();
  for (const entry of entries) if (entry.role === "assistant") result.set(entry.turn, entry.id);
  return result;
}

export function turnQuestions(items: AdjudicationItem[], turn: number): AdjudicationItem[] {
  return items.filter(item => item.source_turn === turn && item.visibility === "public" && ["pending", "confirmed", "rejected"].includes(item.state));
}

export function questionEffect(item: AdjudicationItem, fields: FieldDef[] = []): string {
  const label = (id: unknown) => fields.find(f => f.id === id)?.label ?? String(id ?? "状态");
  return item.operations.map(operation => {
    const args = (operation.args ?? {}) as Record<string, unknown>;
    switch (operation.name) {
      case "acquire_item": return `${String(args.name ?? "物品")} × ${String(args.count ?? 1)}`;
      case "credit_currency": return `金钱 ${Number(args.amount) >= 0 ? "+" : ""}${String(args.amount)}${String(args.unit ?? "")}${args.converted_amount !== undefined ? ` → ${String(args.converted_amount)}（按世界内兑换）` : ""}`;
      case "add_stat": return `${label(args.field)} ${Number(args.delta) >= 0 ? "+" : ""}${String(args.delta)}`;
      case "set_stat": return `${label(args.field)}设为 ${String(args.value)}`;
      case "damage": return `${label(args.target ?? "hp")} −${String(args.amount)}`;
      case "heal": return `${label(args.target ?? "hp")} +${String(args.amount)}`;
      case "add_item": return `物品数量 ${Number(args.count) >= 0 ? "+" : ""}${String(args.count)}`;
      case "update_clothing": return "更新本条问题所述的穿戴";
      case "record_fact": return `记录：${String(args.title ?? item.title)}`;
      default: return "采用本条问题的状态变更";
    }
  }).join("；") || (Object.keys(item.status_patch).length ? "更新本条角色状态" : "仅记录你的确认，不改数值");
}
