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

/* =============================================================================
   الأفلام — تشغيلٌ بلمسة، وتشغيلٌ تلقائيٌّ مشروطٌ بشبكةٍ تحتمل
   -----------------------------------------------------------------------------
   الأفلام الثلاثة 14 ميجا. و`preload="none"` يعني أنّ الصفحة تفتح بأغلفة
   خفيفة ولا شيء يُحمَّل. والتشغيل التلقائي **مشروط** ولا يُفرض:
   من فتح «توفير البيانات» أو كان على شبكة بطيئة يبقى على الغلاف — وفيلمٌ
   يُحمَّل بلا إذنٍ على شبكة جوّال يُكلّف الزائر مالاً.
   ============================================================================= */
(() => {
  'use strict';
  const films = [...document.querySelectorAll('.film')];
  if (!films.length) return;

  const play = (fig) => {
    const v = fig.querySelector('video');
    if (!v) return;
    fig.classList.add('is-playing');
    const p = v.play();
    // وعدٌ مرفوضٌ يُمسَك: يبقى الغلافُ وزرُّ التشغيل، فلا مستطيلَ أسود
    if (p && typeof p.catch === 'function') {
      p.catch(() => { fig.classList.remove('is-playing'); v.controls = true; });
    }
  };

  films.forEach((fig) => {
    const btn = fig.querySelector('.film__play');
    const v = fig.querySelector('video');
    if (btn) btn.addEventListener('click', () => play(fig));
    // الضغط على الفيلم نفسه يُوقف ويُشغّل — ومن شغّله يجب أن يستطيع إيقافه
    if (v) {
      v.addEventListener('click', () => {
        if (v.paused) { play(fig); } else { v.pause(); fig.classList.remove('is-playing'); }
      });
    }
  });

  const c = navigator.connection || {};
  const cheapData = c.saveData === true;
  const slow = typeof c.effectiveType === 'string'
    && /^(slow-)?2g$|^3g$/.test(c.effectiveType);
  const stillMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (cheapData || slow || stillMotion) return;   // يبقى الغلافُ والزرّ

  // فيلمٌ واحدٌ فقط: الذي يملأ أكثرَ من نصفِ النافذة. وثلاثةٌ تعمل معاً
  // تُحجز الشبكةَ وتُسخّن الجهازَ ولا تُشاهَد كلُّها.
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      const fig = e.target;
      const v = fig.querySelector('video');
      if (!v) return;
      if (e.isIntersecting && e.intersectionRatio > 0.55) {
        if (v.paused) play(fig);
      } else if (!v.paused) {
        v.pause();
        fig.classList.remove('is-playing');
      }
    });
  }, { threshold: [0, 0.55, 1] });
  films.forEach((f) => io.observe(f));
})();
