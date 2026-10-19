import { useEffect, useMemo, useRef, useState } from "react";
import { packAssetUrl } from "../api";
import { clothingWearPixel, CLOTHING_CONDITION_LABELS } from "../clothingWear";
import { spriteFrameOffset } from "../spriteGeometry";
import type { FieldDef, SpriteCondition, SpriteLayer, SpriteSheet } from "../types";

/**
 * 分层立绘：把内容包 ui/sprites.json 里的图层按 z 叠到一张 canvas 上。
 *
 * - 图层路径支持 `{字段}` 模板，用当前 state 替换；
 * - `when` / `unless` 用受限比较判断显隐（含 `in` 列表匹配）；
 * - `tint` / `tint_field` 给灰白素材上色（source-in 填充，缓存着色结果）；
 * - `adult` 图层只有打开「成人向图层」时才渲染；
 * - `mask` 用遮罩图的 alpha 裁切本层（DoL 的 soft-clip 那种）；
 * - `sheet.frames`/`fps`：素材每层横向排了 N 帧，按 fps 循环播放（呼吸动画）；
 * - `sheet.rules`：状态联动（例：hp 见底自动换 hurt 表情），只影响绘制不改状态；
 * - `sheet.poses`：姿势/特写（DoL 的 close 画布是 64×64、6 帧），可覆盖窗口与帧数；
 * - 图片按 URL 缓存，同一张图只解码一次，状态变化只重绘不重载。
 */

type Context = Record<string, unknown>;

const imageCache = new Map<string, HTMLImageElement | "loading" | "error">();
const imageFailures = new Map<string,number>();
const tintCache = new Map<string, HTMLCanvasElement>();

function resolveTemplate(template: string, ctx: Context): string {
  return template.replace(/\{(\w+)\}/g, (_m, key: string) => {
    const value = ctx[key];
    return value === undefined || value === null ? "" : String(value);
  });
}

function compare(actual: unknown, op: SpriteCondition["op"], expected: unknown): boolean {
  if (op === "==") return actual === expected;
  if (op === "!=") return actual !== expected;
  if (op === "in") {
    return Array.isArray(expected) ? expected.includes(actual as never) : false;
  }
  if (op === "not_in") {
    return Array.isArray(expected) ? !expected.includes(actual as never) : true;
  }
  // 数值比较：两边都能转成数字才比，否则不成立（配置错误当作不显示，别让画面炸掉）
  const a = typeof actual === "number" ? actual : Number(actual);
  const b = typeof expected === "number" ? expected : Number(expected);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  if (op === ">") return a > b;
  if (op === ">=") return a >= b;
  if (op === "<") return a < b;
  return a <= b;
}

function conditionsPass(list: SpriteCondition[] | undefined, ctx: Context): boolean {
  if (!list || list.length === 0) return true;
  return list.every((cond) => compare(ctx[cond.field], cond.op, cond.value));
}

function conditionsAny(list: SpriteCondition[], ctx: Context): boolean {
  return list.some((cond) => compare(ctx[cond.field], cond.op, cond.value));
}

function layerVisible(layer: SpriteLayer, ctx: Context, explicit: boolean): boolean {
  if (layer.adult && !explicit) return false;
  if (!conditionsPass(layer.when, ctx)) return false;
  if (layer.unless && layer.unless.length > 0 && conditionsAny(layer.unless, ctx)) {
    return false;
  }
  return true;
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  const cached = imageCache.get(src);
  if (cached && cached !== "loading" && cached !== "error") return Promise.resolve(cached);
  if (cached === "error" && Date.now()-(imageFailures.get(src)??0)<2000) return Promise.resolve(null);
  if (cached === "loading") {
    return new Promise((resolve) => {
      const started = Date.now();
      const poll = () => {
        const state = imageCache.get(src);
        if (state && state !== "loading") {
          resolve(state === "error" ? null : state);
        } else if (Date.now() - started > 15000) {
          resolve(null);
        } else {
          window.setTimeout(poll, 50);
        }
      };
      poll();
    });
  }
  imageCache.set(src, "loading");
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      imageCache.set(src, image);
      resolve(image);
    };
    image.onerror = () => {
      imageCache.set(src, "error");
      imageFailures.set(src,Date.now());
      resolve(null);
    };
    image.src = src;
  });
}

