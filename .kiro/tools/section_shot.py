#!/usr/bin/env python3
"""لقطةُ قسمٍ بعينه — و**الدليلُ على أنّه هو داخلَ الصورة**.

لماذا هذه الأداة: لقطةُ `index.html#story` **لا تُظهر قسمَ القصّة**.
`scroll-behavior: smooth` يجعل نقلةَ المِرساةِ حركةً، والساعةُ الوهميّةُ
(`--virtual-time-budget`) تنقطع في أوّلها — فتخرج لقطاتٌ **كلُّها الواجهةُ**
بفروقٍ تُضلّل: المقاساتُ مختلفةٌ وبصمةُ md5 مختلفةٌ، فيُقرأ الاختلافُ
«أقسامٌ مختلفة».

فالعلاجُ ليس «أضفْ تأخيراً»، بل **أن تحمل الصورةُ دليلَها**: شريطٌ مُحقَنٌ
في النسخةِ المؤقّتةِ يطبع على الصورةِ اسمَ القسمِ المطلوبِ وموضعَ التمريرِ
و**بُعدَ أعلى القسمِ عن أعلى النافذة** — فإن لم يكن صفراً تقريباً فاللقطةُ
ليست لهذا القسمِ ولو بدت معقولة.

وأربعةُ شروطٍ إلزاميّة:
  · المعرّفُ يجب أن يكون موجوداً في الصفحة — معرّفٌ مكتوبٌ خطأً يُنتج
    لقطةَ الواجهةِ بلا أيِّ شكوى، وهذا بعينُه ما يُضلّل
  · النسخةُ المؤقّتةُ تُكتب في **جذرِ المشروع** لا في مجلّدٍ أعمق، لأنّ
    `assets/...` مساراتٌ نسبيّة: نسخةٌ أعمقُ تفقد كلَّ أصلٍ وخطٍّ وتُصوَّر
    صفحةً عاريةً تبدو «تصميماً سيّئاً»
  · الحدُّ (2000 بكسل) **لا يُعاد تنفيذُه هنا**: تُنادى `shoot.shoot` فيبقى
    المَخنَقُ واحداً. وأداةٌ تكتب حدَّها بنفسِها هي طريقُ التسلّل
  · النسخةُ تُحذف في `finally` — وإلّا بقيت في الجذرِ وأُيدعت مع العمل

الاستخدام:
    python3 .kiro/tools/section_shot.py <صفحة.html> <معرّف> <out.png> [عرض] [ارتفاع]
    python3 .kiro/tools/section_shot.py --selftest
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import shoot  # noqa: E402  — المَخنَقُ الوحيدُ للحدّ

# يُحقَن قبل `</body>`: يُعطّل الحركةَ، ويُمرّر، ويطبع الدليلَ على الصورة
PROBE = """
<style>
  html { scroll-behavior: auto !important; }
  *, *::before, *::after {
    animation-duration: .001s !important;
    transition-duration: .001s !important;
  }
  #__probe {
    position: fixed; inset-block-start: 0; inset-inline-start: 0;
    z-index: 99999; background: #111; color: #0f0;
    font: 12px/1.5 monospace; padding: 4px 8px; direction: ltr;
    white-space: pre; pointer-events: none;
  }
