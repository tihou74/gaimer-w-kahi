#!/usr/bin/env node
/**
 * reelrec — يُسجّلُ ريلَ إنستقرام MP4/H.264 من مقاطعِ المالكِ نفسِها.
 *
 * لماذا بهذه الطريقة (وكلُّ سطرٍ هنا مبنيٌّ على قياسٍ في هذا الصندوق):
 *   · ffmpeg المرفقُ **لا يفكّ H.264 ولا يُشفّره**: `-decoders` يعطي
 *     `mjpeg` و`vp8` وحدَهما، و`-encoders` يعطي `png` و`libvpx` وحدَهما.
 *     فلا قصَّ ولا دمجَ ولا ترميزَ به — و`webm/vp8` لا يُقبل في إنستقرام.
 *   · وكرومُ الموجودُ أصلاً **يفكّ H.264 ويُشفّره**: مقيسٌ أنّ
 *     `MediaRecorder.isTypeSupported('video/mp4;codecs=avc1.42E01E')`
 *     ⇒ `true`، وأنّ تسجيلَ لوحةٍ أنتج ملفّاً رأسُه `ftyp isom … avc1`
 *     قرأه كرومُ نفسُه: `{"w":540,"h":960,"dur":1.99}`.
 *     فالمسارُ: فيديوهاتُه ← لوحة ← `captureStream` ← `MediaRecorder` ← MP4.
 *
 * ثلاثةُ قيودٍ مفروضةٍ هنا لأنّها أوجعت فعلاً:
 *   · **الصفحةُ تُنقَل إلى `file://` قبل إنشاءِ أيِّ `<video>`.** صفحةُ
 *     `about:blank` ترفض مصدرَ `file://` فيسقط بـ`code=4` الذي يُقرأ
 *     «الصيغةُ غيرُ مدعومة» وهو في الحقيقةِ منعُ أصل.
 *   · **التسجيلُ بزمنٍ حقيقيّ.** ١٧ ثانيةً تأخذ ١٧ ثانية. والمُخرَجُ
 *     **يُقاس** بعدها: إن نقصت مدّتُه عن المطلوبِ أكثرَ من ٨٪ فالإطاراتُ
 *     سقطت ⇒ يُعلَن ويُقترح `--scale .67`، ولا يُسلَّم ريلٌ متهدّجٌ بصمت.
 *   · **النقلُ على دفعات.** ١٧ ثانيةً بـ7Mbps ≈ ١٥ ميجا ⇒ base64 ≈ ٢٠
 *     مليون حرف. تمريرُها في نداءٍ واحدٍ عبر CDP يسقط، فتُقطَّع ٤ ميجا.
 *
 * الاستخدام:
 *   node reelrec.js social/reel.json social/out/reel.mp4
 *   node reelrec.js social/reel.json out.mp4 --scale .67   # لو سقطت إطارات
 *   node reelrec.js --selftest
 */

const fs = require('fs'), os = require('os'), path = require('path');
const { spawn } = require('child_process');

const SHELL = '/inner_container/opt/playwright/chromium_headless_shell-1232/'
  + 'chrome-headless-shell-linux64/chrome-headless-shell';
const CHUNK = 4 * 1024 * 1024;   // حروفُ base64 في الدفعة
const DUR_TOLERANCE = 0.08;      // ٨٪ نقصٍ في المدّةِ = إطاراتٌ ساقطة


/* ===================================================== الصفحةُ التي تُسجّل
   تُنفَّذ **داخلَ** المتصفّح. تُكتب دالّةً واحدةً وتُمرَّر إليها الخطّةُ
   مُسلسَلةً، فلا تعتمد على أيِّ نطاقٍ خارجيّ. */
