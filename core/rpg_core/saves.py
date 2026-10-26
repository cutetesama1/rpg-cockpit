"""存档：会话快照 = 内容包 id + 全量账本事件（必要时附状态快照）。

设计（P4）：
- **不限制可玩性**：槽位数量不限、名字自由（规范化为 [a-z0-9._-]）、随时存/随时读；
  读档只替换内存会话，不改内容包、不改模型设置、不削减能力。
- 存档是"事件流 + 投影快照"：状态可由账本重算（replay == live），快照只用于
  快速展示（列表页不必解析全部事件）。
- 一个槽位一个 JSON：`~/.rpg-framework/saves/<slot>.json`（`RPG_SAVES` 覆盖目录）。
- 自动存档槽位固定为 `auto`：每回合提交后覆盖写；启动时若存在且包匹配则自动续玩。
- 日志导出做脱敏：把 `sk-` 形态的 key、`Authorization` 头等替换成掩码。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContentPack
from .runtime import GameSession
from .visibility import player_events

SAVE_VERSION = 1
AUTO_SLOT = "auto"
_SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\b(api[_-]?key|authorization|bearer)\b[\"'\s:=]+[^\s\"',}]+"),
]


def saves_dir() -> Path:
    env = os.environ.get("RPG_SAVES")
    return Path(env) if env else Path.home() / ".rpg-framework" / "saves"


def normalize_slot(slot: str) -> str:
    value = (slot or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    if not value:
        raise ValueError("存档槽位不能为空")
    if not _SLOT_RE.match(value):
        raise ValueError(
            "存档槽位只能用小写字母/数字开头，包含 [a-z0-9._-]，最长 64（例：night-1）"
        )
    return value


def _path(slot: str, directory: Path | None = None) -> Path:
    return (directory or saves_dir()) / f"{normalize_slot(slot)}.json"


def save_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """列表页用的摘要（不含 events）。"""
    return {
        key: payload.get(key)
        for key in (
            "slot",
            "label",
            "saved_at",
            "pack_id",
            "pack_title",
            "pack_version",
            "turn",
            "scene_id",
            "state",
            "inventory",
            "usage",
            "auto",
        )
    }


def snapshot_payload(
    session: GameSession,
    *,
    slot: str,
    label: str = "",
    auto: bool = False,
) -> dict[str, Any]:
    manifest = session.pack.manifest
    return {
        "save_version": SAVE_VERSION,
        "slot": normalize_slot(slot),
        "label": (label or "").strip(),
        "saved_at": datetime.now().astimezone().isoformat(),
        "pack_id": manifest.id,
        "pack_title": manifest.title,
        "pack_version": manifest.version,
        "turn": session.turn,
        "scene_id": session.scene_id,
        "state": session.state,
        "inventory": session.inventory,
        "usage": session.usage_status(),
        "auto": bool(auto),
        "events": session.ledger.to_dicts(),
        "pack_snapshot": session.pack.model_dump(mode="json"),
    }


def save_session(
    session: GameSession,
    *,
    slot: str = AUTO_SLOT,
    label: str = "",
    directory: Path | None = None,
    auto: bool = False,
) -> dict[str, Any]:
    payload = snapshot_payload(session, slot=slot, label=label, auto=auto)
    target = _path(payload["slot"], directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    return save_summary(payload)


def list_saves(
    directory: Path | None = None, *, pack_id: str | None = None
) -> dict[str, Any]:
    folder = directory or saves_dir()
    saves: list[dict[str, Any]] = []
    broken: list[dict[str, str]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not payload.get("events"):
                    raise ValueError("不是有效存档")
            except (OSError, ValueError) as exc:
                broken.append({"slot": path.stem, "error": str(exc)})
                continue
            if pack_id and payload.get("pack_id") != pack_id:
                continue
            saves.append(save_summary(payload))
    saves.sort(key=lambda row: str(row.get("saved_at") or ""), reverse=True)
    return {"ok": True, "dir": str(folder), "saves": saves, "broken": broken}


def read_save(slot: str, directory: Path | None = None) -> dict[str, Any]:
    target = _path(slot, directory)
    if not target.is_file():
        raise FileNotFoundError(f"存档 {slot} 不存在")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"存档 {slot} 读取失败：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError(f"存档 {slot} 格式不正确（缺少 events）")
    return payload


def delete_save(slot: str, directory: Path | None = None) -> bool:
    target = _path(slot, directory)
    if target.is_file():
        target.unlink()
        return True
    return False


def restore_session(session: GameSession, payload: dict[str, Any]) -> dict[str, Any]:
    """把存档事件流装回会话（会话必须已是同一内容包）。返回存档摘要。"""
    saved_pack = str(payload.get("pack_id") or "")
    active = session.pack.manifest.id
    if saved_pack and saved_pack != active:
        raise ValueError(
            f"这个存档属于「{payload.get('pack_title') or saved_pack}」，"
            f"当前游戏是「{active}」。请先在游戏库切换到对应游戏再读档。"
        )
    events = payload.get("events") or []
    if not events:
        raise ValueError("存档里没有事件，无法继续")
    if isinstance(payload.get("pack_snapshot"),dict):
        snapshot=ContentPack.model_validate(payload["pack_snapshot"])
        if snapshot.manifest.id != active:raise ValueError("存档世界定义不匹配")
        # A saved world keeps its rules and numeric definitions while shared
        # portrait templates may gain fields and layers in a newer application.
        current = session.pack
        old_revision = snapshot.sprites.revision if snapshot.sprites else 0
        if current.sprites and current.sprites.revision > old_revision and (
            current.asset_pack == "new-game" or current.manifest.id == "new-game"
        ):
            import copy
            existing = snapshot.state.by_id()
            for field in current.state.fields:
                if field.group not in ('appearance', 'sprite'): continue
                if field.id not in existing: snapshot.state.fields.append(copy.deepcopy(field))
                elif field.id in current.sprites.controls and field.enum_values:
                    existing[field.id].enum_values = list(dict.fromkeys([*(existing[field.id].enum_values or []), *field.enum_values]))
            snapshot.sprites = current.sprites
            snapshot.asset_pack = current.asset_pack
            if current.wardrobe:
                slots = dict(current.wardrobe.slots)
                if snapshot.wardrobe: slots.update(snapshot.wardrobe.slots)
                snapshot.wardrobe = current.wardrobe.model_copy(update={'slots': slots})
        session.pack=snapshot
        session.executor.wardrobe=snapshot.wardrobe
    session.load_events(events)
    expected = payload.get("state")
    if isinstance(expected, dict) and session.pack.wardrobe:
        expected = dict(expected)
        # Only the new wardrobe condition fields may be absent in older saves.
        for slot in session.pack.wardrobe.slots.values():
            expected.setdefault(slot.condition_field, session.pack.state.by_id()[slot.condition_field].default)
    if isinstance(expected,dict) and (session.pack.asset_pack or session.pack.sprites and session.pack.sprites.revision):
        expected=dict(expected)
        # Legacy worlds gaining shared appearance keep their numeric/event history;
        # only registered appearance defaults are additive; numeric game resources stay strict.
        for field in session.pack.state.fields:
            if field.group in ('appearance','sprite'):expected.setdefault(field.id,field.default)
    if isinstance(expected, dict) and expected != session.state:
        raise ValueError("存档状态与会话回放不一致，可能来自不同版本的内容包，已拒绝读档")
    verify = session.verify()
    if not verify.get("equal"):
        raise ValueError("存档自检失败（replay != live），已拒绝读档")
    return save_summary(payload)


# -- 日志导出（脱敏） ---------------------------------------------------------
def redact_text(text: str) -> str:
    if not text:
        return text
    cleaned = _SECRET_PATTERNS[0].sub("sk-***", text)
    cleaned = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}***", cleaned)
    return cleaned


def redact(value: Any) -> Any:
    """递归脱敏：字符串按 key 模式替换，dict/list 递归。"""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def export_log(
    session: GameSession,
    *,
    settings_view: dict[str, Any] | None = None,
    saves: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """可导出的调试日志：当前会话账本 + 打码设置 + 存档清单，全部脱敏。"""
    manifest = session.pack.manifest
    payload = {
        "export_version": 1,
        "exported_at": datetime.now().astimezone().isoformat(),
        "pack": {
            "id": manifest.id,
            "title": manifest.title,
            "version": manifest.version,
            "rating": manifest.rating,
        },
        "turn": session.turn,
        "scene_id": session.scene_id,
        "state": session.state,
        "inventory": session.inventory,
        "usage": session.usage_status(),
        "llm": session.llm_status(),
        "settings": settings_view or {},
        "saves": saves or {},
        "events": player_events(session.ledger.events),
    }
    return redact(payload)


def save_brief(pack: ContentPack | None = None) -> dict[str, Any]:
    """给 UI 的说明文案（不涉及限制）。"""
    return {
        "auto_slot": AUTO_SLOT,
        "dir": str(saves_dir()),
        "note": "存档数量不限、随时可读；读档不会降低任何可玩能力。",
        "pack_id": pack.manifest.id if pack else None,
    }
