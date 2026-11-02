#!/usr/bin/env python3
"""يُولّد صفحةَ المنيو (عربيّة وإنجليزيّة) من `data/menu.json`.

مُولِّدٌ واحدٌ للغتَين لا ملفّانِ مكتوبانِ بيدٍ: ملفّان يتباعدان بأوّلِ
تعديل، فيُصحَّح سعرٌ في العربيِّ ويبقى القديمُ في الإنجليزيِّ — وزبونٌ
يقرأ سعرَين مختلفَين للطبقِ نفسِه يفقد الثقةَ في المطعمِ لا في الموقع.

وكلُّ محتوى الصفحةِ في HTML: الترشيحُ والبحثُ **تحسينٌ** لا شرط، فمن
تعثّر عنده الجافاسكربت يقرأ المنيو كاملاً.

الاستخدام:
    python3 .kiro/tools/build_menu_page.py data/menu.json
    python3 .kiro/tools/build_menu_page.py --selftest
"""

import html
import json
import os
import sys

# نصوصُ الواجهةِ باللغتَين في مكانٍ واحدٍ — فلا تُنسى ترجمةُ سطر
T = {
    "ar": {
        "lang": "ar", "dir": "rtl", "other": "en", "otherLabel": "English",
        "home": "الرئيسية", "title": "المنيو — قيمر وكاهي",
        "desc": "منيو قيمر وكاهي: {n} طبقاً في {s} أقسام، بالأسعار "
                "ومسبّبات الحساسيّة. مطعم خليجي عراقي في الدوحة.",
        "h1": "المنيو", "eyebrow": "قيمر وكاهي · الدوحة",
        "lede": "{n} طبقاً في {s} أقسام. الأسعار بالريال القطري.",
        "search": "ابحث عن طبق…", "searchLabel": "ابحث في المنيو",
        "all": "الكلّ", "none": "لا طبقَ يطابق بحثك.",
        "ask": "اسأل الفرع", "allergenHead": "مسبّبات الحساسيّة",
        "free": "خالٍ من المسبّبات الشائعة", "gfOnly": "خيار بلا غلوتين",
        "nameMissing": "الاسم العربي في الانتظار",
        "truncated": "الوصف مكمَّل في الفرع",
        "allergenNote": "نصّ مسبّبات الحساسيّة كما سجّله المطعم. وإن كان "
                        "عندك تحسّس، أخبر النادل قبل الطلب — المطبخ واحد "
                        "وقد ينتقل الأثر بين الأطباق.",
        "priceNote": "سعران مختلفان في سجلّات المطعم لهذين الطبقين، فلم "
                     "يُنشر أيّهما. اسأل الفرع.",
        "footerBack": "رجوع إلى الرئيسية",
        "jump": "انتقل إلى قسم",
    },
    "en": {
        "lang": "en", "dir": "ltr", "other": "ar", "otherLabel": "العربية",
        "home": "Home", "title": "Menu — Gaimer W Kahi",
        "desc": "Gaimer W Kahi menu: {n} dishes across {s} sections, with "
                "prices and allergens. Iraqi & Gulf restaurant in Doha.",
        "h1": "Menu", "eyebrow": "Gaimer W Kahi · Doha",
        "lede": "{n} dishes across {s} sections. Prices in Qatari Riyal.",
        "search": "Search a dish…", "searchLabel": "Search the menu",
        "all": "All", "none": "No dish matches your search.",
        "ask": "Ask the branch", "allergenHead": "Allergens",
        "free": "Free from common allergens", "gfOnly": "Gluten-free option",
        "nameMissing": "Arabic name pending",
        "truncated": "Full description at the branch",
        "allergenNote": "Allergen text as recorded by the restaurant. If you "
                        "have an allergy, tell your server before ordering — "
                        "one kitchen prepares all dishes and traces can carry.",
        "priceNote": "Two different prices exist in the restaurant's records "
                     "for these two items, so neither was published. "
                     "Please ask the branch.",
        "footerBack": "Back to home",
        "jump": "Jump to a section",
    },
}