function stagePage() {
  return `
window.__reel = { state: 'init', msg: '' };

window.__run = async (plan) => {
  const R = window.__reel;
  const fail = (m) => { R.state = 'error'; R.msg = m; throw new Error(m); };

  const W = plan.width, H = plan.height, FPS = plan.fps;
  const DIS = plan.dissolve, SAFE = plan.safe;

  // ---- الخطوط: تُحمَّل **قبل** أوّلِ رسم. fillText بخطٍّ لم يُحمَّل
  //      يرسم بخطٍّ بديلٍ بصمت، والعربيُّ يخرج غيرَ متّصل.
  const fonts = [
    new FontFace('Aref Ruqaa', 'url(' + plan.fontDisplay + ')', { weight: '700' }),
    new FontFace('Noto Kufi Arabic', 'url(' + plan.fontBody + ')', { weight: '600' }),
  ];
  for (const f of fonts) { document.fonts.add(await f.load()); }
  await document.fonts.ready;

  // ---- الشعار
  let logo = null;
  if (plan.logo) {
    logo = new Image(); logo.src = plan.logo;
    try { await logo.decode(); } catch (e) { logo = null; }
  }

  // ---- عنصرُ فيديو **لكلِّ لقطة** لا لكلِّ ملفّ: لقطتانِ من نفسِ الملفِّ
  //      تحتاجان موضعَي قراءةٍ مختلفَين في نفسِ اللحظةِ (التلاشي المتقاطع
  //      يرسم اللقطتَين معاً)، وعنصرٌ واحدٌ له مؤشّرُ زمنٍ واحد.
  // ---- صورٌ ثابتةٌ تُحرَّك (كِن بيرنز). لماذا تُخلَط مع المقاطع: مقاطعُ
  //      المالكِ وصلت 464×832 (ضغطُ واتساب) وصورُه 1536×2048. فاللقطةُ
  //      الجميلةُ الساكنةُ تُؤخَذ من **الصورةِ** عالية الدقّةِ بحركةٍ بطيئة،
  //      والمقطعُ يُستعمَل حيث الحركةُ نفسُها هي المقصود (يدٌ تُنزل الصينيّة).
  //      صورةٌ ساكنةٌ ناعمةٌ تُقرأ «جودةً رديئة»، وحركةٌ ناعمةٌ تُقرأ «فيديو جوّال».
  const imgs = [];
  for (const s of plan.shots) {
    if (s.kind !== 'photo') { imgs.push(null); continue; }
    const im = new Image(); im.src = s.src;
    try { await im.decode(); } catch (e) { fail('تعذّر فكُّ الصورة: ' + s.src); }
    imgs.push(im);
  }

  const vids = [];
  for (const s of plan.shots) {
    if (s.kind !== 'clip') { vids.push(null); continue; }
    const v = document.createElement('video');
    v.src = s.src; v.muted = true; v.playsInline = true; v.preload = 'auto';
    document.body.appendChild(v);
    await new Promise((res, rej) => {
      v.addEventListener('loadeddata', res, { once: true });
      v.addEventListener('error', () => rej(new Error(
        'تعذّر فكُّ ' + s.src + ' (code=' + (v.error && v.error.code) + ')')), { once: true });
      setTimeout(() => rej(new Error('مهلةُ تحميل: ' + s.src)), 25000);
    }).catch(e => fail(e.message));
    if (s.in + s.dur > v.duration + 0.05) {
      fail('اللقطةُ تتجاوز طولَ المقطع: ' + s.src + ' تطلب '
        + (s.in + s.dur).toFixed(2) + 's وطولُه ' + v.duration.toFixed(2) + 's');
    }
    v.currentTime = s.in;
    await new Promise(res => v.addEventListener('seeked', res, { once: true }));
    vids.push(v);
  }

  // ---- جدولُ الزمن: كلُّ لقطةٍ تبدأ قبلَ نهايةِ سابقتِها بمدّةِ التلاشي
  let t = 0; const sched = [];
  plan.shots.forEach((s, i) => {
    sched.push({ ...s, i, start: t, end: t + s.dur, vid: vids[i], img: imgs[i] });
    t += s.dur - (i < plan.shots.length - 1 ? DIS : 0);
  });
  const TOTAL = sched[sched.length - 1].end;
  R.total = TOTAL;

  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  document.body.appendChild(c);
  const g = c.getContext('2d', { alpha: false });

  // ---------------------------------------------------------- أدواتُ الرسم
  function cover(v, alpha) {
    const vw = v.videoWidth, vh = v.videoHeight;
    if (!vw || !vh) return;
    const k = Math.max(W / vw, H / vh);
    const w = vw * k, h = vh * k;
    g.save(); g.globalAlpha = alpha;
    g.drawImage(v, (W - w) / 2, (H - h) / 2, w, h);
    g.restore();
  }

  /* صورةٌ ثابتةٌ بحركةٍ بطيئة. الحركةُ **داخلَ** الدقّةِ الزائدةِ لا تكبيرٌ
     فوقها: 1536×2048 على إطارٍ 1080×1920 يعطي هامشاً حقيقيّاً للتحريكِ
     بلا فقدِ تفصيل. والزومُ لا يتجاوز 1.14 — أكثرُ من ذلك يُقرأ اهتزازاً. */
  function kenburns(im, alpha, k, s) {
    const z0 = s.zoom0 != null ? s.zoom0 : 1.02;
    const z1 = s.zoom1 != null ? s.zoom1 : 1.14;
    const ease = k * k * (3 - 2 * k);            // smoothstep — لا بداية حادّة
    const z = z0 + (z1 - z0) * ease;
    const base = Math.max(W / im.naturalWidth, H / im.naturalHeight);
    const kk = base * z;
    const w = im.naturalWidth * kk, h = im.naturalHeight * kk;
    const px = (s.panX || 0) * (w - W) * 0.5 * ease;
    const py = (s.panY != null ? s.panY : -0.5) * (h - H) * 0.5 * ease;
    g.save(); g.globalAlpha = alpha;
    g.drawImage(im, (W - w) / 2 + px, (H - h) / 2 + py, w, h);
    g.restore();
  }

  function scrim(pos, alpha) {
    const gr = g.createLinearGradient(0, 0, 0, H);
    if (pos === 'top') {
      gr.addColorStop(0, 'rgba(13,13,11,.86)');
      gr.addColorStop(.34, 'rgba(13,13,11,.30)');
      gr.addColorStop(.72, 'rgba(13,13,11,.10)');
      gr.addColorStop(1, 'rgba(13,13,11,.55)');
    } else {
      gr.addColorStop(0, 'rgba(13,13,11,.42)');
      gr.addColorStop(.30, 'rgba(13,13,11,.10)');
      gr.addColorStop(.62, 'rgba(13,13,11,.38)');
      gr.addColorStop(1, 'rgba(13,13,11,.90)');
    }
    g.save(); g.globalAlpha = alpha; g.fillStyle = gr; g.fillRect(0, 0, W, H); g.restore();
  }

  function diamonds(cx, cy, n, size, color, alpha) {
    g.save(); g.globalAlpha = alpha; g.fillStyle = color;
    const gap = size * 2.1, total = (n - 1) * gap;
    for (let i = 0; i < n; i++) {
      const x = cx - total / 2 + i * gap;
      g.save(); g.translate(x, cy); g.rotate(Math.PI / 4);
      g.fillRect(-size / 2, -size / 2, size, size); g.restore();
    }
    g.restore();
  }

  function text(str, x, y, font, color, alpha, align) {
    if (!str) return;
    g.save();
    g.globalAlpha = alpha; g.fillStyle = color; g.font = font;
    g.textAlign = align || 'center'; g.textBaseline = 'middle';
    g.direction = 'rtl';
    g.shadowColor = 'rgba(13,13,11,.72)'; g.shadowBlur = 26; g.shadowOffsetY = 3;
    g.fillText(str, x, y);
    g.restore();
  }

  // النصُّ **داخلَ** المنطقةِ الآمنة: إنستقرام يضع الوصفَ والأزرارَ أسفلَ
  // الريل وأزرارَ التفاعلِ على الجانب. نصٌّ تحتها يُقرأ نصفَه المشاهد.
  const capY = H - SAFE.bottom - 120;
  const topY = SAFE.top + 180;

  /* شريطٌ موضعيٌّ تحتَ النصِّ وحدَه.
     لماذا لا يُشَدُّ الحجابُ العامّ: اللقطةُ القريبةُ على الرزِّ بيضاءُ في
     أعلاها كلِّه، فقياسُ البكسلِ تحتَ أوّلِ حرفٍ أعطى **1.97:1** — ساقطٌ.
     وشَدُّ الحجابِ العامِّ كان سيُطفئ الطعامَ كلَّه ليُنجِيَ أربعَ كلمات.
     فالشريطُ يضمن التباينَ **أيّاً كانت الصورة** ولا يمسُّ بقيّةَ الإطار. */
  function capBand(y, alpha) {
    const h = 320;
    const gr = g.createLinearGradient(0, y - h * .62, 0, y + h * .52);
    gr.addColorStop(0, 'rgba(13,13,11,0)');
    gr.addColorStop(.42, 'rgba(13,13,11,.62)');
    gr.addColorStop(.66, 'rgba(13,13,11,.62)');
    gr.addColorStop(1, 'rgba(13,13,11,0)');
    g.save(); g.globalAlpha = alpha; g.fillStyle = gr;
    g.fillRect(0, y - h * .62, W, h * 1.14); g.restore();
  }

  function drawCaption(s, alpha, k) {
    if (alpha <= 0.01) return;
    const rise = (1 - Math.min(1, k * 3)) * 34;   // يصعد قليلاً عند الظهور
    const base = s.pos === 'top' ? topY : capY;
    const y = base + rise;
    if (s.title || s.sub) capBand(y, alpha);
    diamonds(W / 2, y - 112, 4, 15, '#FBF7F0', alpha * .85);
    text(s.title, W / 2, y, '700 104px "Aref Ruqaa", serif', '#FBF7F0', alpha);
    text(s.sub, W / 2, y + 92, '600 44px "Noto Kufi Arabic", sans-serif',
         '#E6DFD2', alpha * .95);
  }

  /* علامةٌ صغيرةٌ ثابتةٌ على لقطةِ الطعام — **مطفأةٌ افتراضيّاً**.
     السبب مرئيٌّ في أوّلِ تصدير: مقاطعُ المالكِ الحاليّةُ تحمل أصلاً
     علامةً محروقةً في الصورة («قيمروكاهي» أعلى الإطار)، فعلامتي فوقها
     أعطت **شعارَين متجاورَين** — وهذا يُقرأ تصديراً مغلوطاً لا هويّةً.
     تُشعَل بوضع mark = true في اللقطةِ للمقاطعِ النظيفةِ بلا حرق.
     (ولا شرطةَ مائلةً خلفيّةً في تعليقاتِ هذه الكتلةِ: جسمُها نصٌّ
      بين علامتَي اقتباسٍ مائلتَين، فأيُّ واحدةٍ تقطعُه وتُسقط الملفَّ
      كلَّه بـSyntaxError — وقع فعلاً.) */
  function watermark(alpha, on) {
    if (!logo || !on) return;
    const lw = W * 0.26, lh = lw * (logo.naturalHeight / logo.naturalWidth);
    g.save();
    g.globalAlpha = alpha * 0.62;
    g.filter = 'brightness(0) invert(1)';
    g.drawImage(logo, SAFE.side, SAFE.top, lw, lh);
    g.restore();
  }

  function drawCard(s, alpha, k) {
    g.save(); g.globalAlpha = alpha;
    g.fillStyle = s.bg || '#0D0D0B'; g.fillRect(0, 0, W, H);
    g.restore();
    const cy = H / 2;
    if (logo && s.logo) {
      const grow = 0.94 + 0.06 * Math.min(1, k * 2.2);
      const lw = W * 0.56 * grow, lh = lw * (logo.naturalHeight / logo.naturalWidth);
      g.save();
      g.globalAlpha = alpha;
      g.filter = 'brightness(0) invert(1)';
      g.drawImage(logo, (W - lw) / 2, cy - lh / 2 - (s.title ? 170 : 0), lw, lh);
      g.restore();
    }
    if (s.title) {
      diamonds(W / 2, cy + 60, 4, 16, '#953B33', alpha);
      text(s.title, W / 2, cy + 185, '700 104px "Aref Ruqaa", serif', '#FBF7F0', alpha);
      text(s.sub, W / 2, cy + 292, '600 40px "Noto Kufi Arabic", sans-serif',
           '#C9C0B2', alpha * .95);
    }
  }

  function drawShot(s, now, alpha, capA) {
    const k = Math.max(0, Math.min(1, (now - s.start) / Math.max(.001, s.dur)));
    if (s.kind === 'card') { drawCard(s, alpha, k); return; }
    if (s.kind === 'photo') {
      kenburns(s.img, alpha, k, s);
      scrim(s.pos, alpha);
      watermark(alpha, s.mark === true || (s.mark !== false && plan.watermark === true));
      drawCaption(s, capA, k);
      return;
    }
    cover(s.vid, alpha);
    scrim(s.pos, alpha);
    watermark(alpha, s.mark === true || (s.mark !== false && plan.watermark === true));
    drawCaption(s, capA, k);
  }

  /* شفافيّةُ **النصِّ** تختلف عن شفافيّةِ **الصورة**.
     في النسخةِ الأولى كانتا واحدةً، فظهر أثناءَ كلِّ تلاشٍ نصّانِ فوق
     بعضِهما («قيمر عراقي» و«بيض على القيمر» معاً عند 4.6s) — ضبابٌ
     يُقرأ عطلاً في التصدير لا تصميماً. فالصورةُ تتلاشى متقاطعةً،
     والنصُّ **يُقطَع**: الخارجُ يختفي قبل أن يدخلَ الداخل. */
  function capAlphaOf(s, now) {
    if (s.i > 0 && now < s.start + DIS) {
      // يدخل في النصفِ الثاني من التلاشي وحدَه
      return Math.max(0, Math.min(1, (now - s.start - DIS * .55) / (DIS * .45)));
    }
    if (s.i < sched.length - 1 && now > s.end - DIS) return 0;
    return 1;
  }

  // ------------------------------------------------------------- التسجيل
  const mime = 'video/mp4;codecs=avc1.42E01E';
  if (!MediaRecorder.isTypeSupported(mime)) fail('لا دعمَ لـ' + mime);
  const stream = c.captureStream(FPS);
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: plan.bitrate });
  const chunks = [];
  rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
  const stopped = new Promise(res => { rec.onstop = res; });

  g.fillStyle = '#0D0D0B'; g.fillRect(0, 0, W, H);
  rec.start(250);
  R.state = 'recording';
  const t0 = performance.now();
  let frames = 0;

  await new Promise((resolve) => {
    const tick = () => {
      const now = (performance.now() - t0) / 1000;
      if (now >= TOTAL) { resolve(); return; }
      frames++;
      g.fillStyle = '#0D0D0B'; g.fillRect(0, 0, W, H);

      // اللقطاتُ الحيّةُ الآن (اثنتان أثناء التلاشي)
      const live = sched.filter(s => now >= s.start - .02 && now <= s.end + .02);
      for (const s of live) {
        let a = 1;
        if (now < s.start + DIS && s.i > 0) a = (now - s.start) / DIS;      // يظهر
        else if (now > s.end - DIS && s.i < sched.length - 1) a = 1;        // السابقُ يبقى تحت
        a = Math.max(0, Math.min(1, a));
        if (s.kind === 'clip' && s.vid.paused) { s.vid.play().catch(() => {}); }
        drawShot(s, now, a, capAlphaOf(s, now));
      }
      R.at = +now.toFixed(2);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  for (const s of sched) { if (s.vid) { try { s.vid.pause(); } catch (e) {} } }
  rec.stop();
  await stopped;

  const blob = new Blob(chunks, { type: 'video/mp4' });
  const u8 = new Uint8Array(await blob.arrayBuffer());
  let b = ''; const STEP = 0x8000;
  for (let i = 0; i < u8.length; i += STEP) {
    b += String.fromCharCode.apply(null, u8.subarray(i, i + STEP));
  }
  window.__b64 = btoa(b);
  R.bytes = u8.length;
  R.b64len = window.__b64.length;
  R.frames = frames;
  R.wall = +((performance.now() - t0) / 1000).toFixed(2);
  R.state = 'done';
  return R;
};
`;
}


