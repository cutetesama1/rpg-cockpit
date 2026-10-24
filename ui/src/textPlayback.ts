/** Display pacing only; no transport, model or game-state timers. */
export function normalizeTextSpeed(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n <= 0 ? 0 : Math.max(5, Math.min(200, n)) : 60;
}
export function advanceCharacters(credit: number, elapsedMs: number, speed: number, remaining: number) {
  if (speed === 0) return { count: remaining, credit: 0 };
  const available = credit + Math.max(0, Math.min(250, elapsedMs)) * normalizeTextSpeed(speed) / 1000;
  const count = Math.min(remaining, Math.floor(available));
  return { count, credit: available - Math.floor(available) };
}
export function commonPrefixLength(left: string, right: string): number {
  const a = Array.from(left), b = Array.from(right);
  let count = 0;
  while (count < a.length && count < b.length && a[count] === b[count]) count++;
  return count;
}