def e(s):
    return html.escape(s or "", quote=True)


def dish_html(d, t, labels):
    """بطاقةُ طبقٍ واحد. كلُّ غيابٍ **يُعلن نفسَه** ولا يُترك فراغاً."""
    ar = t["lang"] == "ar"
    name = (d["nameAr"] or d["name"]) if ar else d["name"]
    # الاسمُ العربيُّ الغائبُ: يُعرض الإنجليزيُّ بـlang/dir صحيحَين وبوسمٍ.
    # ولا يُترجَم — اسمٌ مُخترعٌ يجعل النادلَ لا يعرف ما طُلب.
    name_missing = ar and not d["nameAr"]
    desc = (d["descriptionAr"] or d["description"]) if ar else d["description"]

    rows = [f'<h3 class="mi__n"{" lang=en dir=ltr" if name_missing else ""}>'
            f'{e(name)}</h3>']
    if desc:
        rows.append(f'<p class="mi__d">{e(desc)}</p>')

    tags = []
    if name_missing:
        tags.append(f'<span class="pending">{e(t["nameMissing"])}</span>')
    if d.get("truncated"):
        tags.append(f'<span class="pending">{e(t["truncated"])}</span>')
    if d.get("freeCommon"):
        tags.append(f'<span class="tag tag--veg">{e(t["free"])}</span>')
    if d.get("glutenFreeOnly"):
        tags.append(f'<span class="tag">{e(t["gfOnly"])}</span>')

    # نصُّ المالكِ (`allergenText`) هو المرجعُ ويُعرض كما هو في العربيّة.
    # والإنجليزيّةُ تُبنى من الرموزِ المعنونةِ — ولا تُترجَم نصُّه آلياً.
    al = ""
    if ar and d.get("allergenText"):
        al = e(d["allergenText"])
    elif not ar and d.get("allergenHas"):
        al = ", ".join(e(labels.get(k, {}).get("en", k)) for k in d["allergenHas"])
    if al:
        rows.append(f'<p class="mi__a"><span>{e(t["allergenHead"])}:</span> {al}</p>')

    if tags:
        rows.append('<div class="mi__t">' + "".join(tags) + "</div>")

    if d["price"] is None:
        price = f'<span class="pending">{e(t["ask"])}</span>'
    else:
        p = d["price"]
        num = f"{p:.0f}" if abs(p - round(p)) < 0.005 else f"{p:.2f}"
        cur = t["lang"] == "ar" and "ر.ق" or "QAR"
        price = f'<span class="mi__p price">{num} <small>{cur}</small></span>'

    return ('<li class="mi" data-name="' + e((name + " " + (d["name"] or "")).lower())
            + '">\n  <div class="mi__b">' + "".join(rows) + "</div>\n  "
            + price + "\n</li>")


