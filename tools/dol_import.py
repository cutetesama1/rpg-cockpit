"""从 DoL（Degrees of Lewdity）素材抽取分层立绘，装进内容包。

用法：
    python tools/dol_import.py --dol "<DoL 根目录>" --pack "<内容包目录>"
    python tools/dol_import.py --dol "..." --pack "..." --no-clothes   # 只装身体/脸/头发

它会：
1. 扫描 DoL 的 img/，挑出能用的图层：身体、头、胸、眼、全部表情、全部发型长度、
   上下装（每个款式取一张主图）；
2. 只复制用到的文件到 `<包>/ui/sprites/`（不搬整份 252 MB），并顺手把每张图里
   「放大预览块」清掉（连通域只留角色本体，见 tools/dol_crop.py）；
3. 生成 `<包>/ui/sprites.json`：画布 + 取样窗口 + 全身/半身两种取景 + 全部图层；
4. 写 `<包>/ui/sprites/CREDITS.md`（署名与许可说明）。

素材是 CC BY-NC-SA 4.0：仅限非商业使用，分发时需要保留署名、相同协议。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import pngio  # noqa: E402
from dol_crop import WIN_H, WIN_W, WIN_X, WIN_Y, _keep_components  # noqa: E402

# 画布与取样窗口：DoL 原图 512×256 里，角色占左上角这一块
CANVAS = {"width": 256, "height": 256, "max_height": 320}
CROP = {"x": WIN_X, "y": WIN_Y, "w": 212, "h": WIN_H}
# 半身取景：头部到胸口，放大后看表情
BUST_CROP = {"x": 72, "y": 0, "w": 92, "h": 124}
HAIR_CROWN_OFFSETS = {"thorn and curl": -4, "torn and curl": -4}
HAIR_LENGTHS = ("short", "shoulder", "chest", "navel", "thighs", "feet")
PORTRAIT_VIEWS = {
    "closeup_face": {"x": 78, "y": 8, "w": 80, "h": 80},
    "closeup_mouth": {"x": 101, "y": 62, "w": 40, "h": 24},
    "closeup_upper": {"x": 78, "y": 65, "w": 80, "h": 72},
}
# Ordinary expression presets, composed from the stock face parts. Some nested
# facevariant folders in this distribution contain decorative UI artwork.
FACE_PROFILES = {
    "default": ("mid", "neutral", False), "aloof": ("low", "neutral", True),
    "catty": ("top", "smile", False), "foxy": ("low", "smile", True),
    "gloomy": ("low", "frown", True), "red": ("top", "neutral", False),
    "sweet": ("mid", "smile", False), "makeup": ("mid", "smile", False),
}

# 状态里给模型看的备注服饰文件名（枚举太长会吃掉提示词，这里只列常用款）
CURATED_TOPS = [
    "tshirt", "band tee", "blouse", "hoodie", "sweater", "cardigan", "dress shirt",
    "tank top", "camisole", "crop top", "turtleneck", "sports bra", "bra", "bikini top",
    "apron", "jacket", "coat", "school uniform", "kimono", "bathrobe", "towel",
    "maid", "nurse", "sundress", "pajamas", "none",
]
CURATED_BOTTOMS = [
    "jeans", "shorts", "skirt", "pencil skirt", "pleated skirt", "trousers",
    "leggings", "sweatpants", "panties", "bikini bottom", "swimshorts",
    "stockings", "towel", "none",
]

# 成人向：内衣/内裤/生殖器/身体涂鸦，都只在「成人向图层」开关打开时绘制
CURATED_UNDER_TOPS = [
    "bra", "sports bra", "bikini top", "camisole", "chestwrap", "chestbinder",
    "corset", "classicbikini", "buntiebikinitop", "catgirlbra", "none",
]
CURATED_UNDER_BOTTOMS = [
    "panties", "briefs", "boyshorts", "boxers", "bloomers", "bikini",
    "classicbriefs", "classiclacepanties", "catgirlpanties", "none",
]
CURATED_GENITALS = ["chastitybelt", "chastitycage", "strapon", "chastitybeltfetish", "none"]
CURATED_BODYWITING = ["heart", "flower", "butterfly", "paw print", "skull", "spider", "none"]

EXPRESSION_LABELS = {
    "default": "默认", "aloof": "冷淡", "catty": "俏皮", "foxy": "妩媚",
    "gloomy": "阴郁", "hurt": "难过", "angry": "生气", "shy": "害羞",
    "smile": "微笑", "laughing": "大笑", "sad": "悲伤", "scared": "害怕",
    "surprised": "惊讶", "flirty": "调情", "neutral": "平静", "orgasm": "高潮",
}

CREDITS = """# 立绘素材来源

