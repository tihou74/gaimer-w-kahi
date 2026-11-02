#!/usr/bin/env python3
"""يدمج المنيو الإنجليزيَّ والعربيَّ والحساسيّات في ملفٍّ واحدٍ للموقع.

ثلاثةُ قراراتٍ مقصودة — وكلُّها عن **ألّا يُنشر رقمٌ أو اسمٌ لم يقله المالك**:

  ١) **السعرُ المتعارضُ لا يُنشَر ولا يُخمَّن.** صينيّتان سعرُهما في البرنامج
     يخالف سعرَهما في ملفِّ المالك (188/170 و152/130). فالطبقُ يُوسَم
     `priceConflict` ويُحجَب سعرُه من الموقعِ ويُكتب «اسأل الفرع» — سعرٌ
     خاطئٌ على صفحةٍ عامّةٍ يُنتج خلافاً على الطاولةِ أمام العميل، وسعرٌ
     غائبٌ يُنتج سؤالاً وحدَه.

  ٢) **الاسمُ العربيُّ الغائبُ يسقط على الإنجليزيِّ ولا يُترجَم.** خمسةُ
     أطباقٍ بلا اسمٍ عربيّ. واسمٌ مُخترعٌ في منيو مطعمٍ أسوأُ من اسمٍ
     إنجليزيٍّ يفهمه القارئ، لأنّ النادلَ لا يعرف ما طُلب.

  ٣) **الوصفُ المقطوعُ يبقى مقطوعاً بـ«…»** كما في ملفِّ المالكِ نفسِه،
     ويُوسَم `truncated` فيظهر على الصفحةِ أنّ الكلامَ يتبع.

الاستخدام:
    python3 .kiro/tools/build_menu.py <مجلّد-menu-seed> <out.json>
    python3 .kiro/tools/build_menu.py --selftest
"""

import json
import os
import sys

# ترتيبُ الأقسامِ على الصفحةِ: كما يقرؤها الزبونُ في المطعمِ لا كما
# خرجت من الـPDF — الريوقُ أوّلاً لأنّه هُويّةُ المكان.
SECTION_ORDER = [
    "Breakfast (All Day)",
    "Appetizer Cold & Hot",
    "Lunch And Dinner (All Day)",
    "Iraqi Grill (From 12pm)",
    "Banquet Trays",
    "Gaimer W Kahi Boxes",
    "PASTRY",
    "HOT DRINKS & COFFEE",
    "Fresh Juices & Mocktails",
    "Soft Drinks & Water",
]

# أقسامٌ بوقتٍ مشروطٍ مكتوبٍ في اسمِها — يُفصل الشرطُ عن الاسمِ ليُعرض وسماً
SECTION_NOTE = {
    "Iraqi Grill (From 12pm)": {
        "en": "From 12:00 noon",
        "ar": "من الساعة ١٢ ظهراً",
    },
    "Breakfast (All Day)": {
        "en": "Served all day",
        "ar": "يُقدَّم طول اليوم",
    },
}