/* =========================================================== جانبُ العقدة */

function furl(p, root) {
  const abs = path.isAbsolute(p) ? p : path.join(root, p);
  if (!fs.existsSync(abs)) throw new Error('لا يوجد ملفّ: ' + abs);
  return 'file://' + abs;
}

function buildPlan(cfgPath, scale) {
  const root = path.dirname(path.dirname(path.dirname(path.resolve(cfgPath))));
  const repo = findRepo(path.resolve(cfgPath));
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const s = scale || 1;
  const plan = {
    width: Math.round(cfg.width * s / 2) * 2,
    height: Math.round(cfg.height * s / 2) * 2,
    fps: cfg.fps, bitrate: Math.round(cfg.bitrate * (s * s)),
    dissolve: cfg.dissolve,
    safe: {
      top: Math.round(cfg.safe.top * s),
      bottom: Math.round(cfg.safe.bottom * s),
      side: Math.round(cfg.safe.side * s),
    },
    logo: furl('assets/img/logo.png', repo),
    fontDisplay: furl('assets/fonts/ArefRuqaa-Bold.ttf', repo),
    fontBody: furl('assets/fonts/NotoKufiArabic-SemiBold.ttf', repo),
    shots: cfg.shots.map(x => (x.kind === 'clip' || x.kind === 'photo')
      ? { ...x, src: furl(x.src, repo) } : { ...x }),
  };
  // نوعٌ مجهولٌ يُرفَض **قبل** التسجيل. بلا هذا الحارسِ خطأٌ مطبعيٌّ واحدٌ
  // (`phot` بدل `photo`) يرسم إطاراً **أسودَ** بلا رميٍ ولا رسالة، ويُسلَّم
  // ريلٌ فيه ثلاثُ ثوانٍ سوداء — وتُقرأ عطلاً في الفيديو لا خطأً في ملفّ.
  const KINDS = new Set(['clip', 'photo', 'card']);
  plan.shots.forEach((x, i) => {
    if (!KINDS.has(x.kind)) {
      throw new Error(`اللقطة ${i + 1}: نوعٌ مجهول "${x.kind}". `
        + `المسموح: ${[...KINDS].join(' · ')}`);
    }
    if (!(x.dur > 0)) throw new Error(`اللقطة ${i + 1}: مدّةٌ غيرُ صالحة`);
  });

  plan._expected = plan.shots.reduce((a, x, i) =>
    a + x.dur - (i < plan.shots.length - 1 ? cfg.dissolve : 0), 0)
    + cfg.dissolve * 0;      // آخرُ لقطةٍ لا تُقصَّر
  plan._tag = cfg._tag || null;
  plan._repo = repo;
  return plan;
}

