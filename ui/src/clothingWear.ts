/** Wear is drawn inside the garment's existing alpha: same coverage at every level. */
export const CLOTHING_CONDITION_LABELS: Record<string, string> = {
  intact: "完好", scuffed: "磨损", damaged: "破损", ruined: "严重破损",
};
export function clothingWearPixel(x: number, y: number, condition: unknown): number {
  const grade = condition === "scuffed" ? 1 : condition === "damaged" ? 2 : condition === "ruined" ? 3 : 0;
  if (!grade) return 0;
  const cx = x % 256;
  const seed = (Math.floor(cx / 16) * 7 + Math.floor(y / 18) * 11) % 5;
  if (seed >= grade) return 0;
  const u = cx % 16, v = y % 18;
  if (u >= 2 && u <= 3 + grade && v >= 4 && v <= 4 + grade) return 0.6;
  if (grade >= 2 && u >= 7 && u <= 12 && v === 10) return 0.75;
  if (grade >= 3 && u % 2 === 0 && u >= 7 && u <= 12 && v >= 9 && v <= 11) return 0.45;
  return 0;
}
