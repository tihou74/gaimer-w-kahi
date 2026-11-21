#!/usr/bin/env python3
"""بناءُ صورِ إنستقرام لقيمر وكاهي — من `dish.json` إلى PNG بمقاسٍ دقيق.

لماذا سكربتٌ لا ملفّاتُ HTML مكتوبةٌ بالي
    الطبقُ يُكتب **مرّةً واحدةً** في `dish.json`. تسعُ صورٍ تحمل اسمَه
    وسعرَه، فاسمٌ يُصحَّح في مكانٍ واحدٍ لا في تسعة — وإلّا نُشرت صورةٌ
    بسعرٍ قديمٍ وصورةٌ بسعرٍ جديدٍ في نفسِ الكاروسيل.

الحارسُ الأساسيُّ هنا: **قيمةٌ لم يقلها المالكُ لا تُرسَم بلا وسم.**
    كلُّ قيمةٍ في `dish.json` تبدأ بـ`__` هي قيمةٌ مؤقّتةٌ من عندي.
    · بلا `--draft` ⇒ البناءُ **يسقط** ويُسمّي الحقولَ الناقصة.
    · بـ`--draft`  ⇒ يُبنى، و**شارةُ «نموذج» تُرسَم داخلَ الصورةِ نفسِها**
      لا في المحادثةِ وحدَها — فصورةٌ تُرسَل في واتساب تنفصل عن كلامي،
      ومن يراها بلا الشارةِ يحسبها جاهزةً للنشر.
    وسعرٌ مُختلَقٌ على صورةٍ عامّةٍ يُنتج خلافاً على الطاولةِ أمام العميل.

الاستخدام:
    python3 social/build.py              # نهائيّ — يسقط إن بقي حقلٌ مؤقّت
    python3 social/build.py --draft      # نموذجٌ موسوم
    python3 social/build.py --draft --safe   # ومعه مناطقُ ستوري الآمنة
    python3 social/build.py --only post-1
    python3 social/build.py --data social/dish.sample.json   # نموذجُ شكلٍ بطبقٍ حقيقيّ
    python3 social/build.py --selftest   # يفحص الحارسَ نفسَه
"""

import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
FRAMES = os.path.join(HERE, "frames")
SHOOT = os.path.join(ROOT, ".kiro", "tools", "shoot.py")
MAX_DIM = 2000

PLACEHOLDER = "__"


# --------------------------------------------------------------- أدوات صغيرة

def furl(rel_or_abs):
    """مسارٌ مطلقٌ `file://` — فالصفحةُ تُرسَم من أيِّ مجلّدٍ بلا كسرِ مرجع."""
    p = rel_or_abs
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    if not os.path.exists(p):
        raise SystemExit(f"مرفوض: لا يوجد ملفّ الصورة {p}")
    return "file://" + p


def e(s):
    return html.escape(str(s), quote=True)


def is_ph(v):
    return isinstance(v, str) and v.strip().startswith(PLACEHOLDER)


