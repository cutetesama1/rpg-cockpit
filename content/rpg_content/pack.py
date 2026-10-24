"""内容包 v2 加载与校验。

目录结构见 PLAN 第 6 节、`docs/P2-CONTENT.md`。
加载阶段只负责"读得出来"；能不能上线由 `rpg_content.lint` 决定：

- `load_pack(dir)`：加载 + lint（只把 error 当失败），抛 `PackError` 并一次列全问题。
- `load_pack(dir, lint_warnings=True)`：严格模式，warning 也当失败（作者/CI 用）。
- `validate_pack(pack)`：只做 lint 的错误汇总，供内部与工具复用。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rpg_core.contracts import (
    ContentPack,
    ContentPackManifest,
    FlagSpec,
    ItemSpec,
    NpcSpec,
    OpeningScene,
    QuestSpec,
    SkillSpec,
    CatalogSkill,
    SpriteSheet,
    StateSchema,
    StateField,
    UiLayout,
    WorldbookEntry,
    WardrobeConfig,
)


class PackError(Exception):
    pass


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise PackError(f"缺少文件：{path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{path.name} JSON 解析失败：{exc}") from exc


def _list_of(data: Any, key: str) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get(key, [])
    return []


def _prompt_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _load_scene(path: Path) -> OpeningScene:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise PackError(f"{path.name} 必须是一个对象")
    data.setdefault("id", path.stem)
    return OpeningScene(**data)


def load_pack(
    pack_dir: str | Path, lint_warnings: bool = False, validate: bool = True
) -> ContentPack:
    """加载内容包。

    `validate=False` 只做结构加载、不跑 lint（编辑器/`lint_pack_dir` 用，便于一次列全问题）。
    """
    root = Path(pack_dir)
    if not root.is_dir():
        raise PackError(f"内容包目录不存在：{root}")

    manifest = ContentPackManifest(**_read_json(root / "manifest.json"))
    state = StateSchema(**_read_json(root / "state.json"))

    vocab = root / "vocab"
    skills = [SkillSpec(**x) for x in _list_of(_read_json(vocab / "skills.json"), "skills")]
    items = [ItemSpec(**x) for x in _list_of(_read_json(vocab / "items.json"), "items")]
    npcs = [NpcSpec(**x) for x in _list_of(_read_json(vocab / "npcs.json"), "npcs")]
    quests = [QuestSpec(**x) for x in _list_of(_read_json(vocab / "quests.json"), "quests")]
    flags = [FlagSpec(**x) for x in _list_of(_read_json(vocab / "flags.json"), "flags")]
    for flag in flags:
        if not any(f.id in (flag.id, "flag_"+flag.id) and f.type=="bool" for f in state.fields):
            state.fields.append(StateField(id=flag.id,label=flag.label,type="bool",default=False,display="hidden",group="flags"))
    worldbook_path = vocab / "worldbook.json"
    worldbook = (
        [WorldbookEntry(**x) for x in _list_of(_read_json(worldbook_path), "entries")]
        if worldbook_path.exists()
        else []
    )

    prompts: dict[str, str] = {}
    prompt_versions: dict[str, str] = {}
    prompts_dir = root / "prompts"
    if prompts_dir.is_dir():
        for path in sorted(prompts_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            prompts[path.stem] = text
            prompt_versions[path.stem] = _prompt_version(text)

    ui_path = root / "ui" / "layout.json"
    ui_data = _read_json(ui_path) if ui_path.exists() else {}
    ui = UiLayout(**ui_data if isinstance(ui_data, dict) else {})

    # 可选立绘配置：没有 ui/sprites.json 就当作"这个包不显示立绘"
    sprites_path = root / "ui" / "sprites.json"
    sprites = SpriteSheet(**_read_json(sprites_path)) if sprites_path.exists() else None

    scenes: list[OpeningScene] = []
    scenes_dir = root / "scenes"
    if scenes_dir.is_dir():
        for path in sorted(scenes_dir.glob("*.json")):
            scenes.append(_load_scene(path))

    opening_path = scenes_dir / "opening.json"
    if opening_path.exists():
        opening = _load_scene(opening_path)
    else:
        match = next((s for s in scenes if s.id == "opening"), None)
        opening = match or OpeningScene(id="opening", text="", options=[])
    if all(s.id != opening.id for s in scenes) and (opening.text or opening.options):
        scenes.append(opening)

    catalog_path = vocab / "skill_catalog.json"
    catalog_data = _read_json(catalog_path) if catalog_path.exists() else {}
    if not isinstance(catalog_data, dict) or catalog_data.get("schema_version", 1) != 1:
        raise PackError("skill_catalog.json 需要 schema_version=1 的对象")
    catalog = [CatalogSkill(**item) for item in catalog_data.get("skills", [])]

    pack = ContentPack(
        manifest=manifest,
        personality_roster=(_read_json(root / 'personality-npcs.json') if (root / 'personality-npcs.json').exists() else {}),
        character_card=(_read_json(root / "character-card.json") if (root / "character-card.json").exists() else {}),
        state=state,
        skills=skills,
        skill_catalog=catalog,
        skill_selection=catalog_data.get("selection", {}),
        items=items,
        npcs=npcs,
        quests=quests,
        flags=flags,
        worldbook=worldbook,
        prompts=prompts,
        prompt_versions=prompt_versions,
        ui=ui,
        sprites=sprites,
        asset_pack=(_read_json(root / "appearance.json").get("asset_pack") if (root/"appearance.json").exists() else None),
        wardrobe=WardrobeConfig(**_read_json(root / "wardrobe.json")) if (root / "wardrobe.json").exists() else None,
        opening=opening,
        scenes=scenes,
    )
    if validate:
        errors = validate_pack(pack, lint_warnings=lint_warnings)
        if errors:
            raise PackError("内容包校验失败：\n- " + "\n- ".join(errors))
    return pack


def validate_pack(pack: ContentPack, lint_warnings: bool = False) -> list[str]:
    """返回阻止加载的问题列表；`lint_warnings=True` 时把 warning 也升级为错误。"""
    from rpg_content.lint import lint_pack

    levels = {"error", "warning"} if lint_warnings else {"error"}
    return [i.message for i in lint_pack(pack) if i.level in levels]