这些图片来自 **Degrees of Lewdity**（作者 Vrelnir，https://vrelnir.blogspot.com/）及其
中文汉化整合包中的图片包。素材许可：**CC BY-NC-SA 4.0**（署名—非商业性使用—相同方式共享）。

- 作者 / 原始素材：Vrelnir 与 DoL 社区贡献者
- 汉化与整合：Eltirosto 汉化组（Degrees-of-Lewdity-Chinese-Localization）及本整合包作者
- 本目录只抽取了其中一部分图层（身体/头/表情/发型/上下装），用于本机个人游戏
- 每张图都已按连通域裁掉素材自带的「放大预览块」，只保留角色本体

再分发要求：署名、不得商业使用、衍生作品使用相同协议。
"""


def _stems(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.png"))


def _primary_image(directory: Path) -> Path | None:
    """挑一个款式的主图：优先 full.png，其次 1.png，再退而求其次第一张。"""
    if not directory.is_dir():
        return None
    for name in ("full.png", "1.png", "0.png"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    skip = ("-acc", "cover", "mask", "shadow", "wet", "-xray", "-alt")
    for candidate in sorted(directory.glob("*.png")):
        if not any(token in candidate.stem for token in skip):
            return candidate
    return None


def _slug(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


def _png_size(path: Path) -> tuple[int, int]:
    """读 PNG 头里的宽高（不做完整解码，导入时用来筛对齐尺寸）。"""
    with open(path, "rb") as handle:
        head = handle.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _aligned(path: Path) -> bool:
    """Accept known 1x/2x stock canvases; normalise height before cropping.

    DoL Renderer.rescaleImageToCanvasHeight scales half-size layers to height
    256 using nearest-neighbour. Other dimensions need explicit calibration.
    """
    try:
        width, height = _png_size(path)
    except OSError:
        return False
    return height in (128, 256) and width in (height, height * 2)


def _discover(dol_img: Path, with_clothes: bool) -> tuple[list[tuple[Path, str]], dict]:
    """返回 (复制清单[(源文件, 包内相对路径)], 分类信息)。"""
    files: list[tuple[Path, str]] = []
    info: dict = {"bodies": [], "expressions": [], "hair_styles": [],
                                  "tops": [], "bottoms": [], "breast_sizes": [],
                                  "under_tops": [], "under_bottoms": [], "genitals": [],
                                  "bodywriting": [], "masks": [], "hair_parts": [],
                                  "arms": [], "upper_parts": [], "hair_offsets": {},
                                  "closeup_chest": [], "closeup_mouth": [], "closeup_arse": []}

    from dol_clothing_geometry import read_metadata, panel_for
    html = dol_img.parent / "Degrees of Lewdity.html"
    geometry = read_metadata(html) if html.is_file() else {"upper": {}, "lower": {}}
    info["upper_geometry"] = geometry["upper"]
    body_dir = dol_img / "body"
    for name in _stems(body_dir):
        if name.startswith("base-") and name != "base-head":
            files.append((body_dir / f"{name}.png", f"ui/sprites/body/{name}.png"))
            info["bodies"].append(name.removeprefix("base-"))
    for body in info["bodies"]:
        for arm in ("left", "right"):
            src = body_dir / f"{arm}-arm-idle-{body}.png"
            if src.is_file() and _aligned(src):
                info["arms"].append((body, arm))
                files.append((src, f"ui/sprites/body/{arm}-arm-idle-{body}.png"))
    if (body_dir / "base-head.png").is_file():
        files.append((body_dir / "base-head.png", "ui/sprites/body/base-head.png"))
    for name in _stems(body_dir / "breasts"):
        size = name.removeprefix("breasts-")
        if not name.startswith("breasts-") or not size.isdigit() or int(size) < 1:
            continue
        files.append((body_dir / "breasts" / f"{name}.png",
                      f"ui/sprites/body/breasts/{name}.png"))
        info["breast_sizes"].append(size)

    for name in ("eyeshazel", "eyesblue", "eyesbrown", "eyesgreen", "eyesgrey"):
        src = dol_img / "eyes" / f"{name}.png"
        if src.is_file():
            files.append((src, f"ui/sprites/eyes/{name}.png"))

    face_root = dol_img / "face" / "default"
    if face_root.is_dir():
        # Use the stock face parts, rather than a nested skin whose iris/lash
        # assets can include a phone frame or other mod-specific decorations.
        presets = sorted(p.name for p in face_root.iterdir()
                         if p.is_dir() and (p / "base.png").is_file())
        for expr in presets:
            info["expressions"].append(expr)
            brow, mouth, half = FACE_PROFILES.get(expr, FACE_PROFILES["default"])
            suffix = "-half-closed" if half else ""
            parts = {
                "base": "base", "ears": "ears", "sclera": "sclera",
                "eyelids": f"eyelids{suffix}", "lashes": f"lashes{suffix}",
                "brow": f"brow-{brow}", "mouth": f"mouth-{mouth}",
            }
            for level in range(1, 6):
                parts[f"blush-{level}"] = f"blush-{level}"
            for target, source in parts.items():
                src = face_root / f"{source}.png"
                if src.is_file():
                    files.append((src, f"ui/sprites/face/{expr}/{target}.png"))
            # Stock img/eyes/eyeshazel.png in this distribution is a tall-eye
            # variant. The clean foxy atlas matches the sclera geometry.
            iris = face_root / "foxy" / f"iris{suffix}.png"
            if not iris.is_file():
                iris = face_root / "foxy" / "iris.png"
            if not iris.is_file():
                iris = dol_img / "eyes" / "eyeshazel.png"
            files.append((iris, f"ui/sprites/face/{expr}/iris.png"))

    hair_root = dol_img / "hair"
    fringe_root = hair_root / "fringe"
    if fringe_root.is_dir():
        styles = sorted(p.name for p in fringe_root.iterdir() if p.is_dir())
        for style in styles:
            # 只将六种标准发长加入选择；mask/acc 等辅助文件不能当作发长。
            lengths = [name for name in HAIR_LENGTHS
                       if (fringe_root / style / f"{name}.png").is_file()
                       and _aligned(fringe_root / style / f"{name}.png")]
            if not lengths:
                continue
            info["hair_styles"].append(style)
            info["hair_parts"].extend((style, "fringe", length, f"ui/sprites/hair/fringe/{style}/{length}.png") for length in lengths)
            for length in lengths:
                fringe = fringe_root / style / f"{length}.png"
                w, h, pixels = pngio.read_png_rgba(fringe)
                scale = 256 // h
                # A few half-size mod atlases put the crown 3-6 pixels below
                # the shared head's y=25. Calibrate the whole hairstyle to it.
                top = min((y * scale for y in range(min(h, 40))
                           for x in range(85 // scale, min(w, 151 // scale))
                           if pixels[(y * w + x) * 4 + 3]), default=24)
                info["hair_offsets"][f"{style}/{length}"] = min(HAIR_CROWN_OFFSETS.get(style, 0), max(-8, min(0, 24 - top)))
                files.append((fringe_root / style / f"{length}.png",
                              f"ui/sprites/hair/fringe/{style}/{length}.png"))
                # DoL fringe and sides are independent selectors. Aerial,
                # curtain, etc. have no sides directory: pair those bangs with
                # the stock side hair rather than leaving the scalp exposed.
                side_style = style
                side_file = hair_root / "sides" / side_style / f"{length}.png"
                if not side_file.is_file() or not _aligned(side_file):
                    side_style = "default"
                for part in ("sides", "back"):
                    part_file = hair_root / part / side_style / f"{length}.png"
                    if part_file.is_file() and _aligned(part_file):
                        dst = f"ui/sprites/hair/{part}/{side_style}/{length}.png"
                        info["hair_parts"].append((style, part, length, dst))
                        files.append((part_file, dst))

    crown = fringe_root / "default" / "chest.png"
    info["hair_crown"] = crown.is_file()
    if crown.is_file():
        files.append((crown, "ui/sprites/hair/crown/default.png"))

    if with_clothes:
        for slot in ("under-upper", "under-lower", "genitals"):
            root = dol_img / "clothes" / slot
            if not root.is_dir():
                continue
            bucket = {"under-upper": "under_tops", "under-lower": "under_bottoms",
                      "genitals": "genitals"}[slot]
            for item in sorted(p for p in root.iterdir() if p.is_dir()):
                primary = _primary_image(item)
                if primary is None or not _aligned(primary):
                    continue
                info[bucket].append(item.name)
                files.append((primary, f"ui/sprites/clothes/{slot}/{item.name}.png"))

        write_root = dol_img / "bodywriting"
        if write_root.is_dir():
            for mark in sorted(p.name for p in write_root.iterdir() if p.is_dir()):
                primary = _primary_image(write_root / mark)
                if primary is None:
                    continue
                info["bodywriting"].append(mark)
                files.append((primary, f"ui/sprites/bodywriting/{mark}.png"))

        mask_root = dol_img / "clothes" / "masks"
        if mask_root.is_dir():
            for mask in sorted(mask_root.glob("*.png")):
                info["masks"].append(mask.stem)
                files.append((mask, f"ui/sprites/masks/{mask.name}"))

        for slot, bucket in (("upper", "tops"), ("lower", "bottoms")):
            root = dol_img / "clothes" / slot
            if not root.is_dir():
                continue
            for garment in sorted(p for p in root.iterdir() if p.is_dir()):
                primary = _primary_image(garment)
                if primary is None or not _aligned(primary):
                    continue
                name = garment.name
                info[bucket].append(name)
                files.append((primary, f"ui/sprites/clothes/{slot}/{name}.png"))
                if slot == "upper":
                    # A full.png is often just the hem. The numbered file is
                    # the missing front panel; sleeves are separate again.
                    panels = {int(p.stem): p for p in garment.glob("*.png")
                              if p.stem.isdigit() and _aligned(p)}
                    for size in range(7):
                        if not panels:
                            break
                        selected = panel_for(size, panels, geometry["upper"].get(name))
                        if selected is None or selected not in panels:
                            continue
                        dst = f"ui/sprites/clothes/upper/{name}/panel-{selected}.png"
                        files.append((panels[selected], dst))
                        info["upper_parts"].append((name, "front", size, dst))
                    for arm in ("left", "right"):
                        sleeve = garment / f"{arm}-idle.png"
                        if sleeve.is_file() and _aligned(sleeve):
                            dst = f"ui/sprites/clothes/upper/{name}/{arm}-idle.png"
                            files.append((sleeve, dst))
                            info["upper_parts"].append((name, arm, None, dst))

    # 特写镜头：DoL 的 close 素材是 32×32（或 6 帧 192×32）的小块，画在 64×64 画布上
    close_root = dol_img / "sex" / "close"
    if close_root.is_dir():
        chest_dir = close_root / "chest"
        if chest_dir.is_dir():
            for png in sorted(chest_dir.glob("*.png")):
                if png.stem.isdigit():
                    info["closeup_chest"].append(png.stem)
                    files.append((png, f"ui/sprites/closeup/chest/{png.name}"))

    return list(dict.fromkeys(files)), info


def _cond(field: str, op: str, value) -> dict:
    return {"field": field, "op": op, "value": value}


def _build_layers(info: dict) -> list[dict]:
    layers: list[dict] = []

    def add(layer: dict) -> None:
        layers.append(layer)

    for style, part, length, src in info.get("hair_parts", []):
        add({"id": f"hair_{part}_{_slug(style)}_{length}",
             "src": src,
             "z": {"back": 8, "fringe": 56, "sides": 55}[part],
             "tint_field": "hair_color",
             "y": info.get("hair_offsets", {}).get(f"{style}/{length}", 0),
             "when": [_cond("hair_style", "==", style), _cond("hair_length", "==", length)]})

    if info.get("hair_crown"):
        add({"id": "hair_crown", "src": "ui/sprites/hair/crown/default.png", "z": 54,
             "tint_field": "hair_color",
             "when": [_cond("hair_style", "in", ["french curls", "thorn and curl", "torn and curl"])]})

    for body in info["bodies"]:
        add({
            "id": f"body_{body}",
            "src": f"ui/sprites/body/base-{body}.png",
            "z": 10,
            "when": [_cond("body_type", "==", body)],
        })

    for size in info["breast_sizes"]:
        add({
            "id": f"breasts_{size}",
            "src": f"ui/sprites/body/breasts/breasts-{size}.png",
            "z": 15,
            "adult": True,
            "mask": "ui/sprites/masks/soft-clip.png",
            "when": [_cond("breast_size", "==", int(size))],
        })

    add({"id": "head", "src": "ui/sprites/body/base-head.png", "z": 20})
    for body, arm in info.get("arms", []):
        add({"id": f"arm_{arm}_{body}",
             "src": f"ui/sprites/body/{arm}-arm-idle-{body}.png", "z": 45,
             "when": [_cond("body_type", "==", body)]})
    for garment, part, size, src in info.get("upper_parts", []):
        conditions = [_cond("upper", "==", garment)]
        if size is not None:
            conditions.append(_cond("breast_size", "==", size))
        add({"id": f"upper_piece_{_slug(garment)}_{part}_{size}", "src": src,
             "z": 51 if part == "front" else 49,
             "tint_field": "outfit_color", "wear_field": "upper_condition", "when": conditions})


    # Eye whites below iris, eyelids/lashes above it; all share one origin.
    for eye in ("hazel", "blue", "brown", "green", "grey"):
        add({"id": f"eyes_{eye}", "src": "ui/sprites/face/{expression}/iris.png",
             "mask": "ui/sprites/face/{expression}/sclera.png",
             "tint": {"hazel": "#877334", "blue": "#507eaa", "brown": "#705035", "green": "#52805a", "grey": "#7d858b"}[eye],
             "z": 36, "when": [_cond("eye_color", "==", eye)]})
    for expr in info["expressions"]:
        for part, z in [("base", 31), ("ears", 32), ("sclera", 34),
                        ("eyelids", 38), ("lashes", 39), ("brow", 41), ("mouth", 43)]:
            layer = {"id": f"face_{_slug(expr)}_{part}",
                     "src": f"ui/sprites/face/{expr}/{part}.png", "z": z,
                     "when": [_cond("expression", "==", expr)]}
            if part == "brow":
                layer["tint_field"] = "hair_color"
            add(layer)
        for level in range(1, 6):
            add({"id": f"blush_{_slug(expr)}_{level}",
                 "src": f"ui/sprites/face/{expr}/blush-{level}.png", "z": 37,
                 "when": [_cond("expression", "==", expr), _cond("blush", "==", level)]})

    # 身体涂鸦：在身体之上、衣服之下
    for mark in info["bodywriting"]:
        add({
            "id": f"bodywriting_{_slug(mark)}",
            "src": f"ui/sprites/bodywriting/{mark}.png",
            "z": 38,
            "adult": True,
            "when": [_cond("bodywriting", "==", mark)],
        })

    for garment in info["under_bottoms"]:
        add({
            "id": f"under_lower_{_slug(garment)}",
            "src": f"ui/sprites/clothes/under-lower/{garment}.png",
            "z": 40,
            "adult": True,
            "when": [_cond("under_lower", "==", garment)],
        })

    for garment in info["genitals"]:
        add({
            "id": f"genital_{_slug(garment)}",
            "src": f"ui/sprites/clothes/genitals/{garment}.png",
            "z": 44,
            "adult": True,
            "when": [_cond("genital", "==", garment)],
        })

    for garment in info["under_tops"]:
        add({
            "id": f"under_upper_{_slug(garment)}",
            "src": f"ui/sprites/clothes/under-upper/{garment}.png",
            "z": 48,
            "adult": True,
            "when": [_cond("under_upper", "==", garment)],
        })

    for garment in info["bottoms"]:
        add({
            "id": f"lower_{_slug(garment)}",
            "src": f"ui/sprites/clothes/lower/{garment}.png",
            "z": 42,
            "tint_field": "pants_color", "wear_field": "lower_condition",
            "when": [_cond("lower", "==", garment)],
        })
    # 旧存档里的 lower=full 之类的值，落到最常见的牛仔裤上，别让人裸着
    add({
        "id": "lower_legacy",
        "src": "ui/sprites/clothes/lower/jeans.png",
        "z": 42,
        "tint_field": "pants_color", "wear_field": "lower_condition",
        "when": [_cond("lower", "in", ["full", "frayed", "torn", "tattered"])],
    })

    for garment in info["tops"]:
        add({
            "id": f"upper_{_slug(garment)}",
            "src": f"ui/sprites/clothes/upper/{garment}.png",
            "z": 50,
            "tint_field": "outfit_color", "wear_field": "upper_condition",
            "when": [_cond("upper", "==", garment)],
        })
    add({
        "id": "upper_legacy",
        "src": "ui/sprites/clothes/upper/tshirt.png",
        "z": 50,
        "tint_field": "outfit_color", "wear_field": "upper_condition",
        "when": [_cond("upper", "in", ["full", "frayed", "torn", "tattered"])],
    })

    return layers


CROPS = {"closeup_chest": "closeup/chest"}


def _build_closeup_poses(info: dict) -> dict:
    """Keep the pre-existing standalone closeup; ordinary cameras use views."""
    poses: dict[str, dict] = {}
    # 画布 64×64 = 32×32 素材按整数 2 倍放大（RES=2 时 canvas 正好 64）
    crop = {"x": 0, "y": 0, "w": 32, "h": 32}

    if info["closeup_chest"]:
        layers = []
        for size in info["closeup_chest"]:
            layers.append({
                "id": f"closeup_chest_{size}",
                "src": f"ui/sprites/closeup/chest/{size}.png",
                "z": 10,
                "adult": True,
                "when": [_cond("breast_size", "==", int(size))],
            })
        poses["closeup_chest"] = {"crop": dict(crop), "width": 64, "height": 64,
                                 "frames": 1, "frame_width": 32, "fps": 1.0, "layers": layers}

    return poses


def _build_rules(info: dict, limits: dict[str, int]) -> list[dict]:
    """状态联动：受伤/精力见底时自动换表情（只影响绘制，不改状态）。

    只在玩家没有手动指定表情（default）时接管，免得把调试台的选择顶掉。
    阈值取字段上限的 1/3、1/8，直接写成绝对值（condition 只做数值比较）。
    """
    have = set(info["expressions"])
    if "default" not in have:
        return []
    neutral = [_cond("expression", "in", ["default"])]
    rules: list[dict] = []
    hp_max = limits.get("hp")
    focus_max = limits.get("focus")
    if hp_max and "gloomy" in have:
        rules.append({"when": neutral + [_cond("hp", "<=", max(1, round(hp_max / 8)))],
                      "set": {"expression": "gloomy", "blush": 3}})
        rules.append({"when": neutral + [_cond("hp", "<=", max(1, round(hp_max / 3)))],
                      "set": {"expression": "gloomy"}})
    if focus_max and "aloof" in have:
        rules.append({"when": neutral + [_cond("focus", "<=", max(1, round(focus_max / 4)))],
                      "set": {"expression": "aloof"}})
    return rules


def build_sheet(info: dict) -> dict:
    return {
        **CANVAS,
        "crop": dict(CROP),
        "views": {"full": dict(CROP), "bust": dict(BUST_CROP), **PORTRAIT_VIEWS},
        # DoL 每层横向 2 帧（呼吸动画），2 fps 来回放就是「活着」的感觉
        "frame_width": 256,
        "frames": 2,
        "fps": 2.0,
        "layers": _build_layers(info),
        # 姿势：站姿之外的特写镜头（胸/嘴/臀），由界面「取景」切换
        "poses": _build_closeup_poses(info),
        # 状态联动规则在 main() 里按内容包字段上限补进来
        "rules": [],
    }


def _isolate_character(path: Path) -> None:
    """Normalise portrait layers, then remove preview blocks (never closeups)."""
    if "closeup" in path.parts:
        return
    width, height, px = pngio.read_png_rgba(path)
    original = px
    if height == 128 and width in (128, 256):
        # Same scaling as DoL's scale:true, with integer nearest-neighbour.
        rows = []
        for y in range(height):
            row = b"".join(px[(y * width + x) * 4:(y * width + x + 1) * 4] * 2
                           for x in range(width))
            rows.extend((row, row))
        px = b"".join(rows)
        width, height = width * 2, height * 2
    if height != 256:
        return
    if "face" in path.parts and width >= 512:
        # Face atlases store open/closed eyes, not the body's idle cycle.
        # Keep the open-eye frame until an independent blink track is supplied.
        px = b"".join(px[y * width * 4:(y * width + 256) * 4] for y in range(height))
        width = 256
    if path.parent.name == "crown":
        # Small cap underlay for the three decorative fringes, cut from the
        # stock DoL fringe and clipped to the existing head's crown alpha.
        hw, hh, head = pngio.read_png_rgba(path.parents[2] / "body/base-head.png")
        cap = bytearray(px)
        for y in range(height):
            for x in range(width):
                at = (y * width + x) * 4 + 3
                if not 25 <= y < 31 or not head[(y * hw + x % hw) * 4 + 3]:
                    cap[at] = 0
        px = bytes(cap)
    frames = 2 if width >= 512 and width % 256 == 0 else 1
    out, _ = _keep_components(width, height, px, frames=frames)
    if out != original:
        pngio.encode_png_rgba(path, width, height, out)


_ENUM_FIELDS = {
    "body_type": None,
    "expression": None,
    "hair_style": None,
    "hair_length": None,
    "eye_color": None,
    "upper": "none",
    "lower": "none",
    "under_upper": "none",
    "under_lower": "none",
    "genital": "none",
    "bodywriting": "none",
}


def _state_limits(pack: Path) -> dict[str, int]:
    """从内容包 state.json 读字段上限（hp/focus 之类），用于生成联动阈值。"""
    path = pack / "state.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = {field.get("id") for field in data.get("fields", [])}
    out: dict[str, int] = {}
    # 字段自己的 max（hp 20 / focus 10 …）
    for field in data.get("fields", []):
        if isinstance(field.get("max"), (int, float)):
            out[field["id"]] = int(field["max"])
    # 兼容：schema.limits 里也可能按字段 id 给上限（只取确实是字段的键）
    limits = data.get("limits")
    if isinstance(limits, dict):
        for key, value in limits.items():
            if key in ids and isinstance(value, (int, float)):
                out.setdefault(key, int(value))
    return out


def sync_state_fields(pack: Path, sheet: dict) -> list[str]:
    """把 sprites.json 里出现过的枚举值写回内容包 state.json 的 enum_values。

    DoL 的目录名里带空格（"paw print"、"sports bra"），所以字段值必须和目录名一致，
    否则 `when: {field: ==, value: bra}` 永远匹配不到图层。返回被改写的字段 id。
    """
    state_path = pack / "state.json"
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    fields = state.get("fields") or []
    values: dict[str, set[str]] = {}
    for layer in sheet.get("layers", []):
        for cond in layer.get("when") or []:
            field = cond.get("field")
            if field in _ENUM_FIELDS and cond.get("op") == "==":
                values.setdefault(field, set()).add(str(cond.get("value")))
    changed: list[str] = []
    for entry in fields:
        fid = entry.get("id")
        if fid not in values:
            continue
        items = sorted(values[fid])
        sentinel = _ENUM_FIELDS[fid]
        if sentinel:
            items = sorted(set(items) | {sentinel})
            if entry.get("default") not in items:
                entry["default"] = sentinel
        # 兜底：保留当前默认值（DoL 目录名不一定和我们的默认值同名，例如
        # eye_color 的默认 "hazel" 对不上目录 "eyeshazel"），否则内容包校验会失败。
        default = entry.get("default")
        if isinstance(default, str) and default and default not in items:
            items = sorted(set(items) | {default})
        if entry.get("enum_values") != items:
            entry["enum_values"] = items
            changed.append(fid)
    if changed:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 DoL 素材抽取分层立绘")
    parser.add_argument("--dol", required=True, help="DoL 根目录（含 img/ 的那一层）")
    parser.add_argument("--pack", required=True, help="目标内容包目录")
    parser.add_argument("--no-clothes", action="store_true", help="不导入上下装")
    parser.add_argument("--dry-run", action="store_true", help="只打印清单不复制")
    args = parser.parse_args(argv)

    dol_img = Path(args.dol) / "img"
    if not dol_img.is_dir():
        print(f"找不到 img 目录：{dol_img}", file=sys.stderr)
        return 2
    pack = Path(args.pack)
    if not pack.is_dir():
        print(f"内容包目录不存在：{pack}", file=sys.stderr)
        return 2

    files, info = _discover(dol_img, with_clothes=not args.no_clothes)
    copied = 0
    total = 0
    skipped: list[str] = []
    for src, dst_rel in files:
        if not src.is_file():
            skipped.append(str(src))
            continue
        total += src.stat().st_size
        if args.dry_run:
            continue
        dst = pack / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        _isolate_character(dst)
        copied += 1

    sheet = build_sheet(info)
    limits = _state_limits(pack)
    sheet["rules"] = _build_rules(info, limits)
    if not args.dry_run:
        ui = pack / "ui"
        (ui / "sprites.json").write_text(
            json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        (ui / "sprites" / "CREDITS.md").write_text(CREDITS, encoding="utf-8")
        synced = sync_state_fields(pack, sheet)
    if not args.dry_run and synced:
        print("state 枚举同步：" + ", ".join(synced))
    print(
        f"图层 {len(sheet['layers'])} 个；复制 {copied} 个文件；"
        f"素材合计 {total / 1024 / 1024:.2f} MB；"
        f"表情 {len(info['expressions'])} 种、发型 {len(info['hair_styles'])} 种、"
        f"上衣 {len(info['tops'])} 件、下装 {len(info['bottoms'])} 件、"
        f"内衣 {len(info['under_tops'])}+{len(info['under_bottoms'])} 件、"
        f"生殖器 {len(info['genitals'])} 件、涂鸦 {len(info['bodywriting'])} 个、"
        f"遮罩 {len(info['masks'])} 张"
    )
    if skipped:
        print(f"缺失 {len(skipped)} 个源文件（跳过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
