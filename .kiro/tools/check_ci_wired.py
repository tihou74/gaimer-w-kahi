#!/usr/bin/env python3
"""يرفض بقاءَ سكربتِ فحصٍ **غيرِ مربوطٍ** بوظيفةِ الفحصِ في CI.

لماذا: سكربتُ فحصٍ موجودٌ في المستودعِ وغيرُ مربوطٍ بـCI هو **صفرُ
تأكيدات** — ويُطمئنُ من يقرأ قائمةَ الملفّات، وقد يبقى سنةً لم يُشغَّل
مرّةً. ويحرس معها ثلاثاً:

  · كلُّ `check_*.py` **ومعه `--selftest`** مذكورانِ في `deploy.yml`
  · كلُّ أداةٍ يُناديها السير موجودةٌ فعلاً (لا نداءَ لملفٍّ محذوف)
  · **التعليقاتُ تُحذف قبل البحث**: حارسٌ يبحث في نصٍّ فيه تعليقاتٌ يقرأ
    شرحَه هو كأنّه كودٌ، فيُعلن مربوطاً ما هو مفصول — ويُتحقَّق أنّ
    الحذفَ قصَّر النصَّ ولم يُفرّغه

الاستخدام:
    python3 .kiro/tools/check_ci_wired.py
    python3 .kiro/tools/check_ci_wired.py --selftest
"""

import glob
import os
import re
import sys

WF = ".github/workflows/deploy.yml"
TOOLS_DIR = ".kiro/tools"


def strip_comments(text):
    """يحذف تعليقاتَ YAML (`# …`) ويُبقي ما داخلَ النصوصِ المقتبسة."""
    out = []
    for line in text.split("\n"):
        res, in_s, in_d = [], False, False
        for ch in line:
            if ch == "'" and not in_d:
                in_s = not in_s
            elif ch == '"' and not in_s:
                in_d = not in_d
            elif ch == "#" and not in_s and not in_d:
                break
            res.append(ch)
        out.append("".join(res))
    return "\n".join(out)


def audit(wf_text, tool_names, exists=None):
    """يُعيد (عددَ ما فُحص، الأعطال). والمحاسبةُ كاملةٌ: صفرٌ = فشل.

    `exists` دالّةُ «هل الأداةُ موجودةٌ على القرص؟» — تُمرَّر في الفحصِ
    الذاتيِّ ليعمل على فيكستشرَ لا على القرصِ الحقيقيّ.
    """
    fails = []
    stripped = strip_comments(wf_text)
    if exists is None:
        exists = lambda n: os.path.isfile(os.path.join(TOOLS_DIR, n))

    # ⚠ الحذفُ لا يُفرّغ النصَّ — وإلّا بحثنا في فراغٍ وأعلنّا النجاح.
    # ولا يُشترط هنا أن **يُقصّر**: نصٌّ كلُّ `#` فيه داخلَ اقتباسٍ لا
    # يُقصَّر وهو سليم، وتأكيدُ التقصيرِ بلا قيدٍ يُسقط فيكستشراً سليماً
    # ويُقرأ «الحارسُ أمسك» كذباً. وشرطُ «أُزيل تعليقٌ فعلاً» يُتحقَّق في
    # `main()` على الملفِّ الحقيقيِّ حيث التعليقاتُ معلومةُ الوجود.
    if len(stripped) > len(wf_text):
        fails.append("حذفُ التعليقاتِ أطال النصَّ — تعبيرٌ معطوبٌ في الحارس")
    if len(stripped.strip()) < len(wf_text) * 0.3:
        fails.append("حذفُ التعليقاتِ أفرغ النصَّ — تعبيرٌ معطوبٌ في الحارس")

    checked = 0
    for name in sorted(tool_names):
        checked += 1
        if name not in stripped:
            fails.append(f"{name} موجودٌ في {TOOLS_DIR} وغيرُ مربوطٍ بـCI "
                         f"— صفرُ تأكيداتٍ ويُطمئنُ من يقرأ القائمة")
            continue
        # الفحصُ الذاتيُّ مربوطٌ أيضاً: حارسٌ لم يُجرَّب على عطلٍ معروفٍ
        # لا يُوثق به
        if not re.search(re.escape(name) + r"\s+--selftest", stripped):
            fails.append(f"{name} مربوطٌ بلا `--selftest` — لم يُجرَّب على "
                         f"عطلٍ معروفٍ في أيِّ تشغيل")

    # الاتّجاهُ الآخر: السيرُ ينادي ملفّاً غيرَ موجود
    for called in set(re.findall(r"\.kiro/tools/([A-Za-z0-9_.-]+\.py)", stripped)):
        checked += 1
        if not exists(called):
            fails.append(f"CI ينادي {TOOLS_DIR}/{called} ولا وجودَ له "
                         f"— النشرُ يسقط بلا إيداعٍ يُلام")

    return checked, fails