function findRepo(from) {
  let d = path.dirname(from);
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(d, '.git'))) return d;
    d = path.dirname(d);
  }
  return process.cwd();
}

async function record(plan, out) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'reelrec-'));
  const stageDir = path.join(plan._repo, '.work');
  fs.mkdirSync(stageDir, { recursive: true });
  const stage = path.join(stageDir, '.__reelstage.html');
  fs.writeFileSync(stage,
    '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#0D0D0B">'
    + '<style>video{display:none}canvas{width:200px}</style>');

  const proc = spawn(SHELL, ['--no-sandbox', '--disable-gpu', '--headless',
    '--disable-dev-shm-usage', '--force-color-profile=srgb',
    '--allow-file-access-from-files', '--autoplay-policy=no-user-gesture-required',
    '--mute-audio', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--remote-allow-origins=*', 'about:blank'], { stdio: ['ignore', 'pipe', 'pipe'] });

  const ws = await new Promise((res, rej) => {
    let b = '';
    proc.stderr.on('data', d => {
      b += d.toString();
      const m = b.match(/ws:\/\/[^\s]+/);
      if (m) res(m[0]);
    });
    proc.on('exit', c => rej(new Error('سقط المتصفّح (' + c + ')')));
    setTimeout(() => rej(new Error('مهلةُ تشغيلِ المتصفّح')), 20000);
  });

  const sock = new WebSocket(ws);
  let id = 0; const pend = new Map();
  const send = (method, params = {}, sessionId) => new Promise(res => {
    const i = ++id; pend.set(i, res);
    sock.send(JSON.stringify({ id: i, method, params, sessionId }));
  });
  sock.onmessage = e => {
    const r = JSON.parse(e.data);
    if (r.id && pend.has(r.id)) { pend.get(r.id)(r.result); pend.delete(r.id); }
  };
  await new Promise(res => { sock.onopen = res; });

  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const ev = (expression, awaitPromise = false) => send('Runtime.evaluate',
    { expression, awaitPromise, returnByValue: true }, sessionId);

  await send('Runtime.enable', {}, sessionId);
  await send('Page.enable', {}, sessionId);
  await send('Page.navigate', { url: 'file://' + stage }, sessionId);
  await new Promise(r => setTimeout(r, 500));
  await ev(stagePage());

  const expected = plan._expected;
  process.stdout.write(`التسجيل بزمنٍ حقيقيّ: ${expected.toFixed(1)} ثانية `
    + `بمقاس ${plan.width}x${plan.height} … `);

  const started = Date.now();
  const runP = ev(`window.__run(${JSON.stringify(plan)})`, true);
  const poll = setInterval(async () => {
    const r = await ev('JSON.stringify(window.__reel||{})');
    try {
      const st = JSON.parse(r.result.value || '{}');
      if (st.state === 'recording' && st.at != null) {
        process.stdout.write(`\rالتسجيل: ${st.at}s / ${expected.toFixed(1)}s   `);
      }
    } catch (e) {}
  }, 1000);

  const r = await runP;
  clearInterval(poll);
  process.stdout.write('\n');

  if (r && r.exceptionDetails) {
    const st = await ev('JSON.stringify(window.__reel||{})');
    let msg = '';
    try { msg = (JSON.parse(st.result.value || '{}').msg) || ''; } catch (e) {}
    proc.kill();
    throw new Error('سقط التسجيل: ' + (msg
      || (r.exceptionDetails.exception
        && (r.exceptionDetails.exception.description
          || r.exceptionDetails.exception.value))
      || r.exceptionDetails.text));
  }

  const meta = r.result.value;
  if (!meta || meta.state !== 'done') { proc.kill(); throw new Error('لم يكتمل التسجيل'); }

  // ---- النقلُ على دفعات: نداءٌ واحدٌ بـ٢٠ مليون حرفٍ يسقط عبر CDP
  const total = meta.b64len;
  let b64 = '';
  for (let off = 0; off < total; off += CHUNK) {
    const part = await ev(`window.__b64.substr(${off},${CHUNK})`);
    b64 += part.result.value;
    process.stdout.write(`\rالنقل: ${Math.min(100, Math.round(100 * b64.length / total))}%  `);
  }
  process.stdout.write('\n');
  proc.kill();
  try { fs.unlinkSync(stage); } catch (e) {}

  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, Buffer.from(b64, 'base64'));
  return { meta, expected, bytes: fs.statSync(out).size, wall: (Date.now() - started) / 1000 };
}

