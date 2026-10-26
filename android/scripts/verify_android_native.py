"""Fail packaging when desktop extensions or missing/wrong Android ABIs leak in."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import struct
import zipfile

MACHINES = {'arm64-v8a': 183, 'x86_64': 62}


def verify_elf(data, abi):
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != MACHINES[abi]:
        raise ValueError(f'{abi}: pydantic-core 不是对应架构的64位 Android ELF')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, offset + i * size)
             for i in range(count) if struct.unpack_from('<I', data, offset + i * size)[0] == 1]
    if not loads or any(row[7] < 16384 or (row[3] - row[2]) % 16384 for row in loads):
        raise ValueError(f'{abi}: pydantic-core 未按 16 KB 页对齐，必须重新链接')


def verify_pip(root):
    root = Path(root)
    if list(root.rglob('*.pyd')) or list(root.rglob('*.dll')):
        raise ValueError('Android 依赖目录混入 Windows 动态库')
    for abi in MACHINES:
        path = root / abi / 'pydantic_core/_pydantic_core.so'
        if not path.is_file():
            raise ValueError(f'{abi}: 缺少 Android pydantic-core 原生库')
        verify_elf(path.read_bytes(), abi)
    return {'pip': str(root), 'abis': list(MACHINES), 'ok': True}


def verify_apk(path):
    with zipfile.ZipFile(path) as apk:
        libs = {n.split('/')[1] for n in apk.namelist() if n.startswith('lib/') and n.endswith('/libpython3.13.so')}
        if not libs:
            raise ValueError('APK 没有 Python 运行时')
        for name in apk.namelist():
            if name.startswith('assets/chaquopy/requirements-') and name.endswith('.imy'):
                with zipfile.ZipFile(io.BytesIO(apk.read(name))) as req:
                    if any(n.endswith(('.pyd', '.dll')) for n in req.namelist()):
                        raise ValueError('APK requirements 混入 Windows 动态库')
        for abi in libs:
            name = f'assets/chaquopy/requirements-{abi}.imy'
            with zipfile.ZipFile(io.BytesIO(apk.read(name))) as req:
                verify_elf(req.read('pydantic_core/_pydantic_core.so'), abi)
    return {'apk': str(path), 'abis': sorted(libs), 'ok': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pip', type=Path)
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_pip(args.pip) if args.pip else verify_apk(args.apk), ensure_ascii=False))
