import { useEffect, useState } from "react";
export const MOBILE_LAYOUT_QUERY = "(max-width: 1024px), (pointer: coarse)";
export function useMobileLayout(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const update = () => setMobile(media.matches);
    media.addEventListener("change", update);
    update();
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!mobile) return;
    document.body.dataset.mobileLayout = "true";
    const update = () => document.documentElement.style.setProperty("--mobile-viewport-height", `${window.visualViewport?.height ?? window.innerHeight}px`);
    update();
    window.visualViewport?.addEventListener("resize", update);
    window.addEventListener("resize", update);
    return () => {
      delete document.body.dataset.mobileLayout;
      document.documentElement.style.removeProperty("--mobile-viewport-height");
      window.visualViewport?.removeEventListener("resize", update);
      window.removeEventListener("resize", update);
    };
  }, [mobile]);
  return mobile;
}
