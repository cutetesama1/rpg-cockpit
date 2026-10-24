import type { FieldDef } from "./types";
export interface EditorField extends FieldDef {
  value: unknown; tool: string; input: "select" | "number" | "color" | "text";
  options: Record<string,string>; slot?: string; part?: string;
}
export interface EditorCatalog { pack_id: string; revision: string; fields: EditorField[]; health_field: string }
export type DraftOp = { name: string; args: Record<string, any>; evidence: string; source?: string };
export function rgb(hex: string): number[] { return /^#[\da-f]{6}$/i.test(hex) ? [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)) : [255,255,255]; }
export function hex(channels: number[]): string { return "#" + channels.map(n => Math.max(0,Math.min(255,Math.round(n))).toString(16).padStart(2,"0")).join(""); }
export function fieldDraft(ops: DraftOp[], field: EditorField, value: unknown, health: string): DraftOp[] {
  const list: DraftOp[] = structuredClone(ops);
  const evidence = "玩家裁定";
  if (field.tool === "update_clothing") {
    let op = list.find(row => row.name === "update_clothing");
    if (!op) { op = { name: "update_clothing", args: { changes: [] }, evidence }; list.push(op); }
    if (!Array.isArray(op.args.changes)) throw new Error("衣物草案格式不正确，请先清空或修正草案");
    let entry = op.args.changes.find((row: any) => row.slot === field.slot);
    if (!entry) { entry = { slot: field.slot, evidence }; op.args.changes.push(entry); }
    entry[field.part!] = value;
  } else if (field.tool === "update_portrait") {
    let op = list.find(row => row.name === "update_portrait");
    if (!op) { op = { name: "update_portrait", args: { changes: {} }, evidence }; list.push(op); }
    op.args.changes[field.id] = value;
  } else {
    for (let i=list.length-1;i>=0;i--) {
      const row=list[i];
      const target=row.args.field ?? (row.name === "damage" || row.name === "heal" ? row.args.target ?? health : null);
      if (["damage","heal","set_stat","add_stat","set_value"].includes(row.name) && target === field.id) list.splice(i,1);
    }
    list.push({ name: field.tool, args: { field: field.id, value }, evidence });
  }
  return list;
}
