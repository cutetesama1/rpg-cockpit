import { useEffect, useState } from "react";
import { visibleViewport, type NativeViewport } from "./mobileViewport";
export const MOBILE_LAYOUT_QUERY = "(max-width: 1024px), (pointer: coarse)";
declare global { interface Window { __rpgNativeViewport?: NativeViewport } }

export function useMobileLayout(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const update = () => setMobile(media.matches);
    media.addEventListener("change", update); update();
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!mobile) return;
    document.body.dataset.mobileLayout = "true";
    let baseline = window.innerHeight;
    let pending: ReturnType<typeof setTimeout> | undefined;
    let previous: { height: number; top: number; open: boolean } | undefined;
    const keyboard = (navigator as Navigator & { virtualKeyboard?: EventTarget & { boundingRect: DOMRect } }).virtualKeyboard;
    const editing = () => document.activeElement instanceof HTMLElement && document.activeElement.matches('textarea,input:not([type=checkbox]):not([type=radio]),[contenteditable=true]');
    const commit = () => {
      pending = undefined;
      const viewport = visibleViewport({ innerHeight: window.innerHeight, innerWidth: window.innerWidth,
        visualHeight: window.visualViewport?.height, visualOffsetTop: window.visualViewport?.offsetTop,
        scale: window.visualViewport?.scale, native: window.__rpgNativeViewport,
        keyboardTop: keyboard?.boundingRect?.height ? keyboard.boundingRect.top : undefined });
      if (!editing() && !window.__rpgNativeViewport?.keyboardVisible) baseline = Math.max(baseline, viewport.height);
      const open = Boolean(window.__rpgNativeViewport?.keyboardVisible || editing() && baseline - viewport.height > 100);
      const geometryChanged = !previous || Math.abs(viewport.height - previous.height) > 2 || Math.abs(viewport.top - previous.top) > 2;
      if (geometryChanged) {
        document.documentElement.style.setProperty("--mobile-viewport-height", `${viewport.height}px`);
        document.documentElement.style.setProperty("--mobile-viewport-top", `${viewport.top}px`);
      }
      if (!previous || open !== previous.open) document.body.dataset.keyboardOpen = String(open);
      previous = { height: geometryChanged ? viewport.height : previous!.height, top: geometryChanged ? viewport.top : previous!.top, open };
      // No focus polling and no scrollIntoView: browser panning and native Insets
      // must never feed back into each other through layout and automatic scrolling.
      if (geometryChanged) window.dispatchEvent(new Event("rpg-viewport-resized"));
    };
    const queue = () => { clearTimeout(pending); pending = setTimeout(commit, 100); };
    const orientation = () => { baseline = 0; queue(); };
    commit();
    window.visualViewport?.addEventListener("resize", queue);
    window.visualViewport?.addEventListener("scroll", queue);
    window.addEventListener("resize", queue);
    window.addEventListener("rpg-native-viewport", queue);
    window.addEventListener("orientationchange", orientation);
    keyboard?.addEventListener("geometrychange", queue);
    document.addEventListener("focusin", queue);
    document.addEventListener("focusout", queue);
    return () => {
      clearTimeout(pending);
      delete document.body.dataset.mobileLayout; delete document.body.dataset.keyboardOpen;
      document.documentElement.style.removeProperty("--mobile-viewport-height");
      document.documentElement.style.removeProperty("--mobile-viewport-top");
      window.visualViewport?.removeEventListener("resize", queue);
      window.visualViewport?.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
      window.removeEventListener("rpg-native-viewport", queue);
      window.removeEventListener("orientationchange", orientation);
      keyboard?.removeEventListener("geometrychange", queue);
      document.removeEventListener("focusin", queue); document.removeEventListener("focusout", queue);
    };
  }, [mobile]);
  return mobile;
}
