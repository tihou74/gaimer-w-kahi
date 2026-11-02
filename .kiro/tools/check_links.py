#!/usr/bin/env python3
"""يتحقّق أنّ **كل رابطٍ داخليٍّ يصل إلى صفحةٍ موجودةٍ ومِرساةٍ موجودة**.

لماذا: رابطٌ ميّتٌ في قائمةٍ **لا يُبلّغ عن نفسِه**. الزائر يضغط «المنيو»
فيرى صفحةَ 404، أو يضغط `menu.html#pastry` فيهبط في أعلى الصفحةِ ولا
يفهم لماذا — ولا شيءَ في وحدةِ التحكّمِ يقوله، ولا يكتشفُه إلّا هو.
وهذا بعينُه بابُ «الزرِّ الميّتِ الصامت».

الاستخدام:
    python3 .kiro/tools/check_links.py [<صفحة.html> ...]
    python3 .kiro/tools/check_links.py --selftest
"""

import glob
import os
import re
import sys

HREF = re.compile(r'<a\b[^>]*\bhref\s*=\s*"([^"]*)"', re.I)
ID = re.compile(r'\bid\s*=\s*"([^"]+)"')
# معرّفاتُ الأقسامِ في صفحةِ المنيو مُولَّدةٌ، فتُقرأ من الصفحةِ نفسِها


def ids_of(path):
    try:
        with open(path, encoding="utf-8") as f:
            return set(ID.findall(f.read()))
    except OSError:
        return set()


def check(pages):
    checked, fails = 0, []
    id_cache = {}

    for page in pages:
        with open(page, encoding="utf-8") as f:
            html = f.read()
        base = os.path.dirname(os.path.abspath(page))
        own_ids = set(ID.findall(html))

        for href in HREF.findall(html):
            h = href.strip()
            low = h.lower()
            if (not h or low.startswith(("http:", "https:", "mailto:", "tel:",
                                         "data:", "//", "javascript:"))):
                continue
            checked += 1

            # (أ) مِرساةٌ في نفسِ الصفحة
            if h.startswith("#"):
                anchor = h[1:]
                if anchor and anchor not in own_ids:
                    fails.append(f"{page}: «#{anchor}» لا وجودَ له في نفسِ الصفحة")
                continue

            target, _, anchor = h.partition("#")
            if not target:
                continue

            # (ب) الصفحةُ الهدف
            full = os.path.normpath(os.path.join(base, target))
            if os.path.isdir(full):
                full = os.path.join(full, "index.html")
            if target.endswith("/"):
                full = os.path.normpath(os.path.join(base, target, "index.html"))
            if not os.path.isfile(full):
                fails.append(f"{page}: «{h}» ⇒ لا ملفَّ {os.path.relpath(full)}")
                continue

            # (ج) المِرساةُ **داخلَ** الصفحةِ الهدف — وهي التي تُنسى
            if anchor:
                if full not in id_cache:
                    id_cache[full] = ids_of(full)
                if anchor not in id_cache[full]:
                    fails.append(f"{page}: «{h}» ⇒ الصفحةُ موجودةٌ "
                                 f"و«#{anchor}» لا وجودَ له فيها")

    return checked, fails


def selftest():
    import tempfile
    fails = []

    def run(files, page="a.html"):
        d = tempfile.mkdtemp()
        for name, body in files.items():
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        return check([os.path.join(d, page)])

    # (١) السليمُ يمرُّ أوّلاً
    n, f = run({"a.html": '<a href="b.html#sec">x</a><a href="#here">y</a>'
                          '<div id="here"></div>',
                "b.html": '<section id="sec"></section>'})
    if f:
        fails.append(f"النسخةُ السليمةُ سقطت: {f}")
    if n != 2:
        fails.append(f"فُحص {n} رابطاً لا 2")

    # (٢) صفحةٌ غائبة
    _, f = run({"a.html": '<a href="ghost.html">x</a>'})
    if not any("لا ملفَّ" in x for x in f):
        fails.append("صفحةٌ غائبةٌ لم تُمسَك")

    # (٣) **مِرساةٌ غائبةٌ في صفحةٍ موجودة** — وهي الحالةُ التي تُنسى
    _, f = run({"a.html": '<a href="b.html#nope">x</a>', "b.html": '<p>ب</p>'})
    if not any("لا وجودَ له فيها" in x for x in f):
        fails.append("مِرساةٌ غائبةٌ في صفحةٍ موجودةٍ لم تُمسَك")

    # (٤) مِرساةٌ غائبةٌ في نفسِ الصفحة
    _, f = run({"a.html": '<a href="#nope">x</a>'})
    if not any("نفسِ الصفحة" in x for x in f):
        fails.append("مِرساةٌ غائبةٌ محليّاً لم تُمسَك")

    # (٥) مجلّدٌ بشرطةٍ مائلة ⇒ index.html داخلَه
    n5, f = run({"a.html": '<a href="en/">x</a>', "en/index.html": 'ه'})
    if f:
        fails.append(f"رابطُ مجلّدٍ سليمٌ سقط: {f}")
    if n5 != 1:
        fails.append(f"رابطُ المجلّدِ لم يُفحَص ({n5})")

    # (٦) الخارجيُّ لا يُفحَص
    _, f = run({"a.html": '<a href="https://x.test">x</a><a href="tel:+974">y</a>'})
    if f:
        fails.append(f"رابطٌ خارجيٌّ سقط: {f}")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 6 فحوص نجحت (السليمُ يمرّ · صفحةٌ غائبة · مِرساةٌ غائبةٌ في "
          "صفحةٍ موجودة · مِرساةٌ محليّة · رابطُ مجلّد · الخارجيّ)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    pages = [a for a in argv[1:] if a.endswith(".html")]
    if not pages:
        pages = sorted(glob.glob("*.html") + glob.glob("*/*.html"))
    pages = [p for p in pages if not os.path.basename(p).startswith(".")]
    if not pages:
        print("فشل: لا صفحةَ HTML.", file=sys.stderr)
        return 1

    checked, fails = check(pages)
    if checked == 0:
        print("فشل: لم يُفحَص أيُّ رابط — حارسٌ يفحص صفراً يقول «سليم» دائماً.",
              file=sys.stderr)
        return 1
    for x in fails:
        print(f"✗ {x}")
    if fails:
        print(f"\nسقط {len(fails)} من {checked} رابطاً.", file=sys.stderr)
        return 1
    print(f"✓ {checked} رابطاً داخليّاً في {len(pages)} صفحة — كلّها تصل.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
