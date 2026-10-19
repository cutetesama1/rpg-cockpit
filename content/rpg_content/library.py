"""游戏库：一个内容包 = 一个可玩的 RPG；支持扫描、新建、复制、选择。

- 内置包：随程序发布的 `packs/`（只读，除开发环境）。
- 用户包：`RPG_USER_PACKS` 或 `~/.rpg-framework/packs/`，可自由编辑。
- 当前游戏：`RPG_LIBRARY` 或 `~/.rpg-framework/library.json` 里的 `active_pack`。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rpg_content.pack import PackError, load_pack
from rpg_content.scaffold import PACK_ID_RE, scaffold_pack

SLUG_RE = re.compile(r"[^a-z0-9-]+")
#: 导入内容包时允许的最大压缩包大小（字节）。手机端从文件选择器上传，防误传大文件。
MAX_IMPORT_BYTES = 20 * 1024 * 1024


def _config_root() -> Path:
    return Path(os.environ.get("RPG_CONFIG_DIR") or (Path.home() / ".rpg-framework"))


def user_packs_dir() -> Path:
    raw = os.environ.get("RPG_USER_PACKS")
    return Path(raw) if raw else _config_root() / "packs"


def library_path() -> Path:
    raw = os.environ.get("RPG_LIBRARY")
    return Path(raw) if raw else _config_root() / "library.json"


@dataclass
class PackInfo:
    id: str
    title: str
    version: str = ""
    rating: str = ""
    description: str = ""
    path: str = ""
    builtin: bool = False
    valid: bool = True
    error: str = ""
    worldbook_entries: int = 0
    skills: int = 0
    scenes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def slugify(text: str) -> str:
    slug = SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug[:48] or "new-game"


def read_manifest(root: Path) -> dict:
    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PackError("manifest.json 必须是对象")
    return raw


def _info(root: Path, builtin: bool) -> PackInfo:
    info = PackInfo(
        id=root.name,
        title=root.name,
        path=str(root),
        builtin=builtin,
    )
    try:
        manifest = read_manifest(root)
        info.id = str(manifest.get("id") or root.name)
        info.title = str(manifest.get("title") or info.id)
        info.version = str(manifest.get("version") or "")
        info.rating = str(manifest.get("rating") or "")
        info.description = str(manifest.get("description") or "")
    except Exception as exc:  # noqa: BLE001 - 坏包也要列出来
        info.valid = False
        info.error = f"manifest 读取失败：{exc}"
        return info
    try:
        pack = load_pack(root)
        info.worldbook_entries = len(pack.worldbook)
        info.skills = len(pack.skills)
        info.scenes = len(pack.scenes)
    except Exception as exc:  # noqa: BLE001
        info.valid = False
        info.error = str(exc)[:400]
    return info


def scan_dir(root: Path, builtin: bool) -> list[PackInfo]:
    if not root.is_dir():
        return []
    infos = [
        _info(child, builtin)
        for child in sorted(root.iterdir())
        # 以 . 开头的是导入中间目录/隐藏目录，不算内容包
        if child.is_dir() and not child.name.startswith(".") and (child / "manifest.json").is_file()
    ]
    return infos


def list_packs(builtin_dir: Path, user_dir: Path | None = None) -> list[PackInfo]:
    user_dir = user_dir if user_dir is not None else user_packs_dir()
    merged: dict[str, PackInfo] = {}
    for info in scan_dir(builtin_dir, builtin=True) + scan_dir(user_dir, builtin=False):
        # 同 id 时用户包覆盖内置包
        merged[info.id] = info
    return sorted(merged.values(), key=lambda i: (i.builtin, i.title.lower()))


def find_pack(
    pack_id: str, builtin_dir: Path, user_dir: Path | None = None
) -> PackInfo | None:
    for info in list_packs(builtin_dir, user_dir):
        if info.id == pack_id:
            return info
    return None


def resolve_pack_dir(
    pack_id: str, builtin_dir: Path, user_dir: Path | None = None
) -> Path:
    user_dir = user_dir if user_dir is not None else user_packs_dir()
    candidate = user_dir / pack_id
    if (candidate / "manifest.json").is_file():
        return candidate.resolve()
    candidate = builtin_dir / pack_id
    if (candidate / "manifest.json").is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"找不到内容包：{pack_id}")


def load_library(path: Path | None = None) -> dict:
    target = path or library_path()
    if not target.is_file():
        return {"active_pack": ""}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_pack": ""}
    if not isinstance(data, dict):
        return {"active_pack": ""}
    return {
        "active_pack": str(data.get("active_pack") or ""),
        "user_packs_dir": str(data.get("user_packs_dir") or ""),
    }


def save_library(data: dict, path: Path | None = None) -> None:
    target = path or library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def create_pack(
    user_dir: Path,
    *,
    pack_id: str,
    title: str,
    template: str = "minimal",
) -> Path:
    if not PACK_ID_RE.match(pack_id):
        raise ValueError(
            f"游戏 id 不合法：{pack_id!r}（小写字母/数字/连字符，2-64 位，不以连字符开头）"
        )
    if not title.strip():
        raise ValueError("游戏标题不能为空")
    target = user_dir / pack_id
    if target.exists():
        raise FileExistsError(f"游戏 id 已存在：{pack_id}")
    scaffold_pack(target, pack_id, title.strip(), template=template)
    return target


def clone_pack(
    source: Path,
    user_dir: Path,
    *,
    pack_id: str,
    title: str,
) -> Path:
    if not PACK_ID_RE.match(pack_id):
        raise ValueError(f"游戏 id 不合法：{pack_id!r}")
    if not title.strip():
        raise ValueError("游戏标题不能为空")
    target = user_dir / pack_id
    if target.exists():
        raise FileExistsError(f"游戏 id 已存在：{pack_id}")
    user_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest = read_manifest(target)
    manifest["id"] = pack_id
    manifest["title"] = title.strip()
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not load_pack(target):
        raise PackError("复制后内容包无法加载")
    return target


# -- 世界构筑：读取 / 保存 ---------------------------------------------------
WORLD_PROMPT_KEYS = ("pre", "narrator", "settler")


def world_payload(pack_dir: Path, *, editable: bool) -> dict:
    pack = load_pack(pack_dir)
    prompts = {key: pack.prompts.get(key, "") for key in WORLD_PROMPT_KEYS}
    return {
        "pack_id": pack.manifest.id,
        "title": pack.manifest.title,
        "editable": editable,
        "manifest": pack.manifest.model_dump(mode="json"),
        "worldbook": [entry.model_dump(mode="json") for entry in pack.worldbook],
        "skills": [skill.model_dump(mode="json") for skill in pack.skills],
        "prompts": prompts,
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_and_validate(
    pack_dir: Path, writes: dict[Path, str | None]
) -> list[str]:
    """原子式：先备份，写入后重新加载校验；失败恢复并抛 PackError。返回 warning。"""
    backups: dict[Path, bytes | None] = {}
    for path in writes:
        backups[path] = path.read_bytes() if path.exists() else None
    try:
        for path, content in writes.items():
            if content is None:
                if path.exists():
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        pack = load_pack(pack_dir)  # validate=True：有 error 直接抛
    except Exception:
        for path, previous in backups.items():
            if previous is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_bytes(previous)
        raise
    from rpg_content.lint import lint_pack

    return [issue.message for issue in lint_pack(pack) if issue.level == "warning"]


def save_worldbook(pack_dir: Path, entries: list[dict]) -> list[str]:
    from rpg_core.contracts import WorldbookEntry

    parsed = [WorldbookEntry(**entry).model_dump(mode="json") for entry in entries]
    return _replace_and_validate(
        pack_dir,
        {pack_dir / "vocab" / "worldbook.json": json.dumps({"entries": parsed}, ensure_ascii=False, indent=2) + "\n"},
    )


def save_skills(pack_dir: Path, skills: list[dict]) -> list[str]:
    from rpg_core.contracts import SkillSpec

    parsed = [SkillSpec(**skill).model_dump(mode="json") for skill in skills]
    return _replace_and_validate(
        pack_dir,
        {pack_dir / "vocab" / "skills.json": json.dumps({"skills": parsed}, ensure_ascii=False, indent=2) + "\n"},
    )


def save_prompts(pack_dir: Path, prompts: dict[str, str]) -> list[str]:
    unknown = set(prompts) - set(WORLD_PROMPT_KEYS)
    if unknown:
        raise ValueError(f"未知提示词文件：{', '.join(sorted(unknown))}")
    if not prompts:
        raise ValueError("没有要保存的提示词")
    writes: dict[Path, str | None] = {}
    for key, text in prompts.items():
        if not text.strip():
            raise ValueError(f"提示词 {key} 不能为空")
        writes[pack_dir / "prompts" / f"{key}.md"] = text.strip() + "\n"
    return _replace_and_validate(pack_dir, writes)


def _zip_members(archive: zipfile.ZipFile, prefix: str) -> list[zipfile.ZipInfo]:
    """只保留前缀目录下的文件，并拒绝绝对路径 / .. 等危险条目。"""
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        if member.is_dir():
            continue
        name = member.filename
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        if not relative or relative.startswith("/"):
            continue
        if any(part in ("", "..") for part in Path(relative).parts):
            raise PackError("压缩包包含非法路径")
        members.append(member)
    return members


def import_pack_zip(data: bytes, user_dir: Path | None = None) -> PackInfo:
    """把上传的 zip 内容包导入用户包目录（手机端文件选择器 / 桌面端上传共用）。

    - 压缩包根目录或唯一一层子目录里必须有 `manifest.json`；
    - 拒绝 zip-slip（绝对路径 / `..`），限制大小 `MAX_IMPORT_BYTES`；
    - 导入前用 `load_pack` 完整校验，坏包不落盘；
    - 目录名用 manifest 的 id（不合法时回落到 slug），已存在则报错。
    """
    dest_root = (user_dir if user_dir is not None else user_packs_dir()).resolve()
    if not data:
        raise PackError("上传的内容为空")
    if len(data) > MAX_IMPORT_BYTES:
        raise PackError(f"压缩包太大（上限 {MAX_IMPORT_BYTES // (1024 * 1024)} MB）")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackError("不是有效的 zip 文件") from exc

    with archive:
        manifests = [
            name
            for name in archive.namelist()
            if name == "manifest.json" or name.endswith("/manifest.json")
        ]
        if not manifests:
            raise PackError("压缩包里没有 manifest.json（这不是一个内容包）")
        # 取层级最浅的 manifest.json，作为包根
        root_manifest = min(manifests, key=lambda name: name.count("/"))
        prefix = root_manifest[: -len("manifest.json")]
        members = _zip_members(archive, prefix)
        if not members:
            raise PackError("压缩包里没有可导入的文件")

        dest_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".import-", dir=dest_root))
        try:
            for member in members:
                relative = member.filename[len(prefix):]
                target = temp_dir.joinpath(*Path(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)

            try:
                manifest = read_manifest(temp_dir)
            except Exception as exc:  # noqa: BLE001 - 坏 manifest 给用户可读提示
                raise PackError(f"manifest.json 读取失败：{exc}") from exc
            raw_id = str(manifest.get("id") or "").strip()
            pack_id = raw_id if PACK_ID_RE.match(raw_id) else slugify(raw_id or str(manifest.get("title") or "pack"))
            if not pack_id or not PACK_ID_RE.match(pack_id):
                raise PackError("内容包 id 不合法（小写字母/数字/连字符，2-64 位）")
            destination = dest_root / pack_id
            if destination.exists():
                raise PackError(f"内容包 id 已存在：{pack_id}（先删掉旧的再导入）")
            try:
                load_pack(temp_dir)  # 完整校验（manifest/场景/技能/世界书…）
            except Exception as exc:  # noqa: BLE001
                raise PackError(f"内容包校验失败：{exc}") from exc
            temp_dir.rename(destination)
        except BaseException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    return _info(destination, builtin=False)
