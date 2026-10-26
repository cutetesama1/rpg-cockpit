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
    let timer: ReturnType<typeof setTimeout> | undefined;
    let settlingUntil = 0;
    let previous = "";
    const keyboard = (navigator as Navigator & { virtualKeyboard?: EventTarget & { boundingRect: DOMRect } }).virtualKeyboard;
    const editing = () => document.activeElement instanceof HTMLElement && document.activeElement.matches('textarea,input:not([type=checkbox]):not([type=radio]),[contenteditable=true]');
    const update = () => {
      const viewport = visibleViewport({ innerHeight: window.innerHeight, innerWidth: window.innerWidth,
        visualHeight: window.visualViewport?.height, visualOffsetTop: window.visualViewport?.offsetTop,
        scale: window.visualViewport?.scale, native: window.__rpgNativeViewport,
        keyboardTop: keyboard?.boundingRect?.height ? keyboard.boundingRect.top : undefined });
      if (!editing() && !window.__rpgNativeViewport?.keyboardVisible) baseline = Math.max(baseline, viewport.height);
      const open = Boolean(window.__rpgNativeViewport?.keyboardVisible || editing() && baseline - viewport.height > 100);
      const signature = `${viewport.height}:${viewport.top}:${open}`;
      if (signature !== previous) {
        previous = signature;
        document.documentElement.style.setProperty("--mobile-viewport-height", `${viewport.height}px`);
        document.documentElement.style.setProperty("--mobile-viewport-top", `${viewport.top}px`);
        document.body.dataset.keyboardOpen = String(open);
        window.dispatchEvent(new Event("rpg-viewport-resized"));
        if (editing()) requestAnimationFrame(() => {
          const element = document.activeElement as HTMLElement | null;
          const rect = element?.getBoundingClientRect();
          if (element && rect && (rect.bottom > viewport.top + viewport.height || rect.top < viewport.top)) element.scrollIntoView({ block: "nearest" });
        });
      }
    };
    const poll = () => {
      update();
      if (editing() || Date.now() < settlingUntil) timer = setTimeout(poll, 120);
      else timer = undefined;
    };
    const focus = () => { settlingUntil = Date.now() + 1000; if (!timer) poll(); };
    const orientation = () => { baseline = 0; focus(); };
    update();
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    window.addEventListener("rpg-native-viewport", update);
    window.addEventListener("orientationchange", orientation);
    keyboard?.addEventListener("geometrychange", update);
    document.addEventListener("focusin", focus);
    document.addEventListener("focusout", focus);
    return () => {
      clearTimeout(timer);
      delete document.body.dataset.mobileLayout; delete document.body.dataset.keyboardOpen;
      document.documentElement.style.removeProperty("--mobile-viewport-height");
      document.documentElement.style.removeProperty("--mobile-viewport-top");
      window.visualViewport?.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("rpg-native-viewport", update);
      window.removeEventListener("orientationchange", orientation);
      keyboard?.removeEventListener("geometrychange", update);
      document.removeEventListener("focusin", focus); document.removeEventListener("focusout", focus);
    };
  }, [mobile]);
  return mobile;
}
