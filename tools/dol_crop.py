"""把 DoL 素材裁成「只留角色」的干净图层。

DoL 的立绘 PNG 是 512×256 的复合图：**同一帧里既有 1x 角色，也有一个放大预览块**
（右侧那一大团）。直接整张画会重影。

做法：逐帧识别 alpha 连通域，按完整色块的位置区分角色与放大预览，再按有效高度清理。
部分素材（如 aerial）的放大预览从 x=159 开始，矩形裁剪会留下预览碎片，因此要先判断
整个连通域。角色头发跨出旧矩形时保留完整色块，由渲染镜头决定取景。

用法：
    python tools/dol_crop.py --dir "<包>/ui/sprites"            # 就地处理
    python tools/dol_crop.py --dir "<包>/ui/sprites" --dry-run  # 只报告
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import pngio  # noqa: E402

# 角色所在窗口（与 sprites.json 里的 crop 保持一致）。
# x 放宽到 12..164：双马尾/爆炸头一类的发型会伸到窗口两侧；y 0..190 覆盖头顶到脚底。
# 右边界 164 仍小于放大预览块的起点（约 165），所以不会把预览块带进来。
WIN_X, WIN_Y, WIN_W, WIN_H = 12, 0, 152, 190
# 一帧的宽度：DoL 的 512×256 图是「2 帧横向排布」，每帧 256
FRAME_W = 256


def _keep_components(
    width: int, height: int, px: bytes, frames: int = 1
) -> tuple[bytes, int]:
    """逐帧过滤放大预览，保留横跨旧窗口的角色连通域。

    返回 (清理后的像素, 清空像素数)；帧之间不参与连通域合并。
    """
    frame_w = width // max(frames, 1)
    alpha = px[3::4]
    seen = bytearray(width * height)
    out = bytearray(px)
    cleared = 0
    for start, opacity in enumerate(alpha):
        if not opacity or seen[start]:
            continue
        frame = (start % width) // frame_w
        left, right = frame * frame_w, (frame + 1) * frame_w
        seen[start] = 1
        stack, component = [start], []
        sum_x = 0
        min_x, max_x, min_y = frame_w, 0, height
        while stack:
            pos = stack.pop()
            component.append(pos)
            x, y = pos % width, pos // width
            local_x = x - left
            sum_x += local_x
            min_x, max_x, min_y = min(min_x, local_x), max(max_x, local_x), min(min_y, y)
            neighbours = []
            if x > left: neighbours.append(pos - 1)
            if x + 1 < right: neighbours.append(pos + 1)
            if y > 0: neighbours.append(pos - width)
            if y + 1 < height: neighbours.append(pos + width)
            for neighbour in neighbours:
                if alpha[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    stack.append(neighbour)
        centre = sum_x / len(component)
        intersects = min_x < WIN_X + WIN_W and max_x >= WIN_X and min_y < WIN_Y + WIN_H
        # Aerial's enlarged preview starts at x=159, inside the old rectangle.
        # Classify the WHOLE component before taking a camera crop. Character
        # hair crossing the old rectangle stays intact, preview fragments don't.
        preview = max_x >= 180 and centre >= 155
        keep = intersects and not preview and centre < 165
        for pos in component:
            if not keep or pos // width >= WIN_Y + WIN_H:
                out[pos * 4 + 3] = 0
                cleared += 1
    return bytes(out), cleared



def crop_dir(root: Path, dry_run: bool = False) -> tuple[int, int]:
    """就地裁剪目录下全部 PNG，返回 (改动文件数, 清空像素数)。"""
    changed = 0
    cleared_total = 0
    for path in sorted(root.rglob("*.png")):
        if "closeup" in path.parts:
            continue
        width, height, px = pngio.read_png_rgba(path)
        if height != 256:
            continue
        frames = 2 if width >= FRAME_W * 2 and width % FRAME_W == 0 else 1
        out, cleared = _keep_components(width, height, px, frames=frames)
        if out == px:
            continue
        changed += 1
        cleared_total += cleared
        if not dry_run:
            pngio.encode_png_rgba(path, width, height, out)
    return changed, cleared_total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只保留 DoL 立绘里的角色本体")
    parser.add_argument("--dir", required=True, help="sprites 目录（含 body/ hair/ ...）")
    parser.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    args = parser.parse_args(argv)

    root = Path(args.dir)
    if not root.is_dir():
        parser.error(f"目录不存在：{root}")
    changed, cleared = crop_dir(root, dry_run=args.dry_run)
    print(f"{'将改动' if args.dry_run else '已改动'} {changed} 张，清除 {cleared} 个像素")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
