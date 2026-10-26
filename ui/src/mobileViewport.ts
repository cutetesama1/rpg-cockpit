export interface NativeViewport { widthPx: number; heightPx: number; keyboardVisible?: boolean }
export interface ViewportMetrics {
  innerHeight: number; innerWidth: number;
  visualHeight?: number; visualOffsetTop?: number; scale?: number;
  native?: NativeViewport; keyboardTop?: number;
}

/** Use the smallest observed visible area. Never subtract keyboard height twice. */
export function visibleViewport(metrics: ViewportMetrics): { height: number; top: number } {
  const valid = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0;
  const heights = [metrics.innerHeight].filter(valid);
  const top = Math.max(0, metrics.visualOffsetTop ?? 0);
  if ((metrics.scale ?? 1) <= 1.05 && valid(metrics.visualHeight)) heights.push(metrics.visualHeight);
  if (metrics.native && valid(metrics.native.widthPx) && valid(metrics.native.heightPx) && valid(metrics.innerWidth)) {
    heights.push(metrics.native.heightPx * metrics.innerWidth / metrics.native.widthPx);
  }
  if (valid(metrics.keyboardTop)) heights.push(Math.max(1, metrics.keyboardTop - top));
  return { height: Math.max(1, Math.round(Math.min(...(heights.length ? heights : [1])))), top: Math.round(top) };
}
