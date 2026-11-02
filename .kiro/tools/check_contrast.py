#!/usr/bin/env python3
"""يتحقّق أنّ **كل نسبة تباين مكتوبة في `tokens.css` صحيحة فعلاً**.

لماذا هذا الحارس: تعليقٌ يقول «على الكريمي 6.59:1» يُقرأ وثيقةً ويُعتمد
عليه، ثم يُعدَّل اللون ولا يُعدَّل التعليق — فيبقى رقمٌ يُطمئن ولا يصدق.
والرقم الخاطئ أسوأ من غيابه، لأنّ من يقرؤه لا يُعيد الحساب.

يقرأ كل سطرٍ فيه `--اسم: #لون;` وتعليقٌ فيه `على <الخلفيّة> N:1`،
ويُعيد حساب النسبة بمعادلة WCAG 2.x، ويسقط إن انحرفت عن المكتوب.

ويفحص معها قاعدتين لا تُرى بالعين:
  · كل لونٍ موسومٍ «نصّ» يجب أن يبلغ 4.5:1 فعلاً (أو 3:1 إن قُيّد بالكبير)
  · كل لونٍ موسومٍ «سطح فقط» يجب أن يكون **دون** 4.5:1 — وإلّا فالوسم
    يُخفي لوناً صالحاً للنصّ ويُفقدنا إيّاه

الاستخدام:
    python3 .kiro/tools/check_contrast.py [assets/css/tokens.css]
    python3 .kiro/tools/check_contrast.py --selftest
"""

import os
import re
import sys

TOL = 0.06   # هامش التقريب المسموح بين المكتوب والمحسوب

BACKGROUNDS = {
    "الكريمي": "#FBF7F0",
    "الأبيض": "#FFFFFF",
    "الحبري": "#0D0D0B",
}


def srgb_to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * srgb_to_lin(r) + 0.7152 * srgb_to_lin(g)
            + 0.0722 * srgb_to_lin(b))


def ratio(fg, bg):
    a, b = luminance(fg), luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


# `--اسم: #RRGGBB;` ثم بقيّة السطر تعليقاً
LINE = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})\s*;(.*)$")
CLAIM = re.compile(r"على\s+(\S+?)\s+([0-9]+(?:\.[0-9]+)?):1")


def audit(text):
    """يُعيد (عدد الادّعاءات المفحوصة، قائمة الأعطال)."""
    checked, fails = 0, []
    for lineno, line in enumerate(text.split("\n"), 1):
        m = LINE.search(line)
        if not m:
            continue
        name, color, comment = m.group(1), m.group(2), m.group(3)

        for cm in CLAIM.finditer(comment):
            bg_word, claimed = cm.group(1), float(cm.group(2))
            bg = BACKGROUNDS.get(bg_word.strip("ـ"))
            if bg is None:
                fails.append(f"س{lineno} --{name}: خلفيّةٌ مجهولة «{bg_word}» "
                             f"— أضِفها إلى BACKGROUNDS أو صحّح النصّ")
                continue
            actual = ratio(color, bg)
            checked += 1
            if abs(actual - claimed) > max(TOL, claimed * 0.01):
                fails.append(f"س{lineno} --{name} ({color} على {bg_word}): "
                             f"مكتوبٌ {claimed}:1 والمحسوب {actual:.2f}:1")

        # الوسمُ يجب أن يُطابق القدرة الفعليّة **على الخلفيّة المقصودة**.
        # ولا يُقاس على «أفضل الخلفيّتين»: الفيروزي الفاتح يبلغ 10.39:1 على
        # الحبري و1.75:1 على الكريمي — فقياسُه بالأفضلِ يجعل كلَّ لونٍ صالحاً
        # للنصّ ويُبطل الفحصَ كلَّه. فالمرجعُ الخلفيّةُ المذكورةُ في التعليق،
        # وخلفيّةُ الصفحةِ (الكريمي) عند غيابها.
        claim = CLAIM.search(comment)
        bg_name = claim.group(1).strip("ـ") if claim else "الكريمي"
        bg_ref = BACKGROUNDS.get(bg_name, BACKGROUNDS["الكريمي"])
        actual = ratio(color, bg_ref)

        says_surface = "سطح فقط" in comment
        says_text = ("نصّ" in comment) and not says_surface
        says_large = ("الكبير" in comment) or ("كبير" in comment)

        if says_surface and actual >= 4.5:
            fails.append(f"س{lineno} --{name} ({color}): موسومٌ «سطح فقط» "
                         f"وتباينه على {bg_name} {actual:.2f}:1 — صالحٌ للنصّ، "
                         f"والوسمُ يُفقدنا إيّاه")
        if says_text and not says_large and actual < 4.5:
            fails.append(f"س{lineno} --{name} ({color}): موسومٌ «نصّ» "
                         f"وتباينه على {bg_name} {actual:.2f}:1 — دون 4.5:1، يرسب AA")
        if says_text and says_large and actual < 3.0:
            fails.append(f"س{lineno} --{name} ({color}): موسومٌ للنصّ الكبير "
                         f"وتباينه على {bg_name} {actual:.2f}:1 — دون 3:1، "
                         f"يرسب حتى للكبير")
    return checked, fails