function colorized(image: HTMLImageElement, tint: string, detail = false): HTMLCanvasElement {
  const key = `${image.src}|${tint}|${detail}`;
  const cached = tintCache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.drawImage(image, 0, 0);
    // Garment outlines, shading and prints must survive colour changes.
    ctx.globalCompositeOperation = detail ? "multiply" : "source-in";
    ctx.fillStyle = tint;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (detail) {
      ctx.globalCompositeOperation = "destination-in";
      ctx.drawImage(image, 0, 0);
      ctx.globalCompositeOperation = "source-over";
    }
  }
  tintCache.set(key, canvas);
  return canvas;
}

function worn(image: HTMLImageElement, tint: string | null, detail: boolean, condition: unknown): HTMLImageElement | HTMLCanvasElement {
  const source = tint ? colorized(image, tint, detail) : image;
  if (typeof condition !== "string" || condition === "intact" || !CLOTHING_CONDITION_LABELS[condition]) return source;
  const key = `wear|${image.src}|${tint}|${detail}|${condition}`;
  const cached = tintCache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.drawImage(source, 0, 0);
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        const i = (y * canvas.width + x) * 4;
        if (!pixels.data[i + 3]) continue;
        const mix = clothingWearPixel(x, y, condition);
        for (let channel = 0; channel < 3; channel += 1) {
          pixels.data[i + channel] = Math.floor(pixels.data[i + channel] * (1 - mix) + [60, 52, 45][channel] * mix);
        }
      }
    }
    ctx.putImageData(pixels, 0, 0);
  }
  tintCache.set(key, canvas);
  return canvas;
}

function isValidColor(value: unknown): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{3,8}$/.test(value.trim());
}

interface Props {
  sheet: SpriteSheet;
  state: Record<string, unknown>;
  explicit: boolean;
  /**
   * 取景：`full` = 全身（默认）、`bust` = 半身；也可以填任意姿势名
   * （`closeup_chest` / `closeup_mouth` / `closeup_arse` 特写镜头）。
   */
  view?: string;
  /** 强制使用某个姿势（界面「取景」选了特写时传它，覆盖状态里的 pose） */
  forcedPose?: string;
  /** 是否播放逐帧动画（内容包 frames > 1 时生效） */
  animated?: boolean;
  /** 字段定义（用于把旧存档里已不在枚举内的值回退到第一个合法值） */
  fields?: FieldDef[];
}

