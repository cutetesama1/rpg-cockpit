import { useCallback, useEffect, useMemo, useState } from "react";
import {
  debugJumpScene,
  debugLearnSkill,
  debugResetState,
  debugSetInventory,
  debugSetState,
  getDebugCatalog,
  postUndo,
} from "../api";
import SpriteCanvas from "./SpriteCanvas";
import type { DebugCatalog, FieldDef, Status, SpriteSheet } from "../types";
import { SPRITE_VIEW_LABELS, type ThemeSettings, type SpriteView } from "../theme";

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged: (next?: Status) => Promise<void> | void;
  sheet?: SpriteSheet | null;
  theme: ThemeSettings;
  onThemeChange: (next: ThemeSettings) => void;
  status: Status | null;
}

type Tab = "state" | "sprite" | "scene" | "item" | "skill" | "event" | "json";

const TABS: { id: Tab; label: string }[] = [
  { id: "state", label: "状态字段" },
  { id: "sprite", label: "立绘/外观" },
  { id: "scene", label: "场景" },
  { id: "item", label: "物品" },
  { id: "skill", label: "技能" },
  { id: "event", label: "账本/撤销" },
  { id: "json", label: "原始 JSON" },
];

/** 立绘面板最快用到的字段：顺序 = 从上到下改完就能看到效果。 */
const SPRITE_FIELDS = [
  "pose", "left_arm", "right_arm", "eye_state", "gaze", "mouth_shape", "tears", "freckles",
  "decoration_background", "decoration_foreground",
  "body_type",
  "eye_color",
  "expression",
  "blush",
  "hair_style",
  "hair_length",
  "hair_color",
  "breast_size",
  "upper",
  "upper_condition",
  "outfit_color",
  "lower",
  "lower_condition",
  "pants_color",
  "hairpin_position", "earring_graphic", "accessory_tone",
  "headwear", "facewear", "neckwear", "handwear", "legwear", "footwear",
  "backwear", "earrings", "fingerwear", "handheld",
  "headwear_color", "facewear_color", "neckwear_color", "handwear_color", "legwear_color", "footwear_color",
  "backwear_color", "earrings_color", "fingerwear_color", "handheld_color",
  "under_upper",
  "under_lower",
  "genital",
  "bodywriting",
];

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function FieldRow({
  field,
  value,
  onChange,
  labels,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (value: unknown) => void;
  labels?: Record<string, string>;
}) {
  const choices = field.enum_values ?? [];
  return (
    <label className="dbg-field" data-field-id={field.id}>
      <span className="dbg-field-label" title={field.id}>
        {field.label || field.id}
        <small>{field.id}</small>
      </span>
      {choices.length > 0 ? (
        <select value={valueText(value)} onChange={(event) => onChange(event.target.value)}>
          {!choices.includes(valueText(value)) && valueText(value) !== "" && (
            <option value={valueText(value)}>{valueText(value)}（不在枚举内）</option>
          )}
          {choices.map((choice) => (
            <option key={choice} value={choice}>
              {labels?.[choice] ?? choice}
            </option>
          ))}
        </select>
      ) : field.type === "bool" ? (
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
      ) : field.type === "int" || field.type === "float" ? (
        <input
          type="number"
          step={field.step ?? (field.type === "int" ? 1 : 0.1)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          value={valueText(value)}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      ) : (
        <input
          type="text"
          value={valueText(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

/** 调试台：改状态 / 立绘外观 / 场景 / 物品 / 技能 / 账本，全部写回账本并自动存档。 */
export default function DebugConsole({
  open,
  onClose,
  onChanged,
  theme,
  onThemeChange,
  status,
  sheet,
}: Props) {
  const [catalog, setCatalog] = useState<DebugCatalog | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [tab, setTab] = useState<Tab>("state");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [itemCounts, setItemCounts] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const next = await getDebugCatalog();
      setCatalog(next);
      setJsonText(JSON.stringify(next.state, null, 2));
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  const fields = useMemo(() => {
    if (!catalog) return [];
    return catalog.fields;
  }, [catalog]);

  const changedCount = Object.keys(draft).length;

  const run = async (
    action: () => Promise<{ ok: boolean; changed: number; status?: Status }>,
    okText: string,
    after?: () => void | Promise<void>,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      await refresh();
      await onChanged(result.status);
      await after?.();
      setMessage({ ok: true, text: result.changed ? okText : "没有变化" });
      window.setTimeout(() => setMessage(null), 2200);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const applyDraft = async () => {
    if (!changedCount) return;
    await run(
      () => debugSetState(draft),
      `已应用 ${changedCount} 个字段（可撤销）`,
      () => setDraft({}),
    );
  };

  const applyJson = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      setError("JSON 解析失败");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("JSON 需要是一个对象：{字段: 值}");
      return;
    }
    await run(() => debugSetState(parsed as Record<string, unknown>), "已按 JSON 应用");
  };

  if (!open) return null;

  const switchTab = (next: Tab) => {
    setTab(next);
    setMessage(null);
  };

  const renderField = (field: FieldDef) => (
    <FieldRow
      key={field.id}
      field={field}
      labels={sheet?.labels?.[field.id] ?? sheet?.controls?.[field.id]}
      value={field.id in draft ? draft[field.id] : catalog?.state[field.id]}
      onChange={(value) => setDraft((prev) => ({ ...prev, [field.id]: value }))}
    />
  );

  return (
    <div className="modal-mask" role="dialog" aria-modal="true">
      <div className="modal debug-console">
        <header className="modal-head">
          <div>
            <h2>调试台</h2>
            <p className="muted small">
              {catalog
                ? `${catalog.pack.title} · 回合 ${catalog.turn} · 场景 ${catalog.scene_id} · 字段 ${catalog.fields.length}`
                : "正在读取内容包……"}
              　改动会写进账本并自动存档，能用「撤销上一回合」回退
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} title="关闭">
            ✕
          </button>
        </header>

        <div className="dbg-tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`dbg-tab${tab === item.id ? " active" : ""}`}
              onClick={() => switchTab(item.id)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            className="ghost small dbg-refresh"
            onClick={() => void refresh()}
            disabled={busy}
          >
            重新读取
          </button>
        </div>

        {changedCount > 0 && (
          <div className="dbg-actions" role="status">
            <span className="muted small">待应用 {changedCount} 项，尚未保存到游戏</span>
            <button type="button" className="primary small" disabled={busy} onClick={() => void applyDraft()}>
              {tab === "sprite" ? "保存并应用外观" : "应用改动"}
            </button>
          </div>
        )}
        {message && <p className={`modal-message ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
        {error && <p className="modal-message bad">{error}</p>}

        <div className="dbg-body">
          {!catalog ? (
            <p className="muted">正在读取……</p>
          ) : tab === "state" ? (
            <>
              <p className="muted small">
                改完点右下「应用改动」；数值会按字段 min/max 夹取，枚举只能选列表里的值。
              </p>
              <div className="dbg-grid">{fields.map(renderField)}</div>
            </>
          ) : tab === "sprite" ? (
            <>
              <p className="muted small">
                这些字段直接驱动立绘合成，应用后写入当前游戏并支持撤销。衣物和动作只列出已注册的可用项；标注“表现”的动作使用已有部件配合程序位移或特效，不是独立逐帧原画。
              </p>
              {sheet && (
                <div className="dbg-sprite-preview">
                  <SpriteCanvas sheet={sheet} state={{ ...catalog.state, ...draft }}
                    explicit={theme.explicitLayers} animated={false} view="full" fields={catalog.fields} />
                  <p className="muted small" role="status">
                    {changedCount ? `正在预览 ${changedCount} 项未保存改动，点击下方「应用改动」保存到游戏。` : "当前已保存的外观"}
                  </p>
                </div>
              )}
              {sheet?.motion_notes && <p className="muted small" role="status">动作实现：{sheet.motion_notes[String(draft.pose ?? status?.state.pose ?? "stand")] || "使用当前内容包的已注册姿势"}</p>}
              <div className="dbg-grid">
                {SPRITE_FIELDS.map((id) => fields.find((field) => field.id === id))
                  .filter((field): field is FieldDef => Boolean(field))
                  .map(renderField)}
              </div>
              <h4 className="dbg-sub">外观开关</h4>
              <div className="dbg-grid">
                <label className="dbg-field">
                  <span className="dbg-field-label">
                    显示立绘<small>showSprite</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={theme.showSprite}
                    onChange={(event) =>
                      onThemeChange({ ...theme, showSprite: event.target.checked })
                    }
                  />
                </label>
                <label className="dbg-field">
                  <span className="dbg-field-label">
                    立绘动画<small>spriteAnimated</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={theme.spriteAnimated}
                    onChange={(event) =>
                      onThemeChange({ ...theme, spriteAnimated: event.target.checked })
                    }
                  />
                </label>
                <label className="dbg-field">
                  <span className="dbg-field-label">
                    成人向图层<small>explicitLayers</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={theme.explicitLayers}
                    onChange={(event) =>
                      onThemeChange({ ...theme, explicitLayers: event.target.checked })
                    }
                  />
                </label>
                <label className="dbg-field">
                  <span className="dbg-field-label">
                    取景<small>spriteView</small>
                  </span>
                  <select
                    value={theme.spriteView}
                    onChange={(event) =>
                      onThemeChange({
                        ...theme,
                        spriteView: event.target.value as SpriteView,
                      })
                    }
                  >
                    {SPRITE_VIEW_LABELS.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
              </div>
              {catalog.sprite ? (
                <p className="muted small">
                  当前内容包：{catalog.sprite.layers} 层 · {catalog.sprite.frames} 帧 @{" "}
                  {catalog.sprite.fps}fps · 取景 {catalog.sprite.views.join(" / ") || "默认"} ·
                  取样窗 {catalog.sprite.crop.w}×{catalog.sprite.crop.h}
                </p>
              ) : (
                <p className="muted small">当前内容包没有 sprites.json（不显示立绘）。</p>
              )}
            </>
          ) : tab === "scene" ? (
            <>
              <p className="muted small">直接跳到目标场景（和正常转场写同一条事件，可撤销）。</p>
              <div className="dbg-list">
                {catalog.scenes.map((scene) => (
                  <div key={scene.id} className="dbg-row">
                    <span>
                      <b>{scene.title || scene.id}</b>
                      <small>
                        {scene.id}
                        {scene.opening ? " · 开场" : ""}
                        {scene.id === catalog.scene_id ? " · 当前" : ""}
                      </small>
                    </span>
                    <button
                      type="button"
                      className="ghost small"
                      disabled={busy || scene.id === catalog.scene_id}
                      onClick={() =>
                        void run(
                          () => debugJumpScene(scene.id),
                          `已跳到 ${scene.title || scene.id}`,
                        )
                      }
                    >
                      跳转
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : tab === "item" ? (
            <>
              <p className="muted small">把物品数量设成目标值（按差额补一条 add_item 事件）。</p>
              {catalog.items.length === 0 ? (
                <p className="muted">当前内容包没有声明物品。</p>
              ) : (
                <div className="dbg-list">
                  {catalog.items.map((item) => (
                    <div key={item.id} className="dbg-row">
                      <span>
                        <b>{item.name || item.id}</b>
                        <small>
                          {item.id} · 现有 {catalog.inventory[item.id] ?? 0}
                        </small>
                      </span>
                      <span className="dbg-inline">
                        <input
                          type="number"
                          min={0}
                          value={itemCounts[item.id] ?? String(catalog.inventory[item.id] ?? 0)}
                          onChange={(event) =>
                            setItemCounts((prev) => ({ ...prev, [item.id]: event.target.value }))
                          }
                        />
                        <button
                          type="button"
                          className="ghost small"
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () =>
                                debugSetInventory(
                                  item.id,
                                  Number(itemCounts[item.id] ?? catalog.inventory[item.id] ?? 0),
                                ),
                              `已设置 ${item.name || item.id}`,
                            )
                          }
                        >
                          设置
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : tab === "skill" ? (
            <>
              <p className="muted small">把内容包里的技能直接记成已习得（写 skill.learned）。</p>
              <div className="dbg-list">
                {catalog.skills.map((skill) => (
                  <div key={skill.id} className="dbg-row">
                    <span>
                      <b>{skill.name || skill.id}</b>
                      <small>
                        {skill.id} · 冷却 {skill.cooldown} · 消耗{" "}
                        {Object.entries(skill.cost)
                          .map(([key, value]) => `${key} ${value}`)
                          .join(" / ") || "无"}
                      </small>
                    </span>
                    <button
                      type="button"
                      className="ghost small"
                      disabled={busy || skill.learned}
                      onClick={() =>
                        void run(() => debugLearnSkill(skill.id), `已学会 ${skill.name || skill.id}`)
                      }
                    >
                      {skill.learned ? "已习得" : "学会"}
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : tab === "event" ? (
            <>
              <div className="dbg-actions">
                <button
                  type="button"
                  className="ghost small"
                  disabled={busy || catalog.turn === 0}
                  onClick={() =>
                    void run(async () => {
                      await postUndo();
                      return { ok: true, changed: 1 };
                    }, "已撤销上一回合")
                  }
                >
                  撤销上一回合
                </button>
                <button
                  type="button"
                  className="ghost small"
                  disabled={busy}
                  onClick={() =>
                    void run(() => debugResetState(), "所有字段已恢复内容包默认值")
                  }
                >
                  所有字段恢复默认
                </button>
              </div>
              <p className="muted small">
                最近 {catalog.events.length} 条事件（新→旧）。&quot;tool&quot; 行里能看到调试写入。
              </p>
              <div className="dbg-list dbg-events">
                {[...catalog.events].reverse().map((event) => (
                  <div key={event.seq} className="dbg-row">
                    <span>
                      <b>
                        #{event.seq} · {event.kind}
                      </b>
                      <small>
                        回合 {event.turn}
                        {event.role ? ` · ${event.role}` : ""}
                        {typeof event.payload?.tool === "string"
                          ? ` · ${event.payload.tool}`
                          : ""}
                        {event.payload?.changes && typeof event.payload.changes === "object"
                          ? ` · ${Object.keys(event.payload.changes as object).join(",")}`
                          : ""}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <p className="muted small">
                当前状态的 JSON 快照，可整段改完再点「应用 JSON」（只提交对象里的键）。
              </p>
              <textarea
                className="dbg-json"
                value={jsonText}
                spellCheck={false}
                onChange={(event) => setJsonText(event.target.value)}
              />
              <div className="dbg-actions">
                <button
                  type="button"
                  className="ghost small"
                  disabled={busy}
                  onClick={() => setJsonText(JSON.stringify(catalog.state, null, 2))}
                >
                  还原成当前状态
                </button>
                <button type="button" className="primary small" disabled={busy} onClick={() => void applyJson()}>
                  应用 JSON
                </button>
              </div>
            </>
          )}
        </div>

        <footer className="modal-foot dbg-foot">
          <span className="muted small">
            {status ? `回合 ${status.turn} · 事件 ${status.events.length}` : ""}
            {changedCount > 0 ? ` · 待应用 ${changedCount} 个字段` : ""}
          </span>
          <div className="dbg-actions">
            <button
              type="button"
              className="ghost small"
              disabled={busy || changedCount === 0}
              onClick={() => setDraft({})}
            >
              放弃改动
            </button>
            <button
              type="button"
              className="primary small"
              disabled={busy || changedCount === 0}
              onClick={() => void applyDraft()}
            >
              应用改动
            </button>
            <button type="button" className="ghost small" onClick={onClose}>
              关闭
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
