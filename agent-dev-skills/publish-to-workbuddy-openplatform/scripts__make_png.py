"""手搓一张 256x256 橙红径向渐变 PNG 头像，无需 PIL / Cairo 等第三方依赖。

用法：
  python make_png.py <output.png> [size]

输出：合法 PNG（签名 + IHDR + IDAT + IEND，CRC 正确），可直接作为专家包 avatar 字段引用。
颜色：中心 #ff5e3a -> 外围暗紫，呼应 WorkBuddy 橙红渐变深色风格。
"""
import os
import sys
import zlib
import struct


def make_png(out_path: str, size: int = 256) -> int:
    w = h = size

    def chunk(typ, data):
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png_sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB

    raw = bytearray()
    for y in range(h):
        raw.append(0)  # 每行 filter byte = None
        for x in range(w):
            cx = x - w / 2.0
            cy = y - h / 2.0
            d = min(1.0, (cx * cx + cy * cy) ** 0.5 / (w / 2.0))
            r = int(0xFF - 80 * d)
            g = int(0x5E - 50 * d)
            b = int(0x3A + 110 * d)
            raw.append(r & 0xFF)
            raw.append(g & 0xFF)
            raw.append(b & 0xFF)

    idat = zlib.compress(bytes(raw), 9)
    png = png_sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    with open(out_path, "wb") as f:
        f.write(png)
    return len(png)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "avatar.png"
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    n = make_png(out, size)
    print(f"OK PNG  {out}  {n/1024:6.1f} KB  ({size}x{size} RGB)")
    # 校验签名
    with open(out, "rb") as f:
        sig = f.read(8)
    assert sig == b"\x89PNG\r\n\x1a\n", "签名异常"
    print("    PNG signature OK (89504e470d0a1a0a)")
