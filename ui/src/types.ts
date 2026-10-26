export type Scalar = number | boolean | string;

export type InputMode = "speech" | "action" | "thought";

/** 文字分段：一句话里可以混着话语/动作/心理，未标注段为 plain。 */
export type SegmentMode = InputMode | "plain";

export type ExtraAction = "inspect" | "status" | "task";

export interface InputSegment {
  mode: SegmentMode;
  text: string;
}

/** 随同一次输入提交的技能（框架在本回合统一结算消耗与冷却）。 */
export interface PickedSkill {
  skill_id: string;
  name?: string;
}

export type Action =
  | { kind: "skill"; skill_id: string; target?: string }
  | {
      kind: "text";
      text: string;
      mode?: InputMode;
      modes?: InputMode[];
      segments?: InputSegment[];
      skills?: PickedSkill[];
      extras?: ExtraAction[];
    }
  | { kind: "option"; option_id: string };

export interface StateConfig {
  fields: FieldDef[];
  resource_bindings: Record<string,string>;
  limits: { max_delta_per_turn: Record<string,number>; [key:string]: unknown };
}

export interface FieldDef {
  id: string;
  label: string;
  type: string;
  enum_values?: string[] | null;
  min?: number | null;
  max?: number | null;
  step?: number;
  default?: unknown;
  display: string;
  group?: string;
  llm_visible?: boolean;
  unit?: string | null;
  color?: string | null;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  cost: Record<string, number>;
  cooldown: number;
  targets: string[];
  usable_when?: string | null;
  action_text: string;
  effect_hint?: string | null;
  available?: boolean;
  cooldown_remaining?: number;
  affordable?: boolean;
  blocked_reason?: string | null;
  category?: string;
  brief?: string;
}

export interface Option {
  id: string;
  label: string;
  action_text: string;
}

export interface EventRecord {
  seq: number;
  turn: number;
  kind: string;
  actor?: string | null;
  role?: string | null;
  payload: Record<string, unknown>;
  rolls?: Record<string, unknown>[];
  caused_by?: number | null;
  prompt_version?: string | null;
  model?: string | null;
  ts: number;
}

export interface Layout {
  title: string;
  bars: string[];
  numbers: string[];
  badges: string[];
  skills_section: string;
  options_section: string;
}

export interface Opening {
  id: string;
  text: string;
  options: Option[];
}

export interface ReplayReport {
  equal: boolean;
  live: Record<string, Scalar>;
  replay: Record<string, Scalar>;
  diff: Record<string, unknown>;
}

export interface LlmProfile {
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
}

export interface LlmRoles {
  separated: boolean;
  narrator: LlmProfile;
  settler: LlmProfile;
  arbiter: LlmProfile;
  setup: LlmProfile;
  director: LlmProfile;
  corrector?: LlmProfile | null;
  voice_cast?: LlmProfile | null;
}

export interface ProviderView {
  base_url: string;
  model: string;
  preset: string;
  reasoning_effort: string;
  timeout: number;
  price_in: number;
  price_out: number;
  max_retries: number;
  retry_backoff_ms: number;
  has_key: boolean;
  key_hint: string;
}

/** 模型目录里的一条模型建议（供应商预置 + 手填都能用）。 */
export interface ModelOption {
  id: string;
  label: string;
  note: string;
  efforts: string[];
  price_in: number;
  price_out: number;
}

export interface ModelPreset {
  id: string;
  label: string;
  base_url: string;
  key_hint: string;
  docs_url: string;
  note: string;
  models: ModelOption[];
}

/** 端点返回的一个可用模型（GET {base_url}/models）。 */
export interface RemoteModel {
  id: string;
  owned_by: string;
}

/** 「读取可用模型」的结果。 */
export interface RemoteModelList {
  ok: boolean;
  base_url: string;
  models: RemoteModel[];
  count: number;
  latency_ms: number;
}

export interface EffortOption {
  id: string;
  label: string;
}

export interface ModelCatalog {
  presets: ModelPreset[];
  efforts: EffortOption[];
  default_preset: string;
  custom_preset: string;
}

