import SkillLibraryPanel from "./SkillLibraryPanel";
import { SPRITE_VIEW_LABELS } from "../theme";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  getSettings,
  importPack,
  postSettings,
  probeModels,
  resetSettings,
  testSettings,
} from "../api";
import DebugPanel from "./DebugPanel";
import {
  FONT_TARGETS,
  UI_THEMES,
  SCROLL_STYLES,
  WALLPAPERS,
  type SpriteView,
  type ThemeSettings,
} from "../theme";
import type {
  LlmProfile,
  LlmRoles,
  ModelCatalog,
  ModelPreset,
  ProviderView,
  RemoteModelList,
  SettingsUpdate,
  SettingsView,
  Status,
  TurnResult,
} from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged: () => Promise<void> | void;
  status: Status | null;
  last: TurnResult | null;
  theme: ThemeSettings;
  onThemeChange: (next: ThemeSettings) => void;
  debug: boolean;
  onDebugChange: (on: boolean) => void;
}

type Message = { ok: boolean; text: string } | null;

/** 正在编辑的一个模型端点（api_key 只在本次输入里，不回显）。 */
interface ProviderDraft {
  preset: string;
  base_url: string;
  model: string;
  api_key: string;
  reasoning_effort: string;
  timeout: number;
  price_in: number;
  price_out: number;
  max_retries: number;
  retry_backoff_ms: number;
}

const CUSTOM = "custom";

function presetById(catalog: ModelCatalog | null, id: string): ModelPreset | undefined {
  return catalog?.presets.find((item) => item.id === id);
}

function draftFor(
  catalog: ModelCatalog | null,
  presetId: string,
  saved?: ProviderView | null,
): ProviderDraft {
  const preset = presetById(catalog, presetId);
  return {
    preset: presetId,
    base_url: saved?.base_url ?? preset?.base_url ?? "",
    model: saved?.model || preset?.models[0]?.id || "",
    api_key: "",
    reasoning_effort: saved?.reasoning_effort ?? "",
    timeout: saved?.timeout ?? 60,
    price_in: saved?.price_in ?? 0,
    price_out: saved?.price_out ?? 0,
    max_retries: saved?.max_retries ?? 2,
    retry_backoff_ms: saved?.retry_backoff_ms ?? 500,
  };
}