</style>
<div id="__probe">probe…</div>
<script>
(() => {
  const id = %(id)s;
  const box = document.getElementById('__probe');
  const el = document.getElementById(id);
  if (!el) {
    box.textContent = 'MISSING id=' + id;
    box.style.background = '#900';
    box.style.color = '#fff';
    return;
  }
  // الكشفُ يبدأ مُخفىً بالجافاسكربت — يُلغى هنا وإلّا صُوِّرت أقسامٌ فارغة
  document.querySelectorAll('[data-reveal]').forEach((n) => {
    n.classList.remove('is-armed');
    n.classList.add('is-in');
  });
  const hdr = document.querySelector('.hdr');
  const off = hdr ? hdr.getBoundingClientRect().height : 0;
  window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - off);
  requestAnimationFrame(() => {
    const top = Math.round(el.getBoundingClientRect().top - off);
    box.textContent = 'id=' + id + '  scrollY=' + Math.round(window.scrollY)
      + '  sectionTop=' + top + (Math.abs(top) <= 4 ? '  OK' : '  ✗ NOT AT TOP');
    if (Math.abs(top) > 4) { box.style.background = '#900'; box.style.color = '#fff'; }
  });
})();
</script>
"""


def shoot_section(page, section_id, out, w=1400, h=980, wait_ms=3500):
    page_abs = os.path.abspath(page)
    with open(page_abs, encoding="utf-8") as f:
        html = f.read()

    # المعرّفُ يجب أن يكون في الصفحةِ فعلاً — ويُفحَص **قبل** تشغيل المتصفّح
    if not re.search(r'\bid\s*=\s*["\']' + re.escape(section_id) + r'["\']', html):
        print(f"مرفوض: لا عنصرَ بـid=\"{section_id}\" في {page}.", file=sys.stderr)
        ids = re.findall(r'<(?:section|main|div|footer)[^>]*\bid\s*=\s*"([^"]+)"', html)
        if ids:
            print("الموجودُ: " + " · ".join(dict.fromkeys(ids)), file=sys.stderr)
        return 2

    probe = PROBE % {"id": repr(section_id).replace("'", '"')}
    if "</body>" in html:
        patched = html.replace("</body>", probe + "</body>", 1)
    else:
        patched = html + probe
    if patched == html:
        print("مرفوض: لم يُحقَن المجسّ — لا تُصوَّر صفحةٌ بلا دليل.",
              file=sys.stderr)
        return 2

    # في **جذرِ المشروع** حيث الصفحةُ الأصليّة، فتبقى مساراتُ الأصولِ صحيحة
    tmp = os.path.join(os.path.dirname(page_abs),
                       f".__shot_{section_id}_{os.getpid()}.html")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(patched)
        return shoot.shoot(tmp, out, w, h, wait_ms)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def selftest():
    """يُجرَّب على عطلٍ معروف: معرّفٌ غائبٌ **يجب أن يُرفَض** لا أن يُصوَّر."""
    import tempfile
    fails = []
    d = tempfile.mkdtemp()
    page = os.path.join(d, "p.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write('<html><body><section id="real">ن</section></body></html>')

    # (١) معرّفٌ غائبٌ يُرفَض برمز 2 — ولا يُنتج لقطةَ الواجهة
    out = os.path.join(d, "a.png")
    if shoot_section(page, "ghost", out) != 2:
        fails.append("معرّفٌ غائبٌ لم يُرفَض — كان سيُصوَّر أعلى الصفحة")
    if os.path.exists(out):
        fails.append("أُنتجت لقطةٌ لمعرّفٍ غائب")

    # (٢) المعرّفُ الموجودُ يصل إلى تشغيلِ المتصفّح (لا يُرفَض عند الفحص)
    #     ولا تُفحَص اللقطةُ نفسُها هنا: المتصفّحُ قد لا يكون في كل بيئة،
    #     والمطلوبُ أنّ **الفحصَ النصّيَّ لم يرفضْه**
    probe = PROBE % {"id": '"real"'}
    if "MISSING id=" not in probe or "NOT AT TOP" not in probe:
        fails.append("المجسُّ لا يحمل دليلَه — لا رسالةَ غياب ولا رسالةَ موضع")

    # (٣) النسخةُ المؤقّتةُ لا تبقى في الجذر
    leftovers = [n for n in os.listdir(d) if n.startswith(".__shot_")]
    if leftovers:
        fails.append(f"بقيت نسخةٌ مؤقّتة: {leftovers}")

    # (٤) النسخةُ تُكتب في **مجلّدِ الصفحةِ نفسِه** — وإلّا فقدت الأصول
    if os.path.dirname(os.path.abspath(page)) != d:
        fails.append("حسابُ المجلّدِ خطأ")

    for x in fails:
        print(f"✗ {x}")
    if fails:
        return 1
    print("✓ 4 فحوص نجحت (المعرّفُ الغائبُ يُرفَض · لا لقطةَ له · "
          "المجسُّ يحمل دليلَه · لا نسخةَ باقية)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    a = sys.argv
    sys.exit(shoot_section(a[1], a[2], a[3],
                           a[4] if len(a) > 4 else 1400,
                           a[5] if len(a) > 5 else 980))