export interface SettingsView {
  speech: SpeechSettings;
  ok: boolean;
  roles: LlmRoles;
  providers: Record<string, ProviderView>;
  active_provider: string;
  catalog: ModelCatalog;
  settings_path: string;
}

export interface SettingsUpdate {
  speech?: Partial<SpeechSettings> & { api_key?: string };
  test_role?: string;
  roles?: LlmRoles;
  providers?: Record<
    string,
    {
      copy_from?: string;
      base_url?: string;
      model?: string;
      preset?: string;
      reasoning_effort?: string;
      timeout?: number;
      api_key?: string;
      price_in?: number;
      price_out?: number;
      max_retries?: number;
      retry_backoff_ms?: number;
    }
  >;
}

export interface SettingsTestResult {
  ok: boolean;
  provider?: string;
  model?: string;
  latency_ms?: number;
  tool_calls?: string[];
  narrative?: string;
  error?: string;
}

export interface LlmStatus {
  separated: boolean;
  roles: Record<
    "narrator" | "settler",
    {
      provider: string;
      model: string;
      temperature: number;
      preset?: string;
      preset_label?: string;
      reasoning_effort?: string;
    }
  >;
}

/** 账本折叠出的累计用量（含回滚/重试，调用即计费）。 */
export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  calls: number;
  latency_ms: number;
}

/** 场景推进：当前场景 + 每个作者选项的可用性。 */
export interface SceneOptionView {
  id: string;
  label: string;
  action_text: string;
  next_scene?: string | null;
  available: boolean;
  blocked_reason?: string | null;
}

export interface SceneView {
  id: string;
  title: string;
  text: string;
  requires: { field: string; op: string; value: unknown }[];
  options: SceneOptionView[];
  requires_met: boolean;
  blocked_reason?: string | null;
  /** 作者把该场景标记为结局（只是标记，不限制继续玩）。 */
  ending?: boolean;
  ending_title?: string | null;
}

/** 叙事模型附带的结构化角色状态（右侧状态栏显示；除 name 外都是 0~100 分）。 */
export interface NarratorStatus {
  name: string;
  lewd: number;
  body: number;
  sensitivity: number;
  desire: number;
  /** 四项各自的短描述（叙事措辞），键是 lewd/body/sensitivity/desire */
  notes?: Record<string, string>;
}

export interface DirectorConfig {
  enabled: boolean; use_narrator_model: boolean; on_scene_change: boolean;
  on_milestone: boolean; on_clue_change: boolean; min_turn_gap: number; max_candidates: number;
}
export interface PlotClue { id: string; title: string; summary: string; status: "open" | "resolved" | "paused"; visibility: "public" | "internal"; }
export interface CheckResult { event_id: string; kind: "dice" | "probability" | "certain"; dice?: string; total?: number; rolls?: number[]; kept?: number[]; passed?: boolean | null; }
export interface DirectorView {
  pack_id?: string; config: DirectorConfig; pending_manual: boolean; triggered_count: number;
  clues: PlotClue[]; last_run: { turn: number; reason: string; failed: boolean } | null;
  events: { id: string; title: string; outcome: string; visibility: "public" | "internal"; resolution: CheckResult | null }[];
  audit?: EventRecord[];
}

export interface Status {
  correction_revision?: string;
  director?: DirectorView;
  adjudication?: AdjudicationView;
  appearance_revision?: string;
  story_facts?: Record<string,{title:string;value:Scalar}>;
  turn: number;
  state: Record<string, Scalar>;
  inventory: Record<string, number>;
  scene: SceneView;
  options: Option[];
  opening: Opening;
  /** 开局叙述是否已经由模型生成（false = 还在准备开局） */
  opening_generated: boolean;
  /** 最近一次叙述附带的角色状态（没有就是 null） */
  narrative_status: NarratorStatus | null;
  events: EventRecord[];
  replay: ReplayReport;
  fields: FieldDef[];
  layout: Layout;
  skills: Skill[];
  pack: { id: string; title: string; version: string; rating: string };
  llm: LlmStatus;
  usage: Usage;
}

