#!/usr/bin/env python3
"""
pdftext — استخراج نصّ PDF بفكّ خرائط ToUnicode، مع معالجة العربية.

يحلّ ثلاث مشاكل تجعل الاستخراج الساذج يُنتج رموزاً مشوّشة:
  1. الخطوط المجزّأة (subset) تُخزّن معرّفات رسوم لا Unicode => نقرأ /ToUnicode
  2. العربية تُخزَّن بأشكالها التقديميّة (presentation forms) => NFKC يُعيدها
  3. العربية تُخزَّن بترتيب بصري => نعكس المقاطع العربية لتعود منطقيّة

الاستخدام:
  python3 pdftext.py <file.pdf> [--page N] [--raw]
"""

import re
import sys
import unicodedata
import zlib


# ---------------------------------------------------------------- أدوات PDF


def load_objects(data):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        num = int(m.group(1))
        end = data.find(b"endobj", m.end())
        if end != -1:
            objs[num] = data[m.end():end]
    return objs


def deref(val, objs, depth=0):
    """يتبع `N G R` حتى يصل إلى جسم فعلي."""
    if val is None or depth > 10:
        return val
    m = re.fullmatch(rb"\s*(\d+)\s+\d+\s+R\s*", val)
    if m:
        return deref(objs.get(int(m.group(1)), b""), objs, depth + 1)
    return val


def balanced_dict(body, start):
    """يُرجع نصّ القاموس المتوازن << ... >> بدءاً من موضع '<<'."""
    i = body.find(b"<<", start)
    if i == -1:
        return None
    depth = 0
    j = i
    while j < len(body) - 1:
        if body[j:j + 2] == b"<<":
            depth += 1
            j += 2
            continue
        if body[j:j + 2] == b">>":
            depth -= 1
            j += 2
            if depth == 0:
                return body[i:j]
            continue
        j += 1
    return None


def dict_after_key(body, key):
    """القاموس المتوازن الذي يلي /key مباشرة."""
    m = re.search(rb"/" + key + rb"\s*", body)
    if not m:
        return None
    rest = body[m.end():]
    if rest[:2] != b"<<":
        return None
    return balanced_dict(body, m.end())


def get_stream(body):
    m = re.search(rb"stream\r?\n?", body)
    if not m:
        return None
    end = body.find(b"endstream", m.end())
    if end == -1:
        return None
    raw = body[m.end():end]
    for tail in (b"\r\n", b"\n", b"\r"):
        if raw.endswith(tail):
            raw = raw[:-len(tail)]
            break
    return raw


def inflate(raw):
    for fn in (zlib.decompress,
               lambda r: zlib.decompressobj().decompress(r),
               lambda r: zlib.decompressobj(-15).decompress(r)):
        try:
            return fn(raw)
        except Exception:
            continue
    return None


def stream_data(body):
    raw = get_stream(body)
    if raw is None:
        return None
    if b"FlateDecode" in body:
        return inflate(raw)
    return raw


# ---------------------------------------------------------------- خرائط ToUnicode


def _hex_to_str(h):
    """سلسلة سدَاسيّة بترميز UTF-16BE => نصّ."""
    if not h:
        return ""
    if len(h) % 2:
        h += b"0"
    try:
        b = bytes.fromhex(h.decode("ascii"))
    except Exception:
        return ""
    try:
        return b.decode("utf-16-be", "ignore")
    except Exception:
        return ""


def parse_tounicode(s):
    """يحلّل خريطة ToUnicode => dict{code: نصّ}."""
    cmap = {}

    # bfrange بالصيغة المصفوفيّة: <lo> <hi> [<d1> <d2> ...]
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", s, re.S):
        remaining = block
        for m in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]",
                block, re.S):
            lo = int(m.group(1), 16)
            for i, item in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", m.group(3))):
                cmap[lo + i] = _hex_to_str(item)
            remaining = remaining.replace(m.group(0), b" ")
        # bfrange بالصيغة المتدرّجة: <lo> <hi> <dstStart>
        for m in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                remaining):
            lo, hi = int(m.group(1), 16), int(m.group(2), 16)
            dst = m.group(3)
            base_str = _hex_to_str(dst)
            if not base_str:
                continue
            base = ord(base_str[-1])
            prefix = base_str[:-1]
            if hi - lo > 65535:
                continue
            for i in range(hi - lo + 1):
                cp = base + i
                if cp < 0x110000:
                    cmap[lo + i] = prefix + chr(cp)

    # bfchar: <src> <dst>
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", s, re.S):
        for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            cmap[int(m.group(1), 16)] = _hex_to_str(m.group(2))

    return cmap


