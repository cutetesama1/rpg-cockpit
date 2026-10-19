export interface PortraitMotion {
  x: number; y: number; angle: number; scaleX: number; scaleY: number;
}

/** Procedural presentation, distinct from a pack's original frame atlas. */
export function portraitMotion(kind: string, seconds: number): PortraitMotion {
  const phase = seconds * Math.PI * 2;
  const out = { x: 0, y: 0, angle: 0, scaleX: 1, scaleY: 1 };
  if (kind === "sway") { out.angle = Math.sin(phase * .45) * .012; }
  if (kind === "walk") { out.y = -Math.abs(Math.sin(phase * 1.7)) * 2; out.angle = Math.sin(phase * 1.7) * .018; }
  if (kind === "run") { out.y = -Math.abs(Math.sin(phase * 2.7)) * 4; out.angle = .045 + Math.sin(phase * 2.7) * .02; }
  if (kind === "jump") { out.y = -Math.max(0, Math.sin(phase * .65)) * 12; }
  if (kind === "attack") { const hit = Math.max(0, Math.sin(phase * .8)); out.x = hit * 5; out.angle = hit * .065; }
  if (kind === "cast") { out.y = -2 - Math.sin(phase * .65) * 2; }
  if (kind === "hurt") { out.x = Math.sin(phase * 7) * 1.8; out.angle = -.025; }
  return out;
}

export function portraitContext(state: Record<string, unknown>, seconds = 0, animate = false, preferences: Record<string,string> = {}, modes: Record<string,string[]> = {}) {
  const out = { ...state };
  const pose = String(state.pose ?? "stand");
  out.portrait_left_arm = state.left_arm && state.left_arm !== "auto" ? state.left_arm : pose === "guard" ? "cover" : "idle";
  out.portrait_right_arm = state.right_arm && state.right_arm !== "auto" ? state.right_arm : pose === "guard" ? "cover" : (["hold", "attack", "cast"].includes(pose) || Boolean(state.handheld && state.handheld !== "none")) ? "hold" : "idle";
  const held = String(state.handheld ?? "none");
  if ((!state.right_arm || state.right_arm === "auto") && held !== "none" && modes[held]?.length) {
    if (!["guard", "attack", "cast"].includes(pose) || !modes[held].includes(String(out.portrait_right_arm))) out.portrait_right_arm = preferences[held] ?? "hold";
  }
  out.portrait_mouth = state.mouth_shape ?? "auto";
  if (state.mouth_shape === "auto" && pose === "talk") out.portrait_mouth = animate && Math.floor(seconds * 4) % 2 ? "neutral" : "chew";
  return out;
}

export function paintPortraitEffect(ctx: CanvasRenderingContext2D, kind: string, seconds: number, width: number, height: number) {
  if (!["cast", "attack", "hurt"].includes(kind)) return;
  ctx.save(); ctx.lineWidth = 2; ctx.globalAlpha = .65;
  if (kind === "cast") {
    ctx.strokeStyle = "#93d8ba";
    ctx.beginPath(); ctx.ellipse(width * .51, height * .92, width * .24, height * .025, 0, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = "#e4d7ad";
    for (let i = 0; i < 7; i++) { const a = seconds * 1.3 + i * 2.399; const r = width * .21; ctx.fillRect(width * .51 + Math.cos(a) * r, height * .48 + Math.sin(a) * height * .22, 3, 3); }
  } else if (kind === "attack") {
    ctx.strokeStyle = "#eddbad"; ctx.globalAlpha = Math.max(0, Math.sin(seconds * 5));
    ctx.beginPath(); ctx.ellipse(width * .60, height * .52, width * .30, height * .25, -.4, -.9, 1.5); ctx.stroke();
  } else {
    ctx.fillStyle = "#e5b984";
    for (let i = 0; i < 3; i++) ctx.fillRect(width * (.38 + i * .09), height * .20 - Math.sin(seconds * 4 + i) * 4, 3, 3);
  }
  ctx.restore();
}