async function verify(out, repo) {
  // الدليلُ على أنّ الملفَّ فيديو: **كرومٌ يقرؤه**، لا اسمُ الملفّ.
  const probe = path.join(repo, '.kiro', 'tools', 'vidframes.js');
  if (!fs.existsSync(probe)) return null;
  const { execFileSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(path.join(repo, '.work'), 'vrfy-'));
  try {
    const o = execFileSync(process.execPath, [probe, out, dir, '1', '320', '.7'],
      { encoding: 'utf8', timeout: 90000 });
    const j = JSON.parse(o);
    fs.rmSync(dir, { recursive: true, force: true });
    return j;
  } catch (e) {
    fs.rmSync(dir, { recursive: true, force: true });
    return { error: String(e.message || e).slice(0, 200) };
  }
}


/* ----------------------------------------------------------- فحصٌ ذاتيّ */
function selftest() {
  const fails = [];
  const ck = (c, m) => { if (!c) fails.push(m); };

  // ١) الملفُّ فيديو إن بدأ بـftyp … وmoov — ولا يُحكم بالامتداد
  const sig = (buf) => buf.slice(4, 8).toString() === 'ftyp';
  ck(sig(Buffer.from('0000001c66747970', 'hex')), 'لم يعرف توقيعَ ftyp');
  ck(!sig(Buffer.from('89504e470d0a1a0a', 'hex')), 'عدَّ PNG فيديو');

  // ٢) حسابُ المدّةِ المتوقّعة: التلاشي يُقصِّر كلَّ لقطةٍ إلّا الأخيرة
  const cfg = { dissolve: 0.5, shots: [{ dur: 2 }, { dur: 2 }, { dur: 2 }] };
  const exp = cfg.shots.reduce((a, x, i) =>
    a + x.dur - (i < cfg.shots.length - 1 ? cfg.dissolve : 0), 0);
  ck(Math.abs(exp - 5.0) < 1e-9, `المدّةُ المتوقّعة ${exp} والصحيحُ 5.0`);

  // ٣) الكسرُ **يجب أن يُغيّر الجواب**: بلا تلاشٍ تكون ٦ لا ٥
  const noDis = cfg.shots.reduce((a, x) => a + x.dur, 0);
  ck(noDis === 6 && noDis !== exp, 'الحسابانِ متساويانِ فالتأكيدُ لا يُفرّق');

  // ٤) حدُّ السماحِ يُسقط النقصَ الحقيقيَّ ويقبل التقريبَ الصغير
  const short = (got, want) => (want - got) / want > DUR_TOLERANCE;
  ck(short(10.0, 17.0) === true, 'لم يُسقط نقصاً كبيراً');
  ck(short(16.8, 17.0) === false, 'أسقط تقريباً مقبولاً');
  ck(short(15.5, 17.0) === true, 'لم يُسقط نقصَ ٩٪');

  // ٥) المقاسُ يبقى زوجيّاً بعد التحجيم (H.264 يحتاج أبعاداً زوجيّة)
  for (const s of [1, .67, .5, .75]) {
    const w = Math.round(1080 * s / 2) * 2, h = Math.round(1920 * s / 2) * 2;
    ck(w % 2 === 0 && h % 2 === 0, `مقاسٌ فرديٌّ عند scale=${s}`);
  }

  // ٦) حارسُ النوعِ المجهول — ويُجرَّب على العطلِ المعروفِ نفسِه
  const KINDS = new Set(['clip', 'photo', 'card']);
  ck(KINDS.has('photo') && KINDS.has('clip') && KINDS.has('card'),
     'نوعٌ مشروعٌ مرفوض');
  ck(!KINDS.has('phot'), 'قبِل الخطأَ المطبعيَّ phot');
  ck(!KINDS.has(''), 'قبِل نوعاً فارغاً');
  ck(!KINDS.has(undefined), 'قبِل لقطةً بلا نوع');
  // والمدّةُ: صفرٌ وسالبٌ وغيرُ رقمٍ كلُّها تُرفَض
  for (const bad of [0, -1, undefined, null, 'ثانيتان', NaN]) {
    ck(!(bad > 0), `قبِل مدّةً غيرَ صالحة: ${String(bad)}`);
  }
  ck(3.2 > 0, 'رفضَ مدّةً صالحة');

  // ٧) الأدواتُ التي يعتمد عليها موجودةٌ فعلاً
  const here = __dirname;
  for (const f of ['vidframes.js']) {
    ck(fs.existsSync(path.join(here, f)), 'أداةٌ مفقودة: ' + f);
  }
  ck(fs.existsSync(SHELL), 'لا يوجد chrome-headless-shell في المسار المتوقّع');

  if (fails.length) {
    console.error('سقط الفحصُ الذاتيّ:');
    fails.forEach(m => console.error('  ✗ ' + m));
    return 1;
  }
  console.log('الفحصُ الذاتيّ لـreelrec: مرّ (٧ مجموعات)');
  return 0;
}