def build_font_cmaps(objs):
    """لكل كائن خطّ: (cmap, عدد بايتات الكود)."""
    fonts = {}
    for n, body in objs.items():
        if not re.search(rb"/Type\s*/Font\b", body):
            continue
        two_byte = bool(re.search(rb"/Subtype\s*/Type0\b", body)) or \
            bool(re.search(rb"/Identity-H", body))
        cmap = {}
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if m:
            tu = objs.get(int(m.group(1)))
            if tu:
                sdata = stream_data(tu)
                if sdata:
                    cmap = parse_tounicode(sdata)
        fonts[n] = (cmap, 2 if two_byte else 1)
    return fonts


# ---------------------------------------------------------------- معالجة العربية


ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
)


def is_arabic(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ARABIC_RANGES)


def normalize_arabic(text):
    """الأشكال التقديميّة => حروف أساسيّة (NFKC يتولّى ذلك قياسيّاً)."""
    return unicodedata.normalize("NFKC", text)


def fix_direction(text):
    """النصّ العربي مخزّن بترتيب بصري — نعكسه ليعود منطقيّاً."""
    arabic = sum(1 for c in text if is_arabic(c))
    letters = sum(1 for c in text if c.isalpha())
    if letters and arabic / letters > 0.5:
        return text[::-1]
    return text


# ---------------------------------------------------------------- استخراج الصفحات


def page_tree(objs):
    """قائمة أرقام كائنات الصفحات بترتيب شجرة /Kids إن أمكن."""
    pages = [n for n, b in objs.items() if re.search(rb"/Type\s*/Page\b", b)]
    root = None
    for n, b in objs.items():
        if re.search(rb"/Type\s*/Pages\b", b) and b"/Parent" not in b:
            root = n
            break
    if root is None:
        return sorted(pages)

    order, seen = [], set()

    def walk(num, depth=0):
        if num in seen or depth > 32:
            return
        seen.add(num)
        body = objs.get(num, b"")
        if re.search(rb"/Type\s*/Page\b", body):
            order.append(num)
            return
        kids = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
        if kids:
            for m in re.finditer(rb"(\d+)\s+\d+\s+R", kids.group(1)):
                walk(int(m.group(1)), depth + 1)

    walk(root)
    for p in sorted(pages):
        if p not in order:
            order.append(p)
    return order


def page_content(objs, pnum):
    """يدمج مجاري /Contents للصفحة."""
    body = objs.get(pnum, b"")
    m = re.search(rb"/Contents\s*(\d+)\s+\d+\s+R", body)
    refs = []
    if m:
        refs = [int(m.group(1))]
    else:
        m = re.search(rb"/Contents\s*\[(.*?)\]", body, re.S)
        if m:
            refs = [int(x.group(1))
                    for x in re.finditer(rb"(\d+)\s+\d+\s+R", m.group(1))]
    out = b""
    for r in refs:
        d = stream_data(objs.get(r, b""))
        if d:
            out += d + b"\n"
    return out


def page_fonts(objs, pnum, fonts):
    """خريطة اسم المورد (/F1) => (cmap, bytes) لهذه الصفحة."""
    body = objs.get(pnum, b"")
    res = dict_after_key(body, b"Resources")
    if res is None:
        m = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", body)
        if m:
            res = objs.get(int(m.group(1)), b"")
    if not res:
        return {}
    fdict = dict_after_key(res, b"Font")
    if fdict is None:
        m = re.search(rb"/Font\s+(\d+)\s+\d+\s+R", res)
        if m:
            fdict = objs.get(int(m.group(1)), b"")
    if not fdict:
        return {}
    out = {}
    for m in re.finditer(rb"/([A-Za-z0-9_.\-]+)\s+(\d+)\s+\d+\s+R", fdict):
        ref = int(m.group(2))
        if ref in fonts:
            out[m.group(1)] = fonts[ref]
    return out


def unescape(s):
    out = bytearray()
    i = 0
    esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in esc:
                out.append(esc[nxt]); i += 2; continue
            if 0x30 <= nxt <= 0x37:
                j = 0
                while j < 3 and i + 1 + j < len(s) and 0x30 <= s[i + 1 + j] <= 0x37:
                    j += 1
                out.append(int(s[i + 1:i + 1 + j], 8) & 0xFF); i += 1 + j; continue
            out.append(nxt); i += 2; continue
        out.append(c); i += 1
    return bytes(out)


def decode_with(cmap, nbytes, raw):
    chars = []
    if nbytes == 2:
        for i in range(0, len(raw) - 1, 2):
            code = (raw[i] << 8) | raw[i + 1]
            chars.append(cmap.get(code, ""))
    else:
        for b in raw:
            chars.append(cmap.get(b, chr(b) if 32 <= b < 127 else ""))
    return "".join(chars)


NUM = rb"[-+]?[\d.]+"

