#!/usr/bin/env python3
"""يتحقّق أنّ **كل أصل تشير إليه صفحةٌ موجودٌ فعلاً على القرص**.

لماذا هذا الحارس: صورةٌ مفقودةٌ في `srcset` **لا تُنتج أيّ خطأ يراه
الزائر** — المتصفّح يسقط بهدوءٍ على `<img src>`، أو يترك فراغاً. ولا
شيء في وحدة التحكّم يراه المالك. فتُنشر صفحةٌ فيها فراغٌ ويُقال إنّها
سليمة. وقد وقع فعلاً في هذا المشروع: `kahi-gaimer-rose-960` مكتوبةٌ في
`srcset` ولم تُولَّد قطّ، لأنّ الأصل 947 بكسلاً و**لا يُكبَّر** أصل.

ويفحص معها ثلاث قواعد لا تُرى بالعين:
  · `<img>` بلا `alt` — قارئ الشاشة يقرأ اسم الملفّ أو يسكت
  · `<img>` بلا `width`/`height` — الصفحة تقفز عند تحميل الصورة (CLS)
  · صورةٌ على القرص **لا تشير إليها أيّ صفحة** — وزنٌ يُنشَر بلا سبب

الاستخدام:
    python3 .kiro/tools/check_assets.py [<صفحة.html> ...]
    python3 .kiro/tools/check_assets.py --selftest
"""

import glob
import os
import re
import sys

ROOT = os.getcwd()

# `src="..."` و`href="..."` و`srcset="a 1x, b 2x"` و`content="..."` لـog:image
ATTR = re.compile(r'\b(src|href|srcset|content)\s*=\s*"([^"]*)"', re.I)
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I | re.S)
ASSET_EXT = (".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg",
             ".mp4", ".webm", ".ttf", ".woff", ".woff2", ".ico", ".json")


def candidates(value):
    """يُفكّك قيمة السمة إلى مسارات، ويُسقط الاستعلام والوصف."""
    # ⚠ الفحصُ عن `data:` **قبل** التفكيك بالفاصلة: عنوانُ البيانات يحمل
    # فاصلةً في بنيتِه (`data:image/gif;base64,AA`)، فتفكيكُه أوّلاً يُنتج
    # قطعةً اسمُها `AA` تُقرأ ملفاً مفقوداً. وهذا بعينُه ما أمسكه الفحصُ
    # الذاتيُّ في أوّل نسخةٍ من هذا الحارس.
    head = value.strip().lower()
    if head.startswith(("data:", "http:", "https:", "mailto:", "tel:", "//")):
        return []
    out = []
    for part in value.split(","):
        path = part.strip().split()[0] if part.strip() else ""
        if not path:
            continue
        # ⚠ `?v=1` يُقطع: ترقيم الإصدار لكسر الكاش ليس جزءاً من اسم الملفّ،
        # وأوّل نسخةٍ من هذا الحارس قرأته جزءاً فأبلغت عن ثلاثة أعطالٍ وهميّة
        path = path.split("?")[0].split("#")[0]
        if not path:
            continue
        low = path.lower()
        if low.startswith(("http:", "https:", "data:", "mailto:", "tel:", "//")):
            continue
        out.append(path)
    return out


def check_page(page):
    """يُعيد (عدد المراجع المفحوصة، الأعطال، مجموعة المسارات المُشار إليها)."""
    with open(page, encoding="utf-8") as f:
        html = f.read()
    base = os.path.dirname(os.path.abspath(page))
    checked, fails, seen = 0, [], set()

    for m in ATTR.finditer(html):
        attr, value = m.group(1).lower(), m.group(2)
        for path in candidates(value):
            # `content=` تحمل نصّاً عادياً في أغلب الوسوم — تُفحص إن كان
            # لها امتداد أصلٍ فقط، وإلّا أبلغت عن كل وصفٍ في الصفحة
            if attr == "content" and not path.lower().endswith(ASSET_EXT):
                continue
            if attr == "href" and not path.lower().endswith(ASSET_EXT):
                continue   # روابط الصفحات تُفحص بحارسٍ آخر لا هنا
            full = os.path.normpath(os.path.join(base, path))
            checked += 1
            seen.add(full)
            if not os.path.isfile(full):
                line = html[:m.start()].count("\n") + 1
                fails.append(f"{os.path.relpath(page, ROOT)}:{line} "
                             f"أصلٌ مفقود «{path}» ({attr})")

    for tag in IMG_TAG.findall(html):
        if not re.search(r'\balt\s*=', tag, re.I):
            fails.append(f"{os.path.relpath(page, ROOT)} <img> بلا alt: "
                         f"{tag[:90]}")
        if not (re.search(r'\bwidth\s*=', tag, re.I)
                and re.search(r'\bheight\s*=', tag, re.I)):
            fails.append(f"{os.path.relpath(page, ROOT)} <img> بلا width/height "
                         f"(تقفز الصفحة عند التحميل): {tag[:90]}")

    return checked, fails, seen


