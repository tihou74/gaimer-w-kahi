#!/usr/bin/env python3
"""
pdfpeek — جرد محتوى PDF بـPython الخالص.

البيئة هنا بلا أي محوّل PDF (pdftoppm/mutool/gs) وبلا Pillow، وPyPI وnpm
محجوبان. فهذا المحلّل يستخرج ما يمكن استخراجه بلا اعتماديّات:
الصفحات، الصور المضمّنة وأبعادها ومرشّحاتها، والنصّ.

الاستخدام:
  python3 pdfpeek.py inventory <file.pdf>
  python3 pdfpeek.py images <file.pdf> <outdir>
  python3 pdfpeek.py text <file.pdf>
"""

import os
import re
import sys
import zlib


# ---------------------------------------------------------------- تحليل الكائنات


def load_objects(data):
    """يمسح كل `N G obj ... endobj`. أمتن من قراءة xref الذي قد يكون معطوباً."""
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        num = int(m.group(1))
        start = m.end()
        end = data.find(b"endobj", start)
        if end == -1:
            continue
        objs[num] = data[start:end]
    return objs


def get_dict_value(body, key):
    """يقرأ قيمة مفتاح بسيط من قاموس PDF (رقم أو اسم أو مرجع أو مصفوفة)."""
    m = re.search(rb"/" + key.encode() + rb"\s*(\[[^\]]*\]|/[A-Za-z0-9#]+|\d+\s+\d+\s+R|-?[\d.]+)", body)
    return m.group(1).strip() if m else None


def resolve(val, objs, depth=0):
    """يتبع مرجعاً `N G R` إلى جسم الكائن."""
    if val is None or depth > 8:
        return val
    m = re.fullmatch(rb"(\d+)\s+\d+\s+R", val.strip())
    if m:
        return objs.get(int(m.group(1)))
    return val


def get_stream(body, data_after_obj=None):
    """يستخرج بايتات المجرى بين stream و endstream."""
    m = re.search(rb"stream\r?\n?", body)
    if not m:
        return None
    start = m.end()
    end = body.find(b"endstream", start)
    if end == -1:
        return None
    raw = body[start:end]
    # إزالة سطر جديد نهائي قد يضيفه المنتج
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n") or raw.endswith(b"\r"):
        raw = raw[:-1]
    return raw


def inflate(raw):
    try:
        return zlib.decompress(raw)
    except Exception:
        try:
            return zlib.decompressobj().decompress(raw)  # مجرى مقطوع
        except Exception:
            return None


# ---------------------------------------------------------------- الجرد


def inventory(path):
    with open(path, "rb") as f:
        data = f.read()

    objs = load_objects(data)
    print(f"الحجم: {len(data):,} بايت")
    print(f"إصدار: {data[:8].decode('latin1').strip()}")
    print(f"عدد الكائنات: {len(objs)}")

    pages = [n for n, b in objs.items() if re.search(rb"/Type\s*/Page\b", b)]
    print(f"عدد الصفحات: {len(pages)}")

    # المنتج
    for key in ("Producer", "Creator"):
        m = re.search(rb"/" + key.encode() + rb"\s*\(([^)]{0,120})\)", data)
        if m:
            print(f"{key}: {m.group(1).decode('latin1', 'replace')}")

    # الصور
    images = []
    for n, b in objs.items():
        if re.search(rb"/Subtype\s*/Image\b", b):
            w = get_dict_value(b, "Width")
            h = get_dict_value(b, "Height")
            filt = get_dict_value(b, "Filter")
            cs = get_dict_value(b, "ColorSpace")
            bpc = get_dict_value(b, "BitsPerComponent")
            try:
                wi, hi = int(w), int(h)
            except (TypeError, ValueError):
                wi = hi = 0
            images.append({
                "obj": n, "w": wi, "h": hi,
                "filter": (filt or b"?").decode("latin1"),
                "cs": (cs or b"?").decode("latin1"),
                "bpc": (bpc or b"?").decode("latin1"),
            })

    images.sort(key=lambda d: -(d["w"] * d["h"]))
    print(f"\nالصور المضمّنة: {len(images)}")
    if images:
        over = [i for i in images if max(i["w"], i["h"]) > 2000]
        print(f"منها متجاوزة حدّ 2000 بكسل: {len(over)}")
        print(f"\n{'كائن':>6} {'الأبعاد':>13} {'المرشّح':<18} {'فضاء اللون':<14} {'بت':>3}  حالة")
        print("-" * 76)
        for i in images[:40]:
            longest = max(i["w"], i["h"])
            state = "متجاوز" if longest > 2000 else "آمن"
            print(f"{i['obj']:>6} {i['w']:>6}x{i['h']:<6} {i['filter']:<18} "
                  f"{i['cs']:<14} {i['bpc']:>3}  {state}")
        if len(images) > 40:
            print(f"... و{len(images) - 40} صورة أخرى")

    # الخطوط
    fonts = set()
    for m in re.finditer(rb"/BaseFont\s*/([A-Za-z0-9#+,\-_]+)", data):
        fonts.add(m.group(1).decode("latin1"))
    if fonts:
        print(f"\nالخطوط ({len(fonts)}):")
        for f_ in sorted(fonts):
            print(f"  {f_}")

    return objs, images, pages


