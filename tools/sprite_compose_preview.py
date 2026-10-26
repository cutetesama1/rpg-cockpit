"""离线合成内容包的分层立绘，输出 PNG，便于不启浏览器就核对素材与图层。

用法：
    python tools/sprite_compose_preview.py --pack "C:/Users/Administrator/.rpg-framework/packs/new-game" \
        --out C:/temp/shots/sprite-preview.png [--explicit]

规则与 ui/src/components/SpriteCanvas.tsx 保持一致：
- 图层按 z 排序，`{字段}` 用内容包 state 替换；
- `when`/`unless` 判断显隐，`adult` 图层默认关闭；
- 512×256 的 DoL 素材是两帧横拼，只取左侧第一帧；
- tint 用 source-in 上色（这里直接按 alpha 蒙版涂色）。
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pngio import encode_png_rgba, read_png_rgba  # noqa: E402


def clothing_wear_pixel(x, y, condition):
    grade = {"scuffed": 1, "damaged": 2, "ruined": 3}.get(condition, 0)
    if not grade:
        return 0
    cx = x % 256
    if ((cx // 16) * 7 + (y // 18) * 11) % 5 >= grade:
        return 0
    u, v = cx % 16, y % 18
    if 2 <= u <= 3 + grade and 4 <= v <= 4 + grade:
        return .6
    if grade >= 2 and 7 <= u <= 12 and v == 10:
        return .75
    if grade >= 3 and u % 2 == 0 and 7 <= u <= 12 and 9 <= v <= 11:
        return .45
    return 0


class Image:
    def __init__(self, width: int, height: int, rgba: bytes):
        self.width = width
        self.height = height
        self.pixels = rgba

    @classmethod
    def load(cls, path: Path) -> "Image":
        width, height, pixels = read_png_rgba(path)
        return cls(width, height, pixels)

    def rgba_at(self, x: int, y: int, tint: str | None, detail=False) -> tuple[int, int, int, int]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return 0, 0, 0, 0
        i = (y * self.width + x) * 4
        r, g, b, a = self.pixels[i], self.pixels[i + 1], self.pixels[i + 2], self.pixels[i + 3]
        if tint and a:
            tr, tg, tb = int(tint[1:3], 16), int(tint[3:5], 16), int(tint[5:7], 16)
            r, g, b = (r * tr // 255, g * tg // 255, b * tb // 255) if detail else (tr, tg, tb)
        return r, g, b, a


def compare(actual, op: str, expected) -> bool:
    if op == "==":
        return actual == expected
    if op == "!=":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        return False
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


def conditions_pass(conds, ctx) -> bool:
    if not conds:
        return True
    return all(compare(ctx.get(c["field"]), c["op"], c["value"]) for c in conds)


def portrait_context(state, sheet=None):
    ctx = dict(state)
    pose = ctx.get('pose', 'stand')
    ctx.setdefault('eye_state', 'auto');ctx.setdefault('gaze', 'forward')
    ctx['portrait_left_arm'] = ctx.get('left_arm') if ctx.get('left_arm') not in (None, 'auto') else 'cover' if pose=='guard' else 'idle'
    ctx['portrait_right_arm'] = ctx.get('right_arm') if ctx.get('right_arm') not in (None, 'auto') else 'cover' if pose=='guard' else 'hold' if pose in ('hold','attack','cast') or ctx.get('handheld') not in (None,'none') else 'idle'
    arms=(sheet or {}).get('pose_arms',{}).get(pose,{})
    if ctx.get('left_arm') in (None,'auto') and 'left' in arms:ctx['portrait_left_arm']=arms['left']
    if ctx.get('right_arm') in (None,'auto') and 'right' in arms:ctx['portrait_right_arm']=arms['right']
    held=ctx.get('handheld','none')
    if sheet and ctx.get('right_arm') in (None,'auto') and held!='none':
        modes=sheet.get('handheld_modes',{}).get(held,[])
        if modes and (('right' not in arms and pose not in ('guard','attack','cast')) or ctx['portrait_right_arm'] not in modes):ctx['portrait_right_arm']=sheet.get('arm_preferences',{}).get(held,'hold')
    ctx['portrait_mouth'] = ctx.get('mouth_shape', 'auto')
    if ctx['portrait_mouth']=='auto' and pose=='talk':ctx['portrait_mouth']='chew'
    ctx['_portrait_resolved'] = True
    return ctx


def visible(layer, ctx, explicit: bool) -> bool:
    if not ctx.get('_portrait_resolved'):ctx=portrait_context(ctx)
    if layer.get("adult") and not explicit:
        return False
    if not conditions_pass(layer.get("when"), ctx):
        return False
    unless = layer.get("unless")
    if unless and any(compare(ctx.get(c["field"]), c["op"], c["value"]) for c in unless):
        return False
    return True


def resolve(template: str, ctx) -> str:
    import re

    return re.sub(r"\{(\w+)\}", lambda m: str(ctx.get(m.group(1), "")), template)


def compose(pack: Path, sheet: dict, state: dict, *, explicit=False, view="full", frame=0, fields=None):
    """Mirror SpriteCanvas: state defaults/rules, camera, source stride, tint/mask."""
    ctx = portrait_context(state,sheet)
    for field in fields or []:
        options = field.get("enum_values") or []
        value = ctx.get(field["id"])
        if options and isinstance(value, str) and value not in options:
            default = field.get("default")
            ctx[field["id"]] = default if default in options else options[0]
    ctx["explicit"] = explicit
    for rule in sheet.get("rules", []):
        if conditions_pass(rule.get("when"), ctx):
            ctx.update(rule.get("set", {}))
    pose_name = view if view.startswith("closeup_") else ctx.get("pose", "")
    pose = sheet.get("poses", {}).get(pose_name)
    views = sheet.get("views", {})
    unavailable = view.startswith("closeup_") and not pose and view not in views
    layers = [] if unavailable else pose.get("layers", []) if pose is not None else sheet["layers"]
    model = pose or sheet
    width, height = model.get("width", sheet["width"]), model.get("height", sheet["height"])
    crop = (pose or {}).get("crop") or sheet.get("crop") or {}
    if view != "full" and view in views:
        crop = views[view]
    cx, cy = crop.get("x", 0), crop.get("y", 0)
    cw, ch = crop.get("w") or width, crop.get("h") or height
    frames = model.get("frames", sheet.get("frames", 1))
    stride = model.get("frame_width") or width
    frame %= max(1, frames)
    res = 2
    width, height = cw * res, ch * res
    out = bytearray(width * height * 4)
    drawn = []
    cache = {}
    def load(src):
        if src not in cache:
            cache[src] = Image.load(pack / src)
        return cache[src]
    def offset(img):
        return frame * stride if frames > 1 and img.width >= stride * frames else 0
    for layer in sorted(layers, key=lambda item: item["z"]):
        if not visible(layer, ctx, explicit):
            continue
        src = resolve(layer["src"], ctx)
        if not src or not (pack / src).is_file():
            print(f"missing asset: {src}")
            continue
        image = load(src)
        mask = load(resolve(layer["mask"], ctx)) if layer.get("mask") else None
        tint = ctx.get(layer["tint_field"]) if layer.get("tint_field") else layer.get("tint")
        if not isinstance(tint, str) or len(tint) != 7 or not tint.startswith("#"):
            tint = None
        dx, dy = layer.get("x", 0), layer.get("y", 0)
        for y in range(ch):
            for x in range(cw):
                r, g, b, a = image.rgba_at(cx + x - dx + offset(image), cy + y - dy, tint, (bool(layer.get("wear_field")) or layer.get("tint_field") in ("outfit_color", "pants_color")))
                mix = clothing_wear_pixel(cx + x - dx + offset(image), cy + y - dy, ctx.get(layer.get("wear_field"), "intact"))
                if a and mix:
                    r, g, b = [int(c * (1 - mix) + w * mix) for c, w in zip((r, g, b), (60, 52, 45))]
                if mask:
                    ma = mask.rgba_at(cx + x + offset(mask), cy + y, None)[3]
                    a = a * ma // 255
                a = round(a * layer.get("opacity", 1))
                if not a:
                    continue
                for yy in range(y * res, (y + 1) * res):
                    for xx in range(x * res, (x + 1) * res):
                        o = (yy * width + xx) * 4
                        da = out[o + 3]
                        alpha = a + da * (255 - a) / 255
                        rgb = (r, g, b)
                        for c in range(3):
                            color = rgb[c]
                            if layer.get("blend") == "multiply" and da:
                                color = color * out[o + c] / 255
                            out[o + c] = round((color * a + out[o + c] * da * (255 - a) / 255) / alpha)
                        out[o + 3] = round(alpha)
        drawn.append(layer["id"])
    return width, height, bytes(out), drawn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--explicit", action="store_true")
    parser.add_argument("--view", default="full")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--state", default="{}", help="JSON overrides for preview only")
    parser.add_argument("--api", default="")
    args = parser.parse_args()
    pack = Path(args.pack)
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    fields = json.loads((pack / "state.json").read_text(encoding="utf-8")).get("fields", [])
    state = {f["id"]: f["default"] for f in fields if "default" in f}
    if args.api:
        import urllib.request
        with urllib.request.urlopen(f"{args.api.rstrip('/')}/api/state", timeout=10) as resp:
            state.update(json.loads(resp.read().decode("utf-8")).get("state", {}))
    state.update(json.loads(args.state))
    w, h, rgba, drawn = compose(pack, sheet, state, explicit=args.explicit,
                                view=args.view, frame=args.frame, fields=fields)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    encode_png_rgba(out, w, h, rgba)
    print(f"{w}x{h} view={args.view} frame={args.frame} layers={len(drawn)} -> {out}")
    print("  " + ", ".join(drawn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
