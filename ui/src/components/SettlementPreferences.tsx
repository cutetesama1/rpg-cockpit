import { useEffect, useState } from "react";
import { getSettings, postSettings } from "../api";
import type { SettlementSettings } from "../types";

export default function SettlementPreferences() {
  const [value, setValue] = useState<SettlementSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { let alive = true; getSettings().then(data => { if (alive) setValue(data.settlement); }).catch(e => { if (alive) setMessage(String(e)); }); return () => { alive = false; }; }, []);
  const change = async (key: keyof SettlementSettings, checked: boolean) => {
    setBusy(true); setMessage("");
    try { const data = await postSettings({ settlement: { [key]: checked } }); setValue(data.settlement); setMessage("结算偏好已保存，将从下一次结算生效。"); }
    catch (e) { setMessage(String(e)); } finally { setBusy(false); }
  };
  return <section className="settings-section settlement-preferences"><h3>后端 AI · 结算精度</h3>
    <p className="muted small">后端只读取本轮玩家输入、最终叙述和当前状态，不携带历史对话。</p>
    {value && ([
      ["relaxed_validation", "宽容识别与局部待裁定", "允许唯一名称映射、空白和标点差异；重试后仍有问题的单项交给玩家，其他合法变化照常结算。"],
      ["fuzzy_identification", "模糊鉴定 ID 与数量", "为已发生的模糊数量给出有依据的估值，计入对应资源；新物品生成临时 ID，等你确认入包。"],
      ["confirm_item_gains", "物品入包前询问", "已登记物品也先询问是否放入背包。新建物品始终需要确认。"],
    ] as const).map(([key, title, detail]) => <label key={key}><input type="checkbox" checked={value[key]} disabled={busy} onChange={e => void change(key, e.target.checked)} /><span><strong>{title}</strong><small>{detail}</small></span></label>)}
    {message && <p className="muted small" role="status">{message}</p>}
  </section>;
}