TOKEN = re.compile(
    rb"/([A-Za-z0-9_.\-]+)\s+" + NUM + rb"\s+Tf"      # 1: اختيار خطّ
    rb"|\((?:[^()\\]|\\.)*\)\s*(?:Tj|TJ|')"           # سلسلة مفردة
    rb"|\[((?:[^\[\]\\]|\\.)*)\]\s*TJ"                # 2: مصفوفة TJ
    rb"|<([0-9A-Fa-f\s]+)>\s*(?:Tj|TJ|')"             # 3: سلسلة سدَاسيّة
    rb"|(" + NUM + rb")\s+(" + NUM + rb")\s+(?:Td|TD)"  # 4,5: إزاحة
    rb"|(?:" + NUM + rb"\s+){4}(" + NUM + rb")\s+(" + NUM + rb")\s+Tm"  # 6,7
    rb"|(T\*|ET|BT)",                                 # 8: فواصل
    re.S)


def _group_lines(items):
    """items = [(y, x, text)] => أسطر مرتّبة منطقيّاً.

    العربية تُرسم يميناً-لشمال، فالكلمة ذات x الأكبر تأتي أولاً منطقيّاً.
    """
    if not items:
        return []
    lines = {}
    for y, x, t in items:
        lines.setdefault(round(y, 1), []).append((x, t))

    out = []
    for y in sorted(lines, reverse=True):          # أعلى الصفحة أولاً
        words = lines[y]
        joined = "".join(t for _, t in words)
        arabic = sum(1 for c in joined if is_arabic(c))
        letters = sum(1 for c in joined if c.isalpha())
        rtl = letters and arabic / letters > 0.5
        # في العربية تُخزَّن الرسوم بترتيب بصري على مستويين:
        #   1. الكلمات: الأيمن (x الأكبر) هو الأوّل منطقيّاً
        #   2. الحروف داخل الكلمة: معكوسة، فنعكسها
        words.sort(key=lambda p: -p[0] if rtl else p[0])
        if rtl:
            words = [(x, t[::-1]) for x, t in words]
        text = " ".join(t.strip() for _, t in words if t.strip())
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            out.append(text)
    return out


def extract(path, only_page=None, raw_mode=False):
    with open(path, "rb") as f:
        data = f.read()
    objs = load_objects(data)
    fonts = build_font_cmaps(objs)
    order = page_tree(objs)

    mapped = sum(1 for c, _ in fonts.values() if c)
    print(f"# الصفحات: {len(order)} | الخطوط: {len(fonts)} "
          f"| منها بخريطة ToUnicode: {mapped}\n")

    for idx, pnum in enumerate(order, 1):
        if only_page and idx != only_page:
            continue
        content = page_content(objs, pnum)
        if not content:
            continue
        pfonts = page_fonts(objs, pnum, fonts)
        cur = (dict(), 1)
        cx = cy = 0.0
        items = []          # (y, x, نصّ) لإعادة الترتيب المنطقي لاحقاً

        def emit(txt):
            if txt and txt.strip():
                items.append((cy, cx, normalize_arabic(txt)))

        for m in TOKEN.finditer(content):
            whole = m.group(0)
            if m.group(1):                                   # Tf
                cur = pfonts.get(m.group(1), cur)
            elif m.group(2) is not None:                     # TJ array
                parts = ""
                for sm in re.finditer(rb"\((?:[^()\\]|\\.)*\)|<([0-9A-Fa-f\s]+)>",
                                      m.group(2)):
                    if sm.group(1):
                        hx = re.sub(rb"\s", b"", sm.group(1))
                        try:
                            rawb = bytes.fromhex(hx.decode())
                        except Exception:
                            continue
                    else:
                        rawb = unescape(sm.group(0)[1:-1])
                    parts += decode_with(cur[0], cur[1], rawb)
                emit(parts)
            elif m.group(3):                                 # hex Tj
                hx = re.sub(rb"\s", b"", m.group(3))
                try:
                    emit(decode_with(cur[0], cur[1], bytes.fromhex(hx.decode())))
                except Exception:
                    pass
            elif m.group(4) is not None and m.group(5) is not None:   # Td/TD
                try:
                    cx, cy = float(m.group(4)), float(m.group(5))
                except ValueError:
                    pass
            elif m.group(6) is not None and m.group(7) is not None:   # Tm
                try:
                    cx, cy = float(m.group(6)), float(m.group(7))
                except ValueError:
                    pass
            elif m.group(8):
                pass                                          # BT/ET/T*
            else:                                             # (..) Tj
                inner = whole[whole.index(b"(") + 1:whole.rindex(b")")]
                emit(decode_with(cur[0], cur[1], unescape(inner)))

        if raw_mode:
            lines = [t for _, _, t in items]
        else:
            lines = _group_lines(items)
        if not lines:
            continue

        print(f"{'=' * 64}\n### صفحة {idx}  (كائن {pnum})\n{'=' * 64}")
        for ln in lines:
            if ln.strip():
                print(ln.strip())
        print()


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    page = None
    if "--page" in argv:
        page = int(argv[argv.index("--page") + 1])
    extract(argv[1], page, "--raw" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
