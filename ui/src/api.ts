import type { DirectorConfig, DirectorView, PlotClue, CheckResult } from "./types";
import { consumeEventStream } from "./sse";
import type {
  Action,
  BuilderApplyResult,
  BuilderDraft,
  BuilderGenerateResult,
  BuilderParseResult,
  BuilderPromptView,
  DebugCatalog,
  EventRecord,
  LibraryView,
  OpeningResult,
  NarrativeUpdate,
  SettingsTestResult,
  SettingsUpdate,
  SaveCreateResult,
  SaveDeleteResult,
  SaveLoadResult,
  SavesView,
  SettingsView,
  RemoteModelList,
  Status,
  TurnResult,
  WorldSkill,
  WorldView,
  WorldbookEntry,
} from "./types";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // 非 JSON 错误体（代理/静态服务器）保留原文本
    }
    throw new Error(detail.slice(0, 400) || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

async function sendJson<T>(
  path: string,
  method: "POST" | "PUT",
  body: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<T>(response);
}

export async function getState(): Promise<Status> {
  return readJson<Status>(await fetch("/api/state"));
}

export async function postOpening(): Promise<OpeningResult> {
  return readJson<OpeningResult>(await fetch("/api/opening", { method: "POST" }));
}

export async function postAction(action: Action): Promise<TurnResult> {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return readJson<TurnResult>(response);
}

export interface StreamHandlers {
  onEvent?: (event: EventRecord) => void;
  onNarrative?: (update: NarrativeUpdate) => void;
}

async function gameStream<T>(path: string, body: unknown, handlers: StreamHandlers): Promise<T> {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let result: T | undefined;
  await consumeEventStream(response, (event, data) => {
    if (event === "event") handlers.onEvent?.(data as EventRecord);
    else if (event === "narrative") handlers.onNarrative?.(data as NarrativeUpdate);
    else if (event === "result") result = data as T;
    else if (event === "error") throw new Error((data as { error?: string }).error || "流式响应失败");
  });
  if (!result) throw new Error("流式响应没有返回最终结果，请检查连接");
  return result;
}

export function streamAction(action: Action, handlers: StreamHandlers = {}): Promise<TurnResult> {
  return gameStream<TurnResult>("/api/action/stream", { action, request_id: globalThis.crypto?.randomUUID?.() ?? `action-${Date.now()}-${Math.random()}` }, handlers);
}

export function streamOpening(handlers: StreamHandlers = {}): Promise<OpeningResult> {
  return gameStream<OpeningResult>("/api/opening/stream", {}, handlers);
}

export async function postUndo(): Promise<Record<string, unknown>> {
  return readJson<Record<string, unknown>>(
    await fetch("/api/undo", { method: "POST" }),
  );
}

export async function postReset(): Promise<Status> {
  return readJson<Status>(await fetch("/api/reset", { method: "POST" }));
}

export async function getVerify(): Promise<{
  equal: boolean;
  diff: Record<string, unknown>;
}> {
  return readJson<{ equal: boolean; diff: Record<string, unknown> }>(
    await fetch("/api/replay/verify"),
  );
}

// -- 模型设置 ---------------------------------------------------------------
export async function getSettings(): Promise<SettingsView> {
  return readJson<SettingsView>(await fetch("/api/settings"));
}

/** 用已填/已存的 Key 读取端点 `GET {base_url}/models` 的真实模型列表。 */
export async function probeModels(body: {
  base_url?: string;
  api_key?: string;
  preset?: string;
  provider?: string;
  timeout?: number;
}): Promise<RemoteModelList> {
  return readJson<RemoteModelList>(
    await fetch("/api/models/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function postSettings(
  update: SettingsUpdate,
): Promise<SettingsView> {
  return readJson<SettingsView>(
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  );
}

export async function resetSettings(): Promise<SettingsView> {
  return readJson<SettingsView>(
    await fetch("/api/settings/reset", { method: "POST" }),
  );
}

export async function testSettings(
  update: SettingsUpdate,
): Promise<SettingsTestResult> {
  return readJson<SettingsTestResult>(
    await fetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  );
}

// -- 游戏库 / 世界构筑 -------------------------------------------------------
export async function getLibrary(): Promise<LibraryView> {
  return readJson<LibraryView>(await fetch("/api/library"));
}

export async function newGame(
  title: string,
  id?: string,
): Promise<LibraryView> {
  return sendJson<LibraryView>("/api/library/new", "POST", { title, id });
}

export async function cloneGame(
  source: string,
  title?: string,
  id?: string,
): Promise<LibraryView> {
  return sendJson<LibraryView>("/api/library/clone", "POST", {
    source,
    title,
    id,
  });
}

export async function selectGame(id: string): Promise<LibraryView> {
  return sendJson<LibraryView>("/api/library/select", "POST", { id });
}

export async function getWorld(): Promise<WorldView> {
  return readJson<WorldView>(await fetch("/api/world"));
}

export async function saveWorldbook(
  entries: WorldbookEntry[],
): Promise<{ ok: boolean; warnings: string[]; world: WorldView }> {
  return sendJson("/api/world/worldbook", "PUT", { entries });
}

export async function saveSkills(
  skills: WorldSkill[],
): Promise<{ ok: boolean; warnings: string[]; world: WorldView }> {
  return sendJson("/api/world/skills", "PUT", { skills });
}

export async function savePrompts(
  prompts: Partial<WorldView["prompts"]>,
): Promise<{ ok: boolean; warnings: string[]; world: WorldView }> {
  return sendJson("/api/world/prompts", "PUT", prompts);
}

// -- 存档 / 读档 -------------------------------------------------------------
export async function getBuilderPrompt(): Promise<BuilderPromptView> {
  const response = await fetch("/api/world/builder/prompt");
  return readJson<BuilderPromptView>(response);
}

export async function generateWorldDraft(
  material: string,
  titleHint = "",
  extraRules = "",
): Promise<BuilderGenerateResult> {
  return sendJson<BuilderGenerateResult>("/api/world/builder/generate", "POST", {
    material,
    title_hint: titleHint,
    extra_rules: extraRules,
  });
}

export async function parseWorldDraft(text: string): Promise<BuilderParseResult> {
  return sendJson<BuilderParseResult>("/api/world/builder/parse", "POST", { text });
}

export async function applyWorldDraft(
  draft: BuilderDraft,
  title = "",
  id = "",
): Promise<BuilderApplyResult> {
  return sendJson<BuilderApplyResult>("/api/world/builder/apply", "POST", {
    draft,
    title,
    id: id || null,
  });
}

export async function getSaves(): Promise<SavesView> {
  return readJson<SavesView>(await fetch("/api/saves"));
}

export async function saveGame(
  slot: string,
  label: string,
): Promise<SaveCreateResult> {
  return sendJson<SaveCreateResult>("/api/saves", "POST", { slot, label });
}

export async function loadGame(slot: string): Promise<SaveLoadResult> {
  return sendJson<SaveLoadResult>("/api/saves/load", "POST", { slot });
}

export async function deleteSave(slot: string): Promise<SaveDeleteResult> {
  const response = await fetch(`/api/saves/${encodeURIComponent(slot)}`, {
    method: "DELETE",
  });
  return readJson<SaveDeleteResult>(response);
}

export function logExportUrl(): string {
  return "/api/log/export";
}

export interface PackImportResult {
  ok: boolean;
  pack?: { id: string; title: string; valid?: boolean };
  error?: string;
}

/** 把 zip 内容包读成 base64 上传（手机端文件选择器也走这里）。 */
export async function importPack(file: File): Promise<PackImportResult> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return sendJson<PackImportResult>("/api/library/import", "POST", {
    filename: file.name,
    data_base64: btoa(binary),
  });
}

// ---------------------------------------------------------------------------
// P7：立绘
// ---------------------------------------------------------------------------

export interface SpriteView {
  pack: string;
  sheet: import("./types").SpriteSheet | null;
}

export async function getSprite(): Promise<SpriteView> {
  return readJson<SpriteView>(await fetch("/api/sprite"));
}

/** 内容包内素材的 URL（后端 /api/pack/asset 只读当前包目录） */
export function packAssetUrl(path: string, assetKey = ""): string {
  const clean = path.replace(/^\/+/, "");
  return `/api/pack/asset/${clean.split("/").map(encodeURIComponent).join("/")}${assetKey ? `?v=${encodeURIComponent(assetKey)}` : ""}`;
}

// ---- 调试台 -----------------------------------------------------------
export async function getDebugCatalog(): Promise<DebugCatalog> {
  return readJson<DebugCatalog>(await fetch("/api/debug/catalog"));
}

export async function debugSetState(
  changes: Record<string, unknown>,
): Promise<{ ok: boolean; changed: number; status: Status }> {
  return sendJson("/api/debug/state", "POST", { changes });
}

export async function debugResetState(): Promise<{ ok: boolean; changed: number; status: Status }> {
  return sendJson("/api/debug/reset", "POST", {});
}

export async function debugSetInventory(
  itemId: string,
  count: number,
): Promise<{ ok: boolean; changed: number; status: Status }> {
  return sendJson("/api/debug/inventory", "POST", { item_id: itemId, count });
}

export async function debugJumpScene(
  sceneId: string,
): Promise<{ ok: boolean; changed: number; scene_id: string; status: Status }> {
  return sendJson("/api/debug/scene", "POST", { scene_id: sceneId });
}

export async function debugLearnSkill(
  skillId: string,
): Promise<{ ok: boolean; changed: number; status: Status }> {
  return sendJson("/api/debug/skill", "POST", { skill_id: skillId });
}


export async function getSkillLibraries(): Promise<{ libraries: import("./types").SkillLibraryInfo[]; total_skills: number }> {
  return readJson(await fetch("/api/skill-libraries"));
}
export async function getWorldSkillCatalog(): Promise<import("./types").WorldSkillCatalog> {
  return readJson(await fetch("/api/world/skill-catalog"));
}
export async function getSkillLibrary(id: string): Promise<{ manifest: { id: string }; skills: (Omit<import("./types").CatalogEntry, "ref" | "library_id" | "template_id"> & { id: string; resource_cost: Record<string,number> })[] }> {
  return readJson(await fetch(`/api/skill-libraries/${encodeURIComponent(id)}`));
}
export async function installStandardSkills(): Promise<unknown> {
  return sendJson("/api/skill-libraries/install-standard", "POST", {});
}
export async function importSkillLibrary(file: File): Promise<unknown> {
  if (file.size > 8 * 1024 * 1024) throw new Error("技能库 ZIP 不能超过 8 MB");
  const bytes = new Uint8Array(await file.arrayBuffer()); let binary = "";
  for (let i=0; i<bytes.length; i+=0x8000) binary += String.fromCharCode(...bytes.subarray(i,i+0x8000));
  return sendJson("/api/skill-libraries/import", "POST", { filename:file.name, data_base64:btoa(binary) });
}
export async function matchWorldSkillCatalog(): Promise<{ selection: { pool_count?: number; warnings?: string[] } }> {
  return sendJson("/api/world/skill-catalog/match", "POST", {});
}

export async function saveWorldState(state: import('./types').StateConfig, current_values?: Record<string,import('./types').Scalar>) {
  return readJson<{ok:boolean;world:WorldView;status:Status;warnings:string[]}>(await fetch('/api/world/state',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({state,current_values})}));
}
export async function repairInitialSkills() {
  return readJson<{ok:boolean;status:Status}>(await fetch('/api/world/skill-catalog/repair-initial',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}));
}