export interface TurnResult {
  status?: Status;
  ok: boolean;
  turn: number;
  narrative: string;
  options: Option[];
  state: Record<string, Scalar>;
  inventory: Record<string, number>;
  events: EventRecord[];
  leaks: string[];
  errors: string[];
  scene_id?: string;
}

export interface OpeningResult {
  ok: boolean;
  /** 本次是否真的调用了模型（幂等：已完成的开局再请求不会重复生成） */
  generated: boolean;
  narrative?: string;
  options?: Option[];
  error?: string;
  status: Status;
}

export type SkillTarget = "self" | "enemy" | "scene" | "item" | "npc";

export interface WorldbookEntry {
  case_sensitive?: boolean;
  selective?: boolean;
  secondary_keywords?: string[];
  insertion_order?: number;
  id: string;
  title: string;
  content: string;
  keywords: string[];
  always_on: boolean;
  enabled: boolean;
  priority: number;
  category: string;
}

export interface WorldSkill {
  id: string;
  name: string;
  description: string;
  cost: Record<string, number>;
  cooldown: number;
  targets: string[];
  usable_when?: string | null;
  action_text: string;
  effect_hint?: string;
  brief?: string;
  category?: string;
  color?: string | null;
}

export interface WorldView {
  state: StateConfig;
  current_values: Record<string,Scalar>;
  ok: boolean;
  pack_id: string;
  title: string;
  editable: boolean;
  manifest: Record<string, unknown>;
  worldbook: WorldbookEntry[];
  skills: WorldSkill[];
  prompts: { pre: string; narrator: string; settler: string };
}

export interface GameInfo {
  id: string;
  title: string;
  version: string;
  rating: string;
  description: string;
  path: string;
  builtin: boolean;
  valid: boolean;
  error: string;
  worldbook_entries: number;
  skills: number;
  scenes: number;
  editable: boolean;
  active: boolean;
}

export interface LibraryView {
  ok: boolean;
  active_pack: string;
  active_pack_dir: string;
  packs: GameInfo[];
  builtin_dir: string;
  user_dir: string;
  library_path: string;
  status?: Status;
}

/** 存档摘要（列表页用，不含事件明细）。 */
export interface SaveSummary {
  slot: string;
  label?: string | null;
  saved_at?: string | null;
  pack_id?: string | null;
  pack_title?: string | null;
  pack_version?: string | null;
  turn?: number;
  scene_id?: string | null;
  state?: Record<string, Scalar>;
  inventory?: Record<string, number>;
  usage?: Usage | null;
  auto?: boolean;
}

export interface SavesView {
  ok: boolean;
  dir: string;
  saves: SaveSummary[];
  broken: { slot: string; error: string }[];
  auto_slot: string;
  note?: string;
  pack_id?: string | null;
  resumed?: boolean;
}

export interface SaveCreateResult {
  ok: boolean;
  save: SaveSummary;
  saves: SavesView;
}

export interface SaveLoadResult {
  ok: boolean;
  save: SaveSummary;
  status: Status;
  saves: SavesView;
}

export interface SaveDeleteResult {
  ok: boolean;
  removed: boolean;
  saves: SavesView;
}

/** 世界构筑助手：模型拆出的内容包草稿。 */
export interface BuilderDraft {
  state?: StateConfig;
  character_profile?: Record<string,unknown>;
  title: string;
  description: string;
  prompts: Partial<Record<"pre" | "narrator" | "settler", string>>;
  worldbook: WorldbookEntry[];
  skills: WorldSkill[];
  warnings: string[];
}

export interface BuilderSummary {
  title: string;
  description: string;
  prompt_keys: string[];
  prompt_lengths: Record<string, number>;
  worldbook_count: number;
  skill_count: number;
  warnings: string[];
}

export interface BuilderPromptView {
  ok: boolean;
  prompt: string;
  state_fields: string[];
  targets: string[];
  prompt_keys: string[];
}

