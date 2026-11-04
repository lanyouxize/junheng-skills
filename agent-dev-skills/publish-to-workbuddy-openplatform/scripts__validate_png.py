"""校验 PNG 是否合法：签名 / 各 chunk CRC / IDAT 解压长度。

用法：
  python validate_png.py <file.png>

用途：平台报"avatar 文件不存在/无法解析"时，先排除 PNG 本身非法（而非路径问题）。
重点检查：IHDR 尺寸与 color_type、每个 chunk 的 CRC32、IDAT 解压后字节数是否等于 H*(1+W*bpp)。
"""
import os
import sys
import zlib
import struct


def validate(path: str) -> bool:
    data = open(path, "rb").read()
    print(f"file size: {len(data)} bytes")
    print(f"sig: {data[:8].hex()}")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        print("  ✗ PNG 签名错误")
        return False

    i = 8
    W = H = bd = ct = None
    idat = b""
    ok = True
    while i < len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8].decode("ascii", "replace")
        chunk_data = data[i + 8:i + 8 + length]
        crc_stored = struct.unpack(">I", data[i + 8 + length:i + 8 + length + 4])[0]
        crc_calc = zlib.crc32(data[i + 4:i + 8 + length]) & 0xFFFFFFFF
        mark = "✓" if crc_stored == crc_calc else "✗ CRC MISMATCH"
        print(f"chunk {typ}: length={length}  crc={mark}")
        if crc_stored != crc_calc:
            ok = False
        if typ == "IHDR":
            W, H = struct.unpack(">II", chunk_data[:8])
            bd, ct = chunk_data[8], chunk_data[9]
            print(f"  IHDR -> {W}x{H} bit_depth={bd} color_type={ct}")
        if typ == "IDAT":
            idat += chunk_data
        if typ == "IEND":
            break
        i += 4 + 4 + length + 4

    if ct == 2:  # RGB
        bpp = 3
    elif ct == 6:  # RGBA
        bpp = 4
    else:
        print(f"  ! 未处理 color_type={ct}（本校验仅覆盖 RGB/RGBA）")
        return ok

    try:
        decompressed = zlib.decompress(idat)
        expected = H * (1 + W * bpp)
        match = len(decompressed) == expected
        print(f"IDAT decompressed: {len(decompressed)} bytes (expected {expected}) -> {'✓' if match else '✗ 长度不符'}")
        if not match:
            ok = False
    except Exception as e:
        print(f"  ✗ IDAT 解压失败: {e}")
        ok = False

    print("RESULT:", "合法 ✓" if ok else "非法 ✗")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python validate_png.py <file.png>")
        sys.exit(1)
    validate(sys.argv[1])