export async function getDirector(includeInternal = false): Promise<DirectorView> {
  return readJson(await fetch(`/api/director${includeInternal ? "?include_internal=true" : ""}`));
}
export async function saveDirector(pack_id: string, config: DirectorConfig): Promise<DirectorView> {
  return readJson(await fetch("/api/director", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pack_id, config }) }));
}
export async function requestDirector(pack_id: string): Promise<DirectorView> {
  return readJson(await fetch("/api/director/request", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pack_id }) }));
}
export async function putDirectorClue(pack_id: string, clue: PlotClue): Promise<DirectorView> {
  return readJson(await fetch("/api/director/clues", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pack_id, clue }) }));
}
export async function rollDice(pack_id: string, event_id: string, check: { kind: "dice" | "probability"; dice?: string; target?: number; chance?: number }): Promise<{ result: CheckResult; reused: boolean }> {
  return readJson(await fetch("/api/dice/roll", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pack_id, event_id, check }) }));
}

export async function getAdjudications(includeInternal = false): Promise<import("./types").AdjudicationView> {
  return readJson(await fetch(`/api/adjudications${includeInternal ? "?include_internal=true" : ""}`));
}
export async function previewAdjudication(pack_id: string, id: string, decision: import("./types").DecisionDraft, include_internal = false): Promise<import("./types").DecisionPreview> {
  return sendJson(`/api/adjudications/${encodeURIComponent(id)}/preview`, "POST", { pack_id, decision, include_internal });
}
export async function decideAdjudication(pack_id: string, id: string, decision: import("./types").DecisionDraft, include_internal = false): Promise<import("./types").AdjudicationView & { reused: boolean; receipt_id: number }> {
  return sendJson(`/api/adjudications/${encodeURIComponent(id)}/decide`, "POST", { pack_id, decision, include_internal });
}

