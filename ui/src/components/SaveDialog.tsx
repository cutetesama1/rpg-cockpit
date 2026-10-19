import { useCallback, useEffect, useState } from "react";
import {
  deleteSave,
  getSaves,
  loadGame,
  logExportUrl,
  saveGame,
} from "../api";
import type { SaveSummary, SavesView, Status } from "../types";

interface SaveDialogProps {
  open: boolean;
  busy: boolean;
  turn: number;
  onClose: () => void;
  onLoaded: (status: Status) => void;
}

function formatTime(raw?: string | null): string {
  if (!raw) return "—";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function describe(save: SaveSummary): string {
  const pieces = [`回合 ${save.turn ?? 0}`];
  if (save.scene_id) pieces.push(`场景 ${save.scene_id}`);
  if (save.auto) pieces.push("自动");
  return pieces.join(" · ");
}

/** 存读档面板：不限槽位、随时存读；结局只是标记，读档不会降低可玩能力。 */
export default function SaveDialog({
  open,
  busy,
  turn,
  onClose,
  onLoaded,
}: SaveDialogProps) {
  const [view, setView] = useState<SavesView | null>(null);
  const [slot, setSlot] = useState(`slot-${turn}`);
  const [label, setLabel] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const [working, setWorking] = useState(false);

  const reload = useCallback(async () => {
    try {
      const data = await getSaves();
      setView(data);
      setMessage(null);
    } catch (err) {
      setMessage({ kind: "bad", text: String((err as Error).message || err) });
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setSlot(`slot-${turn}`);
    setLabel("");
    setMessage(null);
    void reload();
  }, [open, turn, reload]);

  async function handleSave(targetSlot = slot, targetLabel = label) {
    setWorking(true);
    try {
      const result = await saveGame(targetSlot, targetLabel);
      setView(result.saves);
      setMessage({ kind: "ok", text: `已保存到 ${result.save.slot}` });
    } catch (err) {
      setMessage({ kind: "bad", text: String((err as Error).message || err) });
    } finally {
      setWorking(false);
    }
  }

  async function handleLoad(target: string) {
    setWorking(true);
    try {
      const result = await loadGame(target);
      setMessage({ kind: "ok", text: `已读取 ${result.save.slot}（回合 ${result.save.turn}）` });
      onLoaded(result.status);
      onClose();
    } catch (err) {
      setMessage({ kind: "bad", text: String((err as Error).message || err) });
    } finally {
      setWorking(false);
    }
  }

  async function handleDelete(target: string) {
    if (!window.confirm(`删除存档 ${target}？此操作不可撤销。`)) return;
    setWorking(true);
    try {
      const result = await deleteSave(target);
      setView(result.saves);
      setMessage({ kind: "ok", text: result.removed ? `已删除 ${target}` : "存档不存在" });
    } catch (err) {
      setMessage({ kind: "bad", text: String((err as Error).message || err) });
    } finally {
      setWorking(false);
    }
  }

  if (!open) return null;
  const saves = view?.saves ?? [];

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>存档 / 读档</h2>
            <p className="modal-sub">
              槽位不限、随时可存可读；读档不会限制或降低任何可玩能力。
            </p>
          </div>
          <button className="ghost" onClick={onClose} title="关闭">✕</button>
        </div>

        {message ? <p className={`modal-message ${message.kind}`}>{message.text}</p> : null}

        <div className="modal-form">
          <div className="save-form-row">
            <label className="inline">
              槽位
              <input
                value={slot}
                onChange={(event) => setSlot(event.target.value)}
                placeholder="slot-1（小写字母/数字/-_.）"
              />
            </label>
            <label className="inline">
              备注
              <input
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="例如：刚进后仓"
                maxLength={40}
              />
            </label>
            <button
              className="primary"
              disabled={busy || working || !slot.trim()}
              onClick={() => void handleSave()}
            >
              保存当前进度
            </button>
          </div>
        </div>

        <div className="save-list">
          {saves.length === 0 ? (
            <p className="empty">还没有存档。随时点上面的按钮存一个。</p>
          ) : (
            saves.map((save) => (
              <div key={save.slot} className={`save-row${save.auto ? " auto" : ""}`}>
                <div className="save-main">
                  <div className="save-title">
                    <strong>{save.label || save.slot}</strong>
                    <code>{save.slot}</code>
                    {save.auto ? <span className="badge ok">自动</span> : null}
                  </div>
                  <div className="save-meta">
                    {describe(save)} · {formatTime(save.saved_at)}
                    {save.pack_title ? ` · ${save.pack_title}` : ""}
                  </div>
                </div>
                <div className="save-actions">
                  <button
                    className="primary"
                    disabled={busy || working}
                    onClick={() => void handleLoad(save.slot)}
                  >
                    读取
                  </button>
                  <button
                    className="ghost"
                    disabled={busy || working}
                    onClick={() => void handleSave(save.slot, save.label || `回合${turn}`)}
                    title="用当前进度覆盖这个槽位"
                  >
                    覆盖
                  </button>
                  <button
                    className="ghost danger"
                    disabled={busy || working}
                    onClick={() => void handleDelete(save.slot)}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))
          )}
          {view?.broken?.length ? (
            <p className="modal-message bad">
              有 {view.broken.length} 个存档读取失败：{view.broken.map((item) => item.slot).join("、")}
            </p>
          ) : null}
        </div>

        <div className="modal-foot">
          <span className="hint">存档目录：{view?.dir ?? "…"}</span>
          <div className="modal-actions">
            <a className="ghost" href={logExportUrl()} download title="导出脱敏调试日志（JSON）">
              导出日志
            </a>
            <button className="ghost" onClick={onClose}>关闭</button>
          </div>
        </div>
      </div>
    </div>
  );
}
