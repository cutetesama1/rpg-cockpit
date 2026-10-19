"""Sprite source geometry, portrait import and camera regression coverage."""
from pathlib import Path
import json
import sys
import pytest
from conftest import ROOT
sys.path.insert(0, str(ROOT / "tools"))
from dol_import import _isolate_character, _aligned, _discover, build_sheet, _build_rules
from dol_crop import crop_dir
from sprite_compose_preview import compose
from pngio import encode_png_rgba, read_png_rgba
from rpg_content import load_pack
from rpg_core.contracts import SpriteSheet


requires_imported_art = pytest.mark.skipif(not (ROOT / "packs/new-game/ui/sprites/body/base-head.png").is_file(), reason="Optional third-party art is excluded from the public source; synthetic renderer tests still run.")


def png(path, w, h, pixels):
    path.parent.mkdir(parents=True, exist_ok=True)
    encode_png_rgba(path, w, h, pixels)


def test_half_resolution_portrait_is_scaled_before_window_crop(tmp_path):
    p = tmp_path / "hair.png"
    pixels = bytearray(256 * 128 * 4)
    pixels[(30 * 256 + 55) * 4:(30 * 256 + 55) * 4 + 4] = bytes((40, 20, 10, 255))
    png(p, 256, 128, pixels)
    assert _aligned(p)
    _isolate_character(p)
    w, h, rgba = read_png_rgba(p)
    assert (w, h) == (512, 256)
    for y in (60, 61):
        for x in (110, 111):
            assert rgba[(y * w + x) * 4:(y * w + x) * 4 + 4] == bytes((40, 20, 10, 255))
    assert rgba[(30 * w + 55) * 4 + 3] == 0


@pytest.mark.parametrize("w", [32, 192])
def test_compact_assets_are_never_character_cropped(tmp_path, w):
    p = tmp_path / "closeup" / "test.png"
    png(p, w, 32, bytes((10, 20, 30, 255)) * w * 32)
    original = p.read_bytes()
    _isolate_character(p)
    crop_dir(tmp_path)
    assert p.read_bytes() == original


@pytest.mark.parametrize("stride,frames,crop_w", [(256, 2, 152), (32, 6, 32)])
def test_source_stride_independent_of_output_and_camera(tmp_path, stride, frames, crop_w):
    # Each frame has a unique solid colour, so wrong offsets cannot pass.
    row = b"".join(bytes((30 * f, 20, 40, 255)) * stride for f in range(frames))
    png(tmp_path / "strip.png", stride * frames, 32, row * 32)
    png(tmp_path / "static.png", stride, 32, bytes((80, 90, 100, 255)) * stride * 32)
    sheet = {"width": 64 if stride == 32 else 256, "height": 32,
             "frame_width": stride, "frames": frames,
             "crop": {"x": 0, "y": 0, "w": crop_w, "h": 32},
             "layers": [{"id": "strip", "src": "strip.png", "z": 0}]}
    for frame in range(frames):
        w, h, rgba, _ = compose(tmp_path, sheet, {}, frame=frame)
        assert rgba[:4] == bytes((30 * frame, 20, 40, 255))
        assert rgba[-4:] == rgba[:4]
    sheet["layers"][0]["src"] = "static.png"
    assert compose(tmp_path, sheet, {}, frame=frames - 1)[2][:4] == bytes((80, 90, 100, 255))


def test_mask_uses_the_same_source_frame(tmp_path):
    png(tmp_path / "img.png", 64, 32, bytes((20, 30, 40, 255)) * 64 * 32)
    row = bytes((0, 0, 0, 255)) * 32 + bytes((0, 0, 0, 0)) * 32
    png(tmp_path / "mask.png", 64, 32, row * 32)
    sheet = {"width": 64, "height": 64, "frame_width": 32, "frames": 2,
             "crop": {"w": 32, "h": 32},
             "layers": [{"id": "masked", "src": "img.png", "mask": "mask.png", "z": 0}]}
    assert compose(tmp_path, sheet, {}, frame=0)[2][3] == 255
    assert not any(compose(tmp_path, sheet, {}, frame=1)[2])