export async function getAdjudicationEditor(): Promise<import("./adjudicationFields").EditorCatalog> {
  return readJson(await fetch("/api/adjudications/editor"));
}

export async function previewCharacterCard(body: import('./types').CardUpload & {options:import('./types').CardOptions}): Promise<import('./types').CardPreview> {
  return sendJson('/api/character-cards/preview','POST',body);
}
export async function importCharacterCard(body: import('./types').CardUpload & {options:import('./types').CardOptions;request_id:string;preview_token:string;expected_pack_id:string}): Promise<{ok:boolean;reused:boolean;imported_pack_id:string}> {
  return sendJson('/api/character-cards/import','POST',body);
}
export async function getCurrentCharacterCard(): Promise<import('./types').CurrentCard> {
  return readJson(await fetch('/api/character-cards/current'));
}

export type CorrectionMode = "narrative" | "state";
export interface CorrectionRequest {
  pack_id: string; request_id: string; revision: string;
  mode: CorrectionMode; instruction: string; persist: boolean;
}
export interface CorrectionResult {
  ok: boolean; receipt_id: number; reused: boolean; mode: CorrectionMode;
  narrative: string; explanation: string;
  changes: Record<string, { field: string; before: unknown; after: number }>;
  status: Status;
}
export function streamCorrection(body: CorrectionRequest, handlers: StreamHandlers = {}): Promise<CorrectionResult> {
  return gameStream<CorrectionResult>("/api/corrections/stream", body, handlers);
}
export function undoCorrection(pack_id: string, receipt_id: number): Promise<{ok:boolean;status:Status}> {
  return sendJson("/api/corrections/undo", "POST", {pack_id, receipt_id});
}
