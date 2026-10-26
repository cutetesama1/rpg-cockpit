/** 外观：壁纸预设 / 自定义图片 / 压暗与模糊。只存在浏览器 localStorage。 */
export type WallpaperPreset = "observatory" | "none" | "night" | "dusk" | "paper" | "aurora";

/** 叙述区滚动方式：略长时出现滚动条 / 固定高度滚动区 / 跟整页一起滚。 */
export type ScrollStyle = "auto" | "always" | "page";

/** 字号调节目标：只放大/缩小叙事正文，或整页所有文字一起变。 */
export type FontTarget = "narrative" | "all";

export const FONT_TARGETS: { id: FontTarget; label: string; hint: string }[] = [
  { id: "narrative", label: "只调叙述", hint: "只改叙述正文的字号，界面按钮/状态栏保持原样" },
  { id: "all", label: "整页字体", hint: "叙述、按钮、状态栏、小票全部一起放大或缩小" },
];

export const SCROLL_STYLES: { id: ScrollStyle; label: string; hint: string }[] = [
  { id: "auto", label: "略长时滚动", hint: "叙述超过区域高度才出现滚动条，并自动跟到最新一段" },
  { id: "always", label: "停留当前位置", hint: "生成回复时保持当前阅读位置，点击“回到最新”追上新内容" },
  { id: "page", label: "连续阅读", hint: "在连续时间线中阅读；上翻历史时暂停跟随，回到底部继续跟随" },
];

export const UI_THEMES = [
  { id: "cockpit", label: "轻量驾驶舱", detail: "雾蓝 · 石墨灰", colors: ["#171c24", "#91b2cc", "#e0e8ed"] },
  { id: "jade", label: "翠金星穹", detail: "深翠 · 香槟金", colors: ["#0b171b", "#82c9ae", "#d2bd89"] },
  { id: "lunar", label: "月海银蓝", detail: "午夜蓝 · 月光银", colors: ["#0c1528", "#92bded", "#c5d5ee"] },
  { id: "amethyst", label: "紫晶秘仪", detail: "墨紫 · 浅玫瑰金", colors: ["#191225", "#c3a2eb", "#e1bfca"] },
  { id: "ember", label: "曜石赤铜", detail: "曜石黑 · 暖铜", colors: ["#1c1412", "#eba47e", "#d5b384"] },
] as const;
export type UiThemeId = (typeof UI_THEMES)[number]["id"];

export function normalizeUiTheme(value: unknown): UiThemeId {
  return UI_THEMES.some(item => item.id === value) ? value as UiThemeId : "cockpit";
}

export interface ThemeSettings {
  uiTheme: UiThemeId;
  wallpaper: WallpaperPreset;
  /** 自定义壁纸（data URL）；设置后优先于预设 */
  custom: string | null;
  /** 0..0.85，越大越暗，保证文字可读 */
  dim: number;
  /** 0..12px，模糊背景 */
  blur: number;
  /** 叙述区滚动方式 */
  narrativeScroll: ScrollStyle;
  /** 字号调节目标：只调叙事正文 / 整页 */
  fontTarget: FontTarget;
  /** 字号百分比，50..160（100 = 默认） */
  fontScale: number;
  /** Characters per second; 0 displays received text immediately. */
  textSpeed: number;
  /** 是否显示分层立绘 */
  showSprite: boolean;
  /** 是否渲染成人向立绘图层（默认关闭） */
  explicitLayers: boolean;
  /** 立绘取景：全身 / 半身特写 */
  spriteView: SpriteView;
  /** 立绘逐帧动画（呼吸）是否播放 */
  spriteAnimated: boolean;
}

export const DEFAULT_THEME: ThemeSettings = {
  uiTheme: "cockpit",
  wallpaper: "none",
  custom: null,
  dim: 0.25,
  blur: 0,
  narrativeScroll: "auto",
  fontTarget: "narrative",
  fontScale: 100,
  textSpeed: 60,
  showSprite: true,
  explicitLayers: false,
  spriteView: "full",
  spriteAnimated: true,
};