def test_severe_damage_rule_reaches_blush():
    rules = _build_rules({"expressions": ["default", "gloomy", "aloof"]}, {"hp": 20, "focus": 10})
    from sprite_compose_preview import conditions_pass
    ctx = {"expression": "default", "hp": 1, "focus": 10}
    for rule in rules:
        if conditions_pass(rule["when"], ctx):
            ctx.update(rule["set"])
    assert ctx["expression"] == "gloomy" and ctx["blush"] == 3


@requires_imported_art
def test_imported_pack_faces_and_cameras_are_complete():
    pack = load_pack(ROOT / "packs/new-game")
    sheet = pack.sprites
    assert sheet.frame_width == 256
    assert {"closeup_face", "closeup_mouth", "closeup_upper"} <= sheet.views.keys()
    state = json.loads((ROOT / "packs/new-game/state.json").read_text(encoding="utf-8"))
    expressions = next(f["enum_values"] for f in state["fields"] if f["id"] == "expression")
    for expr in expressions:
        parts = {layer.id.rsplit("_", 1)[-1] for layer in sheet.layers
                 if any(c.field == "expression" and c.value == expr for c in layer.when)}
        assert {"base", "ears", "sclera", "eyelids", "lashes", "brow", "mouth"} <= parts
    for layer in sheet.layers:
        if "{" not in layer.src:
            assert (ROOT / "packs/new-game" / layer.src).is_file(), layer.src


def test_invalid_source_stride_is_rejected():
    with pytest.raises(ValueError):
        SpriteSheet(frame_width=0)


def test_face_blink_atlas_is_not_played_as_idle(tmp_path):
    p = tmp_path / "face/default/lashes.png"
    row = bytes((10, 20, 30, 255)) * 256 + bytes((200, 100, 50, 255)) * 256
    png(p, 512, 256, row * 256)
    _isolate_character(p)
    w, h, rgba = read_png_rgba(p)
    assert (w, h) == (256, 256)
    assert rgba[(58 * w + 110) * 4:(58 * w + 110) * 4 + 4] == bytes((10, 20, 30, 255))


@requires_imported_art
def test_imported_face_atlases_stay_open_during_idle():
    for part in ("eyelids", "lashes", "mouth"):
        w, h, _ = read_png_rgba(ROOT / f"packs/new-game/ui/sprites/face/default/{part}.png")
        assert (w, h) == (256, 256)