# ---------------------------------------------------------------- استخراج الصور


def extract_images(path, outdir):
    with open(path, "rb") as f:
        data = f.read()
    objs = load_objects(data)
    os.makedirs(outdir, exist_ok=True)

    count = 0
    for n, b in sorted(objs.items()):
        if not re.search(rb"/Subtype\s*/Image\b", b):
            continue
        filt = (get_dict_value(b, "Filter") or b"").decode("latin1")
        raw = get_stream(b)
        if raw is None:
            continue
        w = get_dict_value(b, "Width")
        h = get_dict_value(b, "Height")
        dims = f"{int(w)}x{int(h)}" if w and h else "unknown"

        # المرشّحات متسلسلة ويجب تطبيقها بالترتيب، مثل [/FlateDecode /DCTDecode]
        chain = re.findall(r"/([A-Za-z0-9]+)", filt)
        payload = raw
        ext = "bin"
        ok = True
        for step in chain:
            if step == "FlateDecode":
                dec = inflate(payload)
                if dec is None:
                    ok = False
                    break
                payload = dec
                ext = "raw"
            elif step == "DCTDecode":
                ext = "jpg"      # البايتات الآن JPEG كاملة
                break
            elif step == "JPXDecode":
                ext = "jp2"
                break
            elif step == "CCITTFaxDecode":
                ext = "ccitt"
                break
            elif step in ("ASCII85Decode", "ASCIIHexDecode", "RunLengthDecode",
                          "LZWDecode"):
                ok = False       # غير مدعوم — لا نُخرج بيانات مغلوطة بصمت
                break
        if not ok:
            print(f"  تُرك obj{n} (مرشّح غير مدعوم: {filt})")
            continue

        dst = os.path.join(outdir, f"img{n:04d}_{dims}.{ext}")
        with open(dst, "wb") as f2:
            f2.write(payload)
        count += 1
        print(f"  {os.path.basename(dst)}  ({os.path.getsize(dst):,} بايت, مرشّح={filt})")

    print(f"\nاستُخرجت {count} صورة إلى {outdir}")


# ---------------------------------------------------------------- استخراج النصّ


def _decode_pdf_string(s):
    """يفكّ تهريب سلاسل PDF."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):  # backslash
            nxt = s[i + 1]
            mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if nxt in mapping:
                out.append(mapping[nxt]); i += 2; continue
            if 0x30 <= nxt <= 0x37:  # octal
                oct_digits = s[i + 1:i + 4]
                j = 0
                while j < 3 and j < len(oct_digits) and 0x30 <= oct_digits[j] <= 0x37:
                    j += 1
                out.append(int(oct_digits[:j], 8) & 0xFF); i += 1 + j; continue
            out.append(nxt); i += 2; continue
        out.append(c)
        i += 1
    return bytes(out)


def extract_text(path):
    with open(path, "rb") as f:
        data = f.read()
    objs = load_objects(data)

    chunks = []
    for n, b in sorted(objs.items()):
        raw = get_stream(b)
        if raw is None:
            continue
        if re.search(rb"/Subtype\s*/Image\b", b):
            continue
        content = inflate(raw) if b"FlateDecode" in b else raw
        if content is None or b"Tj" not in content and b"TJ" not in content:
            continue
        # السلاسل داخل عمليّات إظهار النصّ
        for m in re.finditer(rb"\((?:[^()\\]|\\.)*\)", content):
            s = _decode_pdf_string(m.group(0)[1:-1])
            if s.strip():
                chunks.append(s)
        # سلاسل سدَاسيّة <...>
        for m in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>\s*Tj", content):
            hx = re.sub(rb"\s", b"", m.group(1))
            try:
                chunks.append(bytes.fromhex(hx.decode()))
            except Exception:
                pass

    print(f"مقاطع نصّيّة: {len(chunks)}")
    if not chunks:
        print("\n⚠️ لا نصّ قابل للاستخراج — الصفحات على الأرجح صور مُسطَّحة،")
        print("   أو النصّ محوّل إلى مسارات (outlines).")
        return

    print("-" * 70)
    for c in chunks:
        for enc in ("utf-16-be", "utf-8", "cp1256", "latin1"):
            try:
                t = c.decode(enc)
                if t.strip():
                    print(t)
                break
            except Exception:
                continue


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    mode, path = argv[1], argv[2]
    if not os.path.isfile(path):
        print(f"غير موجود: {path}", file=sys.stderr)
        return 1
    if mode == "inventory":
        inventory(path)
    elif mode == "images":
        extract_images(path, argv[3] if len(argv) > 3 else "pdf_images")
    elif mode == "text":
        extract_text(path)
    else:
        print(f"وضع غير معروف: {mode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