def load(seed_dir):
    with open(os.path.join(seed_dir, "gaimer-w-kahi.json"), encoding="utf-8") as f:
        en = json.load(f)
    with open(os.path.join(seed_dir, "ar-menu.json"), encoding="utf-8") as f:
        ar = json.load(f)
    allerg = {}
    path = os.path.join(seed_dir, "allergens.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            allerg = json.load(f)
    return en, ar, allerg


def index_arabic(ar):
    """خريطةُ (القسم، الاسم) ← السطرِ العربيّ.

    المفتاحُ مركّبٌ من القسمِ **والاسم** لا الاسمِ وحدَه: ثلاثةُ أطباقٍ
    مطبوعةٌ في قسمَين من منيو المالك، فمفتاحٌ بالاسمِ وحدَه يُسند وصفَ
    أحدِهما إلى الآخر.
    """
    out = {}
    for row in ar.get("dishes", []):
        out[(row.get("_section", ""), row["name"])] = row
    return out


# الحقولُ التي يقرؤها هذا الملفُّ من `allergens.json`. تُكتب صريحةً
# ويُتحقَّق من وجودِها **في المصدرِ نفسِه** عند كلِّ بناء.
#
# لماذا: أوّلُ نسخةٍ من هذا الملفِّ قرأت حقلاً اسمُه `allergens` **ولا
# وجودَ له** — اسمُه `has`. فخرجت القائمةُ فارغةً في كلِّ طبق، و**لا شيءَ
# كان سيُظهر ذلك**: لا خطأ، ولا تحذير، ولا صفرٌ غريب — فقط منيو بلا
# مسبّبات حساسيّةٍ يبدو سليماً. والحساسيّةُ مسألةُ صحّةٍ لا زينة.
ALLERGEN_FIELDS = ("name", "textAr", "has", "may", "freeCommon", "glutenFreeOnly")


def index_allergens(allerg):
    """خريطةُ الاسمِ ← سطرِ الحساسيّة، مع **محاسبةٍ كاملةٍ على أسماءِ الحقول**."""
    if not isinstance(allerg, dict):
        return {}, {}, []
    rows = allerg.get("dishes") or []
    labels = allerg.get("labels") or {}

    problems = []
    if rows:
        present = set()
        for r in rows:
            if isinstance(r, dict):
                present |= set(r)
        missing = [f for f in ALLERGEN_FIELDS if f not in present]
        if missing:
            problems.append(
                "حقولٌ أقرؤها ولا وجودَ لها في allergens.json: "
                + " · ".join(missing)
                + f" — الموجودُ: {' · '.join(sorted(present))}")

    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get("name"):
            out[r["name"]] = r
    return out, labels, problems


def build(seed_dir):
    en, ar, allerg = load(seed_dir)
    ar_by = index_arabic(ar)
    al_by, labels, field_problems = index_allergens(allerg)

    stats = {
        "dishes": 0, "withArabic": 0, "noArabic": [],
        "priceConflict": [], "truncated": [], "sections": 0,
        "withAllergenText": 0, "freeCommon": 0, "noAllergenRow": [],
        "fieldProblems": field_problems,
    }
    sections = []

    by_name = {s["name"]: s for s in en["sections"]}
    ordered = [n for n in SECTION_ORDER if n in by_name]
    ordered += [s["name"] for s in en["sections"] if s["name"] not in SECTION_ORDER]

    for sec_name in ordered:
        sec = by_name[sec_name]
        dishes = []
        for d in sec["dishes"]:
            if d.get("skip"):
                continue
            arr = ar_by.get((sec_name, d["name"])) or {}
            desc_en = (d.get("description") or "").strip()
            truncated = desc_en.endswith("…") or desc_en.endswith("...")

            price = d.get("price")
            his = arr.get("_priceInHisFile")
            conflict = None
            if his is not None and price is not None and abs(his - price) > 0.001:
                conflict = {"program": price, "ownerFile": his}
                stats["priceConflict"].append(
                    {"name": d["name"], "section": sec_name, **conflict})

            name_ar = (arr.get("nameAr") or "").strip()
            if name_ar:
                stats["withArabic"] += 1
            else:
                stats["noArabic"].append(d["name"])
            if truncated:
                stats["truncated"].append(d["name"])

            al = al_by.get(d["name"])
            if al is None:
                stats["noAllergenRow"].append(d["name"])
                al = {}
            # ⚠ `textAr` **نصُّ المالكِ نفسِه** وهو المرجعُ الذي يُعرض.
            # والرموزُ (`has`) للأيقوناتِ والإنجليزيّةِ **فوقَه لا بدلًا منه**.
            allergen_text = (al.get("textAr") or "").strip()
            if allergen_text:
                stats["withAllergenText"] += 1
            if al.get("freeCommon"):
                stats["freeCommon"] += 1

            dish = {
                "name": d["name"],
                "nameAr": name_ar or None,
                "description": desc_en or None,
                "descriptionAr": (arr.get("descriptionAr") or "").strip() or None,
                # السعرُ يُحجَب عند التعارضِ — لا يُنشَر رقمٌ لا نعرف أيُّهما
                "price": None if conflict else price,
                "priceConflict": conflict,
                "truncated": truncated,
                "allergenText": allergen_text or None,
                "allergenHas": al.get("has") or [],
                "allergenMay": al.get("may") or [],
                "freeCommon": bool(al.get("freeCommon")),
                "glutenFreeOnly": bool(al.get("glutenFreeOnly")),
                # ⚠ لا حقلَ «نباتي» في أيِّ ملفٍّ من ملفّاتِ المالك — ومنيوه
                # يحمل 🌱 على 13 طبقاً. فلا يُستنتَج من نصٍّ ولا يُخمَّن:
                # وسمُ «نباتي» على طبقٍ فيه لحمٌ ضررٌ على من يعتمد عليه.
                # السؤالُ مرفوعٌ في docs/PLAN.md.
            }
            dishes.append(dish)
            stats["dishes"] += 1

        clean = sec_name.split("(")[0].strip()
        sections.append({
            "id": clean.lower().replace(" ", "-").replace("&", "and"),
            "name": clean,
            "nameAr": sec.get("nameAr") or clean,
            "note": SECTION_NOTE.get(sec_name),
            "dishes": dishes,
        })
        stats["sections"] += 1

    return {
        "_source": ("alsheikha-hr/menu-seed "
                    "(gaimer-w-kahi.json + ar-menu.json + allergens.json)"),
        "_rule": ("السعرُ المتعارضُ محجوبٌ ومُوسَّمٌ priceConflict — لا يُخمَّن. "
                  "والاسمُ العربيُّ الغائبُ يسقط على الإنجليزيِّ ولا يُترجَم. "
                  "ونصُّ الحساسيّةِ نصُّ المالكِ (textAr) والرموزُ فوقَه."),
        "currency": "QAR",
        "currencyAr": "ر.ق",
        "allergenLabels": labels,
        "sections": sections,
    }, stats


def selftest():
    """الحارسُ يُجرَّب على عطلٍ معروفٍ وإلّا لم يُوثق به."""
    fails = []

    # (١) السعرُ المتعارضُ يجب أن يُحجَب فعلاً — لا أن يُوسَم ويُنشَر
    seed = {
        "sections": [{"name": "Breakfast (All Day)", "nameAr": "صباح الخير",
                      "dishes": [{"name": "T", "description": "d", "price": 188.0}]}]
    }
    arj = {"dishes": [{"name": "T", "nameAr": "ص", "_section": "Breakfast (All Day)",
                       "_priceInHisFile": 170.0, "_priceInProgram": 188.0}]}
    # فيكستشرُ حساسيّةٍ **بأسماءِ حقولِ المجموعةِ الحقيقيّة** — وإلّا وافق
    # الفحصُ كوداً معطوباً كما وقع فعلاً
    alj = {"labels": {"milk": {"en": "Milk", "ar": "حليب"}},
           "dishes": [{"name": "T", "textAr": "حليب (ألبان)", "has": ["milk"],
                       "may": [], "freeCommon": False, "glutenFreeOnly": False}]}
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        json.dump(seed, open(os.path.join(t, "gaimer-w-kahi.json"), "w"))
        json.dump(arj, open(os.path.join(t, "ar-menu.json"), "w"))
        json.dump(alj, open(os.path.join(t, "allergens.json"), "w"))
        out, st = build(t)
        dish = out["sections"][0]["dishes"][0]
        if dish["price"] is not None:
            fails.append("سعرٌ متعارضٌ نُشر — كان يجب حجبُه")
        if not dish["priceConflict"]:
            fails.append("التعارضُ لم يُوسَم")
        if len(st["priceConflict"]) != 1:
            fails.append(f"عدُّ التعارضِ {len(st['priceConflict'])} لا 1")
        # الحساسيّةُ وُصلت فعلاً — وهو العطلُ الذي كان مكتوماً تماماً
        if dish["allergenText"] != "حليب (ألبان)":
            fails.append(f"نصُّ الحساسيّةِ لم يُوصَل: {dish['allergenText']!r}")
        if dish["allergenHas"] != ["milk"]:
            fails.append(f"رموزُ الحساسيّةِ لم تُوصَل: {dish['allergenHas']!r}")
        if st["withAllergenText"] != 1:
            fails.append("عدُّ نصوصِ الحساسيّةِ صفرٌ — المُدخلُ لم يُنتج شيئاً")
        if st["fieldProblems"]:
            fails.append(f"فيكستشرٌ سليمٌ أُبلغ عنه: {st['fieldProblems']}")
        if "vegetarian" in dish:
            fails.append("حقلُ «نباتي» مُخترعٌ — لا مصدرَ له في ملفّاتِ المالك")

    # (أ) **فيكستشرٌ بأسماءِ حقولٍ خاطئةٍ يجب أن يُبلَّغ عنه** — وهو بعينُه
    #     العطلُ الذي مرَّ صامتاً: `allergens` بدل `has`
    with tempfile.TemporaryDirectory() as t:
        json.dump(seed, open(os.path.join(t, "gaimer-w-kahi.json"), "w"))
        json.dump(arj, open(os.path.join(t, "ar-menu.json"), "w"))
        json.dump({"dishes": [{"name": "T", "allergens": ["milk"]}]},
                  open(os.path.join(t, "allergens.json"), "w"))
        _, st_bad = build(t)
        if not st_bad["fieldProblems"]:
            fails.append("أسماءُ حقولٍ خاطئةٌ مرَّت صامتةً — وهذا هو العطلُ نفسُه")
        elif "textAr" not in st_bad["fieldProblems"][0]:
            fails.append(f"الرسالةُ لا تُسمّي الحقلَ الناقص: {st_bad['fieldProblems']}")

    # (٢) المفتاحُ المركّبُ: نفسُ الاسمِ في قسمَين لا يُخلط وصفُه
    seed2 = {"sections": [
        {"name": "A", "dishes": [{"name": "X", "price": 10}]},
        {"name": "B", "dishes": [{"name": "X", "price": 20}]}]}
    ar2 = {"dishes": [
        {"name": "X", "nameAr": "ألف", "_section": "A"},
        {"name": "X", "nameAr": "باء", "_section": "B"}]}
    with tempfile.TemporaryDirectory() as t:
        json.dump(seed2, open(os.path.join(t, "gaimer-w-kahi.json"), "w"))
        json.dump(ar2, open(os.path.join(t, "ar-menu.json"), "w"))
        out, _ = build(t)
        got = [s["dishes"][0]["nameAr"] for s in out["sections"]]
        if got != ["ألف", "باء"]:
            fails.append(f"الاسمُ العربيُّ اختلط بين قسمَين: {got}")

    # (٣) اسمٌ عربيٌّ غائبٌ: يبقى None ويُعَدّ — ولا يُخترع
    seed3 = {"sections": [{"name": "A", "dishes": [{"name": "Y", "price": 5}]}]}
    with tempfile.TemporaryDirectory() as t:
        json.dump(seed3, open(os.path.join(t, "gaimer-w-kahi.json"), "w"))
        json.dump({"dishes": []}, open(os.path.join(t, "ar-menu.json"), "w"))
        out, st = build(t)
        if out["sections"][0]["dishes"][0]["nameAr"] is not None:
            fails.append("اسمٌ عربيٌّ اختُرع لطبقٍ بلا اسم")
        if st["noArabic"] != ["Y"]:
            fails.append("الطبقُ بلا عربيٍّ لم يُعَدّ")

    # (٤) المُدخلُ أنتج قيماً غير صفريّة — وإلّا حكمنا على بياناتٍ فارغة
    if st["dishes"] != 1:
        fails.append("المُدخلُ لم يُنتج طبقاً — الفحصُ حكم على فراغ")

    for f in fails:
        print(f"✗ {f}")
    if fails:
        return 1
    print("✓ 10 فحوص نجحت (حجبُ السعرِ · الوسمُ · العدُّ · وصلُ نصِّ "
          "الحساسيّةِ · وصلُ الرموزِ · غيرُ صفريّ · لا فيكستشرَ سليمٌ يُبلَّغ "
          "عنه · لا حقلَ نباتيٍّ مُخترع · المفتاحُ المركّبُ · أسماءُ حقولٍ "
          "خاطئةٌ تُمسَك وتُسمّى)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if len(argv) < 3:
        print(__doc__)
        return 1
    data, stats = build(argv[1])
    os.makedirs(os.path.dirname(os.path.abspath(argv[2])), exist_ok=True)
    with open(argv[2], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"الأقسام: {stats['sections']}   الأطباق: {stats['dishes']}")
    print(f"باسمٍ عربيّ: {stats['withArabic']}"
          f"   بلا اسمٍ عربيّ: {len(stats['noArabic'])}")
    if stats["noArabic"]:
        print("  " + " · ".join(stats["noArabic"]))
    print(f"سعرٌ محجوبٌ لتعارضِه: {len(stats['priceConflict'])}")
    for c in stats["priceConflict"]:
        print(f"  {c['name']}: البرنامج {c['program']} / ملفُّك {c['ownerFile']}")
    print(f"وصفٌ مقطوعٌ في ملفِّ المالك: {len(stats['truncated'])}")
    if stats["truncated"]:
        print("  " + " · ".join(stats["truncated"]))
    print(f"بنصِّ حساسيّةٍ من المالك: {stats['withAllergenText']}"
          f"   خالٍ من المسبّباتِ الشائعة: {stats['freeCommon']}")
    if stats["noAllergenRow"]:
        print(f"بلا سطرِ حساسيّةٍ إطلاقاً: {len(stats['noAllergenRow'])}")
        print("  " + " · ".join(stats["noAllergenRow"]))
    if stats["fieldProblems"]:
        for x in stats["fieldProblems"]:
            print(f"✗ {x}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