def page_html(data, lang):
    t = T[lang]
    labels = data.get("allergenLabels") or {}
    secs = data["sections"]
    n = sum(len(s["dishes"]) for s in secs)
    base = "../" if lang != "ar" else ""
    other_href = "en/menu.html" if lang == "ar" else "../menu.html"
    home_href = "index.html" if lang == "ar" else "index.html"

    chips = [f'<button class="chip is-on" data-sec="all" type="button">'
             f'{e(t["all"])}</button>']
    blocks = []
    for s in secs:
        sec_name = s["nameAr"] if lang == "ar" else s["name"]
        note = ""
        if s.get("note"):
            note = f'<em class="ms__note">{e(s["note"][lang])}</em>'
        chips.append(f'<button class="chip" data-sec="{e(s["id"])}" type="button">'
                     f'{e(sec_name)} <span class="num">{len(s["dishes"])}</span></button>')
        items = "\n".join(dish_html(d, t, labels) for d in s["dishes"])
        blocks.append(f'''<section class="ms" id="{e(s["id"])}" data-sec="{e(s["id"])}">
  <h2 class="ms__h">{e(sec_name)} {note}</h2>
  <ul class="ms__l">
{items}
  </ul>
</section>''')

    return f'''<!doctype html>
<html lang="{t["lang"]}" dir="{t["dir"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(t["title"])}</title>
<meta name="description" content="{e(t["desc"].format(n=n, s=len(secs)))}">
<!-- ⚠ مُولَّدٌ آلياً من data/menu.json بـ.kiro/tools/build_menu_page.py
     لا يُحرَّر بيدٍ: التحريرُ يضيع في أوّلِ إعادةِ بناء. -->
<link rel="alternate" hreflang="ar" href="{"./menu.html" if lang == "ar" else "../menu.html"}">
<link rel="alternate" hreflang="en" href="{"en/menu.html" if lang == "ar" else "./menu.html"}">
<link rel="icon" href="{base}assets/img/logo.png">
<link rel="stylesheet" href="{base}assets/css/tokens.css?v=1">
<link rel="stylesheet" href="{base}assets/css/base.css?v=1">
<link rel="stylesheet" href="{base}assets/css/layout.css?v=1">
<link rel="stylesheet" href="{base}assets/css/menu.css?v=1">
</head>
<body>
<a class="skip" href="#menu">{e(t["home"])}</a>

<header class="hdr">
  <div class="wrap hdr__in">
    <a class="hdr__logo" href="{home_href}" aria-label="{e(t["home"])}">
      <img src="{base}assets/img/logo.png" alt="Gaimer W Kahi" width="711" height="351">
    </a>
    <nav class="nav" aria-label="{e(t["jump"])}">
      <a href="{home_href}">{e(t["home"])}</a>
      <a href="{"menu.html" if lang == "ar" else "menu.html"}" aria-current="page">{e(t["h1"])}</a>
    </nav>
    <div class="hdr__side">
      <a class="lang" href="{other_href}" lang="{t["other"]}" hreflang="{t["other"]}">{e(t["otherLabel"])}</a>
    </div>
  </div>
</header>

<main id="menu">
  <div class="wrap">
    <div class="mhead">
      <p class="eyebrow">{e(t["eyebrow"])}</p>
      <h1>{e(t["h1"])}</h1>
      <p class="mhead__lede">{e(t["lede"].format(n=n, s=len(secs)))}</p>
      <p class="mhead__note">{e(t["priceNote"])}</p>
    </div>

    <div class="mtools">
      <label class="sr-only" for="q">{e(t["searchLabel"])}</label>
      <input id="q" class="msearch" type="search" placeholder="{e(t["search"])}"
             autocomplete="off">
      <div class="chips" id="chips">{"".join(chips)}</div>
    </div>

    <p class="mnone" id="none" hidden>{e(t["none"])}</p>

{"".join(blocks)}

    <p class="mfoot">{e(t["allergenNote"])}</p>
    <p class="mfoot"><a href="{home_href}">{e(t["footerBack"])}</a></p>
  </div>
</main>

<script src="{base}assets/js/menu.js?v=1" defer></script>
</body>
</html>
'''


