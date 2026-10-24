import { useEffect, useRef, useState } from "react";
import { advanceCharacters, commonPrefixLength } from "./textPlayback";

export function useTextPlayback(text: string, key: string, speed: number) {
  const target = useRef({ text, key, speed });
  target.current = { text, key, speed };
  const [frame, setFrame] = useState({ key, text: "" });
  const current = useRef({ key, text: "", credit: 0, last: 0 });
  useEffect(() => {
    let raf = 0;
    const tick = (now: number) => {
      const next = target.current;
      const state = current.current;
      if (state.key !== next.key) Object.assign(state, { key: next.key, text: "", credit: 0, last: now });
      const prefix = commonPrefixLength(state.text, next.text);
      const characters = Array.from(next.text);
      const step = advanceCharacters(state.credit, state.last ? now - state.last : 0, next.speed, characters.length - prefix);
      const visible = characters.slice(0, prefix + step.count).join("");
      Object.assign(state, { text: visible, credit: step.credit, last: now });
      setFrame(prev => prev.key === next.key && prev.text === visible ? prev : { key: next.key, text: visible });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  const visible = speed === 0 ? text : frame.key === key ? frame.text : "";
  return { text: visible, playing: visible !== text, finish: () => {
    current.current = { key, text, credit: 0, last: performance.now() };
    setFrame({ key, text });
  }};
}
