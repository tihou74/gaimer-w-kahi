/* =============================================================================
   قيمر وكاهي — ترشيح المنيو وبحثه
   -----------------------------------------------------------------------------
   **تحسينٌ لا شرط**: كل الأطباق في HTML. من تعثّر عنده هذا الملفّ يقرأ
   المنيو كاملاً ويتنقّل بمراسي الأقسام.
   ============================================================================= */
(() => {
  'use strict';

  const q = document.getElementById('q');
  const chips = document.getElementById('chips');
  const none = document.getElementById('none');
  const sections = [...document.querySelectorAll('.ms')];
  const items = [...document.querySelectorAll('.mi')];
  if (!items.length) return;

  let sec = 'all';

  // تطبيعٌ للبحثِ العربيّ: من يكتب «كاهى» بالياء المقصورة أو «شاكشوكه»
  // بالهاء يجب أن يجد «كاهي» و«شكشوكة». وبلا هذا يبحث الزبونُ فلا يجد
  // طبقاً موجوداً فيظنّه غيرَ متوفّر.
  const norm = (s) => s
    .toLowerCase()
    .replace(/[\u064B-\u065F\u0670\u0640]/g, '')   // تشكيل وتطويل
    .replace(/[\u0622\u0623\u0625\u0627]/g, '\u0627')  // أ إ آ ا
    .replace(/\u0649/g, '\u064A')                  // ى ← ي
    .replace(/\u0629/g, '\u0647')                  // ة ← ه
    .replace(/[\u0624]/g, '\u0648')                // ؤ ← و
    .replace(/\s+/g, ' ')
    .trim();

  // النصُّ المفحوصُ يُحسَب **مرّةً واحدةً** ويُخزَّن على العنصر: حسابُه
  // لكل طبقٍ في كل ضغطةِ مفتاحٍ = 144 تطبيعاً × كل حرف، وهو ما يُجمّد
  // الكتابةَ على جوّالٍ متوسّط.
  items.forEach((el) => {
    el.__hay = norm((el.dataset.name || '') + ' ' + el.textContent);
  });

  const apply = () => {
    const term = norm(q ? q.value : '');
    let shown = 0;

    items.forEach((el) => {
      const inSec = sec === 'all'
        || el.closest('.ms').dataset.sec === sec;
      const hit = !term || el.__hay.includes(term);
      const show = inSec && hit;
      el.hidden = !show;
      if (show) shown++;
    });

    // قسمٌ خلا من الأطباقِ يُخفى بعنوانِه: عنوانٌ فوق فراغٍ يُقرأ عطلاً
    sections.forEach((s) => {
      s.hidden = ![...s.querySelectorAll('.mi')].some((el) => !el.hidden);
    });

    if (none) none.hidden = shown > 0;
  };

  if (q) {
    // لا مؤقّتَ تأجيل: الترشيحُ على 144 عنصراً بنصٍّ مُخزَّنٍ أسرعُ من
    // 16ms، والتأجيلُ يُشعر الكتابةَ بالتعثّر لا بالعكس.
    q.addEventListener('input', apply);
    // Escape يُفرغ البحثَ — ومن ضيّق النتائجَ يجب أن يجد طريقَ العودة
    q.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && q.value) { q.value = ''; apply(); }
    });
  }

  if (chips) {
    chips.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.chip');
      if (!btn) return;
      sec = btn.dataset.sec;
      chips.querySelectorAll('.chip').forEach((b) => {
        const on = b === btn;
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-pressed', String(on));
      });
      apply();
    });
    chips.querySelectorAll('.chip').forEach((b) => {
      b.setAttribute('aria-pressed', String(b.classList.contains('is-on')));
    });
  }

  // من وصل برابطٍ فيه مِرساةُ قسمٍ (#pastry من الرئيسيّة) يُرشَّح له
  // ذلك القسمُ فوراً — وإلّا هبط في منتصفِ 144 طبقاً ولم يعرف أين هو
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash) {
    const btn = chips && chips.querySelector(`.chip[data-sec="${CSS.escape(hash)}"]`);
    if (btn) btn.click();
  }
})();
