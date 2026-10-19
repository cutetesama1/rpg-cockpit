# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile 打包：FastAPI sidecar + 内置内容包 + 已构建前端。

路径全部相对本 spec 所在目录（scripts/），因此在别的机器/仓库克隆里也能直接打包：
    python -m PyInstaller scripts/rpg-sidecar.spec --noconfirm
产物：dist/rpg-sidecar.exe
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # scripts/ = 仓库根下的 scripts，上一级即仓库根

a = Analysis(
    [str(ROOT / "api" / "main.py")],
    pathex=[str(ROOT / "core"), str(ROOT / "gateway"), str(ROOT / "content")],
    binaries=[],
    datas=[
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(ROOT / "packs"), "packs"),
        (str(ROOT / "skill-libraries"), "skill-libraries"),
        (str(ROOT / "ui" / "dist"), "ui/dist"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rpg-sidecar",
    icon=str(ROOT / "src-tauri/icons/icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