function RoleEditor({
  title,
  hint,
  profile,
  providers,
  onChange,
}: {
  title: string;
  hint: string;
  profile: LlmProfile;
  providers: string[];
  onChange: (patch: Partial<LlmProfile>) => void;
}) {
  return (
    <div className="role-editor">
      <h4>{title}</h4>
      <p className="muted small">{hint}</p>
      <label>
        <span>provider</span>
        <select
          value={profile.provider}
          onChange={(event) => onChange({ provider: event.target.value })}
        >
          {providers.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>model（留空 = 用端点默认）</span>
        <input
          value={profile.model}
          placeholder="deepseek-chat"
          onChange={(event) => onChange({ model: event.target.value })}
        />
      </label>
      <div className="field-row">
        <label>
          <span>temperature</span>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={profile.temperature}
            onChange={(event) =>
              onChange({ temperature: Number(event.target.value) })
            }
          />
        </label>
        <label>
          <span>max_tokens（0 = 不限制）</span>
          <input
            type="number"
            min="0"
            step="64"
            value={profile.max_tokens}
            onChange={(event) =>
              onChange({ max_tokens: Number(event.target.value) })
            }
          />
        </label>
      </div>
    </div>
  );
}



export default function SettingsDrawer({
  open,
  onClose,
  onChanged,
  status,
  last,
  theme,
  onThemeChange,
  debug,
  onDebugChange,
}: Props) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [roles, setRoles] = useState<LlmRoles | null>(null);
  const [presetId, setPresetId] = useState<string>(CUSTOM);
  const [drafts, setDrafts] = useState<Record<string, ProviderDraft>>({});
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<Message>(null);
  const importRef = useRef<HTMLInputElement | null>(null);
  // 「读取可用模型」：每个页签各自缓存结果，切回来不用重读
  const [probed, setProbed] = useState<Record<string, RemoteModelList>>({});
  const [probeBusy, setProbeBusy] = useState(false);

  const catalog = settings?.catalog ?? null;
  const draft = drafts[presetId] ?? draftFor(catalog, presetId, null);
  const preset = presetById(catalog, presetId);
  const matchedModel = preset?.models.find((item) => item.id === draft.model);
  const availableEfforts = useMemo(() => {
    if (!catalog) return [];
    if (matchedModel) return matchedModel.efforts;
    if (presetId === CUSTOM || !preset) {
      return catalog.efforts.map((item) => item.id).filter(Boolean);
    }
    return [];
  }, [catalog, matchedModel, preset, presetId]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setMessage(null);
    getSettings()
      .then((data) => {
        if (!alive) return;
        setSettings(data);
        setRoles(structuredClone(data.roles));
        const activeName = data.active_provider;
        const saved = data.providers[activeName] ?? null;
        const known = data.catalog.presets.some((item) => item.id === saved?.preset);
        // 已保存过的供应商 → 回到那一家；历史端点（无 preset）→ 自定义页签；
        // 全新/脚本假模型 → 默认推荐第一家（DeepSeek），Key 留空即可先看模型。
        const initialPreset = known && saved?.preset
          ? saved.preset
          : saved
            ? CUSTOM
            : data.catalog.default_preset;
        const initialDraft = draftFor(data.catalog, initialPreset, saved);
        setPresetId(initialPreset);
        setDrafts({ [initialPreset]: initialDraft });
      })
      .catch((err) => setMessage({ ok: false, text: String(err) }));
    return () => {
      alive = false;
    };
  }, [open]);

  if (!open) return null;

  const providerNames = [
    "scripted",
    ...Array.from(
      new Set([
        ...Object.keys(settings?.providers ?? {}),
        ...(catalog?.presets.map((item) => item.id) ?? []),
      ]),
    ),
  ];

  const patchDraft = (patch: Partial<ProviderDraft>) => {
    setDrafts((prev) => ({
      ...prev,
      [presetId]: { ...(prev[presetId] ?? draft), ...patch },
    }));
  };

  const selectPreset = (nextId: string) => {
    setPresetId(nextId);
    setDrafts((prev) => {
      if (prev[nextId]) return prev;
      const saved = settings?.providers[nextId] ?? null;
      return { ...prev, [nextId]: draftFor(catalog, nextId, saved) };
    });
  };

  const pickModel = (modelId: string) => {
    const nextPreset = presetById(catalog, presetId);
    const nextModel = nextPreset?.models.find((item) => item.id === modelId);
    const efforts = nextModel?.efforts ?? [];
    patchDraft({
      model: modelId,
      // 新模型不支持当前思考强度时自动回到「自动」
      reasoning_effort:
        draft.reasoning_effort && !efforts.includes(draft.reasoning_effort)
          ? ""
          : draft.reasoning_effort,
    });
  };

  /** 用当前页签的端点/Key 请求 `GET {base_url}/models`，把真实模型列进下拉。 */
  const probeModelList = async () => {
    setProbeBusy(true);
    setMessage(null);
    try {
      const result = await probeModels({
        preset: presetId,
        base_url: draft.base_url,
        api_key: draft.api_key,
        timeout: 12,
      });
      setProbed((prev) => ({ ...prev, [presetId]: result }));
      setMessage({
        ok: true,
        text: `读取到 ${result.count} 个可用模型（${result.latency_ms} ms），在下面的下拉里选一个。`,
      });
    } catch (err) {
      setMessage({ ok: false, text: String(err) });
    } finally {
      setProbeBusy(false);
    }
  };

  const patchRole = (role: "narrator" | "settler", patch: Partial<LlmProfile>) => {
    setRoles((prev) =>
      prev ? { ...prev, [role]: { ...prev[role], ...patch } } : prev,
    );
  };

  /** 当前选择 → 提交给后端的部分更新。 */
  const payload = (): SettingsUpdate => {
    const baseRoles = roles ? structuredClone(roles) : null;
    if (baseRoles) {
      baseRoles.narrator = { ...baseRoles.narrator, provider: presetId, model: "" };
      if (!baseRoles.separated) {
        baseRoles.settler = { ...baseRoles.settler, provider: presetId, model: "" };
      }
    }
    return {
      roles: baseRoles ?? undefined,
      providers: {
        [presetId]: {
          preset: presetId,
          base_url: draft.base_url.trim(),
          model: draft.model.trim(),
          reasoning_effort: draft.reasoning_effort,
          timeout: Number(draft.timeout) || 60,
          price_in: Number(draft.price_in) || 0,
          price_out: Number(draft.price_out) || 0,
          max_retries: Number(draft.max_retries) || 0,
          retry_backoff_ms: Number(draft.retry_backoff_ms) || 0,
          // 留空 = 后端沿用已保存的 key
          ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
        },
      },
    };
  };

  const reloadFrom = (data: SettingsView) => {
    setSettings(data);
    setRoles(structuredClone(data.roles));
    setDrafts((prev) => ({
      ...prev,
      [presetId]: { ...(prev[presetId] ?? draft), api_key: "" },
    }));
  };

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const data = await postSettings(payload());
      reloadFrom(data);
      setMessage({ ok: true, text: "已保存并应用，下一回合生效。" });
      await onChanged();
    } catch (err) {
      setMessage({ ok: false, text: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async () => {
    setBusy(true);
    setMessage({ ok: true, text: "正在请求模型……" });
    try {
      const result = await testSettings(payload());
      setMessage(
        result.ok
          ? {
              ok: true,
              text: `连接成功：${result.provider} / ${result.model}（${result.latency_ms}ms）`,
            }
          : { ok: false, text: `连接失败：${result.error ?? "未知错误"}` },
      );
    } catch (err) {
      setMessage({ ok: false, text: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleRestore = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const data = await resetSettings();
      setSettings(data);
      setRoles(structuredClone(data.roles));
      setPresetId(data.catalog.default_preset);
      setDrafts({
        [data.catalog.default_preset]: draftFor(
          data.catalog,
          data.catalog.default_preset,
          null,
        ),
      });
      setMessage({ ok: true, text: "已恢复默认（脚本假模型）。" });
      await onChanged();
    } catch (err) {
      setMessage({ ok: false, text: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const pickWallpaper = (id: ThemeSettings["wallpaper"]) => {
    onThemeChange({ ...theme, wallpaper: id, custom: null });
  };

  const uploadWallpaper = (file: File | undefined) => {
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) {
      setMessage({ ok: false, text: "图片超过 3 MB，请先压缩（壁纸存在浏览器本地）。" });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        onThemeChange({ ...theme, custom: reader.result, wallpaper: "none" });
        setMessage({ ok: true, text: "壁纸已应用（仅保存在本机浏览器）。" });
      }
    };
    reader.readAsDataURL(file);
  };

  const uploadPack = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) {
      setImportMessage({ ok: false, text: "请选择 .zip 内容包" });
      return;
    }
    setImporting(true);
    setImportMessage({ ok: true, text: `正在导入 ${file.name}…` });
    try {
      const result = await importPack(file);
      const title = result.pack?.title || result.pack?.id || "内容包";
      setImportMessage({
        ok: true,
        text: `已导入「${title}」，到「游戏库」里点选它就能开玩。`,
      });
    } catch (error) {
      setImportMessage({ ok: false, text: (error as Error).message.slice(0, 300) });
    } finally {
      setImporting(false);
      if (importRef.current) importRef.current.value = "";
    }
  };

  const effortHint = (() => {
    if (!availableEfforts.length) return "该模型不支持思考强度，将使用模型默认行为。";
    return "推理模型越「高」越慢、越贵，但结算更稳。";
  })();

  return (
    <div className="drawer-mask" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <h2>设置</h2>
          <button className="ghost small" onClick={onClose}>
            关闭
          </button>
        </header>

        {!roles || !settings || !catalog ? (
          <p className="muted">正在读取设置……</p>
        ) : (
          <div className="drawer-body">
            <section className="settings-section">
              <h3>模型</h3>
              <p className="muted small">
                选供应商 → 填 API Key → 选模型。叙事与后端始终独立请求，后端不带历史对话；默认复用所选模型。
                每个供应商的 Key 各自保存，切换回来不用重填。
              </p>

              <div className="provider-tabs">
                {catalog.presets.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`provider-tab${presetId === item.id ? " on" : ""}`}
                    onClick={() => selectPreset(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              {preset?.note && <p className="muted small">{preset.note}</p>}

              <label>
                <span>
                  API Key{" "}
                  {settings.providers[presetId]?.has_key
                    ? `（已保存 ${settings.providers[presetId].key_hint}，留空不修改）`
                    : "（只存后端，不上传）"}
                </span>
                <input
                  type="password"
                  value={draft.api_key}
                  placeholder={preset?.key_hint || "sk-..."}
                  onChange={(event) => patchDraft({ api_key: event.target.value })}
                />
              </label>

              <label>
                <span>模型</span>
                <div className="probe-row">
                  <input
                    list={`model-options-${presetId}`}
                    value={draft.model}
                    placeholder="deepseek-chat"
                    onChange={(event) => pickModel(event.target.value)}
                  />
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => void probeModelList()}
                    disabled={probeBusy}
                    title="用上面的 API Key 请求端点，读取真实可用模型"
                  >
                    {probeBusy ? "读取中…" : "读取可用模型"}
                  </button>
                </div>
                <datalist id={`model-options-${presetId}`}>
                  {(preset?.models ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                  {(probed[presetId]?.models ?? [])
                    .filter(
                      (item) => !preset?.models.some((known) => known.id === item.id),
                    )
                    .map((item) => (
                      <option key={`remote-${item.id}`} value={item.id}>
                        {item.owned_by ? `${item.id}（${item.owned_by}）` : item.id}
                      </option>
                    ))}
                </datalist>
              </label>
              {(probed[presetId]?.models.length ?? 0) > 0 && (
                <label>
                  <span>
                    端点可用模型（{probed[presetId].count} 个 · 来自 {probed[presetId].base_url}）
                  </span>
                  <select
                    value={
                      probed[presetId].models.some((item) => item.id === draft.model)
                        ? draft.model
                        : ""
                    }
                    onChange={(event) => pickModel(event.target.value)}
                  >
                    <option value="">（保持手填：{draft.model || "未填"}）</option>
                    {probed[presetId].models.map((item) => (
                      <option key={`pick-${item.id}`} value={item.id}>
                        {item.id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {matchedModel?.note && <p className="muted small">{matchedModel.note}</p>}
              {!matchedModel && presetId !== CUSTOM && (
                <p className="muted small">
                  手填模型名也能用；不确定就点上面的下拉建议。
                </p>
              )}

              <label>
                <span>思考强度（reasoning_effort）</span>
                <select
                  value={draft.reasoning_effort}
                  disabled={!availableEfforts.length}
                  onChange={(event) =>
                    patchDraft({ reasoning_effort: event.target.value })
                  }
                >
                  {catalog.efforts
                    .filter(
                      (item) =>
                        !item.id || availableEfforts.includes(item.id),
                    )
                    .map((item) => (
                      <option key={item.id || "auto"} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                </select>
              </label>
              <p className="muted small">{effortHint}</p>

              {preset?.docs_url && (
                <p className="muted small">
                  获取 Key：<a href={preset.docs_url} target="_blank" rel="noreferrer">{preset.docs_url}</a>
                </p>
              )}

              <details className="advanced-box">
                <summary>高级（端点 / 计价 / 超时 / 重试 / 多模型拆分）</summary>
                <label>
                  <span>base_url（OpenAI 兼容）</span>
                  <input
                    value={draft.base_url}
                    placeholder="https://api.deepseek.com/v1 或 http://127.0.0.1:11434/v1"
                    onChange={(event) => patchDraft({ base_url: event.target.value })}
                  />
                </label>
                <div className="field-row">
                  <label>
                    <span>timeout（秒）</span>
                    <input
                      type="number"
                      min="5"
                      value={draft.timeout}
                      onChange={(event) =>
                        patchDraft({ timeout: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label>
                    <span>max_retries（429/5xx 重试）</span>
                    <input
                      type="number"
                      min="0"
                      max="5"
                      value={draft.max_retries}
                      onChange={(event) =>
                        patchDraft({ max_retries: Number(event.target.value) })
                      }
                    />
                  </label>
                </div>
                <div className="field-row">
                  <label>
                    <span>price_in（$/1M tokens）</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.price_in}
                      onChange={(event) =>
                        patchDraft({ price_in: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label>
                    <span>price_out（$/1M tokens）</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.price_out}
                      onChange={(event) =>
                        patchDraft({ price_out: Number(event.target.value) })
                      }
                    />
                  </label>
                </div>
                <label>
                  <span>retry_backoff_ms（指数退避基数）</span>
                  <input
                    type="number"
                    min="0"
                    max="10000"
                    step="100"
                    value={draft.retry_backoff_ms}
                    onChange={(event) =>
                      patchDraft({ retry_backoff_ms: Number(event.target.value) })
                    }
                  />
                </label>

                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={roles.separated}
                    onChange={(event) =>
                      setRoles({ ...roles, separated: event.target.checked })
                    }
                  />
                  <span>后端使用独立模型（关闭时复用叙事模型连接，职责仍分离）</span>
                </label>

                <RoleEditor
                  title="叙事角色 narrator"
                  hint="正文边生成边显示；完成后结算。"
                  profile={roles.narrator}
                  providers={providerNames}
                  onChange={(patch) => patchRole("narrator", patch)}
                />
                <RoleEditor
                  title="结算角色 settler"
                  hint="每次完整叙述后统一结算所有状态，仅读取当前快照，不发送历史聊天。"
                  profile={roles.settler}
                  providers={providerNames}
                  onChange={(patch) => patchRole("settler", patch)}
                />
              </details>
            </section>

            {message && (
              <p className={`drawer-message ${message.ok ? "ok" : "bad"}`}>
                {message.text}
              </p>
            )}

            <div className="drawer-actions">
              <button className="primary" disabled={busy} onClick={() => void handleSave()}>
                保存并应用
              </button>
              <button className="ghost" disabled={busy} onClick={() => void handleTest()}>
                测试连接
              </button>
              <button className="ghost" disabled={busy} onClick={() => void handleRestore()}>
                恢复默认（脚本假模型）
              </button>
            </div>

            <section className="settings-section ui-theme-settings">
              <h3>外观 · 界面主题</h3>
              <p className="muted small">选择配色，立即预览。壁纸可以另外搭配。</p>
              <div className="ui-theme-grid" role="group" aria-label="界面主题">
                {UI_THEMES.map(item => <button type="button" key={item.id}
                  className={`ui-theme-card${theme.uiTheme === item.id ? " on" : ""}`}
                  aria-pressed={theme.uiTheme === item.id}
                  onClick={() => onThemeChange({ ...theme, uiTheme: item.id })}>
                  <span className="ui-theme-preview" style={{ background: `radial-gradient(ellipse at 90% 0%, ${item.colors[1]}44, transparent 75%), ${item.colors[0]}`, color: item.colors[1] }}>
                    <span className="ui-theme-orbit" style={{ borderColor: item.colors[2] }} />
                    <span className="ui-theme-preview-lines"><i /><i /><i /></span>
                    <span className="ui-theme-dot" style={{ background: item.colors[2] }} />
                  </span>
                  <strong>{item.label}</strong><small>{item.detail}</small>
                  {theme.uiTheme === item.id && <span className="ui-theme-check" aria-hidden="true">✓</span>}
                </button>)}
              </div>
            </section>

            <section className="settings-section">
              <h3>外观 · 壁纸</h3>
              <p className="muted small">
                壁纸与调试开关只保存在本机浏览器；内容包的界面布局不受影响。
              </p>
              <div className="wallpaper-grid">
                {WALLPAPERS.map((item) => {
                  const active = !theme.custom && theme.wallpaper === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`wallpaper-swatch${active ? " on" : ""}`}
                      onClick={() => pickWallpaper(item.id)}
                      title={item.label}
                    >
                      <span
                        className="wallpaper-preview"
                        style={item.css ? { backgroundImage: item.css } : undefined}
                      />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
                <button
                  type="button"
                  className={`wallpaper-swatch${theme.custom ? " on" : ""}`}
                  onClick={() => fileRef.current?.click()}
                  title="上传本地图片作为壁纸"
                >
                  <span
                    className="wallpaper-preview"
                    style={
                      theme.custom
                        ? { backgroundImage: `url("${theme.custom}")` }
                        : { background: "repeating-linear-gradient(45deg, #1a2230 0 6px, #141a24 6px 12px)" }
                    }
                  />
                  <span>上传图片</span>
                </button>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                style={{ display: "none" }}
                onChange={(event) => {
                  uploadWallpaper(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
              <div className="field-row">
                <label>
                  <span>压暗 {theme.dim.toFixed(2)}（保证文字可读）</span>
                  <input
                    type="range"
                    min="0"
                    max="0.85"
                    step="0.05"
                    value={theme.dim}
                    onChange={(event) =>
                      onThemeChange({ ...theme, dim: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  <span>模糊 {theme.blur}px</span>
                  <input
                    type="range"
                    min="0"
                    max="12"
                    step="1"
                    value={theme.blur}
                    onChange={(event) =>
                      onThemeChange({ ...theme, blur: Number(event.target.value) })
                    }
                  />
                </label>
              </div>
              {theme.custom && (
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => onThemeChange({ ...theme, custom: null, wallpaper: "none" })}
                >
                  清除自定义壁纸
                </button>
              )}
            </section>

            <section className="settings-section">
              <h3>外观 · 叙事滚动</h3>
              <p className="muted small">
                控制桌面叙述区滚动；手机使用独立的完整对话历史，始终可向上翻阅。设置存在本机浏览器。
              </p>
              <div className="scroll-styles">
                {SCROLL_STYLES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`scroll-style${theme.narrativeScroll === item.id ? " on" : ""}`}
                    title={item.hint}
                    onClick={() => onThemeChange({ ...theme, narrativeScroll: item.id })}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </section>

            <section className="settings-section">
              <h3>外观 · 字体大小</h3>
              <p className="muted small">
                调大叙述正文方便阅读；也可以选择整页文字一起变。设置存在本机浏览器。
              </p>
              <div className="scroll-styles">
                {FONT_TARGETS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`scroll-style${theme.fontTarget === item.id ? " on" : ""}`}
                    title={item.hint}
                    onClick={() => onThemeChange({ ...theme, fontTarget: item.id })}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <div className="field-row">
                <label>
                  <span>
                    字号 {theme.fontScale}%（{theme.fontTarget === "all" ? "整页" : "叙述正文"}）
                  </span>
                  <input
                    type="range"
                    min="50"
                    max="160"
                    step="5"
                    value={theme.fontScale}
                    onChange={(event) =>
                      onThemeChange({ ...theme, fontScale: Number(event.target.value) })
                    }
                  />
                </label>
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => onThemeChange({ ...theme, fontScale: 100 })}
                >
                  恢复 100%
                </button>
              </div>
              <p className="font-preview">
                预览：雨丝斜进来，落在手背上；你听见柜台后有人轻轻「嗯」了一声。
              </p>
            </section>

            <section className="settings-section">
              <h3>外观 · 立绘</h3>
              <p className="muted small">
                内容包带 ui/sprites.json 时，右栏会按当前状态合成一张分层立绘；
                没有立绘的包不受影响。
              </p>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={theme.showSprite}
                  onChange={(event) =>
                    onThemeChange({ ...theme, showSprite: event.target.checked })
                  }
                />
                <span>显示立绘</span>
              </label>
              <div className="field-row" style={{ gap: 8, alignItems: "center" }}>
                <span className="muted small">取景</span>
                {SPRITE_VIEW_LABELS.map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    className={`chip${theme.spriteView === mode ? " active" : ""}`}
                    onClick={() => onThemeChange({ ...theme, spriteView: mode })}
                    title={
                      mode.startsWith("closeup")
                        ? "DoL 原版的 64×64 特写画布，需要打开「成人向图层」"
                        : undefined
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={theme.spriteAnimated}
                  onChange={(event) =>
                    onThemeChange({ ...theme, spriteAnimated: event.target.checked })
                  }
                />
                <span>立绘呼吸动画（素材有 2 帧时播放）</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={theme.explicitLayers}
                  onChange={(event) =>
                    onThemeChange({ ...theme, explicitLayers: event.target.checked })
                  }
                />
                <span>显示成人向图层（默认关闭；只影响带 adult 标记的图层：内衣、涂鸦、生殖器遮罩等）</span>
              </label>
            </section>

            <SkillLibraryPanel onChanged={onChanged} />

            <section className="settings-section">
              <h3>内容包 · 导入 zip</h3>
              <p className="muted small">
                选一个含 manifest.json 的内容包 zip（手机端会从文件选择器读取），导入到用户游戏目录；
                不会覆盖同 id 的已有包，导入后到「游戏库」里切换。
              </p>
              <div className="field-row">
                <input
                  ref={importRef}
                  type="file"
                  accept=".zip,application/zip"
                  style={{ display: "none" }}
                  onChange={(event) => void uploadPack(event.target.files?.[0])}
                />
                <button
                  type="button"
                  className="ghost small"
                  disabled={importing}
                  onClick={() => importRef.current?.click()}
                >
                  {importing ? "导入中…" : "选择 zip 导入"}
                </button>
              </div>
              {importMessage && (
                <p className={`drawer-message ${importMessage.ok ? "ok" : "bad"}`}>
                  {importMessage.text}
                </p>
              )}
            </section>

            <section className="settings-section debug-section">
              <h3>调试</h3>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={debug}
                  onChange={(event) => onDebugChange(event.target.checked)}
                />
                <span>调试模式：显示全部调试参数（状态、场景、账本、回放、设置、用量）</span>
              </label>
              {debug && <DebugPanel status={status} last={last} settings={settings} theme={theme} />}
            </section>

            <p className="muted small">
              设置文件：{settings.settings_path}（api_key 只存后端，接口不回显明文）
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