def collect_placeholders(d, path=""):
    """كلُّ حقلٍ مؤقّتٍ في الشجرة — ويُتخطّى ما بدأ اسمُه بشرطةٍ سفليّة (شرحٌ لا بيانات)."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if str(k).startswith("_"):
                continue
            out += collect_placeholders(v, f"{path}.{k}" if path else str(k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out += collect_placeholders(v, f"{path}[{i}]")
    elif is_ph(d):
        out.append((path, d))
    return out


# ------------------------------------------------------------------ القوالب

def page(body, css_href, draft, safe, tag=None):
    """صفحةٌ واحدةٌ — والشارةُ تُرسَم آخرَ شيءٍ فتعلو كلَّ طبقة."""
    badge = ""
    text = tag or ("نموذجُ شكلٍ — الاسمُ والسعرُ والمكوّناتُ مؤقّتةٌ "
                   "ولم يُقرّها المالك. لا يُنشَر.")
    if draft or tag:
        badge = (
            '<div style="position:fixed;inset:auto 0 0 0;z-index:99;'
            # شريطٌ رقيقٌ (٤٠ بكسل): الشارةُ تُغطّي أقلَّ ما يمكن من التصميم.
            # نسختُها الأولى كانت ٦٠ بكسلاً فغطّت **شريحةَ السعرِ** في الغلاف
            # وسطرَ التقديمِ في «وش فيه» — فحُكم على تصميمٍ لم يُرَ.
            'background:#953B33;color:#FBF7F0;font-family:\'Noto Kufi Arabic\',sans-serif;'
            'font-weight:600;font-size:20px;letter-spacing:.02em;text-align:center;'
            'padding:10px;line-height:1.1;direction:rtl">' + e(text) + '</div>'
        )
    return (
        '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
        f'<link rel="stylesheet" href="{css_href}">'
        '</head><body>' + body + badge + '</body></html>'
    )


def logo_tag(cls="logo logo--inv"):
    return f'<img class="{cls}" src="{furl("assets/img/logo.png")}" alt="قيمر وكاهي">'


def dia(n=4, cls="dia"):
    return f'<div class="{cls}">' + ("<i></i>" * n) + "</div>"


def allergen_note(d):
    """الحساسيّاتُ تُكتب إن كانت معروفةً، وتُترك فارغةً إن لم تكن.

    لا يُخمَّن مُسبِّبُ حساسيّةٍ أبداً ولا يُقال «لا يحتوي»: سطرٌ خاطئٌ هنا
    خطرٌ على صحّةِ إنسانٍ لا خطأٌ في تصميم. فإن لم يُذكر، لا يُطبَع شيء.
    """
    v = d.get("_مُتحقَّقٌ من هذه وحدها", {})
    a = v.get("allergens")
    if not a or is_ph(a):
        return ""
    # سطرٌ مستقلٌّ لا عنصرٌ في صفٍّ مشترك: في النسخةِ الأولى كان بجانبِ سطرِ
    # التقديمِ فتزاحما وانقطع «مع استكان شاي» إلى سطرٍ وحدَه.
    return (
        '<div style="margin-top:10px;font-family:var(--body);font-size:23px;'
        f'color:var(--maroon)">يحتوي: {e(a)}</div>'
    )


def price_pill(d):
    return (
        '<div class="pricepill price">'
        f'<b>{e(d["price"])}</b><span>{e(d["currency"])}</span></div>'
    )


def t_post_hero(d, safe):
    """١ — الغلاف: الصورةُ تملأ الإطارَ والاسمُ في الأسفلِ على الحجاب."""
    return f'''
<div class="frame frame--sq">
  <div class="ph ph--zoom"><img src="{furl(d["photos"]["hero"])}" alt=""></div>
  <div class="scrim"></div>
  <div class="layer pad">
    <div class="footline">
      <span class="chip">جديد في قيمر وكاهي</span>
      {logo_tag()}
    </div>
    <div class="grow"></div>
    <div class="on-dark">
      {dia(4, "dia dia--cream dia--sm")}
      <div class="name" style="margin-top:26px">{e(d["name_ar"])}</div>
      <div class="name-en soft" style="margin-top:10px">{e(d["name_en"])}</div>
      <div class="lede soft" style="margin-top:26px;max-width:800px">{e(d["lede"])}</div>
      <div style="margin-top:38px">{price_pill(d)}</div>
    </div>
  </div>
</div>'''


def t_post_ing(d, safe):
    """٢ — وش فيه: خلفيّةٌ كريميّةٌ وقائمةٌ مرقّمةٌ بمعيّناتِ الشعار."""
    items = "".join(
        f'<li><span class="n"><b>{i + 1}</b></span>'
        f'<span class="t">{e(x)}</span></li>'
        for i, x in enumerate(d["ingredients"][:6])
    )
    return f'''
<div class="frame frame--sq sheet--paper">
  <div class="layer pad">
    <div class="footline">
      <div>
        <div class="kicker" style="color:var(--maroon)">وش فيه</div>
        <div style="margin-top:20px">{dia(4)}</div>
      </div>
      <img class="logo logo--sm" src="{furl("assets/img/logo.png")}" alt="قيمر وكاهي">
    </div>
    <div style="display:flex;gap:48px;align-items:center;flex:1 1 auto;margin-top:36px">
      <ul class="ing" style="flex:1 1 auto">{items}</ul>
      <div class="cut cut--round" style="flex:0 0 auto;width:300px;height:300px">
        <img src="{furl(d["photos"]["round"])}" alt="">
      </div>
    </div>
    <hr class="rule" style="margin:0 0 24px">
    <div class="small" style="color:var(--ink-soft)">{e(d["serve_note"])}</div>
    {allergen_note(d)}
  </div>
</div>'''


def t_post_detail(d, safe):
    """٣ — القريبة: الحجابُ من الجانبِ فيبقى الطعامُ مكشوفاً على اليسار.

    صُحِّح فيها عطلانِ مرئيّانِ في النسخةِ الأولى:
      · `justify-content:center` مع عنصرِ `.grow` داخلَه ⇒ السلاكُ كلُّه ذهب
        للـgrow فطُبع النصُّ في **أعلى** الإطارِ لا وسطِه. الوسطُ يُضبَط
        بـ`margin:auto 0` على الكتلةِ نفسِها لا بـjustify-content.
      · الحجابُ الجانبيُّ الأوّلُ كان خفيفاً فوقع اسمُ الطبقِ الكريميُّ على
        حرفِ الطبقِ الأبيضِ ⇒ تباينٌ ساقط. شُدَّ إلى .94 عند الحافّة.
    """
    return f'''
<div class="frame frame--sq">
  <div class="ph"><img src="{furl(d["photos"]["detail"])}" alt=""></div>
  <div class="scrim scrim--side"></div>
  <div class="layer pad on-dark" style="align-items:flex-start">
    <div style="max-width:545px;margin:auto 0">
      {dia(3, "dia dia--gold")}
      <div class="name name--sm" style="margin-top:26px">{e(d["name_ar"])}</div>
      <div class="body soft" style="margin-top:22px">{e(d["serve_note"])}</div>
      <div style="margin-top:36px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
        <span class="chip chip--cream price">{e(d["price"])} {e(d["currency"])}</span>
        <span class="chip chip--ghost">{e(d["branches_note"])}</span>
      </div>
    </div>
    {logo_tag("logo logo--sm logo--inv")}
  </div>
</div>'''


def t_post_branches(d, safe):
    """٤ — الفرعان. أُعيد تصميمُها لسببَين حقيقيَّين لا لذوق:

    · **خصوصيّة:** النسخةُ الأولى وضعت `branch-westwalk-960.jpg` و
      `branch-oldport-960.jpg`، وفي الأولى **زبائنُ جالسون ووجوهُهم ظاهرة**.
      صورةُ شخصٍ حقيقيٍّ لا تُنشَر بلا إذنِه المكتوب — فحُذفت الصورتان.
    · **نسبةُ صورةٍ إلى فرعٍ لا أملكُ إثباتَها:** لا أعرف أيَّ فرعٍ تُصوّر
      كلُّ لقطة، ووضعُ صورةِ فرعٍ تحت اسمِ الآخرِ خطأٌ على منشورٍ عامّ.
      فالتصميمُ صار **خلفيّةَ علامةٍ واحدةً** (لوحةُ المحلِّ النحاسيّة — لا
      بشرَ فيها) والاسمانِ نصّاً، فلا يُنسَب شيءٌ إلى غيرِ موضعِه.

    ولا ساعاتٍ ولا هاتفَ هنا: البروفايلُ نفسُه يسمهما «غيرَ مملوكَين».
    """
    v = d["_مُتحقَّقٌ من هذه وحدها"]
    return f'''
<div class="frame frame--sq">
  <div class="ph"><img src="{furl("assets/img/photo/poster-port.jpg")}" alt=""></div>
  <div class="scrim scrim--heavy"></div>
  <div class="layer pad on-dark">
    <div class="footline">
      <!-- الكلمةُ الدالّةُ **كريميّةٌ لا فيروزيّة**: الفيروزيُّ الفاتح
           1.75:1 على الفاتح — سطحٌ لا نصّ، وهي قاعدةُ tokens.css نفسُها
           وكنتُ قد خالفتُها هنا على خلفيّةِ صورةٍ نحاسيّةٍ فاتحة. -->
      <div class="kicker">وين تلقاه</div>
      {logo_tag("logo logo--sm logo--inv")}
    </div>
    <div style="margin:auto 0;display:flex;flex-direction:column;gap:46px">
      <div>
        {dia(4, "dia dia--cream dia--sm")}
        <div style="font-family:var(--display);font-size:76px;margin-top:18px">
          {e(v["branch_1"])}</div>
        <div class="body soft" style="margin-top:6px">{e(v["branch_1_addr"])}</div>
      </div>
      <hr class="rule rule--ink">
      <div>
        {dia(4, "dia dia--cream dia--sm")}
        <div style="font-family:var(--display);font-size:76px;margin-top:18px">
          {e(v["branch_2"])}</div>
        <div class="body soft" style="margin-top:6px">{e(v["city"])}</div>
      </div>
    </div>
    <div class="small soft">مطعم خليجي عراقي في الدوحة منذ {e(v["since"])}</div>
  </div>
</div>'''


def t_post_close(d, safe):
    """٥ — الختام: الشعارُ على الفيروزيِّ — سطحٌ لا نصّ، فالنصُّ حبريٌّ عليه."""
    v = d["_مُتحقَّقٌ من هذه وحدها"]
    return f'''
<div class="frame frame--sq sheet--teal">
  <div class="layer pad" style="align-items:center;justify-content:center;text-align:center">
    <img class="logo" style="height:150px" src="{furl("assets/img/logo.png")}" alt="قيمر وكاهي">
    <div style="margin-top:40px">{dia(4)}</div>
    <div class="name name--sm" style="margin-top:36px;color:var(--teal-deep)">
      {e(d["name_ar"])}</div>
    <div class="lede" style="margin-top:20px;color:var(--teal-deep);max-width:760px">
      {e(d["lede"])}</div>
    <div style="margin-top:44px">
      <span class="chip" style="font-size:34px;padding:24px 46px">
        {e(d["branches_note"])}</span>
    </div>
    <div class="small" style="margin-top:46px;color:var(--teal-deep);opacity:.85">
      {e(v["branch_1"])} &nbsp;&nbsp;|&nbsp;&nbsp; {e(v["branch_2"])}
    </div>
  </div>
</div>'''


def t_story_teaser(d, safe):
    """ستوري ١ — النصُّ داخلَ المنطقةِ الآمنةِ وحدَها، فإنستقرام يغطّي الحواف."""
    sa = ' data-safe="on"' if safe else ""
    return f'''
<div class="frame frame--st"{sa}>
  <div class="ph ph--zoom"><img src="{furl(d["photos"]["hero"])}" alt=""></div>
  <div class="scrim scrim--heavy"></div>
  <div class="safe"></div>
  <div class="layer pad--st st-top st-bottom on-dark">
    <div style="display:flex;justify-content:center">
      {logo_tag("logo logo--inv")}
    </div>
    <div class="grow"></div>
    <div style="text-align:center">
      <span class="chip">جديد</span>
      <div class="name name--xl" style="margin-top:34px">{e(d["name_ar"])}</div>
      <div class="name-en soft" style="margin-top:14px;text-align:center">
        {e(d["name_en"])}</div>
      <div class="lede soft" style="margin-top:30px">{e(d["lede"])}</div>
      <div style="margin-top:44px;display:flex;justify-content:center">{price_pill(d)}</div>
    </div>
    <div class="grow"></div>
    <div style="display:flex;justify-content:center">
      {dia(4, "dia dia--cream dia--sm")}
    </div>
  </div>
</div>'''


def t_story_ing(d, safe):
    """ستوري ٢ — يُترك فراغٌ أسفلَ النصِّ لملصقِ التصويتِ أو السؤال."""
    sa = ' data-safe="on"' if safe else ""
    items = "".join(
        f'<li><span class="n"><b>{i + 1}</b></span>'
        f'<span class="t">{e(x)}</span></li>'
        for i, x in enumerate(d["ingredients"][:5])
    )
    return f'''
<div class="frame frame--st sheet--paper"{sa}>
  <div class="safe"></div>
  <div class="layer pad--st st-top st-bottom">
    <div class="footline">
      <div class="kicker" style="color:var(--maroon)">وش فيه</div>
      <img class="logo logo--sm" src="{furl("assets/img/logo.png")}" alt="قيمر وكاهي">
    </div>
    <div class="cut" style="margin-top:38px;height:520px">
      <img src="{furl(d["photos"]["side"])}" alt="">
    </div>
    <div class="name name--sm" style="margin-top:38px">{e(d["name_ar"])}</div>
    <ul class="ing" style="margin-top:34px">{items}</ul>
    <div class="grow"></div>
    <div class="small" style="color:var(--ink-soft);text-align:center;
         border:3px dashed var(--cream-400,#D6C8AF);border-radius:18px;padding:30px">
      اتركْ هذا الفراغَ لملصقِ التصويتِ في إنستقرام — «تجرّبه؟ نعم / أكيد»
    </div>
  </div>
</div>'''


def t_story_cta(d, safe):
    sa = ' data-safe="on"' if safe else ""
    v = d["_مُتحقَّقٌ من هذه وحدها"]
    return f'''
<div class="frame frame--st"{sa}>
  <div class="ph"><img src="{furl(d["photos"]["detail"])}" alt=""></div>
  <div class="scrim scrim--heavy"></div>
  <div class="safe"></div>
  <div class="layer pad--st st-top st-bottom on-dark"
       style="text-align:center;align-items:center">
    <div class="grow"></div>
    {dia(4, "dia dia--gold dia--sm")}
    <div class="name" style="margin-top:30px">{e(d["name_ar"])}</div>
    <div style="margin-top:34px">{price_pill(d)}</div>
    <div class="body soft" style="margin-top:40px;max-width:780px">
      {e(d["branches_note"])}<br>{e(v["branch_1"])} &nbsp;|&nbsp; {e(v["branch_2"])}
    </div>
    <div class="grow"></div>
    {logo_tag("logo logo--inv")}
  </div>
</div>'''


SPECS = [
    ("post-1-hero",     t_post_hero,     1080, 1080),
    ("post-2-what",     t_post_ing,      1080, 1080),
    ("post-3-detail",   t_post_detail,   1080, 1080),
    ("post-4-branches", t_post_branches, 1080, 1080),
    ("post-5-close",    t_post_close,    1080, 1080),
    ("story-1-teaser",  t_story_teaser,  1080, 1920),
    ("story-2-what",    t_story_ing,     1080, 1920),
    ("story-3-cta",     t_story_cta,     1080, 1920),
]


# ------------------------------------------------------------------- البناء

def build(draft=False, safe=False, only=None, data=None):
    src = data or os.path.join(HERE, "dish.json")
    with open(src, encoding="utf-8") as f:
        d = json.load(f)

    missing = collect_placeholders(d)
    if missing and not draft:
        print("البناءُ موقوف: حقولٌ لم يقلها المالكُ بعد.\n", file=sys.stderr)
        for path, val in missing:
            print(f"  · {path} = {val}", file=sys.stderr)
        print("\nاملأها في social/dish.json، أو ابنِ نموذجاً موسوماً بـ--draft.",
              file=sys.stderr)
        return 2
    if missing:
        print(f"نموذج: {len(missing)} حقلاً مؤقّتاً — الشارةُ تُرسَم داخلَ كلِّ صورة.")

    tag = d.get("_tag")
    if tag:
        print(f"وسمٌ داخلَ كلِّ صورة: {tag}")

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(FRAMES, exist_ok=True)
    css = "file://" + os.path.join(HERE, "kit.css")

    made = []
    for name, fn, w, h in SPECS:
        if only and only != name:
            continue
        if w > MAX_DIM or h > MAX_DIM:
            raise SystemExit(f"مرفوض: {name} = {w}x{h} يتجاوز {MAX_DIM}")
        hp = os.path.join(FRAMES, name + ".html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(page(fn(d, safe), css, draft, safe, tag))
        png = os.path.join(OUT, name + ".png")
        r = subprocess.run(
            [sys.executable, SHOOT, "file://" + hp, png, str(w), str(h)],
            capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(png):
            print(f"سقط الرسم: {name}\n{r.stdout}\n{r.stderr}", file=sys.stderr)
            return 1
        made.append((name, f"{w}x{h}", os.path.getsize(png) // 1024))

    print(f"\nرُسمت {len(made)} صورة في social/out/:")
    for n, size, kb in made:
        print(f"  {n:<18} {size:>9}  {kb:>5} ك.ب")
    return 0


# -------------------------------------------------------------- فحصٌ ذاتيّ

def selftest():
    """يُجرَّب الحارسُ على عطلٍ معروفٍ — وحارسٌ لم يُجرَّب لا يُوثق به."""
    fails = []

    def ck(cond, msg):
        if not cond:
            fails.append(msg)

    # ١) يُمسك الحقلَ المؤقّتَ في كلِّ شكلٍ يَرِد فيه
    ck(collect_placeholders({"a": "__x__"}) == [("a", "__x__")], "لم يمسك قيمةً مباشرة")
    ck(len(collect_placeholders({"a": ["ok", "__y__"]})) == 1, "لم يمسك داخلَ مصفوفة")
    ck(len(collect_placeholders({"a": {"b": "__z__"}})) == 1, "لم يمسك داخلَ قاموس")

    # ٢) يتخطّى حقولَ الشرحِ (تبدأ بشرطةٍ سفليّة) ولا يُسقط البناءَ بسببها
    ck(collect_placeholders({"_ملاحظة": "__شرح__"}) == [], "لم يتخطَّ حقلَ شرح")

    # ٣) **لا يُسقط البياناتَ السليمة** — حارسٌ يمنع أكثرَ من اللازمِ يُعطَّل
    good = {"name_ar": "كاهي بالقيمر", "price": "45",
            "ingredients": ["قيمر", "عسل"], "_tip": "__شرح__"}
    ck(collect_placeholders(good) == [], "أسقط بياناتٍ سليمة")

    # ٤) الفخُّ الحقيقيّ: اسمٌ عربيٌّ فيه شرطتانِ سفليّتانِ في وسطِه ليس مؤقّتاً
    ck(not is_ph("كاهي__خاص"), "عدَّ شرطةً في الوسطِ قيمةً مؤقّتة")
    ck(is_ph("  __x__"), "لم يتجاوز مسافةً بادئة")

    # ٥) الملفّ الحقيقيُّ الآن **يجب** أن يكون مؤقّتاً — وإلّا فالحارسُ يبارك فراغاً
    with open(os.path.join(HERE, "dish.json"), encoding="utf-8") as f:
        real = json.load(f)
    found = collect_placeholders(real)
    ck(len(found) >= 4,
       f"dish.json فيه {len(found)} حقلاً مؤقّتاً فقط — إن كان مملوءاً فهذا صحيح، "
       "وإن كان فارغاً فالحارسُ لا يرى")

    # ٦) كلُّ مقاسٍ تحت الحدّ، وكلُّ قالبٍ موجود
    for name, fn, w, h in SPECS:
        ck(w <= MAX_DIM and h <= MAX_DIM, f"{name} يتجاوز الحدّ")
        ck(callable(fn), f"{name} بلا قالب")
    ck(len(SPECS) == len({s[0] for s in SPECS}), "اسمٌ مكرّرٌ في SPECS")

    # ٧) كلُّ صورةٍ في dish.json موجودةٌ فعلاً وتحت الحدّ
    for k, v in real["photos"].items():
        p = os.path.join(ROOT, v)
        ck(os.path.exists(p), f"صورةٌ مفقودة: {k} -> {v}")

    if fails:
        print("سقط الفحصُ الذاتيّ:", file=sys.stderr)
        for m in fails:
            print("  ✗ " + m, file=sys.stderr)
        return 1
    print(f"الفحصُ الذاتيّ: مرّ ({7} مجموعات)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(selftest())
    only = a[a.index("--only") + 1] if "--only" in a else None
    data = a[a.index("--data") + 1] if "--data" in a else None
    sys.exit(build(draft="--draft" in a, safe="--safe" in a, only=only, data=data))
