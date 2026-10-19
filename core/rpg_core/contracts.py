"""P0 契约（单一真相：Python 模型）。

七份契约：
1. StateSchema   —— 状态字段、范围、显示、每回合限额
2. Mutator       —— LLM 唯一可用的改值工具集合
3. Event         —— 账本事件
4. ContentPack   —— 内容包（manifest/state/vocab/prompts/ui/scenes）
5. NarratorIO    —— 叙事角色的输入输出（narrative + options）
6. SettlerIO     —— 结算角色的输出（tool_calls）与工具结果
7. LlmRole/Router—— 角色到模型的映射；一期单 LLM（separated=False）

contracts/*.json 由 tools/export_contracts.py 从这些模型导出，UI 侧类型在
ui/src/contracts.ts 手工镜像（P0 不引入代码生成依赖）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

FieldType = Literal["int", "float", "bool", "enum", "string"]
DisplayKind = Literal["bar", "number", "badge", "text", "hidden"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# 1. StateSchema
# --------------------------------------------------------------------------
class StateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: FieldType = "int"
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    default: Any = 0
    display: DisplayKind = "number"
    group: str = "misc"
    llm_visible: bool = True
    enum_values: Optional[list[str]] = None
    unit: Optional[str] = None
    color: Optional[str] = None


class TurnLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tool_rounds: int = 6
    max_rejections: int = 1
    narrative_number_check: bool = True
    # 单回合单字段最大变化量；缺省表示不限制
    max_delta_per_turn: dict[str, float] = Field(default_factory=dict)


class StateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[StateField]
    resource_bindings: dict[str, str] = Field(default_factory=dict)
    limits: TurnLimits = Field(default_factory=TurnLimits)

    def by_id(self) -> dict[str, StateField]:
        return {f.id: f for f in self.fields}

    def defaults(self) -> dict[str, Any]:
        return {f.id: f.default for f in self.fields}


# --------------------------------------------------------------------------
# 2. Mutator 工具
# --------------------------------------------------------------------------
MutatorName = Literal[
    "roll",
    "damage",
    "heal",
    "add_stat",
    "set_stat",
    "add_item",
    "set_flag",
    "enter_scene",
    "learn_skill",
    "learn_catalog_skills",
    "update_clothing",
]


class MutatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MutatorName
    description: str
    params: dict[str, Any]
    permission: str = "settler"


MUTATORS: list[MutatorSpec] = [
    MutatorSpec(
        name="roll",
        description="掷骰。点数由框架生成，LLM 不得自行编造。",
        params={
            "type": "object",
            "properties": {"dice": {"type": "string", "description": "如 1d6+2"}},
            "required": ["dice"],
        },
    ),
    MutatorSpec(
        name="damage",
        description="对目标造成伤害（默认 hp）。",
        params={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
                "reason": {"type": "string"},
            },
            "required": ["amount"],
        },
    ),
    MutatorSpec(
        name="heal",
        description="恢复生命/资源（默认 hp）。",
        params={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
                "reason": {"type": "string"},
            },
            "required": ["amount"],
        },
    ),
    MutatorSpec(
        name="add_stat",
        description="对某个已声明数值字段做增量修改。",
        params={
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "delta": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["field", "delta"],
        },
    ),
    MutatorSpec(
        name="set_stat",
        description="把某个已声明字段设为指定值（仅在确有必要时使用）。",
        params={
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "value": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["field", "value"],
        },
    ),
    MutatorSpec(
        name="add_item",
        description="获得物品。",
        params={
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "count": {"type": "integer", "minimum": 1},
                "reason": {"type": "string"},
            },
            "required": ["item_id"],
        },
    ),
    MutatorSpec(
        name="set_flag",
        description="设置剧情标记。",
        params={
            "type": "object",
            "properties": {
                "flag": {"type": "string"},
                "value": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["flag", "value"],
        },
    ),
    MutatorSpec(
        name="enter_scene",
        description="进入另一个场景。只能进入内容包已声明且进入条件已满足的场景。",
        params={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string", "description": "目标场景 id"},
                "reason": {"type": "string"},
            },
            "required": ["scene_id"],
        },
    ),
    MutatorSpec(
        name="learn_skill",
        description=(
            "玩家习得一个新技能（剧情奖励/学习成果）。只允许在叙事里真的写到他学会/掌握了这门新本事时调用；"
            "技能会立刻出现在玩家技能栏里，之后可以和输入一起勾选使用。"
            "只能新增内容包里还没有的技能 id，不能修改已有技能。"
        ),
        params={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "技能 id：小写英文字母开头，只能用小写字母/数字/下划线，2~40 字符，如 shadow_step",
                },
                "name": {"type": "string", "description": "技能中文名，如 潜行"},
                "description": {"type": "string", "description": "技能说明（一句话）"},
                "cost": {
                    "type": "object",
                    "description": "施展消耗：内容包已声明的数值字段 → 数值，如 {\"stamina\": 2}；可为空对象",
                },
                "cooldown": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 20,
                    "description": "冷却回合数，0 表示无冷却",
                },
                "action_text": {
                    "type": "string",
                    "description": "使用技能时玩家视角的一句行动文本（可空）",
                },
                "category": {"type": "string", "description": "分类，如 生存/战斗（可空）"},
                "effect_hint": {"type": "string", "description": "技能效果提示（可空）"},
                "reason": {"type": "string", "description": "习得原因（剧情依据）"},
            },
            "required": ["id", "name"],
        },
    ),
]


MUTATORS.append(MutatorSpec(
    name="learn_catalog_skills",
    description="按世界预设技能目录登记已学会的技能，只引用 ref 与本次叙述原文证据，不生成或修改技能定义。无学习则 skills=[]。",
    params={"type": "object", "additionalProperties": False, "properties": {
        "skills": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"ref": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["ref", "evidence"]}},
    }, "required": ["skills"]},
))

MUTATORS.append(MutatorSpec(
    name="update_clothing",
    description="读取本次最终叙述后，原子更新衣物款式、颜色和损坏程度。无变化时提交空 changes。仅限衣物后置结算阶段。",
    params={
        "type": "object", "additionalProperties": False,
        "properties": {"changes": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "slot": {"type": "string", "description": "衣物槽位，例如 upper/lower"},
                    "garment": {"type": "string", "description": "目录里的衣物 id，未换衣时省略"},
                    "condition": {"type": "string", "enum": ["intact", "scuffed", "damaged", "ruined"]},
                    "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                    "evidence": {"type": "string", "minLength": 2, "maxLength": 300, "description": "本次叙述中证明实际换衣、损坏或修复已经发生的原文片段"},
                },
                "required": ["slot", "evidence"],
            },
        }},
        "required": ["changes"],
    },
))


# --------------------------------------------------------------------------
# 3. Event（账本）
# --------------------------------------------------------------------------
EventKind = Literal[
    "turn.started",
    "skill.used",
    "skill.learned",
    "scene.entered",
    "narrative.generated",
    "narrative.checked",
    "clothing.checked",
    "settlement.checked",
    "settlement.rejected",
    "status.updated",
    "story.fact",
    "world.configured",
    "skills.checked",
    "roll.resolved",
    "tool.proposed",
    "tool.applied",
    "tool.rejected",
    "llm.usage",
    "turn.committed",
    "turn.rolled_back",
    "state.snapshot",
]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    turn: int
    kind: EventKind
    actor: str = "system"
    role: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    rolls: list[dict[str, Any]] = Field(default_factory=list)
    caused_by: Optional[int] = None
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    ts: datetime = Field(default_factory=_now)


# --------------------------------------------------------------------------
# 4. ContentPack
# --------------------------------------------------------------------------
class ContentPackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    version: str
    schema_version: int = 1
    rating: str = "all"
    dependencies: list[str] = Field(default_factory=list)
    description: str = ""


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    cost: dict[str, float] = Field(default_factory=dict)
    cooldown: int = 0
    targets: list[str] = Field(default_factory=lambda: ["self"])
    usable_when: Optional[str] = None
    action_text: str = ""
    effect_hint: str = ""
    category: str = ""
    brief: str = ""


class CatalogSkill(BaseModel):
    """World-local, immutable snapshot of a skill-library entry."""
    model_config = ConfigDict(extra="forbid")
    ref: str
    library_id: str
    template_id: str
    kind: Literal["martial", "magic"]
    tier: Literal["low", "mid", "high"]
    school: str
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    instruction: str
    resource_cost: dict[str, float] = Field(default_factory=dict)
    skill: SkillSpec


class WorldbookEntry(BaseModel):
    """世界书条目：一段世界观设定，按关键词命中时注入 LLM 上下文。

    `always_on` 的条目每回合都注入（用于世界的底层规则/基调），其余按命中。
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    content: str
    keywords: list[str] = Field(default_factory=list)
    always_on: bool = False
    enabled: bool = True
    priority: int = 0
    category: str = ""


class ItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    stackable: bool = False
    use_effect_hint: str = ""


class NpcSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""


class QuestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""


class FlagSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str = ""


class UiLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    bars: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    skills_section: str = "技能"
    options_section: str = "接下来"


class Condition(BaseModel):
    """场景/选项的进入条件：对已声明状态字段做受限比较（结构化，不解析自由文本）。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in"] = "=="
    value: Any = True


class SceneOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    action_text: str = ""
    # 确定性转场：玩家选这个选项时框架直接进目标场景（仍需满足条件）
    next_scene: Optional[str] = None
    # 选项可见/可用的条件（不满足 → 不可选）
    requires: list[Condition] = Field(default_factory=list)


class OpeningScene(BaseModel):
    """一个场景。opening 是其中一个特殊场景（也是默认起点）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = ""
    text: str
    # 进入该场景的条件（LLM 调 enter_scene / 选项转场时由护栏校验）
    requires: list[Condition] = Field(default_factory=list)
    options: list[SceneOption] = Field(default_factory=list)
    # P4：结局场景只是"标记 + 展示"，不锁死任何操作（仍可继续/返回/重开）
    ending: bool = False
    ending_title: str = ""


class SpriteLayer(BaseModel):
    """立绘的一层：图片路径 + 层序 + 显示条件 + 着色/遮罩。

    `src` 是相对内容包根目录的路径模板，可以用 `{field}` 引用状态字段，
    例如 `ui/sprites/body/base-{body_type}.png`；字段值会原样替换。
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    src: str
    z: int = 0
    # 全部满足才显示；`unless` 任一满足就隐藏
    when: list[Condition] = Field(default_factory=list)
    unless: list[Condition] = Field(default_factory=list)
    # 着色（十六进制颜色），用于给灰白素材上色（发色/瞳色等）
    tint: Optional[str] = None
    # 从状态字段取颜色值（值需是 #rrggbb），优先于 tint
    tint_field: Optional[str] = None
    opacity: float = 1.0
    # 在衣物原有 alpha 内绘制磨损，不改变覆盖范围。
    wear_field: Optional[str] = None
    blend: Literal["normal", "multiply"] = "normal"
    # 遮罩图（相对内容包根目录），用它的 alpha 裁切本层
    mask: Optional[str] = None
    x: int = 0
    y: int = 0
    # 成人向图层：只有设置里打开「显示成人向图层」时才渲染
    adult: bool = False


class SpriteCrop(BaseModel):
    """素材里的有效区域（像素）。

    DoL 的立绘 PNG 是 512×256 的大图，真正的角色只占左上角一小块，右侧另有一块
    放大预览；整张画会重影。`crop` 指定从每层图片的哪一块取样，所有图层共用同一
    窗口，再等比放大到画布。
    """

    model_config = ConfigDict(extra="forbid")

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


class SpritePose(BaseModel):
    """一种姿势：自己的取样窗口 + 图层列表。

    立绘默认用 `SpriteSheet.layers`；当状态字段 `pose` 的值等于某个姿势名时，
    改用该姿势的窗口和图层。DoL 的坐/卧/性交姿势都是独立的一套图层，
    取样窗口也和站姿不同，所以每个姿势自带 `crop`。
    """

    model_config = ConfigDict(extra="forbid")

    crop: Optional[SpriteCrop] = None
    layers: list[SpriteLayer] = Field(default_factory=list)
    # 覆盖画布尺寸/动画（特写是 DoL 的 64×64、6 帧画布，和站姿 256×256、2 帧不同）
    width: Optional[int] = None
    height: Optional[int] = None
    frames: Optional[int] = None
    fps: Optional[float] = None
    frame_width: Optional[int] = Field(default=None, gt=0)


class SpriteRule(BaseModel):
    """状态联动规则：满足 `when` 时把若干字段替换成 `set` 里的值再画。

    只影响绘制，不改状态本身（不写账本）——「受伤时换成 hurt 表情」这类
    表现层联动适合放这里；真要改数值请用调试台或剧情事件。
    """

    model_config = ConfigDict(extra="forbid")

    when: list[Condition] = Field(default_factory=list)
    set: dict[str, object] = Field(default_factory=dict)


class SpriteSheet(BaseModel):
    """内容包可选的立绘配置：ui/sprites.json。"""

    model_config = ConfigDict(extra="forbid")

    width: int = 256
    height: int = 256
    # 容器最大显示高度（px），手机上会自动按宽度等比缩放
    max_height: int = 320
    # 可选：素材有效区域；w/h 为 0 表示整张图
    crop: SpriteCrop = Field(default_factory=SpriteCrop)
    layers: list[SpriteLayer] = Field(default_factory=list)
    # 可选：不同姿势；键名和状态字段 pose 的值对应
    poses: dict[str, SpritePose] = Field(default_factory=dict)
    # 可选：同一套图层的不同取景（如全身 / 半身），由界面设置切换
    views: dict[str, SpriteCrop] = Field(default_factory=dict)
    # 可选：状态联动（按顺序覆盖字段，后面的覆盖前面的）
    rules: list[SpriteRule] = Field(default_factory=list)
    # 动画：素材里每层横向排了 `frames` 帧（DoL 是 2 帧呼吸动画），按 `fps` 循环播放。
    # 帧宽为 frame_width，省略时兼容 width；取景 crop 不改变素材步长。
    frame_width: Optional[int] = Field(default=None, gt=0)
    frames: int = 1
    fps: float = 2.0


CLOTHING_CONDITIONS = ("intact", "scuffed", "damaged", "ruined")


class WardrobeSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    condition_field: str
    color_field: Optional[str] = None
    # 只允许目录里的现有衣物；值是提供给模型的易读名称。
    items: dict[str, str] = Field(min_length=1)


class WardrobeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slots: dict[str, WardrobeSlot] = Field(min_length=1, max_length=8)


class ContentPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: ContentPackManifest
    state: StateSchema
    skills: list[SkillSpec] = Field(default_factory=list)
    skill_catalog: list[CatalogSkill] = Field(default_factory=list)
    skill_selection: dict[str, Any] = Field(default_factory=dict)
    items: list[ItemSpec] = Field(default_factory=list)
    npcs: list[NpcSpec] = Field(default_factory=list)
    quests: list[QuestSpec] = Field(default_factory=list)
    flags: list[FlagSpec] = Field(default_factory=list)
    worldbook: list[WorldbookEntry] = Field(default_factory=list)
    prompts: dict[str, str] = Field(default_factory=dict)  # pre / narrator / settler
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    ui: UiLayout = Field(default_factory=UiLayout)
    # P7：可选立绘配置；没有就不显示（老包不受影响）
    sprites: Optional[SpriteSheet] = None
    asset_pack: str | None = None
    wardrobe: Optional[WardrobeConfig] = None
    opening: OpeningScene = Field(
        default_factory=lambda: OpeningScene(id="opening", text="")
    )
    # scenes/ 下的全部场景（含 opening）；P2 先做校验与加载，场景推进在 P4 接
    scenes: list[OpeningScene] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 5. NarratorIO
# --------------------------------------------------------------------------
class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    action_text: str = ""


class NarratorStatus(BaseModel):
    """叙事模型附带的结构化角色状态（只给右侧状态栏用，不写进叙事正文）。

    name 是文本；其余四项统一 0~100 分（越界会被夹到范围里），方便 UI 画条。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=40)
    lewd: int = 0
    body: int = 0
    sensitivity: int = 0
    desire: int = 0
    # 四项各自的短描述（来自叙事正文的措辞），键是 lewd/body/sensitivity/desire
    notes: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: Any) -> str:
        return str(value or "").strip()[:40]

    @field_validator("lewd", "body", "sensitivity", "desire", mode="before")
    @classmethod
    def _clamp_score(cls, value: Any) -> int:
        if isinstance(value, dict):
            value = value.get("score", value.get("值", value.get("分值", 0)))
        try:
            score = int(round(float(value)))
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, score))

    @field_validator("notes", mode="before")
    @classmethod
    def _clean_notes(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        aliases = {
            "lewd": "lewd",
            "色情程度": "lewd",
            "色情值": "lewd",
            "body": "body",
            "小穴与身体": "body",
            "身体": "body",
            "小穴": "body",
            "sensitivity": "sensitivity",
            "敏感度": "sensitivity",
            "desire": "desire",
            "倾向": "desire",
            "欲望": "desire",
        }
        cleaned: dict[str, str] = {}
        for key, text in value.items():
            field_id = aliases.get(str(key).strip())
            if field_id is None or field_id in cleaned:
                continue
            note = str(text or "").strip()
            if note:
                cleaned[field_id] = note[:60]
        return cleaned


class NarratorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative: str
    options: list[Option] = Field(default_factory=list, min_length=0, max_length=4)
    status: Optional[NarratorStatus] = None


# --------------------------------------------------------------------------
# 6. SettlerIO
# --------------------------------------------------------------------------
class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class SettlerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calls: list[ToolCall] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 7. LlmRole / Router
# --------------------------------------------------------------------------
LlmRoleName = Literal["narrator", "settler", "arbiter", "setup"]


class LlmProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "scripted"
    model: str = ""  # 空 = 继承 provider 端点配置的 model
    temperature: float = 0.7
    # 0 = 不限制：请求里完全不传 max_tokens，交给模型/端点自己的上限。
    max_tokens: int = 0


class LlmRolesConfig(BaseModel):
    """一期：narrator 与 settler 指向同一 profile，separated=False。

    拆分多 LLM 只改这里：separated=True + settler 指向小模型，核心契约不变。
    """

    model_config = ConfigDict(extra="forbid")

    separated: bool = False
    narrator: LlmProfile = Field(default_factory=LlmProfile)
    settler: LlmProfile = Field(default_factory=lambda: LlmProfile(temperature=0.0))
    arbiter: LlmProfile = Field(default_factory=LlmProfile)
    setup: LlmProfile = Field(default_factory=LlmProfile)


class ProviderSettings(BaseModel):
    """一个模型端点的连接信息。api_key 只存后端，接口返回时打码。"""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    # 供应商预设（deepseek / chatgpt / gemini / grok / custom）：只用于界面回显与迁移，
    # 真正决定调用的是 base_url + model + reasoning_effort。
    preset: str = ""
    # 思考强度：空 = 不传；low / medium / high 透传给 OpenAI 兼容端点
    reasoning_effort: str = ""
    timeout: float = 60.0
    # 计量与容错：单价按 USD / 1M tokens；重试只对 429/5xx/网络错误生效
    price_in: float = Field(default=0.0, ge=0.0)
    price_out: float = Field(default=0.0, ge=0.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_ms: int = Field(default=500, ge=0, le=10000)


class LlmSettings(BaseModel):
    """持久化模型设置：角色 → profile，provider 名 → 端点信息。

    provider 名为 "scripted" 时走内置脚本假模型；其余按 OpenAI 兼容端点调用，
    默认只有一个名为 "openai" 的端点槽位，接 DeepSeek / LM Studio / vLLM 都填这里。
    """

    model_config = ConfigDict(extra="forbid")

    roles: LlmRolesConfig = Field(default_factory=LlmRolesConfig)
    providers: dict[str, ProviderSettings] = Field(
        default_factory=lambda: {"openai": ProviderSettings()}
    )
