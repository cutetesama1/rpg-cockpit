import DirectorPanel from "./DirectorPanel";
import ModelConnections from "./ModelConnections";
import SkillLibraryPanel from "./SkillLibraryPanel";
import { useEffect, useRef, useState } from "react";
import { getSettings, importPack } from "../api";
import DebugPanel from "./DebugPanel";
import { FONT_TARGETS, UI_THEMES, SCROLL_STYLES, WALLPAPERS, SPRITE_VIEW_LABELS, type SpriteView, type ThemeSettings } from "../theme";
import type { SettingsView, Status, TurnResult } from "../types";
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
export default function SettingsDrawer({ open, onClose, onChanged, status, last, theme, onThemeChange, debug, onDebugChange }: Props) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const importRef = useRef<HTMLInputElement | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<Message>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  useEffect(() => { if (open) void getSettings().then(setSettings).catch(() => {}); }, [open]);
  if (!open) return null;
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

  return (
    <div className="drawer-mask" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <h2>设置 <small className="muted">0.993</small></h2>
          <button className="ghost small" onClick={onClose}>
            关闭
          </button>
        </header>

        <div className="drawer-body">
            <ModelConnections onChanged={async () => { setSettings(await getSettings()); await onChanged(); }} packId={status?.pack.id} />
            {message && <p className={`drawer-message ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
            <DirectorPanel independentDirector={settings?.roles.director.provider.startsWith("role_")} key={status?.pack.id ?? "none"} status={status} onChanged={onChanged} />

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
                控制桌面对话历史的滚动；电脑和手机均保留你的输入与 AI 回复，可向上翻阅。设置存在本机浏览器。
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
              <h3>阅读 · 文字展示速度</h3>
              <p className="muted small">只影响收到文字后的显示节奏，不改变模型生成、网络请求或后端结算速度。桌面与手机通用。</p>
              <label><span>{theme.textSpeed === 0 ? "即时显示" : `${theme.textSpeed} 字符 / 秒`}</span><input aria-label="文字展示速度" type="range" min="0" max="200" step="5" value={theme.textSpeed} onChange={event => onThemeChange({...theme,textSpeed:Number(event.target.value)})}/></label>
              <button className="ghost small" type="button" onClick={() => onThemeChange({...theme,textSpeed:0})}>即时显示</button>
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
              设置文件：{settings?.settings_path || "正在读取"}（api_key 只存后端，接口不回显明文）
            </p>
          </div>
      </aside>
    </div>
  );
}
