#!/usr/bin/env python
"""内容包工具的仓库级入口：`python tools/pack.py <new|lint|validate>`。

把 core/gateway/content 加进 sys.path，这样不用设 PYTHONPATH 也能直接用。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("core", "gateway", "content"):
    sys.path.insert(0, str(ROOT / sub))

from rpg_content.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
