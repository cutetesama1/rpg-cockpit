"""最小 PNG 编解码：把任意 DoL 素材（调色板 / 低位深灰度 / RGBA / Adam7 交错）统一解成 8 位 RGBA。

只为本仓库的离线工具服务，保留原始尺寸，不保留 16 位精度（右移 8 位）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Adam7 交错的 7 个 pass：(x0, y0, dx, dy)
ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def _unfilter(raw: bytes, width: int, height: int, bpp: int, stride: int, pos: int = 0) -> tuple[bytearray, int]:
    out = bytearray(height * stride)
    prev = bytearray(stride)
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return out, pos


def _bits(row: bytes, count: int, depth: int) -> list[int]:
    if depth == 8:
        return list(row[:count])
    if depth == 16:
        return [row[i * 2] for i in range(count)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    values = []
    for i in range(count):
        byte = row[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        values.append((byte >> shift) & mask)
    return values


def _decode_pixels(
    pixels: bytearray,
    width: int,
    height: int,
    stride: int,
    color_type: int,
    depth: int,
    palette: bytes,
    trns: bytes,
) -> bytearray:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    rgba = bytearray(width * height * 4)
    if color_type == 3:
        palette_rgb = [
            (palette[i], palette[i + 1], palette[i + 2]) for i in range(0, len(palette), 3)
        ]
        alpha = list(trns) if trns else []
        for y in range(height):
            row = pixels[y * stride : (y + 1) * stride]
            for x, index in enumerate(_bits(bytes(row), width, depth)):
                if index < len(palette_rgb):
                    r, g, b = palette_rgb[index]
                else:
                    r = g = b = 0
                a = alpha[index] if index < len(alpha) else 255
                o = (y * width + x) * 4
                rgba[o : o + 4] = bytes((r, g, b, a))
        return rgba

    gray_alpha = trns if color_type == 0 and len(trns) >= 2 else b""
    for y in range(height):
        row = pixels[y * stride : (y + 1) * stride]
        values = _bits(bytes(row), width * channels, depth)
        for x in range(width):
            if color_type == 0:
                gray = values[x]
                a = 0 if gray_alpha and gray == gray_alpha[1] else 255
                r = g = b = gray
            elif color_type == 4:
                gray = values[x * 2]
                a = values[x * 2 + 1]
                if depth == 16:
                    a = a >> 8 if a > 255 else a
                r = g = b = gray
            elif color_type == 2:
                r, g, b = values[x * 3], values[x * 3 + 1], values[x * 3 + 2]
                a = 255
            else:
                r, g, b, a = (
                    values[x * 4],
                    values[x * 4 + 1],
                    values[x * 4 + 2],
                    values[x * 4 + 3],
                )
            o = (y * width + x) * 4
            rgba[o : o + 4] = bytes((r, g, b, a))
    return rgba


def read_png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:8] != SIGNATURE:
        raise ValueError(f"{path}: not a PNG")
    pos = 8
    width = height = depth = color_type = interlace = 0
    palette = b""
    trns = b""
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bits_per_pixel = channels * depth
    bpp = max(1, bits_per_pixel // 8)
    raw = zlib.decompress(bytes(idat))

    if not interlace:
        stride = (width * bits_per_pixel + 7) // 8
        pixels, _ = _unfilter(raw, width, height, bpp, stride)
        return width, height, bytes(_decode_pixels(pixels, width, height, stride, color_type, depth, palette, trns))

    # Adam7：每个 pass 是一张独立编码的小图，解出来再按步长铺回整图
    out = bytearray(width * height * 4)
    offset = 0
    for x0, y0, dx, dy in ADAM7:
        pw = (width - x0 + dx - 1) // dx
        ph = (height - y0 + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        stride = (pw * bits_per_pixel + 7) // 8
        pixels, offset = _unfilter(raw, pw, ph, bpp, stride, offset)
        sub = _decode_pixels(pixels, pw, ph, stride, color_type, depth, palette, trns)
        for y in range(ph):
            target_row = (y0 + y * dy) * width
            for x in range(pw):
                src = (y * pw + x) * 4
                dst = (target_row + x0 + x * dx) * 4
                out[dst : dst + 4] = sub[src : src + 4]
    return width, height, bytes(out)


def encode_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride : (y + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = SIGNATURE
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
