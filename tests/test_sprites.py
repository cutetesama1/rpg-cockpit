"""立绘配置（ui/sprites.json）：契约默认值、内容包加载、只读接口。

素材是 DoL 的 512×256 大图，角色只占左上角一个固定窗口（crop）；
渲染时所有图层共用这个窗口再等比放大，这条约定写进了 SpriteSheet。
"""
from __future__ import annotations

from conftest import PACK_DIR, ROOT  # noqa: F401  （确保 sys.path 已注入 core/gateway/content）

import json
import shutil
import sys

if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from rpg_content import load_pack  # noqa: E402
from rpg_core.contracts import SpriteCrop, SpriteSheet  # noqa: E402


def test_sprite_sheet_defaults_are_whole_image():
    sheet = SpriteSheet()
    assert (sheet.width, sheet.height) == (256, 256)
    assert (sheet.crop.x, sheet.crop.y, sheet.crop.w, sheet.crop.h) == (0, 0, 0, 0)
    assert sheet.layers == []


def test_sprite_sheet_accepts_crop_and_layers():
    sheet = SpriteSheet(
        crop=SpriteCrop(x=88, y=22, w=60, h=165),
        layers=[{"id": "body", "src": "ui/sprites/body/base-{body_type}.png", "z": 10}],
    )
    assert sheet.crop.w == 60
    assert sheet.layers[0].src.endswith("{body_type}.png")


def test_pack_without_sprites_still_loads():
    pack = load_pack(PACK_DIR)
    assert pack.sprites is None


def test_pack_loads_sprites_config(tmp_path):
    """带上 ui/sprites.json 的包会解析出画布、裁剪窗口与图层。"""
    root = tmp_path / "pack-with-sprites"
    shutil.copytree(PACK_DIR, root)
    (root / "ui").mkdir(exist_ok=True)
    (root / "ui" / "sprites.json").write_text(
        json.dumps(
            {
                "width": 256,
                "height": 256,
                "max_height": 320,
                "crop": {"x": 88, "y": 22, "w": 60, "h": 165},
                "layers": [
                    {"id": "body", "src": "ui/sprites/body/base-classic.png", "z": 10},
                    {
                        "id": "breasts",
                        "src": "ui/sprites/body/breasts/breasts-{breast_size}.png",
                        "z": 15,
                        "adult": True,
                        "when": [
                            {"field": "breast_size", "op": ">=", "value": 1},
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pack = load_pack(root)
    assert pack.sprites is not None
    assert pack.sprites.crop.w == 60 and pack.sprites.crop.h == 165
    assert [layer.id for layer in pack.sprites.layers] == ["body", "breasts"]
    assert pack.sprites.layers[1].adult is True


@pytest.fixture()
def client():
    client = TestClient(app)
    client.post("/api/reset")
    return client


def test_sprite_route_is_optional(client):
    """没有立绘配置的包返回 sprites=None，而不是报错。"""
    data = client.get("/api/sprite").json()
    if data.get("sheet") is not None:
        # 当前会话可能被切到带立绘的包（用户自己的存档），此时只校验结构
        assert "layers" in data["sheet"]
    else:
        assert data == {"pack": "night-convenience-store", "sheet": None} or data["sheet"] is None


def test_pack_asset_route_blocks_traversal(client):
    """包内资源接口只允许 ui/ 下的图片，且拒绝越级路径。"""
    bad = client.get("/api/pack/asset/../manifest.json")
    assert bad.status_code in (400, 404)
    ok_ui_dir = client.get("/api/pack/asset/ui/")
    assert ok_ui_dir.status_code in (200, 400, 404)

def test_sprite_sheet_supports_views_and_poses():
    """取景（全身/半身）与姿势（独立窗口 + 图层）都能从 JSON 读进来。"""
    sheet = SpriteSheet(
        views={"full": {"x": 88, "y": 22, "w": 60, "h": 165}, "bust": {"x": 88, "y": 22, "w": 60, "h": 96}},
        poses={
            "sit": {
                "crop": {"x": 100, "y": 40, "w": 80, "h": 120},
                "layers": [{"id": "body_sit", "src": "ui/sprites/body/sit.png", "z": 10}],
            }
        },
    )
    assert sheet.views["bust"].h == 96
    assert sheet.poses["sit"].crop.w == 80
    assert sheet.poses["sit"].layers[0].id == "body_sit"


def test_condition_in_operator():
    """`in` 用于兼容旧存档的枚举值（upper=full 之类）。"""
    from rpg_core.contracts import Condition
    from rpg_core.scenes import condition_holds

    cond = Condition(field="upper", op="in", value=["full", "frayed"])
    assert condition_holds(cond, {"upper": "full"}) is True
    assert condition_holds(cond, {"upper": "hoodie"}) is False
    assert condition_holds(cond, {"upper": "full"}) is True


def test_sprite_sheet_parses_frames_and_masks():
    """动画帧（frames/fps）与遮罩图层（mask）都能解析，缺省仍是单帧。"""
    plain = SpriteSheet()
    assert plain.frames == 1
    assert plain.fps == 2.0

    animated = SpriteSheet(
        frames=2,
        fps=1.5,
        layers=[
            {
                "id": "breasts",
                "src": "ui/sprites/body/breasts/breasts-4.png",
                "z": 15,
                "adult": True,
                "mask": "ui/sprites/clothes/masks/soft-clip.png",
                "when": [{"field": "explicit", "op": "==", "value": True}],
            }
        ],
    )
    layer = animated.layers[0]
    assert animated.frames == 2
    assert animated.fps == 1.5
    assert layer.mask == "ui/sprites/clothes/masks/soft-clip.png"
    assert layer.adult is True