def selftest():
    """يُجرَّب على عطلٍ مُصطنَعٍ **يُغيّر الجواب**، وإلّا لم يُثبت شيئاً."""
    fails = []

    # (١) النسخةُ السليمةُ تمرُّ — أوّل سطرٍ دائماً، وإلّا كلُّ «أُمسك» كذب.
    #     والرقمُ 6.66 **محسوبٌ** لا مكتوبٌ تخميناً (#953B33 على #FBF7F0).
    good = "  --x: #953B33;  /* على الكريمي 6.66:1 — نصّ */"
    n, f = audit(good)
    if f:
        fails.append(f"النسخةُ السليمةُ سقطت: {f}")
    if n != 1:
        fails.append(f"فُحص {n} ادّعاءٍ لا 1 — الحارسُ لم يرَ السطر")

    # (٢) رقمٌ مكتوبٌ خطأً يُمسَك
    bad = "  --x: #953B33;  /* على الكريمي 9.90:1 — نصّ */"
    _, f = audit(bad)
    if not any("والمحسوب" in x for x in f):
        fails.append("رقمٌ خاطئٌ لم يُمسَك")

    # (٣) لونٌ موسومٌ «نصّ» وهو راسبٌ على خلفيّتِه يُمسَك
    weak = "  --x: #74CBD2;  /* على الكريمي 1.75:1 — نصّ */"
    _, f = audit(weak)
    if not any("يرسب AA" in x for x in f):
        fails.append("لونٌ راسبٌ موسومٌ «نصّ» لم يُمسَك")

    # (٤) **ونفسُ اللونِ** موسوماً «سطح فقط» يجب أن يمرّ — فالوسمُ يُفرّق فعلاً
    #     ولا يُصدِّق الحارسُ نفسَه: المُدخلةُ واحدةٌ والجوابُ اختلف بالوسمِ وحدَه
    ok_surface = "  --x: #74CBD2;  /* على الكريمي 1.75:1 — سطح فقط */"
    _, f2 = audit(ok_surface)
    if f2:
        fails.append(f"لونُ سطحٍ سليمٌ سقط: {f2}")

    # (٥) لونٌ قويٌّ موسومٌ «سطح فقط» يُمسَك — حارسٌ لا يمنع إلّا الضعيفَ نصفُ حارس
    mislabeled = "  --x: #27474A;  /* سطح فقط */"
    _, f = audit(mislabeled)
    if not any("يُفقدنا إيّاه" in x for x in f):
        fails.append("لونٌ قويٌّ موسومٌ «سطح فقط» لم يُمسَك")

    # (٦) الفيروزي على الحبري **يمرُّ** نصّاً (10.39:1) — فالمرجعُ هو الخلفيّةُ
    #     المذكورةُ لا اللونُ بذاتِه. ولولا هذا الصفُّ لجاز أن يُمنع لونٌ سليم
    on_dark_ok = "  --x: #74CBD2;  /* على الحبري 10.39:1 — نصّ */"
    _, f = audit(on_dark_ok)
    if f:
        fails.append(f"الفيروزي على الحبري سقط وهو سليم: {f}")

    # (٧) خلفيّةٌ مجهولةٌ تُسقط التشغيل ولا تُمرّ بصمت
    unknown = "  --x: #000000;  /* على الأزرق 5.00:1 — نصّ */"
    _, f = audit(unknown)
    if not any("مجهولة" in x for x in f):
        fails.append("خلفيّةٌ مجهولةٌ مُرّت بصمتٍ — والصامتُ يُقرأ نجاحاً")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 7 فحوص نجحت (السليمُ يمرّ · الرقمُ الخاطئُ · الراسبُ الموسومُ نصّاً "
          "· نفسُه موسوماً سطحاً يمرّ · القويُّ الموسومُ سطحاً · الفيروزي على "
          "الحبري يمرّ · الخلفيّةُ المجهولة)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    path = argv[1] if len(argv) > 1 else "assets/css/tokens.css"
    if not os.path.isfile(path):
        print(f"لا ملفّ: {path}", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as f:
        checked, fails = audit(f.read())

    # المحاسبةُ الكاملة: حارسٌ يفحص صفراً يقول «سليم» دائماً
    if checked == 0:
        print("فشل: لم يُفحَص أيُّ ادّعاءِ تباين — الفجوةُ في الحارسِ لا في الكود.",
              file=sys.stderr)
        return 1

    for x in fails:
        print(f"✗ {x}")
    if fails:
        print(f"\nسقط {len(fails)} من {checked} ادّعاءً مفحوصاً.", file=sys.stderr)
        return 1
    print(f"✓ {checked} نسبة تباين مكتوبة في {path} — كلّها تطابق الحساب.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