@requires_imported_art
def test_iris_is_clipped_to_the_eye_whites():
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    iris = next(layer for layer in sheet["layers"] if layer["id"] == "eyes_hazel")
    assert iris["mask"] == "ui/sprites/face/{expression}/sclera.png"
    sheet["layers"] = [iris]
    w, h, rgba, _ = compose(pack, sheet, {"eye_color": "hazel", "expression": "default"}, view="closeup_face")
    ys = [i // 4 // w // 2 + 8 for i in range(3, len(rgba), 4) if rgba[i]]
    assert ys and max(ys) <= 64 and min(ys) >= 57


def test_preview_component_overlapping_old_crop_is_removed():
    from dol_crop import _keep_components
    w, h = 256, 256
    rgba = bytearray(w * h * 4)
    # Character strand crossing the old x=164 boundary remains whole.
    for y in range(25, 30):
        for x in range(135, 173): rgba[(y*w+x)*4+3] = 255
    # Enlarged preview begins at x=159, INSIDE that old crop, but connects right.
    for y in range(40, 50):
        for x in range(159, 245): rgba[(y*w+x)*4+3] = 255
    clean, _ = _keep_components(w, h, bytes(rgba))
    assert clean[(26*w+170)*4+3] == 255
    assert clean[(45*w+160)*4+3] == 0


def test_fringe_only_style_gets_independent_side_hair(tmp_path):
    from dol_import import _discover
    color = bytes((20, 30, 40, 255)) * 512 * 256
    png(tmp_path / "hair/fringe/aerial/chest.png", 512, 256, color)
    png(tmp_path / "hair/sides/default/chest.png", 512, 256, color)
    files, info = _discover(tmp_path, False)
    assert ("aerial", "sides", "chest", "ui/sprites/hair/sides/default/chest.png") in info["hair_parts"]


@requires_imported_art
def test_all_body_types_have_both_idle_arms():
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    from sprite_compose_preview import visible
    for body in ("classic", "curvy", "slender", "soft"):
        arms = [l for l in sheet["layers"] if l["id"].startswith("arm_") and visible(l, {"body_type": body}, False)]
        assert len(arms) == 2
        assert {l["id"].split("_")[1] for l in arms} == {"left", "right"}


@requires_imported_art
def test_all_hair_choices_include_fringe_and_sides():
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    from sprite_compose_preview import visible
    fringe = [l for l in sheet["layers"] if l["id"].startswith("hair_fringe_")]
    for layer in fringe:
        ctx = {c["field"]: c["value"] for c in layer["when"]}
        sides = [l for l in sheet["layers"] if l["id"].startswith("hair_sides_") and visible(l, ctx, False)]
        assert len(sides) == 1, ctx
        assert (pack / sides[0]["src"]).is_file()


@requires_imported_art
def test_clothes_have_front_panels_and_separate_sleeves():
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    from sprite_compose_preview import visible
    for garment in ("tshirt", "hoodie", "sweater", "babydoll"):
        layers = [l for l in sheet["layers"] if l["id"].startswith("upper_piece_") and visible(l, {"upper": garment, "breast_size": 3}, False)]
        assert any("_front_" in l["id"] for l in layers)
        if garment != "babydoll":
            assert len(layers) == 3
        assert not any(l.get("adult") for l in layers)


@requires_imported_art
def test_changing_upper_changes_pixels_without_adult_toggle():
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    fields = json.loads((pack / "state.json").read_text(encoding="utf-8"))["fields"]
    state = {f["id"]: f.get("default") for f in fields}
    images = []
    for garment in ("tshirt", "hoodie", "sweater", "babydoll"):
        state["upper"] = garment
        w, h, rgba, drawn = compose(pack, sheet, state, view="closeup_upper", fields=fields)
        assert any(x.startswith("upper_piece_") for x in drawn)
        images.append(rgba)
    assert len(set(images)) == 4


@pytest.mark.parametrize("style", ["aerial", "french curls", "thorn and curl", "torn and curl"])
@requires_imported_art
def test_corrected_crowns_do_not_leave_bare_skin_line(style):
    pack = ROOT / "packs/new-game"
    sheet = json.loads((pack / "ui/sprites.json").read_text(encoding="utf-8"))
    fields = json.loads((pack / "state.json").read_text(encoding="utf-8"))["fields"]
    state = {f["id"]: f.get("default") for f in fields}
    state.update(hair_style=style, hair_length="chest")
    w, h, result, _ = compose(pack, sheet, state)
    hw, hh, head = read_png_rgba(pack / "ui/sprites/body/base-head.png")
    for sy in range(25, 28):
        for sx in range(108, 125):
            hp = (sy * hw + sx) * 4
            if head[hp + 3] == 255:
                dst = ((sy - sheet["crop"]["y"]) * 2 * w + (sx - sheet["crop"]["x"]) * 2) * 4
                assert result[dst:dst + 3] != head[hp:hp + 3], (style, sx, sy)


def test_outfit_colour_preserves_patterns_and_dark_outlines(tmp_path):
    # A white fabric pixel and a black seam must not become the same flat block.
    row = bytes((255, 255, 255, 255)) * 16 + bytes((0, 0, 0, 255)) * 16
    png(tmp_path / "shirt.png", 32, 32, row * 32)
    sheet = {"width": 32, "height": 32, "layers": [{"id":"shirt", "src":"shirt.png", "z":0, "tint_field":"outfit_color"}]}
    w, h, rgba, _ = compose(tmp_path, sheet, {"outfit_color":"#2f6f8f"})
    assert rgba[:4] == bytes((47, 111, 143, 255))
    assert rgba[32*4:32*4+4] == bytes((0, 0, 0, 255))
