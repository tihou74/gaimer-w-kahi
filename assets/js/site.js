/* =============================================================================
   قيمر وكاهي — جافاسكربت الموقع
   -----------------------------------------------------------------------------
   كل محتوى الصفحة في HTML. هذا الملفّ **تحسين** لا شرط: لو لم يُحمَّل بقي
   كل شيء مقروءاً ومتنقّلاً — ولهذا يُسلَّح الكشفُ من هنا ولا يبدأ من CSS
   بـ`opacity:0` (وإلّا كانت الصفحةُ بيضاءَ عند تعثّر الملفّ).
   ============================================================================= */
(() => {
  'use strict';

  /* ------------------------------------------------------- قائمة الجوّال */
  const burger = document.getElementById('burger');
  const nav = document.getElementById('nav');

  if (burger && nav) {
    const setOpen = (open) => {
      document.body.classList.toggle('is-nav-open', open);
      burger.setAttribute('aria-expanded', String(open));
      burger.setAttribute('aria-label', open ? 'إغلاق القائمة' : 'فتح القائمة');
    };

    burger.addEventListener('click', () => {
      setOpen(!document.body.classList.contains('is-nav-open'));
    });

    // الضغط على رابط يُغلق القائمة، وإلّا بقيت فوق المحتوى المقصود
    nav.addEventListener('click', (e) => {
      if (e.target.closest('a')) setOpen(false);
    });

    // Escape يُغلق ويُعيد البؤرة إلى الزرّ — ومن فتحها بلوحة المفاتيح
    // يجب أن يجد طريق العودة
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && document.body.classList.contains('is-nav-open')) {
        setOpen(false);
        burger.focus();
      }
    });

    // تكبير النافذة إلى المقاس الكبير يُخفي زرّ القائمة بالـCSS، فتبقى
    // السمة على <body> وتظهر القائمة مفتوحةً بلا زرٍّ يُغلقها
    const wide = window.matchMedia('(min-width: 921px)');
    wide.addEventListener('change', (ev) => { if (ev.matches) setOpen(false); });
  }

  /* --------------------------------------------- حدّ الترويسة عند التمرير */
  const hdr = document.getElementById('hdr');
  if (hdr) {
    // عنصرٌ مراقَبٌ عند أعلى الصفحة: أرخص من الاستماع لكل حدث تمرير،
    // ولا يُشغل الخيط الرئيسي في كل بكسل
    const sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    sentinel.style.cssText = 'position:absolute;top:0;height:1px;width:1px';
    document.body.prepend(sentinel);
    new IntersectionObserver(
      ([entry]) => hdr.classList.toggle('is-stuck', !entry.isIntersecting),
    ).observe(sentinel);
  }

  /* ------------------------------------------------------------ الكشف */
  const reveals = document.querySelectorAll('[data-reveal]');
  if (reveals.length && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    reveals.forEach((el) => el.classList.add('is-armed'));
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove('is-armed');
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);   // مرّةً واحدة — لا يُعاد إخفاؤه
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.04 });
    reveals.forEach((el) => io.observe(el));
  }

  /* -------------------------------------------------------- الفيديو */
  // بعض المتصفّحات ترفض التشغيل التلقائي ولو كان مكتوماً. الوعدُ المرفوض
  // يُمسَك فلا يظهر خطأ في وحدة التحكّم، وتبقى صورةُ الغلاف ظاهرةً —
  // فلا مستطيلَ أسودَ مكان الفيديو.
  document.querySelectorAll('video[autoplay]').forEach((v) => {
    const p = v.play();
    if (p && typeof p.catch === 'function') p.catch(() => { v.controls = true; });
  });
})();
