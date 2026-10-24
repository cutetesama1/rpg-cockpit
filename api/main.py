"""RPG Framework API：单会话 + 动作/撤销/回放 + 模型设置 + 游戏库/世界构筑 + 存档。

启动：python -m uvicorn main:app --app-dir api --port 8787
环境变量：
- `RPG_PACK`：启动时强制使用某个包（目录名或路径），默认用上次选择的游戏。
- `RPG_USER_PACKS`：用户游戏目录，默认 `~/.rpg-framework/packs`。
- `RPG_LIBRARY`：游戏库状态文件，默认 `~/.rpg-framework/library.json`。
- `RPG_SAVES`：存档目录，默认 `~/.rpg-framework/saves`。
- `RPG_NO_RESUME=1`：启动时不自动读取 `auto` 存档（默认自动续玩）。
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import queue
import shutil
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

if getattr(sys, "frozen", False):
    # PyInstaller onefile：资源随 exe 解包到 _MEIPASS
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    ROOT = Path(__file__).resolve().parents[1]

for _sub in ("core", "gateway", "content"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from rpg_content import PackError, load_pack  # noqa: E402
from rpg_content.library import (  # noqa: E402
    clone_pack,
    create_pack,
    import_pack_zip,
    list_packs,
    load_library,
    resolve_pack_dir,
    save_library,
    save_prompts,
    save_skills,
    save_worldbook,
    user_packs_dir,
    world_payload,
)
from rpg_content.skill_library import (  # noqa: E402
    import_skill_library_zip, installed_libraries, library_summary,
)
from rpg_gateway.skill_selection import configure_world_catalog  # noqa: E402
from rpg_core.contracts import LlmSettings  # noqa: E402
from rpg_core.runtime import GameSession  # noqa: E402
from rpg_core.corrections import Correction, apply as apply_correction, undo as undo_correction
from rpg_core.adjudication import DecisionError
from rpg_core.saves import (  # noqa: E402
    AUTO_SLOT,
    delete_save,
    export_log,
    list_saves,
    read_save,
    restore_session,
    save_brief,
    save_session,
    saves_dir,
)
from rpg_gateway import (  # noqa: E402
    BUILDER_SYSTEM_PROMPT,
    KNOWN_TARGETS,
    PROMPT_KEYS,
    STATE_FIELDS,
    ModelListError,
    build_router,
    builder_compose,
    builder_request,
    catalog_payload,
    default_settings,
    get_preset,
    draft_summary,
    extract_json,
    list_endpoint_models,
    load_settings,
    merge_update,
    parse_draft,
    public_view,
    save_settings,
)

BUILTIN_PACKS = ROOT / "packs"
UI_DIST = ROOT / "ui" / "dist"
API_VERSION = "0.991beta-builder"


# -- 请求体 -----------------------------------------------------------------
class ActionBody(BaseModel):
    request_id: str | None = Field(default=None,max_length=80)
    action: dict[str, Any] = Field(default_factory=dict)


class ModelProbeBody(BaseModel):
    """读取某个端点可用模型列表的请求体。"""

    base_url: str = ""
    api_key: str = ""
    preset: str = ""
    timeout: float = Field(default=10.0, ge=1.0, le=60.0)


class SettingsUpdate(BaseModel):
    """部分更新：api_key 省略或留空表示沿用旧值。"""

    roles: dict[str, Any] | None = None
    providers: dict[str, dict[str, Any]] | None = None


class NewGameBody(BaseModel):
    title: str
    id: str | None = None
    template: str | None = None


class CloneGameBody(BaseModel):
    source: str
    title: str | None = None
    id: str | None = None


class SelectGameBody(BaseModel):
    id: str


class PackImportBody(BaseModel):
    """导入内容包：桌面端/手机端都把 zip 读成 base64 上传。"""

    filename: str = ""
    data_base64: str = ""


class WorldbookBody(BaseModel):
    entries: list[dict[str, Any]]


class SkillsBody(BaseModel):
    skills: list[dict[str, Any]]


class StateConfigBody(BaseModel):
    state: dict[str, Any]
    current_values: dict[str, Any] | None = None


class PromptsBody(BaseModel):
    pre: str | None = None
    narrator: str | None = None
    settler: str | None = None


class BuilderGenerateBody(BaseModel):
    """把一段素材交给模型拆成世界构筑草稿。"""

    material: str
    title_hint: str = ""
    extra_rules: str = ""


class BuilderParseBody(BaseModel):
    """解析用户从外部 AI 粘回来的 JSON 文本。"""

    text: str


class BuilderApplyBody(BaseModel):
    """把（可能已被用户改过的）草稿落成新游戏。"""

    draft: dict[str, Any]
    title: str = ""
    id: str | None = None


class SaveBody(BaseModel):
    slot: str
    label: str = ""


class LoadBody(BaseModel):
    slot: str


class DebugStateBody(BaseModel):
    """调试台：直接改一组状态字段。"""

    changes: dict[str, Any] = {}


class DebugInventoryBody(BaseModel):
    item_id: str
    count: int = 0


class DebugSceneBody(BaseModel):
    scene_id: str


class DebugSkillBody(BaseModel):
    skill_id: str


def _pack_errors(exc: Exception) -> str:
    return str(exc)


class SessionManager:
    def __init__(self) -> None:
        self.settings: LlmSettings = load_settings()
        self.lock = threading.Lock()
        self.builtin_dir = BUILTIN_PACKS
        self.user_dir = user_packs_dir()
        self.library = load_library()
        self.pack_dir: Path = self._initial_pack_dir()
        self._upgrade_wardrobe(self.pack_dir)
        self.session: GameSession = self._safe_build()
        # P4：启动自动续玩（auto 槽位；RPG_NO_RESUME=1 可关，不限制任何玩法）
        self.resumed: bool = self._resume_auto()

    # -- 内容包 ---------------------------------------------------------
    def _initial_pack_dir(self) -> Path:
        raw = os.environ.get("RPG_PACK", "").strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_dir():
                return candidate.resolve()
            try:
                return resolve_pack_dir(raw, self.builtin_dir, self.user_dir)
            except FileNotFoundError:
                pass
        active = str(self.library.get("active_pack") or "").strip()
        if active:
            try:
                return resolve_pack_dir(active, self.builtin_dir, self.user_dir)
            except FileNotFoundError:
                pass
        try:
            return resolve_pack_dir(
                "night-convenience-store", self.builtin_dir, self.user_dir
            )
        except FileNotFoundError:
            packs = list_packs(self.builtin_dir, self.user_dir)
            if not packs:
                raise RuntimeError("没有可用的内容包（packs/ 为空）")
            return Path(packs[0].path)

    @property
    def active_pack(self) -> str:
        return self.session.pack.manifest.id

    def editable(self, pack_dir: Path | None = None) -> bool:
        target = (pack_dir or self.pack_dir).resolve()
        try:
            target.relative_to(self.user_dir.resolve())
            return True
        except ValueError:
            return False

    def _safe_build(self) -> GameSession:
        """配置损坏/端点未填时不阻塞启动：回退脚本假模型。"""
        try:
            return GameSession(load_pack(self.pack_dir), build_router(self.settings))
        except ValueError:
            self.settings = default_settings()
            return GameSession(load_pack(self.pack_dir), build_router(self.settings))

    def _upgrade_wardrobe(self, pack_dir: Path) -> None:
        if self.editable(pack_dir):
            from rpg_content.appearance import attach_default_appearance
            attach_default_appearance(pack_dir, self.builtin_dir / "new-game")
            from rpg_content.migrations import upgrade_wardrobe
            upgrade_wardrobe(pack_dir, self.builtin_dir / "new-game")

    def _activate(self, pack_dir: Path) -> GameSession:
        self._upgrade_wardrobe(pack_dir)
        pack = load_pack(pack_dir)  # 校验失败抛 PackError
        router = build_router(self.settings)
        self.pack_dir = pack_dir.resolve()
        self.session = GameSession(pack, router)
        self.library = {**self.library, "active_pack": pack.manifest.id}
        save_library(self.library)
        return self.session

    def reset(self) -> GameSession:
        self.session = self._safe_build()
        return self.session

    # -- 存档 -----------------------------------------------------------
    def _resume_auto(self) -> bool:
        if os.environ.get("RPG_NO_RESUME", "").strip() == "1":
            return False
        try:
            payload = read_save(AUTO_SLOT)
        except (FileNotFoundError, ValueError):
            return False
        if payload.get("pack_id") != self.active_pack:
            return False
        try:
            restore_session(self.session, payload)
            return True
        except ValueError:
            return False

    def auto_save(self) -> None:
        if os.environ.get("RPG_AUTOSAVE", "").strip() == "0":
            return
        try:
            save_session(self.session, slot=AUTO_SLOT, label="自动存档", auto=True)
        except (OSError, ValueError):
            return

    def saves_view(self) -> dict[str, Any]:
        listing = list_saves(pack_id=self.active_pack)
        return {
            **listing,
            **save_brief(self.session.pack),
            "pack_id": self.active_pack,
            "resumed": self.resumed,
        }

    def save(self, slot: str, label: str) -> dict[str, Any]:
        return save_session(self.session, slot=slot, label=label)

    def load(self, slot: str) -> dict[str, Any]:
        payload = read_save(slot)
        summary = restore_session(self.session, payload)
        self.resumed = True
        return {**summary, "status": self.session.status()}

    def delete_save(self, slot: str) -> bool:
        return delete_save(slot)

    def apply_settings(self, settings: LlmSettings) -> GameSession:
        router = build_router(settings)  # 先校验，失败不落盘不改会话
        save_settings(settings)
        self.settings = settings
        self.session.router = router
        return self.session

    # -- 游戏库 ---------------------------------------------------------
    def packs(self) -> list[dict[str, Any]]:
        rows = []
        for info in list_packs(self.builtin_dir, self.user_dir):
            row = info.to_dict()
            row["editable"] = not info.builtin
            row["active"] = info.id == self.active_pack
            rows.append(row)
        return rows

    def library_view(self) -> dict[str, Any]:
        return {
            "ok": True,
            "active_pack": self.active_pack,
            "active_pack_dir": str(self.pack_dir),
            "packs": self.packs(),
            "builtin_dir": str(self.builtin_dir),
            "user_dir": str(self.user_dir),
            "library_path": str(self.user_dir.parent / "library.json"),
        }

    def select(self, pack_id: str) -> GameSession:
        try:
            target = resolve_pack_dir(pack_id, self.builtin_dir, self.user_dir)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        return self._activate(target)

    def create(self, title: str, pack_id: str | None = None, template: str | None = None) -> GameSession:
        from rpg_content.library import slugify

        new_id = (pack_id or "").strip() or slugify(title)
        try:
            target = create_pack(
                self.user_dir,
                pack_id=new_id,
                title=title,
                template=template or "minimal",
            )
        except (ValueError, FileExistsError) as exc:
            raise ValueError(str(exc)) from exc
        try:
            from rpg_content.state_config import write_initial_state,suggest_state
            write_initial_state(target,suggest_state(title))
            self._configure_skill_catalog(target)
            session = self._activate(target)
            self._record_selection_usage(session)
            return session
        except Exception:
            if target.resolve().is_relative_to(self.user_dir.resolve()):
                shutil.rmtree(target, ignore_errors=True)
            raise

    def clone(self, source: str, title: str | None, pack_id: str | None) -> GameSession:
        from rpg_content.library import slugify

        try:
            source_dir = resolve_pack_dir(source, self.builtin_dir, self.user_dir)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        source_pack = load_pack(source_dir)
        new_title = (title or "").strip() or f"{source_pack.manifest.title} 副本"
        new_id = (pack_id or "").strip() or slugify(new_title)
        try:
            target = clone_pack(source_dir, self.user_dir, pack_id=new_id, title=new_title)
        except (ValueError, FileExistsError) as exc:
            raise ValueError(str(exc)) from exc
        return self._activate(target)

    def _configure_skill_catalog(self, target: Path, *, preserve_initial: bool = False) -> dict:
        return configure_world_catalog(target, installed_libraries(), build_router(self.settings), preserve_initial=preserve_initial)

    def _record_selection_usage(self, session: GameSession) -> None:
        selection = session.pack.skill_selection
        if selection.get("method") == "llm":
            session._record(turn=0,kind="llm.usage",role="settler",payload={
                "provider":"skill-selection","model":selection.get("model", ""),
                "usage":selection.get("usage", {}),"cost_usd":selection.get("cost_usd", 0),"latency_ms":0,"attempts":1})

    def _sync_current_config(self):
        from rpg_core.world_config import config_of
        from rpg_content.library import _replace_and_validate
        data=config_of(self.session.pack)
        writes={self.pack_dir/'state.json':json.dumps(data['state'],ensure_ascii=False),self.pack_dir/'ui/layout.json':json.dumps(data['ui'],ensure_ascii=False),self.pack_dir/'vocab/skills.json':json.dumps({'skills':data['skills']},ensure_ascii=False)}
        if self.session.pack.skill_selection:writes[self.pack_dir/'vocab/skill_catalog.json']=json.dumps({'schema_version':1,'selection':self.session.pack.skill_selection,'skills':data['skill_catalog']},ensure_ascii=False)
        _replace_and_validate(self.pack_dir,writes)

    def _reload_content(self):
        from rpg_core.world_config import config_of
        old=self.session;pack=load_pack(self.pack_dir)
        events=[e.model_dump(mode='json') for e in old.ledger.events]
        new=GameSession(pack,build_router(self.settings))
        if events:new.load_events(events)
        if any(e.kind=='world.configured' for e in old.ledger.events) and config_of(pack)!=config_of(old.pack):
            values={f.id:old.state.get(f.id,f.default) for f in pack.state.fields}
            turn=new._next_turn()
            new._record(turn=turn,kind='world.configured',actor='player',payload={'before':config_of(old.pack),'after':config_of(pack),'values':values})
            new._record(turn=turn,kind='turn.committed',actor='player',payload={'configuration':True})
            new.pack=pack;new._refresh_executor_skills()
        self.session=new

    def match_current_skill_catalog(self) -> dict:
        self._require_editable()
        self._sync_current_config()
        result = self._configure_skill_catalog(self.pack_dir, preserve_initial=self.session.turn > 0)
        self._reload_content()
        return result

    def world_skill_catalog(self) -> dict:
        from rpg_core.skill_catalog import known_refs
        known = known_refs(self.session.pack.skill_catalog, self.session.all_skills())
        return {"ok":True,"selection":self.session.pack.skill_selection,"editable":self.editable(),
            "skills":[{**e.model_dump(mode="json"),"known":e.ref in known,
                "learnable":e.ref not in known and set(e.prerequisites)<=known,
                "missing_prerequisites":sorted(set(e.prerequisites)-known)} for e in self.session.pack.skill_catalog]}

    # -- 世界构筑 -------------------------------------------------------
    def world(self) -> dict[str, Any]:
        from rpg_content.state_config import normalize_state
        return {"ok": True, **world_payload(self.pack_dir, editable=self.editable()), "state":normalize_state(self.session.pack.state.model_dump(mode="json")), "current_values":self.session.state}

    def _require_editable(self) -> None:
        if not self.editable():
            raise ValueError(
                "内置内容包只读：请先在游戏库里「复制为新游戏」，再到副本里编辑世界书/技能/提示词。"
            )

    def update_worldbook(self, entries: list[dict]) -> list[str]:
        self._require_editable()
        self._sync_current_config()
        warnings = save_worldbook(self.pack_dir, entries)
        self._reload_content()
        return warnings

    def update_skills(self, skills: list[dict]) -> list[str]:
        self._require_editable()
        self._sync_current_config()
        warnings = save_skills(self.pack_dir, skills)
        self._reload_content()
        return warnings

    def update_prompts(self, prompts: dict[str, str]) -> list[str]:
        self._require_editable()
        self._sync_current_config()
        warnings = save_prompts(self.pack_dir, prompts)
        self._reload_content()
        return warnings

    # -- 世界构筑助手（AI 快速创建）----------------------------------------
    def builder_prompt(self, material: str = "", *, title_hint: str = "", extra_rules: str = "") -> str:
        if material.strip():
            return builder_compose(material, title_hint=title_hint, extra_rules=extra_rules)
        return BUILDER_SYSTEM_PROMPT

    def builder_generate(
        self, material: str, *, title_hint: str = "", extra_rules: str = ""
    ) -> dict[str, Any]:
        material = (material or "").strip()
        if len(material) < 20:
            raise ValueError("素材太短：至少给一段 20 字以上的世界观/剧情/规则描述")
        router = build_router(self.settings)
        request = builder_request(material, title_hint=title_hint, extra_rules=extra_rules)
        try:
            response = router.complete("narrator", request)
        except Exception as exc:  # noqa: BLE001 - 模型错误原样转 400 供界面显示
            raise ValueError(f"模型调用失败：{exc}") from exc
        text = (response.narrator.narrative if response.narrator else "") or response.raw
        try:
            payload = extract_json(text)
        except ValueError as exc:
            preview = " ".join(text.split())[:280]
            raise ValueError(f"{exc}。模型实际返回的开头：{preview or '（空）'}") from exc
        try:
            draft = parse_draft(payload)
        except ValueError as exc:
            preview = " ".join(json.dumps(payload, ensure_ascii=False).split())[:280]
            raise ValueError(f"{exc}。模型输出的 JSON 开头：{preview}") from exc
        if not draft["title"]:
            draft["title"] = title_hint.strip() or "未命名世界"
        return {
            "ok": True,
            "draft": draft,
            "summary": draft_summary(draft),
            "model": response.model,
            "provider": response.provider,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
        }

    def builder_apply(self, draft: dict[str, Any], *, title: str = "", pack_id: str | None = None) -> dict[str, Any]:
        parsed = parse_draft(draft)
        name = (title or parsed["title"] or "").strip()
        if not name:
            raise ValueError("请填写作品名（草稿里没有 title，需要手动给一个）")
        import hashlib

        from rpg_content.library import slugify

        new_id = (pack_id or "").strip() or slugify(name)
        if new_id == "new-game":
            # 纯中文标题没有 ascii 骨架：用稳定哈希生成一个可读性尚可的 id
            new_id = "world-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        try:
            target = create_pack(self.user_dir, pack_id=new_id, title=name, template="minimal")
        except (ValueError, FileExistsError) as exc:
            raise ValueError(str(exc)) from exc
        try:
            warnings: list[str] = []
            from rpg_content.state_config import write_initial_state
            write_initial_state(target,parsed['state'])
            (target/'character_profile.json').write_text(json.dumps(parsed.get('character_profile',{}),ensure_ascii=False),encoding='utf-8')
            if parsed["description"]:
                manifest_path = target / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["description"] = parsed["description"]
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            if parsed["prompts"]:
                warnings += save_prompts(target, parsed["prompts"])
            if parsed["worldbook"]:
                warnings += save_worldbook(target, parsed["worldbook"])
            if parsed["skills"]:
                warnings += save_skills(target, parsed["skills"])
            selection = self._configure_skill_catalog(target)
            warnings += selection.get("warnings", [])
            session = self._activate(target)
            self._record_selection_usage(session)
        except Exception:
            if target.resolve().is_relative_to(self.user_dir.resolve()):
                shutil.rmtree(target, ignore_errors=True)
            raise
        return {
            "ok": True,
            "warnings": list(dict.fromkeys(warnings)),
            "world": self.world(),
            **self.library_view(),
            "status": self.session.status(),
            "pack_id": self.active_pack,
            "skill_selection": self.session.pack.skill_selection,
        }


manager = SessionManager()
app = FastAPI(title="RPG Framework", version=API_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _settings_payload() -> dict[str, Any]:
    return {"ok": True, **public_view(manager.settings)}


# -- 健康 / 会话 -------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": API_VERSION,
        "pack": manager.session.pack.manifest.id,
        "pack_title": manager.session.pack.manifest.title,
        "pack_editable": manager.editable(),
        "llm": manager.session.llm_status(),
        "usage": manager.session.usage_status(),
        "resumed": manager.resumed,
        "saves_dir": str(saves_dir()),
    }


@app.post("/api/session")
def new_session() -> dict[str, Any]:
    return manager.reset().status()


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return manager.session.status()


@app.post("/api/action")
def submit_action(body: ActionBody) -> dict[str, Any]:
    with manager.lock:
        result = manager.session.submit_action(body.action,body.request_id)
        # Preserve private draw receipts even when a turn is rolled back.
        manager.auto_save()
    return asdict(result)


@app.post("/api/opening")
def generate_opening() -> dict[str, Any]:
    """新游戏开局：让叙事模型生成开场叙述（幂等，不占回合、不改状态）。"""
    with manager.lock:
        result = manager.session.start_opening()
        if result.get("ok"):
            manager.auto_save()
        status = manager.session.status()
    return {**result, "status": status}


def _session_stream(*, action: dict[str, Any] | None = None, request_id: str | None = None, correction: Correction | None = None) -> StreamingResponse:
    """Public narrative snapshots are transient; only the final transaction is saved."""
    def generate():
        bus: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        connected = threading.Event()
        connected.set()

        def send(kind: str, payload: Any) -> None:
            if connected.is_set():
                bus.put((kind, payload))

        def work() -> None:
            try:
                with manager.lock:
                    session = manager.session
                    previous = session.on_event, session.on_narrative
                    session.on_event = lambda event: send("event", event)
                    session.on_narrative = lambda update: send("narrative", update)
                    try:
                        if correction is not None:
                            result = apply_correction(session, correction)
                            manager.auto_save()
                            payload = {**result, "status": session.status()}
                        elif action is None:
                            result = session.start_opening()
                            if result.get("ok"):
                                manager.auto_save()
                            payload = {**result, "status": session.status()}
                        else:
                            result = session.submit_action(action,request_id)
                            manager.auto_save()
                            payload = asdict(result)
                    finally:
                        session.on_event, session.on_narrative = previous
                send("result", payload)
            except Exception as exc:
                send("error", {"error": str(exc)})
            finally:
                send("done", None)

        threading.Thread(target=work, daemon=True).start()
        try:
            while True:
                try:
                    kind, payload = bus.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                if kind == "done":
                    break
                data = json.dumps(payload, ensure_ascii=False, default=str)
                yield f"event: {kind}\ndata: {data}\n\n"
        finally:
            # A disconnect stops queuing previews; the atomic turn still finishes.
            connected.clear()

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/action/stream")
def submit_action_stream(body: ActionBody) -> StreamingResponse:
    return _session_stream(action=body.action,request_id=body.request_id)


@app.post("/api/opening/stream")
def generate_opening_stream() -> StreamingResponse:
    return _session_stream()



@app.post('/api/corrections')
def correct_ai(body: Correction):
    with manager.lock:
        try:
            result = apply_correction(manager.session, body)
        except DecisionError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        manager.auto_save()
        return {**result, 'status': manager.session.status()}


@app.post('/api/corrections/stream')
def correct_ai_stream(body: Correction):
    return _session_stream(correction=body)


class CorrectionUndoBody(BaseModel):
    pack_id: str
    receipt_id: int


@app.post('/api/corrections/undo')
def correct_ai_undo(body: CorrectionUndoBody):
    with manager.lock:
        try:
            result = undo_correction(manager.session, body.pack_id, body.receipt_id)
        except DecisionError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        manager.auto_save()
        return {**result, 'status': manager.session.status()}


@app.post("/api/undo")
def undo() -> dict[str, Any]:
    with manager.lock:
        payload = manager.session.undo()
        manager.auto_save()
        return payload


@app.get("/api/replay/verify")
def replay_verify() -> dict[str, Any]:
    return manager.session.verify()


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    with manager.lock:
        return manager.reset().status()


# -- 存档 -------------------------------------------------------------------
@app.get("/api/saves")
def get_saves() -> dict[str, Any]:
    return manager.saves_view()


@app.post("/api/saves")
def create_save(body: SaveBody) -> dict[str, Any]:
    try:
        with manager.lock:
            summary = manager.save(body.slot, body.label)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "save": summary, "saves": manager.saves_view()}


@app.post("/api/saves/load")
def load_save(body: LoadBody) -> dict[str, Any]:
    try:
        with manager.lock:
            payload = manager.load(body.slot)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **payload, "saves": manager.saves_view()}


@app.delete("/api/saves/{slot}")
def drop_save(slot: str) -> dict[str, Any]:
    try:
        removed = manager.delete_save(slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "removed": removed, "saves": manager.saves_view()}


# -- 调试台（本地测试：改状态/物品/场景/技能，全部写账本、可撤销） ------------
@app.get("/api/debug/catalog")
def debug_catalog() -> dict[str, Any]:
    return manager.session.debug_catalog()


def _debug_apply(action: Callable[["GameSession"], dict[str, Any]]) -> dict[str, Any]:
    """统一加锁 + 自动存档 + 带回最新 status（UI 改完即可直接刷新）。"""
    with manager.lock:
        try:
            result = action(manager.session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result.get("changed"):
            manager.auto_save()
        return {**result, "status": manager.session.status()}


@app.post("/api/debug/state")
def debug_state(body: DebugStateBody) -> dict[str, Any]:
    return _debug_apply(lambda session: session.debug_set_state(body.changes))


@app.post("/api/debug/reset")
def debug_reset() -> dict[str, Any]:
    return _debug_apply(lambda session: session.debug_reset_state())


@app.post("/api/debug/inventory")
def debug_inventory(body: DebugInventoryBody) -> dict[str, Any]:
    return _debug_apply(lambda session: session.debug_set_inventory(body.item_id, body.count))


@app.post("/api/debug/scene")
def debug_scene(body: DebugSceneBody) -> dict[str, Any]:
    return _debug_apply(lambda session: session.debug_jump_scene(body.scene_id))


@app.post("/api/debug/skill")
def debug_skill(body: DebugSkillBody) -> dict[str, Any]:
    return _debug_apply(lambda session: session.debug_learn_skill(body.skill_id))


@app.get("/api/log/export")
def export_debug_log() -> JSONResponse:
    from fastapi.responses import JSONResponse as _JSONResponse

    log = export_log(
        manager.session,
        settings_view=_settings_payload(),
        saves=manager.saves_view(),
    )
    payload = json.dumps(log, ensure_ascii=False, indent=1)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return _JSONResponse(
        content=log,
        headers={
            "Content-Disposition": f'attachment; filename="rpg-log-{stamp}.json"',
            "X-Log-Bytes": str(len(payload.encode("utf-8"))),
        },
    )


# -- 游戏库 -----------------------------------------------------------------
@app.get("/api/sprite")
def get_sprite() -> dict[str, Any]:
    """当前内容包的立绘配置（没有配置就返回 sheet=None，前端不显示）。"""
    sheet = manager.session.pack.sprites
    return {
        "pack": manager.active_pack,
        "sheet": {**sheet.model_dump(mode="json"),"resource_bindings":manager.session.pack.state.resource_bindings,"asset_key":manager.active_pack+":"+manager.session.appearance_revision()} if sheet is not None else None,
    }


@app.get("/api/pack/asset/{asset_path:path}")
def get_pack_asset(asset_path: str) -> FileResponse:
    """读取当前内容包里的静态素材（立绘图层）。

    只允许访问内容包目录内的文件；路径穿越、绝对路径、隐藏文件一律拒绝。
    """
    root = manager.pack_dir.resolve()
    try:
        target = (root / asset_path).resolve()
    except OSError as exc:  # 非法路径字符
        raise HTTPException(status_code=400, detail=f"非法素材路径：{exc}") from exc
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="素材路径越界") from exc
    if not target.is_file() and manager.session.pack.asset_pack:
        asset_pack = manager.session.pack.asset_pack
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", asset_pack):
            raise HTTPException(status_code=400, detail="立绘资源包 id 无效")
        shared_root = (BUILTIN_PACKS / asset_pack).resolve()
        shared_target = (shared_root / asset_path).resolve()
        if shared_target.is_relative_to(shared_root): target = shared_target
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"素材不存在：{asset_path}")
    suffix = target.suffix.lower()
    if suffix not in {".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg"}:
        raise HTTPException(status_code=403, detail=f"不支持的素材类型：{suffix}")
    return FileResponse(
        target,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/library")
def get_library() -> dict[str, Any]:
    return manager.library_view()


@app.post("/api/library/new")
def new_game(body: NewGameBody) -> dict[str, Any]:
    try:
        with manager.lock:
            manager.create(body.title, body.id, body.template)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=_pack_errors(exc)) from exc
    return {**manager.library_view(), "status": manager.session.status()}


@app.post("/api/library/clone")
def clone_game(body: CloneGameBody) -> dict[str, Any]:
    try:
        with manager.lock:
            manager.clone(body.source, body.title, body.id)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=_pack_errors(exc)) from exc
    return {**manager.library_view(), "status": manager.session.status()}


@app.post("/api/library/select")
def select_game(body: SelectGameBody) -> dict[str, Any]:
    try:
        with manager.lock:
            manager.select(body.id)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=_pack_errors(exc)) from exc
    return {**manager.library_view(), "status": manager.session.status()}


@app.post("/api/library/import")
def import_game(body: PackImportBody) -> dict[str, Any]:
    """导入一个 zip 内容包到用户包目录（不切换当前游戏）。"""
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="上传数据不是合法的 base64") from exc
    try:
        info = import_pack_zip(data, manager.user_dir)
    except PackError as exc:
        raise HTTPException(status_code=400, detail=_pack_errors(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"写入失败：{exc}") from exc
    return {"ok": True, "pack": info.to_dict(), "library": manager.library_view()}


# -- 技能库：数据 ZIP 导入 / 浏览 / 世界技能池 -------------------------------
def _library_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc)[:600])


@app.get("/api/skill-libraries")
def get_skill_libraries() -> dict[str, Any]:
    try:
        libs = installed_libraries()
        return {"ok":True,"libraries":[library_summary(lib) for lib in libs],"total_skills":sum(len(lib.skills) for lib in libs)}
    except (ValueError, OSError, KeyError) as exc:
        raise _library_error(exc) from exc


@app.post("/api/skill-libraries/import")
def import_skill_library(body: PackImportBody) -> dict[str, Any]:
    try:
        data = base64.b64decode(body.data_base64, validate=True)
        with manager.lock:
            lib = import_skill_library_zip(data)
        return {"ok":True,"library":library_summary(lib),**get_skill_libraries()}
    except (ValueError, OSError, PackError) as exc:
        raise _library_error(exc) from exc


@app.post("/api/skill-libraries/install-standard")
def install_standard_skills() -> dict[str, Any]:
    try:
        with manager.lock:
            lib = import_skill_library_zip((ROOT/"skill-libraries/standard-300.zip").read_bytes())
        return {"ok":True,"library":library_summary(lib),**get_skill_libraries()}
    except (ValueError, OSError, PackError) as exc:
        raise _library_error(exc) from exc


@app.get("/api/skill-libraries/template.zip")
def download_skill_library_template() -> FileResponse:
    return FileResponse(ROOT/"skill-libraries/author-template.zip", media_type="application/zip",filename="skill-library-author-template.zip")


@app.get("/api/skill-libraries/{library_id}")
def get_skill_library(library_id: str) -> dict[str, Any]:
    try:
        lib = next((lib for lib in installed_libraries() if lib.manifest.id == library_id), None)
        if lib is None: raise HTTPException(status_code=404, detail="技能库不存在")
        return {"ok":True, **lib.model_dump(mode="json")}
    except (ValueError, OSError, KeyError) as exc:
        raise _library_error(exc) from exc


@app.get("/api/world/skill-catalog")
def get_world_skill_catalog() -> dict[str, Any]:
    with manager.lock:
        return manager.world_skill_catalog()


@app.post("/api/world/skill-catalog/match")
def match_world_skill_catalog() -> dict[str, Any]:
    try:
        with manager.lock:
            result = manager.match_current_skill_catalog()
            manager.auto_save()
        return {"ok":True,"selection":result,"status":manager.session.status()}
    except (ValueError, OSError, PackError) as exc:
        raise _library_error(exc) from exc


# -- 世界构筑 ---------------------------------------------------------------
@app.get("/api/world")
def get_world() -> dict[str, Any]:
    return manager.world()


@app.put("/api/world/worldbook")
def put_worldbook(body: WorldbookBody) -> dict[str, Any]:
    try:
        with manager.lock:
            warnings = manager.update_worldbook(body.entries)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "warnings": warnings, "world": manager.world()}


@app.put("/api/world/skills")
def put_skills(body: SkillsBody) -> dict[str, Any]:
    try:
        with manager.lock:
            warnings = manager.update_skills(body.skills)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "warnings": warnings, "world": manager.world()}


@app.put("/api/world/prompts")
def put_prompts(body: PromptsBody) -> dict[str, Any]:
    prompts = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        with manager.lock:
            warnings = manager.update_prompts(prompts)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "warnings": warnings, "world": manager.world()}


# -- 世界构筑助手（AI 快速创建）--------------------------------------------
@app.put('/api/world/state')
def put_world_state(body:StateConfigBody):
    try:
        with manager.lock:
            manager._require_editable()
            from rpg_content.state_config import reconfigure
            warnings=reconfigure(manager.session,manager.pack_dir,body.state,body.current_values)
            manager.auto_save()
        return {'ok':True,'warnings':warnings,'world':manager.world(),'status':manager.session.status()}
    except (ValueError,PackError) as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@app.post('/api/world/skill-catalog/repair-initial')
def repair_initial_skills():
    try:
        with manager.lock:
            manager._require_editable()
            manager._sync_current_config()
            result=manager._configure_skill_catalog(manager.pack_dir,preserve_initial=False)
            manager._reload_content()
            manager.auto_save()
        return {'ok':True,'selection':result,'status':manager.session.status()}
    except (ValueError,PackError) as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@app.get("/api/world/builder/prompt")
def get_builder_prompt() -> dict[str, Any]:
    """可复制给任何外部 AI 的世界构筑提示词。**

    界面上的「复制提示词」按钮用它；也允许带上素材直接拼成完整提示词。
    """
    return {
        "ok": True,
        "prompt": manager.builder_prompt(),
        "state_fields": list(STATE_FIELDS),
        "targets": sorted(KNOWN_TARGETS),
        "prompt_keys": list(PROMPT_KEYS),
    }


@app.post("/api/world/builder/generate")
def builder_generate(body: BuilderGenerateBody) -> dict[str, Any]:
    """用当前配置的模型把素材拆成草稿（不落盘，先给用户预览/编辑）。"""
    try:
        with manager.lock:
            return manager.builder_generate(
                body.material, title_hint=body.title_hint, extra_rules=body.extra_rules
            )
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/world/builder/parse")
def builder_parse(body: BuilderParseBody) -> dict[str, Any]:
    """把粘贴回来的模型输出解析成草稿（只校验归一化，不落盘）。"""
    try:
        draft = parse_draft(extract_json(body.text))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "draft": draft, "summary": draft_summary(draft)}


@app.post("/api/world/builder/apply")
def builder_apply(body: BuilderApplyBody) -> dict[str, Any]:
    """按草稿新建一个用户内容包（提示词/世界书/技能一次写全）并切换过去。"""
    try:
        with manager.lock:
            return manager.builder_apply(body.draft, title=body.title, pack_id=body.id)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- 模型设置 ---------------------------------------------------------------
@app.get("/api/models")
def list_models() -> dict[str, Any]:
    """模型供应商目录：预设端点 + 常见模型 + 支持哪些思考强度。"""
    return {"ok": True, **catalog_payload()}


@app.post("/api/models/probe")
def probe_models(body: ModelProbeBody) -> dict[str, Any]:
    """用本次填的（或该供应商已保存的）Key 读取端点真实可用模型列表。

    界面上的「读取可用模型」按钮走这里：先取 `{base_url}/models`，
    再把 id 列表交给前端做下拉选择，免得用户手打模型名。
    """
    base_url = body.base_url.strip()
    preset = body.preset.strip()
    if not base_url and preset:
        endpoint = get_preset(preset)
        base_url = str((endpoint or {}).get("base_url") or "")
    api_key = body.api_key.strip()
    if not api_key and preset:
        saved = manager.settings.providers.get(preset)
        api_key = saved.api_key if saved is not None else ""
    try:
        result = list_endpoint_models(base_url, api_key, timeout=body.timeout)
    except ModelListError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return _settings_payload()


@app.post("/api/settings")
def update_settings(body: SettingsUpdate) -> dict[str, Any]:
    try:
        merged = merge_update(manager.settings, body.model_dump(exclude_none=True))
        with manager.lock:
            manager.apply_settings(merged)
    except (ValueError, PackError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_payload()


@app.post("/api/settings/reset")
def reset_settings() -> dict[str, Any]:
    manager.apply_settings(default_settings())
    return _settings_payload()


@app.post("/api/settings/test")
def test_settings(body: SettingsUpdate | None = None) -> dict[str, Any]:
    """用当前（或本次提交但未保存的）设置发一次最小请求，验证端点可用。"""
    try:
        settings = (
            merge_update(manager.settings, body.model_dump(exclude_none=True))
            if body is not None
            else manager.settings
        )
        router = build_router(settings)
        request = {
            "system_prompt": "你是连通性测试。用一句中文回答即可。",
            "state_brief": "",
            "vocab": "",
            "recent": "",
            "action": {"kind": "text", "text": "测试连接"},
        }
        started = time.perf_counter()
        response = router.complete("narrator", request)
        latency = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": True,
            "provider": response.provider,
            "model": response.model,
            "latency_ms": latency,
            "tool_calls": [c.name for c in response.tool_calls],
            "narrative": (response.narrator.narrative if response.narrator else "")[:120],
        }
    except Exception as exc:  # noqa: BLE001 - 测试端点把错误原样返回
        return {"ok": False, "error": str(exc)}


# -- Optional plot director and deterministic dice ---------------------------
from rpg_core.plot_director import DirectorConfig,PlotClue,configure as configure_director,view as director_view,put_clue,request_once
from rpg_core.dice import Check,resolve as resolve_dice

class DirectorUpdateBody(BaseModel):
    pack_id: str
    config: DirectorConfig

class DirectorRequestBody(BaseModel):
    pack_id: str

class DirectorClueBody(BaseModel):
    pack_id: str
    clue: PlotClue

class DiceBody(BaseModel):
    pack_id: str
    event_id: str = Field(min_length=1,max_length=160)
    check: Check

def require_current_pack(pack_id):
    if pack_id!=manager.active_pack:raise HTTPException(409,"游戏已切换，请重新读取当前游戏")

@app.get("/api/director")
def get_director(include_internal: bool=False):
    with manager.lock:return {"pack_id":manager.active_pack,**director_view(manager.session,include_internal=include_internal)}

@app.put("/api/director")
def set_director(body:DirectorUpdateBody):
    with manager.lock:
        require_current_pack(body.pack_id)
        try:result=configure_director(manager.session,body.config)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        manager.auto_save()
        return {"pack_id":manager.active_pack,**result}

@app.post("/api/director/request")
def ask_director(body:DirectorRequestBody):
    with manager.lock:
        require_current_pack(body.pack_id)
        try:result=request_once(manager.session)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        manager.auto_save();return {"pack_id":manager.active_pack,**result}

@app.put("/api/director/clues")
def update_director_clue(body:DirectorClueBody):
    with manager.lock:
        require_current_pack(body.pack_id);put_clue(manager.session,body.clue);manager.auto_save()
        return {"pack_id":manager.active_pack,**director_view(manager.session)}

@app.post("/api/dice/roll")
def manual_dice(body:DiceBody):
    with manager.lock:
        require_current_pack(body.pack_id)
        if body.event_id.startswith(('director:','settlement:')):raise HTTPException(400,"手动检定不能使用系统事件命名空间")
        try:result,reused=resolve_dice(manager.session,'manual:'+body.event_id,body.check,turn=0)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        if not any(e.kind=='roll.resolved' and e.payload.get('event_id')==result['event_id'] for e in manager.session.ledger.events):
            manager.session._record(turn=0,kind='roll.resolved',payload={**result,'origin':'manual'})
        manager.auto_save();return {"result":result,"reused":reused}


# -- Player adjudication center -------------------------------------------
from rpg_core.adjudication import Decision,DecisionError,view as adjudication_view,preview as adjudication_preview,act as adjudication_act

class AdjudicationBody(BaseModel):
    model_config = {'extra': 'forbid'}
    pack_id: str
    include_internal: bool=False
    decision: Decision

@app.get('/api/adjudications/editor')
def get_adjudication_editor():
    from rpg_core.adjudication_editor import editor_catalog
    with manager.lock:return editor_catalog(manager.session)

@app.get('/api/adjudications')
def get_adjudications(include_internal: bool=False):
    with manager.lock:return adjudication_view(manager.session,include_internal=include_internal)

@app.post('/api/adjudications/{item_id}/preview')
def preview_adjudication(item_id: str,body: AdjudicationBody):
    with manager.lock:
        require_current_pack(body.pack_id)
        try:return adjudication_preview(manager.session,item_id,body.decision,include_internal=body.include_internal)
        except (ValueError,DecisionError) as exc:raise HTTPException(getattr(exc,'status',400),str(exc)) from None

@app.post('/api/adjudications/{item_id}/decide')
def decide_adjudication(item_id: str,body: AdjudicationBody):
    with manager.lock:
        require_current_pack(body.pack_id)
        try:result=adjudication_act(manager.session,item_id,body.decision,include_internal=body.include_internal)
        except (ValueError,DecisionError) as exc:raise HTTPException(getattr(exc,'status',400),str(exc)) from None
        manager.auto_save()
        return {**result,**adjudication_view(manager.session,include_internal=body.include_internal)}


# -- Character Card V2/V3 ------------------------------------------------
from rpg_content.character_cards import CardOptions,CardError,MAX_FILE,preview_card,create_card_pack

class CharacterCardBody(BaseModel):
    model_config={'extra':'forbid'}
    filename: str=Field(default='',max_length=255)
    data_base64: str=Field(min_length=1,max_length=28*1024*1024)
    options: CardOptions=Field(default_factory=CardOptions)

class CharacterCardImportBody(CharacterCardBody):
    request_id: str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9_.:-]+$')
    preview_token: str=Field(min_length=64,max_length=64)
    expected_pack_id: str

def _card_bytes(body):
    try:raw=base64.b64decode(body.data_base64,validate=True)
    except (ValueError,binascii.Error):raise HTTPException(400,'文件 Base64 编码不合法') from None
    if len(raw)>MAX_FILE:raise HTTPException(400,'角色卡文件不能超过 20 MB')
    return raw

@app.post('/api/character-cards/preview')
def preview_character_card(body:CharacterCardBody):
    try:result=preview_card(_card_bytes(body),body.filename,body.options)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    with manager.lock:return {**result,'active_pack_id':manager.active_pack}

@app.post('/api/character-cards/import')
def import_character_card(body:CharacterCardImportBody):
    raw=_card_bytes(body)
    try:preview=preview_card(raw,body.filename,body.options)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    if preview['preview_token']!=body.preview_token:raise HTTPException(409,'文件或映射选项已变化，请重新预览后导入')
    with manager.lock:
        # Repeated network requests return their existing pack without resetting
        # a game or switching away from a newer user choice.
        for path in manager.user_dir.glob('*/character-card.json'):
            try:metadata=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if not isinstance(metadata,dict):continue
            if metadata.get('request_id')==body.request_id:
                if metadata.get('request_hash')!=body.preview_token:raise HTTPException(409,'该请求编号已用于不同导入')
                return {'ok':True,'reused':True,'imported_pack_id':path.parent.name,'status':manager.session.status(),**manager.library_view()}
        require_current_pack(body.expected_pack_id)
        previous=(manager.pack_dir,manager.session,dict(manager.library))
        from rpg_content.library import library_path
        library_file=library_path();previous_library=library_file.read_bytes() if library_file.exists() else None
        target=None
        try:
            target,preview=create_card_pack(raw,body.filename,body.options,manager.user_dir,body.request_id)
            manager._activate(target)
            manager.auto_save()
        except (ValueError,PackError,OSError) as exc:
            manager.pack_dir,manager.session,manager.library=previous
            if target is not None and target.resolve().is_relative_to(manager.user_dir.resolve()) and target.resolve()!=manager.user_dir.resolve():shutil.rmtree(target)
            if previous_library is not None:library_file.write_bytes(previous_library)
            elif library_file.exists():library_file.unlink()
            raise HTTPException(400,str(exc)) from None
        return {'ok':True,'reused':False,'imported_pack_id':manager.active_pack,'warnings':preview['warnings'],'status':manager.session.status(),**manager.library_view()}

@app.get('/api/character-cards/current')
def current_character_card():
    with manager.lock:
        card=manager.session.pack.character_card
        return {'pack_id':manager.active_pack,'card':{key:card[key] for key in ('name','spec','spec_version','creator','creator_notes','character_version','warnings','unsupported','mappings','options','filename') if key in card} if card else None}

@app.get('/api/character-cards/source')
def export_character_card(pack_id: str|None=None):
    with manager.lock:
        if pack_id is not None:require_current_pack(pack_id)
        card=manager.session.pack.character_card
        if not card or 'raw' not in card:raise HTTPException(404,'当前游戏没有角色卡原始数据')
        return JSONResponse(card['raw'],headers={'Content-Disposition':'attachment; filename="character-card.json"'})

@app.get('/api/character-cards/source-file')
def export_original_character_card(pack_id: str|None=None):
    with manager.lock:
        if pack_id is not None:require_current_pack(pack_id)
        card=manager.session.pack.character_card
        path=manager.pack_dir/'character-card/source.bin'
        if not card or not path.is_file():raise HTTPException(404,'原始二进制文件不可用；仍可导出保留的 JSON')
        return FileResponse(path,filename=card.get('filename') or 'character-card.bin',media_type='application/octet-stream')


# -- Personality-only NPCs and event-sourced world memory -----------------
from rpg_core.personality_npcs import Roster,PersonalityNpc,extract_personality,view as npc_view,roster_for
from rpg_core.dynamic_worldbook import Change as WorldMemoryChange,view as memory_view
from rpg_core.adjudication import digest as data_digest,propose as propose_decision
from rpg_core.settlement import Pending as PendingDecision,Operation as SettlementOperation

class PersonalityFile(BaseModel):
    model_config={'extra':'forbid'}
    filename: str=Field(max_length=255)
    data_base64: str=Field(min_length=1,max_length=28*1024*1024)

class PersonalityPreview(BaseModel):
    model_config={'extra':'forbid'}
    files: list[PersonalityFile]=Field(min_length=1,max_length=10)
    pack_id: str

class PersonalityImport(PersonalityPreview):
    request_id: str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9_.:-]+$')
    preview_token: str=Field(min_length=64,max_length=64)
    revision: str
    npcs: list[PersonalityNpc]=Field(min_length=1,max_length=10)

class PersonalityConfig(BaseModel):
    model_config={'extra':'forbid'}
    pack_id: str
    revision: str
    request_id: str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9_.:-]+$')
    roster: Roster

def _personality_preview(body):
    items=[];sources={};total=0
    for file in body.files:
        raw=_card_bytes(file);total+=len(raw)
        if total>60*1024*1024:raise ValueError('本批角色卡总大小不能超过60 MB')
        item,original=extract_personality(raw,file.filename);key=item['npc']['id']
        if key in sources:raise ValueError('同一角色卡重复选择，请只保留一份')
        items.append(item);sources[key]=(raw,original,file.filename)
    token=data_digest([body.pack_id,[(i['filename'],i['npc']['source_hash']) for i in items]])
    return items,sources,token

@app.get('/api/personality-npcs')
def get_personality_npcs():
    with manager.lock:return {**npc_view(manager.session),'editable':manager.editable()}

@app.post('/api/personality-npcs/preview')
def preview_personality_npcs(body:PersonalityPreview):
    try:items,_,token=_personality_preview(body)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    with manager.lock:
        require_current_pack(body.pack_id)
        return {'items':items,'preview_token':token,**npc_view(manager.session),'editable':manager.editable()}

def _npc_receipt(body,request_hash):
    for event in manager.session.ledger.events:
        if event.kind=='npc.import.receipt' and event.payload.get('request_id')==body.request_id:
            if event.payload['request_hash']!=request_hash:raise HTTPException(409,'该请求编号已用于不同人物编辑')
            return {'reused':True,**npc_view(manager.session),'editable':manager.editable()}
    if body.revision!=npc_view(manager.session)['revision']:raise HTTPException(409,'候场人物列表已变化，请刷新后重新操作')
    return None

def _write_roster(body,roster,request_hash,sources=None):
    from rpg_content.library import _replace_and_validate
    writes={manager.pack_dir/'personality-npcs.json':json.dumps(roster.model_dump(mode='json'),ensure_ascii=False)}
    for npc_id,(raw,original,filename) in (sources or {}).items():
        # Source bytes and unsupported fields are archived, never sent to a model.
        directory=manager.pack_dir/'personality-cards'/npc_id
        writes[directory/'source.bin']=raw
        writes[directory/'original.json']=json.dumps(original,ensure_ascii=False)
        writes[directory/'metadata.json']=json.dumps({'filename':filename},ensure_ascii=False)
    # _replace_and_validate supports text and rolls all files back on validation failure.
    _replace_and_validate(manager.pack_dir,writes)
    manager.session.pack.personality_roster=roster.model_dump(mode='json')
    manager.session._record(turn=0,kind='npc.roster.configured',payload={'roster':roster.model_dump(mode='json'),'visibility':'internal'})
    manager.session._record(turn=0,kind='npc.import.receipt',payload={'request_id':body.request_id,'request_hash':request_hash,'visibility':'internal'})
    if roster.enabled:
        from rpg_core.dice import ensure_seed
        ensure_seed(manager.session)
    manager.auto_save()
    return {'reused':False,**npc_view(manager.session),'editable':manager.editable()}

@app.post('/api/personality-npcs/import')
def import_personality_npcs(body:PersonalityImport):
    try:items,sources,token=_personality_preview(body)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    if token!=body.preview_token:raise HTTPException(409,'角色卡文件已变化，请重新预览')
    expected={i['npc']['id']:i['npc'] for i in items}
    if any(n.id not in expected or n.source_hash!=expected[n.id]['source_hash'] for n in body.npcs):raise HTTPException(400,'人物必须来自本批预览的角色卡')
    with manager.lock:
        require_current_pack(body.pack_id)
        if not manager.editable():raise HTTPException(400,'内置游戏只读，请先复制成自己的游戏')
        request_hash=data_digest(body.model_dump(mode='json'));receipt=_npc_receipt(body,request_hash)
        if receipt:return receipt
        existing={n.id:n for n in roster_for(manager.session).npcs};existing.update({n.id:n for n in body.npcs})
        try:
            roster=Roster(enabled=True,npcs=list(existing.values()))
            return _write_roster(body,roster,request_hash,{n.id:sources[n.id] for n in body.npcs})
        except (ValueError,OSError,PackError) as exc:raise HTTPException(400,str(exc)) from None

@app.put('/api/personality-npcs')
def configure_personality_npcs(body:PersonalityConfig):
    with manager.lock:
        require_current_pack(body.pack_id)
        if not manager.editable():raise HTTPException(400,'内置游戏只读，请先复制成自己的游戏')
        request_hash=data_digest(body.model_dump(mode='json'));receipt=_npc_receipt(body,request_hash)
        if receipt:return receipt
        old={n.id:n.source_hash for n in roster_for(manager.session).npcs}
        if any(old.get(n.id)!=n.source_hash for n in body.roster.npcs):raise HTTPException(400,'新增人物请先导入角色卡，不能伪造来源')
        try:return _write_roster(body,body.roster,request_hash)
        except (ValueError,OSError,PackError) as exc:raise HTTPException(400,str(exc)) from None

@app.get('/api/personality-npcs/source/{npc_id}')
def export_personality_source(npc_id:str,pack_id:str):
    with manager.lock:
        require_current_pack(pack_id)
        if npc_id not in {n.id for n in roster_for(manager.session).npcs}:raise HTTPException(404,'未找到角色卡')
        path=manager.pack_dir/'personality-cards'/npc_id/'original.json'
        if not path.is_file():raise HTTPException(404,'原始卡片不在本设备；存档保留的人格仍可使用')
        return JSONResponse(json.loads(path.read_text(encoding='utf-8')),headers={'Content-Disposition':'attachment; filename="personality-card-original.json"'})

class MemoryProposal(BaseModel):
    model_config={'extra':'forbid'}
    pack_id: str
    request_id: str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9_.:-]+$')
    change: WorldMemoryChange
    reason: str=Field(min_length=1,max_length=500)

@app.get('/api/world/dynamic')
def get_dynamic_worldbook(include_internal:bool=False):
    with manager.lock:return memory_view(manager.session,include_internal=include_internal)

@app.post('/api/world/dynamic/propose')
def propose_world_memory(body:MemoryProposal):
    with manager.lock:
        require_current_pack(body.pack_id)
        request_hash=data_digest(body.model_dump(mode='json'))
        for e in manager.session.ledger.events:
            if e.kind=='worldbook.proposal.receipt' and e.payload.get('request_id')==body.request_id:
                if e.payload['request_hash']!=request_hash:raise HTTPException(409,'请求编号已用于不同世界书草案')
                return {'ok':True,'reused':True}
        from rpg_core.dynamic_worldbook import stage_change
        try:_,payload=stage_change(manager.session,body.change.model_dump(exclude_none=True),evidence=body.reason,turn=-1)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        entry=payload['entry'];visibility='internal' if entry['visibility']=='internal' or (payload['before'] or {}).get('visibility')=='internal' else 'public'
        pending=PendingDecision(title='世界书：'+entry['title'],reason=body.reason,evidence=body.reason,visibility=visibility,
            operations=[SettlementOperation(name='update_worldbook',args=body.change.model_dump(exclude_none=True),evidence=body.reason)])
        propose_decision(manager.session,manager.session.turn,pending,len(manager.session.ledger.events),origin='world_builder')
        manager.session._record(turn=0,kind='worldbook.proposal.receipt',payload={'request_id':body.request_id,'request_hash':request_hash,'visibility':'internal'})
        manager.auto_save();return {'ok':True,'reused':False,'message':'已加入裁定中心，请预览差异后确认'}


if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("RPG_PORT", "8787"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
