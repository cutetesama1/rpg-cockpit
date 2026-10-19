"""Versioned, data-only skill-library ZIP import and world-local snapshot binding."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from rpg_core.contracts import CatalogSkill, SkillSpec, StateSchema
from .pack import PackError

RESOURCE_ALIASES = {"effort": ["stamina", "energy", "focus"], "mana": ["mp", "mana", "focus"]}
MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_UNPACKED_BYTES = 16 * 1024 * 1024
TARGETS = {"self", "enemy", "scene", "item", "npc", "any", "all", "ally"}


class SkillLibraryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["rpg.skill-library"]
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    title: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(default="", max_length=1000)
    resources: dict[str, list[str]] = Field(default_factory=lambda: {k: list(v) for k, v in RESOURCE_ALIASES.items()})


class LibrarySkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    kind: Literal["martial", "magic"]
    tier: Literal["low", "mid", "high"]
    school: str = Field(min_length=1, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=24)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    requires_world_tags: list[str] = Field(default_factory=list, max_length=16)
    excludes_world_tags: list[str] = Field(default_factory=list, max_length=16)
    prerequisites: list[str] = Field(default_factory=list, max_length=16)
    resource_cost: dict[str, float] = Field(default_factory=dict)
    instruction: str = Field(min_length=8, max_length=1600)
    skill: SkillSpec

    @model_validator(mode="after")
    def valid_definition(self):
        if self.skill.id != self.id:
            raise ValueError("skill.id 必须与条目 id 相同")
        if not self.skill.name.strip() or len(self.skill.name) > 30 or not self.skill.action_text.strip():
            raise ValueError("技能需要非空名称（最多30字）和 action_text")
        if self.skill.cost:
            raise ValueError("库内 skill.cost 必须为空；用 resource_cost 声明抽象资源消耗")
        if not 0 <= self.skill.cooldown <= 99 or not self.skill.targets or set(self.skill.targets) - TARGETS:
            raise ValueError("技能冷却或目标不合法")
        if any(not math.isfinite(v) or v < 0 for v in self.resource_cost.values()):
            raise ValueError("资源消耗必须是有限的非负数")
        if self.kind == "magic" and "magic" not in self.requires_world_tags:
            raise ValueError("魔法技能必须声明 requires_world_tags 包含 magic")
        return self


class SkillLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: SkillLibraryManifest
    skills: list[LibrarySkill] = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def references_valid(self):
        ids = {item.id for item in self.skills}
        if len(ids) != len(self.skills):
            raise ValueError("技能 id 重复")
        for role, aliases in self.manifest.resources.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", role) or not aliases or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in aliases):
                raise ValueError("resources 需为资源角色到状态字段 id 列表")
        by_id = {item.id: item for item in self.skills}
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(key):
            if key in visiting: raise ValueError("技能前置条件存在循环")
            if key in visited: return
            visiting.add(key)
            for parent in by_id[key].prerequisites:
                if parent not in by_id: raise ValueError(f"未知前置技能：{parent}")
                visit(parent)
            visiting.remove(key); visited.add(key)
        for item in self.skills:
            if set(item.resource_cost) - self.manifest.resources.keys():
                raise ValueError(f"技能 {item.id} 引用了未声明资源")
            visit(item.id)
        return self


def libraries_dir() -> Path:
    return Path(os.environ.get("RPG_SKILL_LIBRARIES") or (Path(os.environ.get("RPG_CONFIG_DIR") or (Path.home()/".rpg-framework"))/"skill-libraries"))


def load_library(root: Path) -> SkillLibrary:
    manifest = json.loads((root/"manifest.json").read_text(encoding="utf-8-sig"))
    data = json.loads((root/"skills.json").read_text(encoding="utf-8-sig"))
    return SkillLibrary(manifest=manifest, skills=data["skills"])


def installed_libraries(directory: Path | None = None) -> list[SkillLibrary]:
    root = directory or libraries_dir()
    if not root.exists(): return []
    return [load_library(path.parent) for path in sorted(root.glob("*/manifest.json")) if not path.parent.name.startswith(".")]


def library_summary(lib: SkillLibrary) -> dict:
    return {**lib.manifest.model_dump(mode="json"), "count": len(lib.skills),
        "counts": {f"{kind}_{tier}": sum(s.kind==kind and s.tier==tier for s in lib.skills)
                   for kind in ("martial", "magic") for tier in ("low", "mid", "high")}}


def import_skill_library_zip(data: bytes, directory: Path | None = None) -> SkillLibrary:
    if not data or len(data) > MAX_ZIP_BYTES:
        raise PackError("技能库 ZIP 不能为空且不能超过 8 MB")
    root = (directory or libraries_dir()).resolve()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        with archive:
            infos = archive.infolist()
            if len(infos) > 40 or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
                raise PackError("技能库 ZIP 文件数量或展开大小超出限制")
            names = set()
            for info in infos:
                name = info.orig_filename
                parts = PurePosixPath(name).parts
                if "\\" in name or name.startswith("/") or any(p in ("..", ".") or ":" in p for p in parts) or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise PackError("技能库 ZIP 包含非法路径或符号链接")
                if name in names: raise PackError("技能库 ZIP 包含重名文件")
                names.add(name)
            manifests = [n for n in names if n == "manifest.json" or n.endswith("/manifest.json")]
            if len(manifests) != 1: raise PackError("技能库 ZIP 需要唯一的 manifest.json")
            prefix = manifests[0][:-len("manifest.json")]
            if prefix.count("/") > 1: raise PackError("manifest.json 只能位于根目录或一层文件夹中")
            if prefix+"skills.json" not in names: raise PackError("技能库 ZIP 缺少 skills.json")
            manifest = json.loads(archive.read(prefix+"manifest.json").decode("utf-8-sig"))
            skill_data = json.loads(archive.read(prefix+"skills.json").decode("utf-8-sig"))
            lib = SkillLibrary(manifest=manifest, skills=skill_data["skills"])
    except PackError:
        raise
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, RuntimeError, RecursionError) as exc:
        raise PackError(f"技能库格式校验失败：{exc}") from exc
    root.mkdir(parents=True, exist_ok=True)
    target = root/lib.manifest.id
    if target.exists(): raise PackError(f"技能库 id 已存在：{lib.manifest.id}；不会覆盖已有库")
    temp = Path(tempfile.mkdtemp(prefix=".import-",dir=root)).resolve()
    try:
        (temp/"manifest.json").write_text(json.dumps(lib.manifest.model_dump(mode="json"),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (temp/"skills.json").write_text(json.dumps({"skills":[s.model_dump(mode="json") for s in lib.skills]},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        temp.rename(target)
    except BaseException:
        if temp.is_relative_to(root): shutil.rmtree(temp,ignore_errors=True)
        raise
    return lib


def bind_skill(lib: SkillLibrary, entry: LibrarySkill, schema: StateSchema) -> CatalogSkill | None:
    fields = schema.by_id()
    cost: dict[str,float] = {}
    for role, amount in entry.resource_cost.items():
        if amount == 0: continue
        aliases = ([schema.resource_bindings[role]] if schema.resource_bindings[role] else []) if role in schema.resource_bindings else lib.manifest.resources[role]
        field = next((fields[key] for key in aliases if key in fields and fields[key].type in ("int","float")),None)
        if field is None: return None  # Missing resources never silently turn a skill free.
        cost[field.id] = cost.get(field.id,0) + amount
    ref = f"{lib.manifest.id}:{entry.id}"
    skill_id = "preset_"+hashlib.sha256(ref.encode()).hexdigest()[:24]
    skill = entry.skill.model_copy(update={"id":skill_id,"cost":cost})
    return CatalogSkill(ref=ref,library_id=lib.manifest.id,template_id=entry.id,
        kind=entry.kind,tier=entry.tier,school=entry.school,tags=entry.tags,aliases=entry.aliases,
        prerequisites=[f"{lib.manifest.id}:{key}" for key in entry.prerequisites],
        instruction=entry.instruction,resource_cost=entry.resource_cost,skill=skill)
