#!/usr/bin/env python3
"""
imgguard — حارس أبعاد الصور / image dimension guard.

السبب: قراءة صورة يتجاوز أحد بُعديها 2000 بكسل تُرفض بالخطأ
  "At least one of the image dimensions exceed max allowed size
   for many-image requests: 2000 pixels"
والرفض يأتي بعد انتهاء العمل كله => تضيع الجلسة ويُهدر الرصيد.

يقرأ الأبعاد من ترويسة الملف فقط: لا اعتماديّات، لا فكّ ضغط،
وبدون تحميل الصورة في الذاكرة.

أنماط الاستخدام:
  python3 imgguard.py check <file> [<file> ...]   # تحقّق صريح، للاستخدام اليدوي
  python3 imgguard.py dpi <inches_w> <inches_h>   # أقصى DPI آمن لتخطيط بالبوصة
  python3 imgguard.py hook                        # وضع الخطّاف: JSON على stdin

رموز الخروج:
  0 = آمن
  2 = محجوب (بُعد > الحدّ، أو صورة مجهولة الأبعاد)
"""

import json
import os
import struct
import sys

MAX_DIM = 2000

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif",
    ".webp", ".bmp", ".tif", ".tiff",
}


# ---------------------------------------------------------------- قرّاء الترويسات


def _png(fh):
    fh.seek(16)
    w, h = struct.unpack(">II", fh.read(8))
    return w, h


def _gif(fh):
    fh.seek(6)
    w, h = struct.unpack("<HH", fh.read(4))
    return w, h


def _bmp(fh):
    fh.seek(14)
    header_size = struct.unpack("<I", fh.read(4))[0]
    if header_size == 12:  # BITMAPCOREHEADER
        w, h = struct.unpack("<hh", fh.read(4))
    else:  # BITMAPINFOHEADER وما بعده
        w, h = struct.unpack("<ii", fh.read(8))
    return abs(w), abs(h)