export default function SpriteCanvas({
  sheet,
  state,
  explicit,
  view = "full",
  forcedPose,
  animated = true,
  fields,
}: Props) {
  // 画布按取样窗口的 2 倍整数分辨率合成（60×165 → 120×330）：
  // 整数倍最近邻不会插值出错，再由浏览器 CSS 放大到面板宽度。
  // 之前把 60×165 的窗口直接画进 256（3.1 倍非整数放大）会出条纹伪影。
  const RES = 2;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [assetsVersion, setAssetsVersion] = useState(0);

  // 状态联动：rules 按顺序覆盖字段，只用于绘制
  // 旧存档可能存着已下架的枚举值（比如换了内容包/主题），画的时候回退到第一个合法值，
  // 免得整层素材匹配不到、出现「光头 / 光身子」。
  const safeState = useMemo<Record<string, unknown>>(() => {
    if (!fields || fields.length === 0) return state;
    const next: Record<string, unknown> = { ...state };
    for (const field of fields) {
      const options = field.enum_values;
      const value = next[field.id];
      if (options && options.length > 0 && typeof value === "string" && !options.includes(value)) {
        next[field.id] = typeof field.default === "string" && options.includes(field.default)
          ? field.default : options[0];
      }
    }
    return next;
  }, [state, fields]);

  const context = useMemo<Context>(() => {
    const base: Context = { ...safeState, explicit };
    for (const rule of sheet.rules ?? []) {
      if (conditionsPass(rule.when, base)) {
        for (const [key, value] of Object.entries(rule.set ?? {})) base[key] = value;
      }
    }
    return base;
  }, [safeState, explicit, sheet.rules]);

  // 姿势：界面的「取景」优先，其次看状态里的 pose
  const poseName = useMemo(() => {
    if (forcedPose) return forcedPose;
    return typeof context.pose === "string" ? context.pose : "";
  }, [forcedPose, context.pose]);

  const pose = poseName && sheet.poses?.[poseName] ? sheet.poses[poseName] : null;

  const unavailable = Boolean(forcedPose && !pose && !sheet.views?.[view]);
  const layers = pose ? pose.layers : sheet.layers;
  // 取景优先于姿势窗口；特写姿势自带窗口
  const crop = useMemo(() => {
    if (unavailable) return sheet.crop ?? {x:0,y:0,w:0,h:0};
    if (view !== "full" && view !== "bust" && pose?.crop) return pose.crop;
    if (view !== "full" && sheet.views?.[view]) return sheet.views[view];
    return pose?.crop ?? sheet.crop ?? { x: 0, y: 0, w: 0, h: 0 };
  }, [view, sheet, pose, unavailable]);

  const width = Math.max(1, pose?.width ?? sheet.width);
  const height = Math.max(1, pose?.height ?? sheet.height);
  const frameWidth = Math.max(1, pose
    ? pose.frame_width ?? pose.width ?? sheet.frame_width ?? sheet.width
    : sheet.frame_width ?? sheet.width);
  const frames = Math.max(1, Math.floor(pose?.frames ?? sheet.frames ?? 1));
  const fps = Math.max(0.1, pose?.fps ?? sheet.fps ?? 2);

  const visible = useMemo(() => {
    return layers
      .filter((layer) => layerVisible(layer, context, explicit))
      .map((layer) => ({
        layer,
        src: packAssetUrl(resolveTemplate(layer.src, context),sheet.asset_key),
        mask: layer.mask ? packAssetUrl(resolveTemplate(layer.mask, context),sheet.asset_key) : null,
        tint: (isValidColor(layer.tint_field ? context[layer.tint_field] : layer.tint)
          ? (layer.tint_field ? context[layer.tint_field] : layer.tint)
          : layer.tint) as string | null,
      }))
      .filter((item) => !item.src.endsWith("/"))
      .sort((a, b) => a.layer.z - b.layer.z);
  }, [layers, context, explicit, sheet.asset_key]);

  // 只重绘用的数据：图片 + 遮罩图，加载完成后放进 ref 供动画帧复用
  const assetsRef = useRef<{
    items: { layer: SpriteLayer; image: HTMLImageElement; mask: HTMLImageElement | null; tint: string | null }[];
  }>({ items: [] });

  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const playing = animated && frames > 1 && !reduced;

  const drawFrame = (timeMs: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const cropW = crop.w > 0 ? crop.w : width;
    const cropH = crop.h > 0 ? crop.h : height;
    if (canvas.width !== cropW * RES || canvas.height !== cropH * RES) {
      canvas.width = cropW * RES;
      canvas.height = cropH * RES;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = false;
    const frame = playing ? Math.floor((timeMs / 1000) * fps) % frames : 0;
    (window as unknown as { __spriteFrame?: number }).__spriteFrame = frame;
    let drawn = 0;
    for (const item of assetsRef.current.items) {
      const image = item.image;
      if (!image || image.naturalWidth === 0) continue;
      // 只有「这张图确实有 N 帧」时才按帧偏移取图（单帧小图不能加偏移）
      const offset = spriteFrameOffset(image.naturalWidth, frameWidth, frames, frame);
      const source = worn(image, item.tint, ["outfit_color", "pants_color"].includes(item.layer.tint_field ?? ""), item.layer.wear_field ? context[item.layer.wear_field] : "intact");
      ctx.globalAlpha = item.layer.opacity ?? 1;
      ctx.globalCompositeOperation =
        item.layer.blend === "multiply" ? "multiply" : "source-over";
      if (item.mask) {
        // 遮罩：先把这层画到离屏画布，再用遮罩 alpha 裁一刀
        const off = document.createElement("canvas");
        off.width = cropW * RES;
        off.height = cropH * RES;
        const offCtx = off.getContext("2d");
        if (offCtx) {
          offCtx.imageSmoothingEnabled = false;
          offCtx.drawImage(
            source,
            crop.x + offset,
            crop.y,
            cropW,
            cropH,
            (item.layer.x ?? 0) * RES,
            (item.layer.y ?? 0) * RES,
            cropW * RES,
            cropH * RES,
          );
          const maskOffset = spriteFrameOffset(item.mask.naturalWidth, frameWidth, frames, frame);
          offCtx.globalCompositeOperation = "destination-in";
          offCtx.drawImage(
            item.mask,
            crop.x + maskOffset,
            crop.y,
            cropW,
            cropH,
            0,
            0,
            cropW * RES,
            cropH * RES,
          );
          offCtx.globalCompositeOperation = "source-over";
          ctx.drawImage(off, 0, 0);
        }
      } else {
        ctx.drawImage(
          source,
          crop.x + offset,
          crop.y,
          cropW,
          cropH,
          (item.layer.x ?? 0) * RES,
          (item.layer.y ?? 0) * RES,
          cropW * RES,
          cropH * RES,
        );
      }
      drawn += 1;
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    setReady(true);
    setFailed(drawn === 0);
  };

  // 载入所有图层（含遮罩），加载完再交给动画循环
  useEffect(() => {
    let alive = true;
    setReady(false);
    setFailed(false);
    void Promise.all(
      visible.map(async (item) => {
        const [image, mask] = await Promise.all([
          loadImage(item.src),
          item.mask ? loadImage(item.mask) : Promise.resolve(null),
        ]);
        return image ? { layer: item.layer, image, mask, tint: item.tint } : null;
      }),
    ).then((rows) => {
      if (!alive) return;
      assetsRef.current.items = rows.filter(
        (row): row is NonNullable<typeof row> => row !== null,
      );
      setAssetsVersion((v) => v + 1);
    });
    return () => {
      alive = false;
    };
  }, [visible]);

  // 绘制 + 逐帧动画：图片就绪后先画一帧，需要动画时按 fps 循环（帧号变化才重绘）
  useEffect(() => {
    if (assetsVersion === 0) return;
    let alive = true;
    const start = performance.now();
    let lastFrame = -1;
    const paint = (t: number) => {
      if (!alive) return;
      const frame = playing ? Math.floor((t / 1000) * fps) % frames : 0;
      if (frame !== lastFrame) {
        lastFrame = frame;
        drawFrame(t);
      }
    };
    paint(start);
    if (!playing) return () => { alive = false; };
    let raf = window.requestAnimationFrame(function loop(t) {
      if (!alive) return;
      paint(t);
      raf = window.requestAnimationFrame(loop);
    });
    return () => {
      alive = false;
      window.cancelAnimationFrame(raf);
    };
    // drawFrame 依赖 crop/frames/fps/width，都在下面的依赖里
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetsVersion, playing, frames, fps, crop, width, height, frameWidth]);

  return (
    <section className={`panel sprite-panel${ready ? " ready" : ""}`}>
      <h2>立绘</h2>
      <div className="clothing-condition-row" aria-label="衣物状态">
        {[...new Set(layers.map(layer => layer.wear_field).filter((field): field is string => Boolean(field)))].map(field => (
          <span className="muted small" key={field}>
            {fields?.find(item => item.id === field)?.label ?? "衣物"}：{CLOTHING_CONDITION_LABELS[String(context[field] ?? "intact")] ?? "完好"}
          </span>
        ))}
      </div>
      <div className="sprite-stage" style={{ maxHeight: `${sheet.max_height}px` }}>
        <canvas
          ref={canvasRef}
          className="sprite-canvas"
          width={(crop.w > 0 ? crop.w : width) * RES}
          height={(crop.h > 0 ? crop.h : height) * RES}
        />
        {!ready && !failed && <p className="muted small sprite-hint">正在载入立绘…</p>}
        {failed && <p className="muted small sprite-hint">这个内容包暂时没有可显示的图层</p>}
      </div>
    </section>
  );
}