def selftest():
    import tempfile
    fails = []

    def run(html, extra_files=()):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "a"), exist_ok=True)
        for name in extra_files:
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("x")
        page = os.path.join(d, "i.html")
        open(page, "w", encoding="utf-8").write(html)
        return check_page(page)

    GOOD = ('<img src="a/x.jpg" width="1" height="1" alt="ص">'
            '<link rel="stylesheet" href="a/s.css?v=3">')

    # (١) السليمُ يمرُّ أوّلاً — وإلّا كلُّ «أُمسك» كذب
    n, f, _ = run(GOOD, ("a/x.jpg", "a/s.css"))
    if f:
        fails.append(f"النسخةُ السليمةُ سقطت: {f}")
    if n != 2:
        fails.append(f"فُحص {n} مرجعاً لا 2 — الحارسُ لم يرَ السطور")

    # (٢) `?v=` لا يُقرأ جزءاً من الاسم — وهو العطلُ الذي وقع في أوّل نسخة
    _, f, _ = run('<link rel="stylesheet" href="a/s.css?v=9">', ("a/s.css",))
    if f:
        fails.append(f"الاستعلامُ ?v= قُرئ جزءاً من الاسم: {f}")

    # (٣) أصلٌ مفقودٌ في srcset يُمسَك — وهو ما يسقط بهدوءٍ في المتصفّح
    _, f, _ = run('<img src="a/x.jpg" srcset="a/x-960.webp 960w" '
                  'width="1" height="1" alt="ص">', ("a/x.jpg",))
    if not any("x-960.webp" in x for x in f):
        fails.append("أصلٌ مفقودٌ في srcset لم يُمسَك")

    # (٤) alt غائب
    _, f, _ = run('<img src="a/x.jpg" width="1" height="1">', ("a/x.jpg",))
    if not any("بلا alt" in x for x in f):
        fails.append("<img> بلا alt لم يُمسَك")

    # (٥) width/height غائبان
    _, f, _ = run('<img src="a/x.jpg" alt="ص">', ("a/x.jpg",))
    if not any("width/height" in x for x in f):
        fails.append("<img> بلا أبعاد لم يُمسَك")

    # (٦) الخارجيُّ والـdata لا يُفحصان — وإلّا سقط كلُّ موقعٍ سليم
    _, f, _ = run('<img src="https://x.test/a.png" alt="ص" width="1" height="1">'
                  '<img src="data:image/gif;base64,AA" alt="ص" width="1" height="1">')
    if f:
        fails.append(f"مرجعٌ خارجيٌّ أو data سقط: {f}")

    # (٧) رابطُ صفحةٍ (`href="menu.html"`) ليس أصلاً ولا يُفحَص هنا
    _, f, _ = run('<a href="menu.html">م</a>')
    if f:
        fails.append(f"رابطُ صفحةٍ عُدَّ أصلاً مفقوداً: {f}")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 7 فحوص نجحت (السليمُ يمرّ · ?v= · srcset مفقود · alt · "
          "الأبعاد · الخارجيّ · رابطُ الصفحة)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    pages = [a for a in argv[1:] if a.endswith(".html")]
    if not pages:
        pages = sorted(glob.glob("*.html") + glob.glob("*/*.html"))
    if not pages:
        print("فشل: لا صفحةَ HTML — الفجوةُ في الحارسِ لا في الكود.",
              file=sys.stderr)
        return 1

    total, all_fails, seen = 0, [], set()
    for p in pages:
        n, f, s = check_page(p)
        total += n
        all_fails += f
        seen |= s

    if total == 0:
        print("فشل: لم يُفحَص أيُّ مرجعٍ — حارسٌ يفحص صفراً يقول «سليم» دائماً.",
              file=sys.stderr)
        return 1

    # أصولٌ على القرص لا تشير إليها أيّ صفحة — تُقال ولا تُسقط التشغيل
    on_disk = {os.path.abspath(p) for p in glob.glob("assets/img/**/*", recursive=True)
               if os.path.isfile(p) and p.lower().endswith(
                   (".png", ".jpg", ".jpeg", ".webp", ".svg"))}
    orphan = sorted(on_disk - seen)

    for x in all_fails:
        print(f"✗ {x}")
    print(f"\nفُحص {total} مرجعاً في {len(pages)} صفحة.")
    if orphan:
        print(f"ℹ {len(orphan)} صورة على القرص لا تُستعمل في أيّ صفحة "
              f"(وزنٌ يُنشَر بلا سبب — أو صورٌ محفوظةٌ لمراحل قادمة):")
        for p in orphan[:12]:
            print(f"    {os.path.relpath(p, ROOT)}")
        if len(orphan) > 12:
            print(f"    … و{len(orphan) - 12} غيرها")
    if all_fails:
        print(f"سقط {len(all_fails)}.", file=sys.stderr)
        return 1
    print("✓ كل أصلٍ مُشارٍ إليه موجود، وكل <img> له alt وأبعاد.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