export interface BuilderGenerateResult {
  ok: boolean;
  draft: BuilderDraft;
  summary: BuilderSummary;
  model: string;
  provider: string;
  usage?: Record<string, number>;
  latency_ms?: number;
}

export interface BuilderParseResult {
  ok: boolean;
  draft: BuilderDraft;
  summary: BuilderSummary;
}

export interface BuilderApplyResult extends LibraryView {
  warnings: string[];
  world: WorldView;
  status: Status;
  pack_id: string;
}

// ---------------------------------------------------------------------------
// P7：分层立绘（pack/ui/sprites.json）
// ---------------------------------------------------------------------------

export interface SpriteCondition {
  field: string;
  op: "==" | "!=" | ">" | ">=" | "<" | "<=" | "in" | "not_in";
  value: string | number | boolean | Array<string | number>;
}

export interface SpriteLayer {
  id: string;
  src: string;
  z: number;
  when?: SpriteCondition[];
  unless?: SpriteCondition[];
  tint?: string | null;
  tint_field?: string | null;
  opacity?: number;
  wear_field?: string | null;
  blend?: "normal" | "multiply";
  mask?: string | null;
  x?: number;
  y?: number;
  adult?: boolean;
  space?: "character" | "background" | "foreground";
}

export interface SpriteCrop {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SpritePose {
  crop?: SpriteCrop | null;
  layers: SpriteLayer[];
  /** 覆盖画布尺寸/动画：DoL 的特写画布是 64×64、6 帧，和站姿不同 */
  width?: number | null;
  height?: number | null;
  frames?: number | null;
  fps?: number | null;
  /** 素材单帧宽度，与输出尺寸、取景窗口相互独立 */
  frame_width?: number | null;
}

/** 状态联动：满足 when 时把字段换成 set 里的值再画（只影响绘制，不改状态） */
export interface SpriteRule {
  when: SpriteCondition[];
  set: Record<string, string | number | boolean>;
}

export interface SpriteSheet {
  asset_key?: string;
  width: number;
  height: number;
  max_height: number;
  /** 素材有效区域；w/h 为 0 或缺省表示整张图 */
  crop?: SpriteCrop | null;
  layers: SpriteLayer[];
  /** 不同姿势，键名与状态字段 pose 对应 */
  poses?: Record<string, SpritePose>;
  controls?: Record<string, Record<string, string>>;
  motions?: Record<string, string>;
  catalog_version?: number;
  motion_notes?: Record<string, string>;
  pose_arms?: Record<string, { left?: string; right?: string }>;
  revision?: number;
  arm_preferences?: Record<string, string>;
  handheld_modes?: Record<string, string[]>;
  resource_bindings?: Record<string, string>;
  labels?: Record<string, Record<string, string>>;
  /** 同一套图层的不同取景（full / bust …），由界面设置切换 */
  views?: Record<string, SpriteCrop>;
  /** 状态联动规则（按顺序覆盖，后面的赢） */
  rules?: SpriteRule[];
  /** 每层横向排了几帧（DoL 是 2 帧呼吸动画），默认 1 */
  frame_width?: number | null;
  frames?: number;
  /** 动画帧率，默认 2 */
  fps?: number;
}

// ---- 调试台 -----------------------------------------------------------
export interface DebugItemRow {
  id: string;
  name: string;
  description?: string;
  stackable?: boolean;
}

export interface DebugSkillRow {
  id: string;
  name: string;
  cost: Record<string, number>;
  cooldown: number;
  description?: string;
  category?: string;
  learned: boolean;
}

export interface DebugSceneRow {
  id: string;
  title: string;
  opening: boolean;
}

export interface DebugSpriteInfo {
  frames: number;
  fps: number;
  layers: number;
  views: string[];
  poses: string[];
  crop: { x: number; y: number; w: number; h: number };
}

export interface DebugCatalog {
  pack: { id: string; title: string; version: string; rating?: string };
  turn: number;
  scene_id: string;
  state: Record<string, Scalar | string | null>;
  inventory: Record<string, number>;
  fields: FieldDef[];
  limits: Record<string, unknown>;
  items: DebugItemRow[];
  flags: { id: string; label: string; description?: string }[];
  skills: DebugSkillRow[];
  scenes: DebugSceneRow[];
  sprite: DebugSpriteInfo | null;
  events: EventRecord[];
}


/** Transient public narration; replaced by the committed ledger entry. */
export interface NarrativeUpdate {
  turn: number;
  text: string;
  phase: "waiting" | "writing" | "settling";
}


export interface SkillLibraryInfo {
  id: string; title: string; version: string; description: string; count: number;
  counts: Record<string, number>;
}
export interface CatalogEntry {
  ref: string; library_id: string; template_id: string;
  kind: "martial" | "magic"; tier: "low" | "mid" | "high"; school: string;
  instruction: string; skill: WorldSkill; prerequisites: string[];
  known?: boolean; learnable?: boolean; missing_prerequisites?: string[];
}
export interface WorldSkillCatalog {
  ok: boolean; editable: boolean; selection: { method?: string; model?: string; reason?: string; initial_count?: number; pool_count?: number; warnings?: string[] };
  skills: CatalogEntry[];
}

export interface AdjudicationChange { domain: string; field: string; before: unknown; after: unknown }
export interface AdjudicationItem {
  id: string; title: string; reason: string; evidence: string; visibility: "public" | "internal";
  operations: Record<string,unknown>[]; status_patch: Record<string,unknown>; source_turn: number;
  state: "pending" | "deferred" | "confirmed" | "rejected"; version: number; stale: boolean; can_undo: boolean;
}
export interface AdjudicationView {
  pack_id: string; revision: string; items: AdjudicationItem[]; pending_count: number; deferred_count: number;
  history: { seq: number; id: string; action: string; reason: string; ts: string; before_state: string; title: string; source_withdrawn: boolean; changes: AdjudicationChange[] }[];
}
export interface DecisionDraft {
  request_id: string; revision: string; action: "confirm" | "modify" | "reject" | "defer" | "resume" | "undo";
  reason?: string; operations?: Record<string,unknown>[]; status_patch?: Record<string,unknown>; preview_token?: string;
}
export interface DecisionPreview {
  pack_id: string; revision: string; preview_token: string; changes: AdjudicationChange[]; no_state_change: boolean;
}

export interface CardOptions { title:string; id:string; user_name:string; role:'npc'|'player'; greeting:number; include:string[] }
export interface CardUpload { filename:string; data_base64:string }
export interface CardPreview {
  spec:string; spec_version:string; format:string; name:string; title:string; id:string; creator:string; creator_notes:string; character_version:string;
  warnings:string[]; unsupported:{path:string;message:string}[]; raw_preserved:boolean; source_sha256:string; preview_token:string; active_pack_id:string;
  greetings:{index:number;label:string;text:string}[]; selected_greeting:number; mappings:{source:string;target:string;enabled:boolean}[];
  entry_mapping:{source_index:number;target_id:string|null}[]; worldbook_count:number; prompts:Record<string,string>; raw:Record<string,unknown>;
}
export interface CurrentCard { pack_id:string; card:{name:string; spec:string; creator:string; creator_notes:string; [key:string]:unknown}|null }


export interface SpeechSettings {
  enabled: boolean; mode: "imported" | "automatic"; base_url: string; model: string; voice: string;
  speed: number; timeout: number; has_key: boolean; key_hint: string;
}
export interface VoiceCharacter { id: string; name: string; description: string; source: "imported" | "automatic"; enabled: boolean; voice: string }
export interface VoiceView { pack_id: string; speech: SpeechSettings; characters: VoiceCharacter[] }
export interface VoiceLine { id: string; character_id: string; name: string; text: string; enabled: boolean; voice: string }
export interface VoiceDialogue { pack_id: string; entry_id: string; revision: string; lines: VoiceLine[]; characters: VoiceCharacter[] }
