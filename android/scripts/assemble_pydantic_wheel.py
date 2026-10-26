"""把 pydantic-core 的 Android 动态库 + 纯 Python 部分组装成 Chaquopy 可用的 wheel。

用法：
  python assemble_wheel.py <sdist_dir> <lib.so> <android_tag> <out_dir>
例如：
  python assemble_wheel.py pydantic_core-2.50.1 target/x86_64-linux-android/release/lib_pydantic_core.so android_29_x86_64 dist
"""

from __future__ import annotations

import base64
import hashlib
import sys
import zipfile
from pathlib import Path


def record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def main() -> int:
    sdist = Path(sys.argv[1])
    lib_path = Path(sys.argv[2])
    android_tag = sys.argv[3]  # e.g. android_29_x86_64
    out_dir = Path(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)

    version = None
    for line in (sdist / "PKG-INFO").read_text(encoding="utf-8").splitlines():
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
            break
    if not version:
        raise SystemExit("PKG-INFO 里找不到 Version")

    dist_info = f"pydantic_core-{version}.dist-info"
    wheel_name = f"pydantic_core-{version}-cp313-cp313-{android_tag}.whl"
    wheel_path = out_dir / wheel_name

    files: list[tuple[str, bytes]] = []
    py_root = sdist / "python" / "pydantic_core"
    for path in sorted(py_root.rglob("*")):
        # Runtime wheels omit the same-name type-stub namespace.
        if path.is_file() and not path.relative_to(py_root).as_posix().startswith("_pydantic_core/"):
            arc = "pydantic_core/" + path.relative_to(py_root).as_posix()
            files.append((arc, path.read_bytes()))
    files.append(("pydantic_core/_pydantic_core.so", lib_path.read_bytes()))

    metadata = (sdist / "PKG-INFO").read_bytes()
    files.append((f"{dist_info}/METADATA", metadata))
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: rpg-android-manual\n"
        "Root-Is-Purelib: false\n"
        f"Tag: cp313-cp313-{android_tag}\n"
    ).encode()
    files.append((f"{dist_info}/WHEEL", wheel_meta))
    # pydantic-core 没有 entry point，但 pip 允许省略；补一个空的更稳。
    files.append((f"{dist_info}/top_level.txt", b"pydantic_core\n"))

    lines = [record_line(name, data) for name, data in files]
    lines.append(f"{dist_info}/RECORD,,")
    files.append((f"{dist_info}/RECORD", ("\n".join(lines) + "\n").encode()))

    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)

    print(f"wrote {wheel_path} ({wheel_path.stat().st_size} bytes, {len(files)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
