#!/usr/bin/env python3
"""لقطةُ شاشةٍ بحدٍّ مفروضٍ عند نقطةِ التوليد.

لماذا عند التوليد: الخطّافُ يحمي **قراءةَ** الصور من القرص، ولا يمنع
إنتاجَ صورةٍ متجاوزةٍ أصلاً. وأيُّ سكربتٍ جديدٍ يتجاوز حارساً موضعياً،
فالحدُّ يُفرَض في المَخنَق الذي تمرُّ به كلُّ لقطة.

قواعد مفروضة هنا:
  · العرضُ والارتفاعُ ≤ 2000 بكسل، وإلّا يُرفَض الطلبُ قبل تشغيلِ المتصفّح
  · لا لقطةَ صفحةٍ كاملة (--full) — ارتفاعُها غير محدود
  · تُفحَص الصورةُ المُنتَجةُ بـimgguard بعد التوليد، فلا يُعتمَد على النيّة

الاستخدام:
    python3 .kiro/tools/shoot.py <ملفّ أو file://> <out.png> [عرض] [ارتفاع]
"""
import os
import subprocess
import sys

MAX_DIM = 2000
SHELL = ("/inner_container/opt/playwright/chromium_headless_shell-1232/"
         "chrome-headless-shell-linux64/chrome-headless-shell")

# كروم العاديّ يفشل في هذا الصندوق بـ
#   chrome_crashpad_handler: --database is required
# ولا تُصلحه --crash-dumps-dir ولا --disable-crash-reporter ولا --headless=new
# (جُرِّبت الخمسُ). المسارُ الصحيحُ هو chrome-headless-shell.


def shoot(url, out, w=1280, h=900, wait_ms=1800):
    w, h = int(w), int(h)
    if w > MAX_DIM or h > MAX_DIM:
        print(f"مرفوض: {w}x{h} يتجاوز الحدّ {MAX_DIM} بكسل لكل بُعد.",
              file=sys.stderr)
        print(f"أقصى مسموح: {MAX_DIM}x{MAX_DIM}.", file=sys.stderr)
        return 2
    if w < 80 or h < 80:
        print(f"مرفوض: {w}x{h} أصغر من أن يُفيد.", file=sys.stderr)
        return 2

    if not os.path.isfile(SHELL):
        print(f"مرفوض: لا متصفّحَ عند {SHELL}", file=sys.stderr)
        return 1

    if not url.startswith(("http://", "https://", "file://")):
        url = "file://" + os.path.abspath(url)

    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    cmd = [
        SHELL, "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--disable-dev-shm-usage", "--force-color-profile=srgb",
        "--user-data-dir=/projects/sandbox/.cp-shell",
        f"--window-size={w},{h}",
        f"--virtual-time-budget={wait_ms}",
        f"--screenshot={out}",
        url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)

    if not os.path.isfile(out):
        print(f"فشل: لم تُنتَج {out}", file=sys.stderr)
        return 1

    # لا يُعتمَد على النيّة: تُقاس الصورةُ المُنتَجةُ فعلاً
    guard = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "imgguard.py")
    res = subprocess.run([sys.executable, guard, "check", out],
                         capture_output=True, text=True)
    sys.stdout.write(res.stdout)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        print(f"الصورةُ المُنتَجةُ متجاوزةٌ — تُحذَف: {out}", file=sys.stderr)
        os.remove(out)
        return 2

    size_kb = os.path.getsize(out) // 1024
    print(f"  -> {os.path.relpath(out)} ({size_kb} ك.ب)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    a = sys.argv
    sys.exit(shoot(a[1], a[2],
                   a[3] if len(a) > 3 else 1280,
                   a[4] if len(a) > 4 else 900))