def _jpeg(fh):
    """يمسح المقاطع بحثاً عن SOFn. التسلسل الصحيح الوحيد لأبعاد JPEG."""
    fh.seek(2)
    while True:
        byte = fh.read(1)
        if not byte:
            return None
        if byte != b"\xff":
            continue
        # تخطّي حشو 0xFF المتكرّر
        marker = fh.read(1)
        while marker == b"\xff":
            marker = fh.read(1)
        if not marker:
            return None
        m = marker[0]
        # علامات مستقلّة بلا طول
        if m in (0x01, 0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            continue
        length_bytes = fh.read(2)
        if len(length_bytes) < 2:
            return None
        length = struct.unpack(">H", length_bytes)[0]
        # SOF0..SOF15 ما عدا DHT(C4) و JPG(C8) و DAC(CC)
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            fh.read(1)  # precision
            h, w = struct.unpack(">HH", fh.read(4))
            return w, h
        if m == 0xDA:  # بداية المسح: لا أبعاد بعدها
            return None
        fh.seek(length - 2, os.SEEK_CUR)


def _webp(fh):
    fh.seek(12)
    chunk = fh.read(4)
    fh.read(4)  # chunk size
    if chunk == b"VP8 ":
        fh.read(6)  # frame tag + sync code
        w, h = struct.unpack("<HH", fh.read(4))
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = struct.unpack("<I", fh.read(4))[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        fh.read(4)  # flags + reserved
        wb = fh.read(3)
        hb = fh.read(3)
        w = (wb[0] | wb[1] << 8 | wb[2] << 16) + 1
        h = (hb[0] | hb[1] << 8 | hb[2] << 16) + 1
        return w, h
    return None


def _tiff(fh, little):
    e = "<" if little else ">"
    fh.seek(4)
    offset = struct.unpack(e + "I", fh.read(4))[0]
    fh.seek(offset)
    count = struct.unpack(e + "H", fh.read(2))[0]
    w = h = None
    for _ in range(count):
        entry = fh.read(12)
        if len(entry) < 12:
            break
        tag, typ = struct.unpack(e + "HH", entry[:4])
        if tag in (256, 257):
            # type 3 = SHORT, 4 = LONG
            val = struct.unpack(e + "H", entry[8:10])[0] if typ == 3 \
                else struct.unpack(e + "I", entry[8:12])[0]
            if tag == 256:
                w = val
            else:
                h = val
    if w and h:
        return w, h
    return None


def dimensions(path):
    """يعيد (w, h) أو None إذا لم تُعرف الأبعاد."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 2:
                return None
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                return _png(fh)
            if head.startswith(b"\xff\xd8"):
                return _jpeg(fh)
            if head.startswith((b"GIF87a", b"GIF89a")):
                return _gif(fh)
            if head.startswith(b"BM"):
                return _bmp(fh)
            if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
                return _webp(fh)
            if head.startswith(b"II*\x00"):
                return _tiff(fh, True)
            if head.startswith(b"MM\x00*"):
                return _tiff(fh, False)
    except Exception:
        return None
    return None


def looks_like_image(path):
    """امتداد معروف أو ترويسة معروفة — أيّهما كان."""
    if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except Exception:
        return False
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8")
        or head.startswith((b"GIF87a", b"GIF89a"))
        or head.startswith(b"BM")
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
        or head.startswith((b"II*\x00", b"MM\x00*"))
    )


# ---------------------------------------------------------------- منطق الحكم


def verdict(path):
    """يعيد (ok: bool, message: str)."""
    if not os.path.isfile(path):
        return True, ""
    if not looks_like_image(path):
        return True, ""

    dim = dimensions(path)
    if dim is None:
        return False, (
            f"محجوب: {path}\n"
            "  صورة لم تُقرأ أبعادها => مجهولة الأبعاد.\n"
            "  القاعدة: لا تُقرأ صورة مجهولة الأبعاد أبداً."
        )

    w, h = dim
    if w > MAX_DIM or h > MAX_DIM:
        longest = max(w, h)
        scale = MAX_DIM / longest
        return False, (
            f"محجوب: {path}\n"
            f"  الأبعاد {w}x{h} بكسل — الحدّ {MAX_DIM} بكسل لكل بُعد.\n"
            f"  قراءتها تُرفض بـ \"image dimensions exceed max allowed size\"،\n"
            f"  والرفض يأتي بعد انتهاء العمل => تضيع الجلسة ويُهدر الرصيد.\n"
            f"  العلاج: صغّر بمعامل {scale:.3f} أو أقل "
            f"(=> {int(w * scale)}x{int(h * scale)})، أو أعد التوليد بدقّة أقل."
        )

    return True, f"آمن: {path} = {w}x{h}"


# ---------------------------------------------------------------- الأوضاع


def mode_check(paths):
    blocked = False
    for p in paths:
        ok, msg = verdict(p)
        if ok:
            print(msg or f"آمن (ليس صورة): {p}")
        else:
            blocked = True
            print(msg, file=sys.stderr)
    return 2 if blocked else 0


def mode_dpi(args):
    if len(args) < 2:
        print("الاستخدام: imgguard.py dpi <inches_w> <inches_h>", file=sys.stderr)
        return 1
    w_in, h_in = float(args[0]), float(args[1])
    longest = max(w_in, h_in)
    max_dpi = int(MAX_DIM // longest)
    print(f"تخطيط {w_in}x{h_in} إنش — أطول بُعد {longest} إنش")
    print(f"أقصى DPI آمن = {MAX_DIM} / {longest} = {max_dpi}")
    print(f"عند {max_dpi} DPI => {int(w_in * max_dpi)}x{int(h_in * max_dpi)} بكسل")
    return 0


def _walk_strings(node):
    """يستخرج كل السلاسل من JSON متداخل — مناعة ضدّ تغيّر مخطّط الخطّاف."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def mode_hook():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # لا نحجب على إدخال غير مفهوم

    messages = []
    seen = set()
    for s in _walk_strings(payload):
        if not s or len(s) > 4096 or s in seen:
            continue
        seen.add(s)
        if not os.path.isfile(s):
            continue
        ok, msg = verdict(s)
        if not ok:
            messages.append(msg)

    if messages:
        print(
            "⛔ imgguard حجب قراءة صورة (حدّ 2000 بكسل):\n\n"
            + "\n\n".join(messages),
            file=sys.stderr,
        )
        return 2
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    mode, rest = argv[1], argv[2:]
    if mode == "check":
        return mode_check(rest)
    if mode == "dpi":
        return mode_dpi(rest)
    if mode == "hook":
        return mode_hook()
    print(f"وضع غير معروف: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