def selftest():
    fails = []
    labels = {"milk": {"en": "Milk", "ar": "حليب"}}
    data = {
        "allergenLabels": labels,
        "sections": [{
            "id": "breakfast", "name": "Breakfast", "nameAr": "صباح الخير",
            "note": {"ar": "طول اليوم", "en": "All day"},
            "dishes": [
                {"name": "Kahi", "nameAr": "كاهي", "description": "puff",
                 "descriptionAr": "فطيرة", "price": 35.0, "priceConflict": None,
                 "truncated": False, "allergenText": "غلوتين، حليب",
                 "allergenHas": ["milk"], "allergenMay": [],
                 "freeCommon": False, "glutenFreeOnly": False},
                {"name": "Ryoq Tray", "nameAr": None, "description": "tray",
                 "descriptionAr": None, "price": None,
                 "priceConflict": {"program": 188, "ownerFile": 170},
                 "truncated": True, "allergenText": None,
                 "allergenHas": [], "allergenMay": [],
                 "freeCommon": True, "glutenFreeOnly": False},
            ]}]}

    ar = page_html(data, "ar")
    en = page_html(data, "en")

    # (١) المُدخلُ أنتج محتوًى غيرَ فارغ
    cards = ar.count('class="mi"')
    if cards != 2:
        fails.append(f"بطاقاتُ الأطباقِ {cards} لا 2")

    # (٢) السعرُ المحجوبُ **لا يظهر رقمُه** — لا 188 ولا 170
    if "188" in ar or "170" in ar:
        fails.append("رقمُ سعرٍ متعارضٍ ظهر في الصفحة")
    if "اسأل الفرع" not in ar:
        fails.append("بديلُ السعرِ المحجوبِ غائب")

    # (٣) الاسمُ العربيُّ الغائبُ: يظهر الإنجليزيُّ بـlang=en **ووسمٌ**
    if 'lang=en dir=ltr>Ryoq Tray' not in ar:
        fails.append("الاسمُ الإنجليزيُّ بلا lang/dir في الصفحةِ العربيّة")
    if "الاسم العربي في الانتظار" not in ar:
        fails.append("وسمُ الاسمِ العربيِّ الغائبِ لم يظهر")

    # (٤) نصُّ المالكِ يُعرض في العربيّة، والإنجليزيّةُ من الرموزِ المعنونة
    if "غلوتين، حليب" not in ar:
        fails.append("نصُّ حساسيّةِ المالكِ لم يُعرض في العربيّة")
    if "Milk" not in en:
        fails.append("عنوانُ الحساسيّةِ الإنجليزيُّ لم يُبنَ من الرموز")
    if "غلوتين، حليب" in en:
        fails.append("نصٌّ عربيٌّ ظهر في الصفحةِ الإنجليزيّة")

    # (٥) الاتّجاهُ واللغةُ صحيحانِ في كلٍّ
    if 'lang="ar" dir="rtl"' not in ar or 'lang="en" dir="ltr"' not in en:
        fails.append("lang/dir خطأٌ في إحدى الصفحتَين")

    # (٦) مساراتُ الأصولِ تختلف بعمقِ المجلّد — وإلّا فقدت en/ خطَّها وصورَها
    if 'href="assets/css/tokens.css?v=1"' not in ar:
        fails.append("مسارُ الأصولِ في العربيّةِ ليس نسبيّاً للجذر")
    if 'href="../assets/css/tokens.css?v=1"' not in en:
        fails.append("مسارُ الأصولِ في en/ لا يصعد مجلّداً — ستُصوَّر بلا خطّ")

    # (٧) كلُّ قسمٍ له مِرساةٌ بنفسِ المعرّفِ الذي تُشير إليه الرئيسيّة
    if 'id="breakfast"' not in ar:
        fails.append("مِرساةُ القسمِ غائبةٌ — رابطُ الرئيسيّةِ #breakfast يسقط")

    # (٨) الوصفُ المقطوعُ مُوسَّم
    if "الوصف مكمَّل في الفرع" not in ar:
        fails.append("وسمُ الوصفِ المقطوعِ غائب")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 8 فحوص نجحت (العددُ · حجبُ الرقمِ · lang الاسمِ الغائبِ · نصُّ "
          "المالكِ ولا عربيَّ في الإنجليزيّةِ · الاتّجاهُ · عمقُ الأصولِ · "
          "المِرساةُ · الوصفُ المقطوع)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    src = argv[1] if len(argv) > 1 else "data/menu.json"
    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    n = sum(len(s["dishes"]) for s in data["sections"])
    if n == 0:
        print("فشل: صفرُ أطباقٍ — لا تُكتب صفحةٌ فارغةٌ فوقَ صفحةٍ عاملة.",
              file=sys.stderr)
        return 1

    for lang, out in (("ar", "menu.html"), ("en", "en/menu.html")):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(page_html(data, lang))
        print(f"  {out}  ({os.path.getsize(out) // 1024} ك.ب)")
    print(f"✓ {n} طبقاً في {len(data['sections'])} أقسام × لغتَين")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