def selftest():
    fails = []
    GOOD = (
        "jobs:\n  check:\n    steps:\n"
        "      - name: x\n"
        "        run: |\n"
        "          python3 .kiro/tools/check_a.py --selftest\n"
        "          python3 .kiro/tools/check_a.py assets\n")

    # (١) السليمُ يمرُّ أوّلاً
    have = {"check_a.py"}.__contains__
    n, f = audit(GOOD, {"check_a.py"}, have)
    if f:
        fails.append(f"النسخةُ السليمةُ سقطت: {f}")
    if n < 2:
        fails.append(f"فُحص {n} فقط — المحاسبةُ ناقصة")

    # (٢) أداةٌ غيرُ مربوطةٍ تُمسَك
    _, f = audit(GOOD, {"check_a.py", "check_b.py"}, have)
    if not any("check_b.py" in x and "غيرُ مربوط" in x for x in f):
        fails.append("أداةٌ غيرُ مربوطةٍ لم تُمسَك")

    # (٣) مربوطةٌ بلا `--selftest` تُمسَك
    _, f = audit("run: python3 .kiro/tools/check_a.py assets\n",
                 {"check_a.py"}, have)
    if not any("--selftest" in x for x in f):
        fails.append("أداةٌ بلا --selftest لم تُمسَك")

    # (٤) **اسمٌ مذكورٌ في تعليقٍ فقط يُقرأ غيرَ مربوط** — وهو العطلُ
    #     الذي يُصدّق الحارسَ نفسَه
    commented = GOOD + "      # python3 .kiro/tools/check_b.py --selftest\n"
    _, f = audit(commented, {"check_a.py", "check_b.py"}, have)
    if not any("check_b.py" in x and "غيرُ مربوط" in x for x in f):
        fails.append("اسمٌ في تعليقٍ قُرئ مربوطاً — الحارسُ يقرأ شرحَه هو")

    # (٥) `#` داخلَ نصٍّ مقتبسٍ لا يُقطع السطرَ
    quoted = ('run: |\n          python3 .kiro/tools/check_a.py --selftest\n'
              '      - name: "خطوة # ليست تعليقاً"\n'
              '        run: python3 .kiro/tools/check_a.py x\n')
    _, f = audit(quoted, {"check_a.py"}, have)
    if f:
        fails.append(f"`#` داخلَ اقتباسٍ كسر الحارسَ: {f}")

    # (٦) نداءٌ لملفٍّ محذوفٍ يُمسَك
    _, f = audit("run: python3 .kiro/tools/check_zzz_missing.py --selftest\n",
                 set(), have)
    if not any("ولا وجودَ له" in x for x in f):
        fails.append("نداءٌ لملفٍّ محذوفٍ لم يُمسَك")

    # (٧) `strip_comments` **يُزيل تعليقاً فعلاً** — وهو الشرطُ الذي بلا
    #     تحقّقٍ منه يصير الحارسُ يبحث في نصٍّ لم يُنظَّف
    src = "a: 1  # تعليق\nb: 2\n"
    got = strip_comments(src)
    if "تعليق" in got:
        fails.append("strip_comments لم يُزل تعليقاً — الحارسُ يقرأ شرحَه هو")
    if "b: 2" not in got or "a: 1" not in got:
        fails.append("strip_comments أزال كوداً مع التعليق")

    # (٨) `#` داخلَ اقتباسٍ **يبقى** — فلا يُقطع سطرٌ سليم
    kept = strip_comments('name: "خطوة # ليست تعليقاً"\n')
    if "#" not in kept:
        fails.append("`#` داخلَ اقتباسٍ حُذف — سطرٌ سليمٌ قُطع")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 8 فحوص نجحت (السليمُ يمرّ · غيرُ مربوطة · بلا --selftest · "
          "اسمٌ في تعليق · # داخلَ اقتباس · ملفٌّ محذوف · التعليقُ يُزال "
          "فعلاً · # المقتبسُ يبقى)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not os.path.isfile(WF):
        print(f"فشل: لا ملفَّ سيرٍ عند {WF}", file=sys.stderr)
        return 1
    with open(WF, encoding="utf-8") as f:
        wf = f.read()

    tools = {os.path.basename(p) for p in glob.glob(os.path.join(TOOLS_DIR, "check_*.py"))}
    if not tools:
        print(f"فشل: لا سكربتَ `check_*.py` في {TOOLS_DIR} — "
              f"حارسٌ يفحص صفراً يقول «سليم» دائماً.", file=sys.stderr)
        return 1

    # على الملفِّ الحقيقيِّ: التعليقاتُ معلومةُ الوجودِ فيه، فيُتحقَّق أنّ
    # التنظيفَ عمل. وبلا هذا قد يبحث الحارسُ في نصٍّ لم يُنظَّف فيقرأ
    # اسماً مذكوراً في شرحٍ كأنّه ربطٌ حقيقيّ.
    if len(strip_comments(wf)) >= len(wf):
        print("فشل: لم يُزَل أيُّ تعليقٍ من ملفِّ السير مع أنّه يحتويها — "
              "الفجوةُ في الحارسِ لا في الكود.", file=sys.stderr)
        return 1

    checked, fails = audit(wf, tools)
    if checked == 0:
        print("فشل: لم يُفحَص شيء.", file=sys.stderr)
        return 1
    for x in fails:
        print(f"✗ {x}")
    if fails:
        print(f"\nسقط {len(fails)}.", file=sys.stderr)
        return 1
    print(f"✓ {len(tools)} سكربتَ فحصٍ كلُّها مربوطةٌ بـCI مع --selftest "
          f"({checked} تحقّقاً).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