export const WALLPAPERS: {
  id: WallpaperPreset;
  label: string;
  css: string;
}[] = [
  { id: "observatory", label: "星穹庭院", css: 'url("/art/ui-v1/night-background.png")' },
  { id: "none", label: "纯深色", css: "" },
  {
    id: "night",
    label: "夜空",
    css:
      "radial-gradient(900px 600px at 15% 0%, rgba(84,120,214,0.6), transparent 60%)," +
      "radial-gradient(700px 500px at 85% 20%, rgba(38,62,120,0.55), transparent 65%)," +
      "linear-gradient(160deg, #05070d 0%, #0a1020 55%, #05070d 100%)",
  },
  {
    id: "dusk",
    label: "黄昏",
    css:
      "radial-gradient(900px 600px at 80% 10%, rgba(239,128,72,0.55), transparent 62%)," +
      "radial-gradient(700px 500px at 10% 90%, rgba(122,58,148,0.5), transparent 65%)," +
      "linear-gradient(170deg, #0b0710 0%, #251223 55%, #08060c 100%)",
  },
  {
    id: "aurora",
    label: "极光",
    css:
      "radial-gradient(800px 500px at 25% 20%, rgba(46,196,160,0.45), transparent 62%)," +
      "radial-gradient(700px 500px at 75% 75%, rgba(64,124,220,0.45), transparent 65%)," +
      "linear-gradient(180deg, #03080a 0%, #071418 60%, #03080a 100%)",
  },
  {
    id: "paper",
    label: "纸纹",
    css:
      "repeating-linear-gradient(0deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 4px)," +
      "repeating-linear-gradient(90deg, rgba(0,0,0,0.18) 0 1px, transparent 1px 5px)," +
      "radial-gradient(1200px 800px at 20% 10%, #2a241c, #15110c 70%)",
  },
];

const STORAGE_KEY = "rpg-theme";
const DEBUG_KEY = "rpg-debug";

/** 开发/验收用：URL 参数临时覆盖取景（?spriteView=bust），不改本地设置 */
export const SPRITE_VIEW_LABELS = [
  ["full", "全身"], ["bust", "半身"], ["closeup_face", "特写·面部"],
  ["closeup_mouth", "特写·嘴部"], ["closeup_upper", "特写·上半身"],
  ["closeup_chest", "特写·胸"],
] as const;
const SPRITE_VIEWS = [...SPRITE_VIEW_LABELS.map(([view]) => view), "closeup_arse"] as const;
export type SpriteView = (typeof SPRITE_VIEWS)[number];

function normalizeSpriteView(value: unknown): SpriteView {
  return typeof value === "string" && (SPRITE_VIEWS as readonly string[]).includes(value)
    ? (value as SpriteView)
    : "full";
}

function spriteViewOverride(): SpriteView | null {
  try {
    const value = new URLSearchParams(window.location.search).get("spriteView");
    return typeof value === "string" && (SPRITE_VIEWS as readonly string[]).includes(value)
      ? (value as SpriteView)
      : null;
  } catch {
    return null;
  }
}

export function loadTheme(): ThemeSettings {
  const theme = loadStoredTheme();
  const override = spriteViewOverride();
  let result = override ? { ...theme, spriteView: override } : theme;
  // 开发/验收用：?explicit=1 临时打开成人向图层（不改本地设置）
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.has("explicit")) {
      result = { ...result, explicitLayers: params.get("explicit") !== "0" };
    }
  } catch {
    // 没有 window 的环境（测试）直接忽略
  }
  return result;
}

function loadStoredTheme(): ThemeSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_THEME };
    const parsed = JSON.parse(raw) as Partial<ThemeSettings>;
    return {
      uiTheme: normalizeUiTheme(parsed.uiTheme),
      wallpaper: (parsed.wallpaper as WallpaperPreset) ?? DEFAULT_THEME.wallpaper,
      custom: typeof parsed.custom === "string" ? parsed.custom : null,
      dim: clamp(Number(parsed.dim ?? DEFAULT_THEME.dim), 0, 0.85),
      blur: clamp(Number(parsed.blur ?? DEFAULT_THEME.blur), 0, 12),
      narrativeScroll:
        parsed.narrativeScroll === "always" || parsed.narrativeScroll === "page"
          ? parsed.narrativeScroll
          : "auto",
      fontTarget: parsed.fontTarget === "all" ? "all" : "narrative",
      fontScale: clamp(Number(parsed.fontScale ?? DEFAULT_THEME.fontScale), 50, 160),
      textSpeed: Number(parsed.textSpeed) === 0 ? 0 : clamp(Number(parsed.textSpeed ?? DEFAULT_THEME.textSpeed), 5, 200),
      showSprite: parsed.showSprite !== false,
      explicitLayers: parsed.explicitLayers === true,
      spriteView: normalizeSpriteView(parsed.spriteView),
      spriteAnimated: parsed.spriteAnimated !== false,
    };
  } catch {
    return { ...DEFAULT_THEME };
  }
}

export function saveTheme(theme: ThemeSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(theme));
  } catch {
    // 自定义图片过大或隐私模式：忽略持久化失败，不阻塞使用
  }
}

export function loadDebug(): boolean {
  try {
    return localStorage.getItem(DEBUG_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveDebug(on: boolean): void {
  try {
    localStorage.setItem(DEBUG_KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function wallpaperCss(theme: ThemeSettings): string {
  if (theme.custom) return `url("${theme.custom}")`;
  const preset = WALLPAPERS.find((item) => item.id === theme.wallpaper);
  return preset?.css ?? "";
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}
