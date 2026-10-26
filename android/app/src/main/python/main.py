"""Android 端本地引擎启动器（P3：真 FastAPI 后端 + 真 UI）。

Kotlin 侧先调用 :class:`com.rpgframework.cockpit.AssetInstaller` 把打包进
APK 的 ``assets/backend`` 解压到 ``filesDir/runtime/backend``，然后通过
Chaquopy 调用 ``start_server(files_dir)``：

1. 把内容包/存档/配置目录重定向到 app 私有目录（filesDir/rpg/...）；
2. 把 ``runtime/backend/{core,gateway,content}`` 挂到 sys.path，加载
   ``runtime/backend/api/main.py``（即桌面端的 FastAPI 应用）；
3. 用 uvicorn 在后台线程监听 127.0.0.1 的临时端口；
4. 返回端口号，Kotlin 轮询 ``/api/health`` 通过后用 WebView 加载真 UI。

后端本身零改动：``api/main.py`` 用 ``ROOT = parents[1]`` 找到自己所在的
backend 根目录，``ROOT/ui/dist`` 是解压出来的 Web UI，``ROOT/packs`` 是随
APK 内置的内容包。
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import threading
from types import ModuleType
from typing import Any

_server: Any = None
_thread: threading.Thread | None = None
_port: int = 0
_api: ModuleType | None = None


def _log(message: str) -> None:
    """同时写入 stdout（logcat）与 Python 日志。"""
    print(f"[rpg-android] {message}", flush=True)


def _prepare_env(files_dir: str) -> str:
    """把内容包/存档/配置目录重定向到 app 私有目录。"""
    base = os.path.join(files_dir, "rpg")
    saves = os.path.join(base, "saves")
    packs = os.path.join(base, "packs")
    config_dir = os.path.join(base, "config")
    data_dir = os.path.join(base, "data")
    for path in (saves, packs, config_dir, data_dir):
        os.makedirs(path, exist_ok=True)

    os.environ["RPG_SAVES"] = saves
    os.environ["RPG_USER_PACKS"] = packs
    os.environ["RPG_CONFIG_DIR"] = config_dir
    os.environ["RPG_DATA_DIR"] = data_dir
    os.environ.setdefault("RPG_LIBRARY", os.path.join(config_dir, "library.json"))
    os.environ.setdefault("RPG_SETTINGS", os.path.join(config_dir, "settings.json"))
    os.environ.setdefault("RPG_HOST", "127.0.0.1")
    # 不再设 RPG_PACK：那个变量优先级高于 library.json 的 active_pack，会把每次
    # 启动都拽回样例包，用户选过的包在重启后丢失。未选包时由 api 侧回落到
    # night-convenience-store（内置样例包，随 APK 发在 backend/packs/ 下）。
    return base


def _load_app(backend: str) -> ModuleType:
    """以独立模块名加载桌面端 api/main.py，返回 FastAPI 应用模块。"""
    for sub in ("core", "gateway", "content"):
        path = os.path.join(backend, sub)
        if path not in sys.path:
            sys.path.insert(0, path)
    api_path = os.path.join(backend, "api", "main.py")
    if not os.path.isfile(api_path):
        raise FileNotFoundError(f"后端入口不存在：{api_path}")
    spec = importlib.util.spec_from_file_location("rpg_api_main", api_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载后端入口：{api_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rpg_api_main"] = module
    spec.loader.exec_module(module)
    return module


#: 固定端口。WebView 的 localStorage / 主题 / 「不再提示」都按 origin（含端口）隔离，
#: 端口一变这些本地设置就全丢了；固定端口被占用时才回落到系统随机端口。
PREFERRED_PORT = 8710


def _free_port(preferred: int = PREFERRED_PORT) -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", preferred))
            return int(preferred)
    except OSError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(files_dir: str) -> int:
    """启动本地 FastAPI 服务并返回端口号（幂等）。"""
    global _server, _thread, _port, _api
    if _server is not None:
        return _port

    base = _prepare_env(files_dir)
    backend = os.path.join(files_dir, "runtime", "backend")
    _log(f"files base = {base}")
    _log(f"backend root = {backend}")

    _api = _load_app(backend)
    _log(f"fastapi app loaded: {getattr(_api, 'API_VERSION', '?')}")

    import uvicorn

    _port = _free_port()
    config = uvicorn.Config(
        _api.app,
        host="127.0.0.1",
        port=_port,
        log_level="info",
        access_log=False,
    )
    _server = uvicorn.Server(config)
    _thread = threading.Thread(target=_server.run, name="rpg-api", daemon=True)
    _thread.start()
    _log(f"uvicorn listening on http://127.0.0.1:{_port}")
    return _port


def probe(files_dir: str) -> dict[str, object]:
    """轻量自检：返回后端模块的版本与关键路径（调试用）。"""
    try:
        backend = os.path.join(files_dir, "runtime", "backend")
        return {
            "ok": True,
            "backend": backend,
            "api_py": os.path.isfile(os.path.join(backend, "api", "main.py")),
            "ui_index": os.path.isfile(os.path.join(backend, "ui", "dist", "index.html")),
            "packs": sorted(os.listdir(os.path.join(backend, "packs")))
            if os.path.isdir(os.path.join(backend, "packs"))
            else [],
        }
    except Exception as exc:  # noqa: BLE001 - 自检把原始异常返回给 Kotlin
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def stop_server() -> None:
    """停止本地服务（退出时可选调用）。"""
    global _server, _thread
    if _server is not None:
        try:
            _server.should_exit = True
        except Exception:  # noqa: BLE001 - 退出路径不抛出
            pass
        _server = None
    if _thread is not None:
        _thread.join(timeout=3)
        _thread = None
