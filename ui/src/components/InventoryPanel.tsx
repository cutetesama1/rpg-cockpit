import type { Status } from "../types";

export default function InventoryPanel({ status }: { status: Status }) {
  const entries = Object.entries(status.inventory).filter(([, count]) => count > 0);
  return <details className="panel panel-compact inventory-panel"><summary>背包 <small>{entries.length} 种物品</small></summary>
    {entries.length === 0 ? <p className="muted small">背包为空。待裁定物品确认后会出现在这里。</p> : entries.map(([id, count]) => <p key={id} title={status.items?.find(item => item.id === id)?.description}><span>{status.items?.find(item => item.id === id)?.name ?? id}</span><strong>× {count}</strong></p>)}
  </details>;
}