/* ------------------------------------------------------------------ main */
(async () => {
  const a = process.argv.slice(2);
  if (a.includes('--selftest')) process.exit(selftest());
  if (a.length < 2) {
    console.error('الاستخدام: node reelrec.js <reel.json> <out.mp4> [--scale .67]');
    process.exit(2);
  }
  const scale = a.includes('--scale') ? parseFloat(a[a.indexOf('--scale') + 1]) : 1;
  const cfgPath = path.resolve(a[0]);
  const out = path.resolve(a[1]);

  let plan;
  try { plan = buildPlan(cfgPath, scale); }
  catch (e) { console.error('خطأٌ في الخطّة: ' + e.message); process.exit(2); }

  if (plan._tag) console.log('وسم: ' + plan._tag);

  let r;
  try { r = await record(plan, out); }
  catch (e) { console.error(e.message); process.exit(1); }

  const v = await verify(out, plan._repo);
  const got = v && v.duration ? v.duration : null;

  console.log('');
  console.log(`الملفّ      : ${path.relative(process.cwd(), out)}`);
  console.log(`الحجم       : ${(r.bytes / 1048576).toFixed(2)} ميجابايت`);
  console.log(`المقاس      : ${v && v.source ? v.source : plan.width + 'x' + plan.height}`);
  console.log(`المدّة       : ${got ? got.toFixed(2) + 's' : '؟'}`
    + `  (المطلوب ${r.expected.toFixed(2)}s)`);
  console.log(`الإطارات    : ${r.meta.frames} مرسومة`
    + ` ≈ ${(r.meta.frames / r.meta.wall).toFixed(1)} إطاراً/ث`);

  if (v && v.error) {
    console.error('\n⚠ تعذّر إثباتُ أنّ الملفَّ فيديوٌ صالح: ' + v.error);
    process.exit(1);
  }
  if (got && (r.expected - got) / r.expected > DUR_TOLERANCE) {
    console.error(`\n⚠ سقطت إطارات: المدّةُ ${got.toFixed(2)}s والمطلوب `
      + `${r.expected.toFixed(2)}s. أعِدْ بـ--scale .67 ثمّ كبِّرْ في المحرّر، `
      + 'أو أنقِصْ عددَ اللقطاتِ المتداخلة.');
    process.exit(1);
  }
  console.log('\nبلا صوت — تُضاف الموسيقى من مكتبةِ إنستقرام عند النشر.');
})();
