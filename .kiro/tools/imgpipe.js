#!/usr/bin/env node
/**
 * imgpipe — محرّكُ صورٍ بلا أيّ مكتبة: كرومُ نفسُه يفكّ ويُصغّر ويُشفّر.
 *
 * لماذا: هذا الصندوقُ بلا Pillow وبلا PyPI وبلا npm، وffmpeg المرفقُ
 * مجزوءٌ (يفكّ mjpeg ولا يُشفّره). والمتصفّحُ الموجودُ أصلاً يفكّ
 * JPEG/PNG/WebP كلَّها ويُشفّر WebP وJPEG بـ`canvas.toDataURL`.
 *
 * ثلاثةُ قراراتٍ مقصودة:
 *   · الصورةُ تُمرَّر **data: URL** لا `file://` — فلا تتلوّث اللوحةُ
 *     (canvas taint) ولا نحتاج `--allow-file-access-from-files`.
 *   · المنفذُ `0` ويُقرأ الحقيقيُّ من stderr — منفذٌ ثابتٌ يتعارض مع
 *     أيِّ تشغيلٍ آخر ويُفشل الأداةَ بلا سببٍ ظاهر.
 *   · كلُّ مُخرَجٍ يُقاس بـimgguard بعد الكتابة — لا يُعتمَد على النيّة.
 *
 * الاستخدام:
 *   node imgpipe.js probe <ملفّ>                       # الأبعادُ فقط
 *   node imgpipe.js resize <دخل> <خرج> <عرض> [جودة]
 *   node imgpipe.js responsive <دخل> <مجلّد> <اسم> [عروض] [جودة]
 *   node imgpipe.js batch <ملفّ-خطّة.json>
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn, execFileSync } = require('child_process');

const SHELL = '/inner_container/opt/playwright/chromium_headless_shell-1232/'
  + 'chrome-headless-shell-linux64/chrome-headless-shell';
const MAX_DIM = 2000;
const HERE = __dirname;

const MIME = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
  '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
  '.avif': 'image/avif',
};

function mimeOf(p) {
  const m = MIME[path.extname(p).toLowerCase()];
  if (!m) throw new Error(`صيغةٌ غيرُ مدعومة: ${p}`);
  return m;
}

// ------------------------------------------------------------------ المتصفّح

class Browser {
  async start() {
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'imgpipe-'));
    this.profile = profile;
    this.proc = spawn(SHELL, [
      '--no-sandbox', '--disable-gpu', '--headless',
      '--disable-dev-shm-usage', '--force-color-profile=srgb',
      '--remote-debugging-port=0', `--user-data-dir=${profile}`,
      '--remote-allow-origins=*',
      'about:blank',
    ], { stdio: ['ignore', 'pipe', 'pipe'] });

    const wsUrl = await new Promise((resolve, reject) => {
      let buf = '';
      const timer = setTimeout(
        () => reject(new Error('المتصفّحُ لم يُعلن منفذَه خلال 30 ثانية')), 30000);
      this.proc.stderr.on('data', (d) => {
        buf += d.toString();
        const m = buf.match(/ws:\/\/[^\s]+/);
        if (m) { clearTimeout(timer); resolve(m[0]); }
      });
      this.proc.on('exit', (c) => {
        clearTimeout(timer);
        reject(new Error(`المتصفّحُ خرج برمز ${c}\n${buf.slice(-800)}`));
      });
    });

    this.ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      this.ws.onopen = res;
      this.ws.onerror = () => rej(new Error('تعذّر الاتصالُ بـCDP'));
    });
    this.id = 0;
    this.pending = new Map();
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      const slot = this.pending.get(msg.id);
      if (!slot) return;
      this.pending.delete(msg.id);
      if (msg.error) slot.rej(new Error(JSON.stringify(msg.error)));
      else slot.res(msg.result);
    };

    const { targetId } = await this.send('Target.createTarget',
      { url: 'about:blank' });
    const { sessionId } = await this.send('Target.attachToTarget',
      { targetId, flatten: true });
    this.sessionId = sessionId;
    await this.send('Runtime.enable', {}, sessionId);
  }

  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }

  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    }, this.sessionId);
    if (r.exceptionDetails) {
      throw new Error('خطأٌ في المتصفّح: '
        + (r.exceptionDetails.exception?.description
          || r.exceptionDetails.text));
    }
    return r.result.value;
  }

  stop() {
    try { this.ws && this.ws.close(); } catch (e) { /* مغلقٌ أصلاً */ }
    try { this.proc && this.proc.kill('SIGKILL'); } catch (e) { /* خرج */ }
    try {
      this.profile && fs.rmSync(this.profile, { recursive: true, force: true });
    } catch (e) { /* لا يضرّ */ }
  }
}

// ------------------------------------------------------------------ العمليّات

/** يُحمّل الصورةَ في المتصفّحِ ويُعيد أبعادَها الحقيقيّة. */
const JS_PROBE = (dataUrl) => `(async () => {
  const img = new Image();
  img.src = ${JSON.stringify(dataUrl)};
  await img.decode();
  return { w: img.naturalWidth, h: img.naturalHeight };
})()`;

/**
 * يُصغّر إلى عرضٍ هدفٍ ويُشفّر. لا يُكبّر أبداً:
 * تكبيرُ صورةٍ يُنتج ملفاً أثقلَ بلا تفصيلٍ أكثر، وهو خدعةُ جودةٍ لا جودة.
 */
const JS_RESIZE = (dataUrl, w, type, q) => `(async () => {
  const img = new Image();
  img.src = ${JSON.stringify(dataUrl)};
  await img.decode();
  const target = Math.min(${w}, img.naturalWidth);
  const scale = target / img.naturalWidth;
  const outW = Math.round(target);
  const outH = Math.round(img.naturalHeight * scale);
  if (outW > ${MAX_DIM} || outH > ${MAX_DIM}) {
    throw new Error('المُخرَجُ ' + outW + 'x' + outH + ' يتجاوز ${MAX_DIM}');
  }
  const c = new OffscreenCanvas(outW, outH);
  const g = c.getContext('2d');
  g.imageSmoothingEnabled = true;
  g.imageSmoothingQuality = 'high';
  g.drawImage(img, 0, 0, outW, outH);
  const blob = await c.convertToBlob({ type: ${JSON.stringify(type)}, quality: ${q} });
  const buf = await blob.arrayBuffer();
  let s = '';
  const bytes = new Uint8Array(buf);
  const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return { b64: btoa(s), w: outW, h: outH, type: blob.type };
})()`;

/**
 * يُعيد الألوانَ الغالبةَ مع **نسبةِ كلِّ لونٍ من البكسلات**.
 * لماذا النسبة: لونٌ يملأ 1٪ من الشعار ليس لونَ الهويّة ولو أعجب العين،
 * ولا يُحتجّ به. والشفّافُ يُستثنى وإلّا كان «الأبيضُ» هو أغلبَ شعارٍ شفّاف.
 */
const JS_PALETTE = (dataUrl, buckets, top) => `(async () => {
  const img = new Image();
  img.src = ${JSON.stringify(dataUrl)};
  await img.decode();
  const W = Math.min(img.naturalWidth, 900);
  const H = Math.round(img.naturalHeight * (W / img.naturalWidth));
  const c = new OffscreenCanvas(W, H);
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0, W, H);
  const d = g.getImageData(0, 0, W, H).data;
  const step = 256 / ${buckets};
  const bins = new Map();
  let opaque = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 128) continue;          // شفّافٌ لا يُحسَب
    opaque++;
    const key = [0, 1, 2].map((k) =>
      Math.min(${buckets} - 1, Math.floor(d[i + k] / step))).join(',');
    const b = bins.get(key) || { n: 0, r: 0, g: 0, b: 0 };
    b.n++; b.r += d[i]; b.g += d[i + 1]; b.b += d[i + 2];
    bins.set(key, b);
  }
  const hex = (v) => Math.round(v).toString(16).padStart(2, '0');
  const lum = (r, gg, b) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(gg) + 0.0722 * f(b);
  };
  return {
    total: opaque,
    colors: [...bins.values()].sort((a, b) => b.n - a.n).slice(0, ${top}).map((b) => {
      const r = b.r / b.n, gg = b.g / b.n, bb = b.b / b.n;
      const L = lum(r, gg, bb);
      return {
        hex: '#' + hex(r) + hex(gg) + hex(bb),
        pct: +(100 * b.n / opaque).toFixed(2),
        onWhite: +((1.05) / (L + 0.05)).toFixed(2),
        onBlack: +((L + 0.05) / 0.05).toFixed(2),
      };
    }),
  };
})()`;

async function cmdPalette(files, buckets, top) {
  const b = new Browser();
  await b.start();
  try {
    for (const f of files) {
      const r = await b.evaluate(
        JS_PALETTE(toDataUrl(f), Number(buckets || 6), Number(top || 10)));
      console.log(`\n${path.basename(f)} — ${r.total.toLocaleString()} بكسل غير شفّاف`);
      console.log('  اللون      النسبة%   تباين/أبيض  تباين/أسود');
      for (const c of r.colors) {
        console.log(`  ${c.hex}  ${String(c.pct).padStart(6)}   `
          + `${String(c.onWhite).padStart(8)}   ${String(c.onBlack).padStart(8)}`);
      }
    }
  } finally { b.stop(); }
}

/**
 * إطارُ غلافٍ من فيديو. ffmpeg المرفقُ لا يفكّ mp4 (لا مُفكِّكَ h264 ولا
 * mp4 demuxer)، والمتصفّحُ يُشغّله أصلاً — فهو المُفكِّك.
 * الانتظارُ على `seeked` لا على مؤقّت: مؤقّتٌ قصيرٌ يُنتج إطاراً أسودَ
 * يبدو «غلافاً» ولا يُشكُّ فيه.
 */
const JS_POSTER = (dataUrl, atSec, w, type, q) => `(async () => {
  const v = document.createElement('video');
  v.muted = true; v.preload = 'auto';
  v.src = ${JSON.stringify(dataUrl)};
  await new Promise((res, rej) => {
    v.onloadeddata = res;
    v.onerror = () => rej(new Error('تعذّر فكُّ الفيديو في المتصفّح'));
    setTimeout(() => rej(new Error('الفيديو لم يُحمَّل خلال 30 ثانية')), 30000);
  });
  const at = Math.min(${atSec}, Math.max(0, (v.duration || 1) - 0.05));
  await new Promise((res, rej) => {
    v.onseeked = res;
    v.onerror = () => rej(new Error('تعذّر الانتقالُ إلى الثانية ' + at));
    setTimeout(() => rej(new Error('الانتقالُ لم يكتمل')), 20000);
    v.currentTime = at;
  });
  const target = Math.min(${w}, v.videoWidth);
  const outW = Math.round(target);
  const outH = Math.round(v.videoHeight * (target / v.videoWidth));
  if (outW > ${MAX_DIM} || outH > ${MAX_DIM}) {
    throw new Error('المُخرَجُ ' + outW + 'x' + outH + ' يتجاوز ${MAX_DIM}');
  }
  const c = new OffscreenCanvas(outW, outH);
  const g = c.getContext('2d');
  g.imageSmoothingQuality = 'high';
  g.drawImage(v, 0, 0, outW, outH);
  // إطارٌ أسودُ تمامًا = الانتقالُ لم يُنتج صورةً. يُرفَض ولا يُكتَب.
  const d = g.getImageData(0, 0, Math.min(outW, 64), Math.min(outH, 64)).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i + 1] + d[i + 2];
  const avg = sum / (d.length / 4) / 3;
  if (avg < 3) throw new Error('الإطارُ عند ' + at + 'ث أسودُ (متوسّط ' + avg.toFixed(1) + ') — جرّب ثانيةً أخرى');
  const blob = await c.convertToBlob({ type: ${JSON.stringify(type)}, quality: ${q} });
  const buf = await blob.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let s = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return { b64: btoa(s), w: outW, h: outH, dur: v.duration, vw: v.videoWidth, vh: v.videoHeight, at, avg: +avg.toFixed(1) };
})()`;

/**
 * لقطةُ صفحةٍ أو قسمٍ بعينه **بالاقتصاص** لا بالتمرير.
 *
 * لماذا الاقتصاص: التمريرُ إلى مِرساةٍ ثمّ التصويرُ غيرُ موثوق — جُرِّب
 * فخرجت صفحةٌ فارغةٌ ومجسٌّ يقول `NOT AT TOP`. و`Page.captureScreenshot`
 * بـ`clip` يُصوّر **مستطيلاً من الصفحةِ كاملةً** بلا تمريرٍ أصلاً، فلا
 * شيءَ يتعلّق بالحركةِ ولا بالساعةِ الوهميّة.
 *
 * وأربعةُ شروطٍ إلزاميّة:
 *   · يُنتظَر `document.fonts.ready` **وفكُّ كلِّ صورة** — وإلّا صُوِّرت
 *     صفحةٌ بخطٍّ بديلٍ وصورٍ فارغةٍ تُقرأ «تصميماً معطوباً»
 *   · `loading="lazy"` يُنزَع: صورةٌ خارجَ النافذةِ لا تُحمَّل أبداً،
 *     والاقتصاصُ لا يُمرّر إليها فتبقى فراغاً
 *   · الكشفُ (`data-reveal`) يُلغى، وإلّا صُوِّرت أقسامٌ شفّافة
 *   · الحدُّ 2000 بكسل يُفحَص على **المستطيل المطلوب** قبل التصوير،
 *     وعلى الملفِّ بعده — فلا يُعتمَد على النيّة
 */
const JS_PREP = `(async () => {
  document.documentElement.style.scrollBehavior = 'auto';
  const s = document.createElement('style');
  // ⚠ شريطُ التمريرِ يُخفى **قبل القياس**. في RTL يقع الشريطُ يساراً،
  // فتختلف إحداثيّاتُ التخطيط (clientWidth) عن إحداثيّاتِ اللقطةِ بعرضِه،
  // ويُقتطع من يمينِ الصورةِ بقدرِه — ظهر فعلاً: 15 بكسلاً قطعت أوّلَ
  // حرفٍ من كلِّ عنوانٍ عربيّ. وإخفاؤه يُوحّد الفضاءَين فلا تصحيحَ هشّ.
  s.textContent = '*,*::before,*::after{animation-duration:.001s!important;'
    + 'transition-duration:.001s!important}'
    + 'html{scrollbar-width:none!important}'
    + '::-webkit-scrollbar{display:none!important}';
  document.head.appendChild(s);
  document.querySelectorAll('[data-reveal]').forEach((n) => {
    n.classList.remove('is-armed'); n.classList.add('is-in');
  });
  const imgs = [...document.images];
  imgs.forEach((i) => { i.loading = 'eager'; });
  await Promise.allSettled(imgs.map((i) => (i.decode ? i.decode() : null)));
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return {
    imgs: imgs.length,
    broken: imgs.filter((i) => !i.complete || i.naturalWidth === 0)
      .map((i) => i.currentSrc || i.src),
    docH: document.documentElement.scrollHeight,
    docW: document.documentElement.scrollWidth,
  };
})()`;

const JS_RECT = (sel) => `(() => {
  const el = document.querySelector(${JSON.stringify(sel)});
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left + window.scrollX, y: r.top + window.scrollY,
           w: r.width, h: r.height };
})()`;

/**
 * يُسمّي العناصرَ التي تتجاوز عرضَ النافذة — تجاوزٌ أفقيٌّ في RTL يُزيح
 * الصفحةَ كلَّها ويُقرأ «التصميمُ مكسور»، و`overflow-x: hidden` يُخفي
 * العَرَضَ ولا يُصلح السبب. والتخمينُ في هذا البابِ أضيعُ من القياس.
 */
const JS_OVERFLOW = `(() => {
  const vw = document.documentElement.clientWidth;
  const out = [];
  // عنصرٌ داخلَ حاويةٍ لافّةٍ أفقيّاً (overflow-x: auto أو scroll) يُقصَد
  // أن يتجاوزها — شريطُ الأطباقِ مثلاً. وعدُّه تجاوزاً يُنتج 18 إنذاراً
  // كاذباً، وإنذارٌ كاذبٌ واحدٌ يُعلّم من يقرأ أن يتجاهل الأداةَ كلَّها.
  // ⚠ ولا باكتيك في تعليقٍ داخلَ قالبٍ نصّيّ: يُغلق القالبَ ويُسقط الملفَّ
  // كلَّه بـSyntaxError — وقع فعلاً في هذا السطر بعينه.
  const inScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  document.querySelectorAll('*').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1) return;
    if (inScroller(el)) return;
    const left = r.left + window.scrollX;
    const right = left + r.width;
    if (right > vw + 1 || left < -1) {
      out.push({
        sel: el.tagName.toLowerCase()
          + (el.id ? '#' + el.id : '')
          + (el.className && typeof el.className === 'string'
             ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.') : ''),
        left: Math.round(left), right: Math.round(right),
        w: Math.round(r.width),
      });
    }
  });
  return {
    vw,
    docW: document.documentElement.scrollWidth,
    bodyW: document.body.scrollWidth,
    dir: document.documentElement.dir || getComputedStyle(document.documentElement).direction,
    items: out.slice(0, 25),
    total: out.length,
  };
})()`;

async function cmdOverflow(page, w, h) {
  const b = new Browser();
  await b.start();
  try {
    await b.send('Emulation.setDeviceMetricsOverride', {
      width: Number(w || 1400), height: Number(h || 1000),
      deviceScaleFactor: 1, mobile: false,
    }, b.sessionId);
    await b.send('Page.navigate', { url: 'file://' + path.resolve(page) }, b.sessionId);
    for (let i = 0; i < 100; i++) {
      if (await b.evaluate('document.readyState') === 'complete') break;
      await new Promise((r) => setTimeout(r, 100));
    }
    await b.evaluate(JS_PREP);
    const r = await b.evaluate(JS_OVERFLOW);
    console.log(`${path.basename(page)} — نافذة ${r.vw} · dir=${r.dir}`);
    console.log(`  عرض المستند ${r.docW} · عرض body ${r.bodyW}`);
    if (!r.total) { console.log('  ✓ لا عنصرَ يتجاوز عرضَ النافذة'); return; }
    console.log(`  ✗ ${r.total} عنصراً يتجاوز:`);
    r.items.forEach((i) => console.log(
      `    [${String(i.left).padStart(6)} → ${String(i.right).padStart(6)}]`
      + ` عرض ${String(i.w).padStart(5)}  ${i.sel}`));
    process.exitCode = 1;
  } finally { b.stop(); }
}

async function cmdShot(page, out, opts) {
  const sel = opts.sel || null;
  const w = Number(opts.w || 1400);
  const h = Number(opts.h || 900);
  if (w > MAX_DIM || h > MAX_DIM) {
    throw new Error(`النافذةُ ${w}x${h} تتجاوز ${MAX_DIM} بكسل`);
  }

  const b = new Browser();
  await b.start();
  try {
    await b.send('Emulation.setDeviceMetricsOverride', {
      width: w, height: h, deviceScaleFactor: 1, mobile: !!opts.mobile,
    }, b.sessionId);
    await b.send('Page.enable', {}, b.sessionId);

    const url = 'file://' + path.resolve(page);
    await b.send('Page.navigate', { url }, b.sessionId);
    // الانتظارُ على جاهزيّةِ المستند لا على مؤقّتٍ ثابت
    for (let i = 0; i < 100; i++) {
      const st = await b.evaluate('document.readyState');
      if (st === 'complete') break;
      await new Promise((r) => setTimeout(r, 100));
    }
    const prep = await b.evaluate(JS_PREP);
    if (prep.broken.length) {
      console.error(`⚠ ${prep.broken.length} صورة لم تُحمَّل — تُسمّى ولا تُكتم:`);
      prep.broken.slice(0, 8).forEach((u) => console.error(`    ${u}`));
    }

    // ⚠ عرضُ الاقتصاصِ **لا يتجاوز عرضَ المستندِ الحقيقيّ**: طلبُ 1400
    // على مستندٍ عرضُه 1385 (نافذةٌ ناقصةُ شريطِ التمرير) يجعل
    // `captureBeyondViewport` يُعيد التخطيطَ فتُزاح الصفحةُ في RTL
    // مئاتَ البكسلات وتُقرأ اللقطةُ «تصميماً مكسوراً» — وقع فعلاً.
    const clipW = Math.min(w, prep.docW, MAX_DIM);
    let clip = { x: 0, y: 0, width: clipW, height: h, scale: 1 };
    if (sel) {
      const r = await b.evaluate(JS_RECT(sel));
      if (!r) {
        // محدِّدٌ غائبٌ يُرفَض ولا يُنتج لقطةَ أعلى الصفحةِ بلا شكوى
        const ids = await b.evaluate(
          "[...document.querySelectorAll('[id]')].map(n=>n.id).join(' · ')");
        throw new Error(`لا عنصرَ يُطابق «${sel}».\nالمعرّفاتُ الموجودة: ${ids}`);
      }
      if (r.h < 4) throw new Error(`العنصرُ «${sel}» ارتفاعُه ${r.h} — مخفيٌّ أو فارغ`);
      const height = Math.min(Math.round(r.h), MAX_DIM);
      if (Math.round(r.h) > MAX_DIM) {
        console.error(`⚠ «${sel}» ارتفاعُه ${Math.round(r.h)} — يُقتطع عند ${MAX_DIM}`);
      }
      clip = { x: Math.round(r.x), y: Math.round(r.y),
               width: Math.min(Math.round(r.w) || w, MAX_DIM), height, scale: 1 };
    }

    const { data } = await b.send('Page.captureScreenshot',
      { format: 'png', clip, captureBeyondViewport: true }, b.sessionId);
    fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
    fs.writeFileSync(out, Buffer.from(data, 'base64'));

    const verdict = guard(out);
    if (!verdict.startsWith('آمن')) {
      fs.unlinkSync(out);
      throw new Error(`المُخرَجُ متجاوزٌ فحُذف\n${verdict}`);
    }
    console.log(`الصفحةُ ${prep.docW}x${prep.docH} · ${prep.imgs} صورة`
      + (prep.broken.length ? ` (${prep.broken.length} معطوبة)` : ' (كلّها سليمة)'));
    console.log(`  اقتصاص ${clip.width}x${clip.height} عند (${clip.x},${clip.y})`
      + `  ⇒ ${Math.round(fs.statSync(out).size / 1024)} ك.ب  ${out}`);
    if (prep.broken.length) process.exitCode = 1;
  } finally { b.stop(); }
}

async function cmdPoster(src, out, atSec, width, q) {
  const b = new Browser();
  await b.start();
  try {
    const type = path.extname(out).toLowerCase() === '.webp'
      ? 'image/webp' : 'image/jpeg';
    const r = await b.evaluate(JS_POSTER(
      `data:video/mp4;base64,${fs.readFileSync(src).toString('base64')}`,
      Number(atSec || 0.5), Number(width || 1440), type, Number(q || 0.8)));
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, Buffer.from(r.b64, 'base64'));
    const verdict = guard(out);
    if (!verdict.startsWith('آمن')) {
      fs.unlinkSync(out);
      throw new Error(`المُخرَجُ متجاوزٌ فحُذف\n${verdict}`);
    }
    console.log(`الفيديو ${r.vw}x${r.vh} · ${r.dur.toFixed(1)}ث`);
    console.log(`  إطارٌ عند ${r.at}ث (سطوع ${r.avg}) ⇒ ${r.w}x${r.h}  `
      + `${Math.round(fs.statSync(out).size / 1024)} ك.ب  ${out}`);
  } finally { b.stop(); }
}

function toDataUrl(file) {
  const b = fs.readFileSync(file);
  return `data:${mimeOf(file)};base64,${b.toString('base64')}`;
}

function guard(file) {
  const r = execFileSync('python3',
    [path.join(HERE, 'imgguard.py'), 'check', file],
    { encoding: 'utf8' });
  return r.trim();
}

async function cmdProbe(files) {
  const b = new Browser();
  await b.start();
  try {
    for (const f of files) {
      const d = await b.evaluate(JS_PROBE(toDataUrl(f)));
      const over = (d.w > MAX_DIM || d.h > MAX_DIM) ? '  ⚠ متجاوز' : '';
      console.log(`${d.w}x${d.h}\t${path.basename(f)}${over}`);
    }
  } finally { b.stop(); }
}

async function writeOne(b, src, out, width, type, q) {
  const r = await b.evaluate(JS_RESIZE(toDataUrl(src), width, type, q));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, Buffer.from(r.b64, 'base64'));
  const kb = Math.round(fs.statSync(out).size / 1024);
  const verdict = guard(out);
  if (!verdict.startsWith('آمن')) {
    fs.unlinkSync(out);
    throw new Error(`المُخرَجُ متجاوزٌ فحُذف: ${out}\n${verdict}`);
  }
  console.log(`  ${r.w}x${r.h}  ${String(kb).padStart(5)} ك.ب  ${path.relative(process.cwd(), out)}`);
  return { w: r.w, h: r.h, kb };
}

async function cmdResize(src, out, width, q) {
  const type = path.extname(out).toLowerCase() === '.webp'
    ? 'image/webp' : 'image/jpeg';
  const b = new Browser();
  await b.start();
  try { await writeOne(b, src, out, Number(width), type, Number(q || 0.82)); }
  finally { b.stop(); }
}

async function cmdResponsive(src, outdir, name, widths, q) {
  const ws = (widths || '480,960,1440').split(',').map(Number);
  const quality = Number(q || 0.82);
  const b = new Browser();
  await b.start();
  try {
    const d = await b.evaluate(JS_PROBE(toDataUrl(src)));
    console.log(`${path.basename(src)} — الأصل ${d.w}x${d.h}`);
    for (const w of ws) {
      if (w > d.w) {
        console.log(`  تُخطّى ${w} — أوسعُ من الأصل (${d.w}) ولا يُكبَّر`);
        continue;
      }
      await writeOne(b, src, path.join(outdir, `${name}-${w}.webp`), w, 'image/webp', quality);
      await writeOne(b, src, path.join(outdir, `${name}-${w}.jpg`), w, 'image/jpeg', quality);
    }
  } finally { b.stop(); }
}

async function cmdBatch(planFile) {
  const plan = JSON.parse(fs.readFileSync(planFile, 'utf8'));
  const b = new Browser();
  await b.start();
  let done = 0; const failed = [];
  try {
    for (const item of plan) {
      const widths = item.widths || [480, 960, 1440];
      const quality = item.quality ?? 0.82;
      let d;
      try { d = await b.evaluate(JS_PROBE(toDataUrl(item.src))); }
      catch (e) { failed.push(`${item.src}: ${e.message}`); continue; }
      console.log(`${item.name} ← ${path.basename(item.src)} (${d.w}x${d.h})`);
      for (const w of widths) {
        if (w > d.w) continue;
        try {
          await writeOne(b, item.src, path.join(item.outdir, `${item.name}-${w}.webp`), w, 'image/webp', quality);
          await writeOne(b, item.src, path.join(item.outdir, `${item.name}-${w}.jpg`), w, 'image/jpeg', quality);
          done += 2;
        } catch (e) { failed.push(`${item.name}@${w}: ${e.message}`); }
      }
    }
  } finally { b.stop(); }
  console.log(`\nكُتبت ${done} صورة.`);
  if (failed.length) {
    console.error(`سقط ${failed.length}:`);
    failed.forEach((f) => console.error(`  ${f}`));
    process.exit(1);
  }
}

// ------------------------------------------------------------------ المدخل

(async () => {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd) { console.log(require('fs').readFileSync(__filename, 'utf8').split('*/')[0]); process.exit(1); }
  try {
    if (cmd === 'probe') await cmdProbe(rest);
    else if (cmd === 'palette') {
      const flag = rest.findIndex((x) => x === '--buckets');
      let buckets = 6; let files = rest;
      if (flag >= 0) { buckets = rest[flag + 1]; files = rest.filter((_, i) => i !== flag && i !== flag + 1); }
      await cmdPalette(files, buckets, 12);
    }
    else if (cmd === 'resize') await cmdResize(rest[0], rest[1], rest[2], rest[3]);
    else if (cmd === 'poster') await cmdPoster(rest[0], rest[1], rest[2], rest[3], rest[4]);
    else if (cmd === 'overflow') await cmdOverflow(rest[0], rest[1], rest[2]);
    else if (cmd === 'shot') {
      // imgpipe.js shot <page> <out> [--sel '#id'] [--w 1400] [--h 900] [--mobile]
      const o = {};
      for (let i = 2; i < rest.length; i++) {
        if (rest[i] === '--sel') o.sel = rest[++i];
        else if (rest[i] === '--w') o.w = rest[++i];
        else if (rest[i] === '--h') o.h = rest[++i];
        else if (rest[i] === '--mobile') o.mobile = true;
      }
      await cmdShot(rest[0], rest[1], o);
    }
    else if (cmd === 'responsive') await cmdResponsive(rest[0], rest[1], rest[2], rest[3], rest[4]);
    else if (cmd === 'batch') await cmdBatch(rest[0]);
    else { console.error(`أمرٌ مجهول: ${cmd}`); process.exit(1); }
  } catch (e) {
    console.error(`فشل: ${e.message}`);
    process.exit(1);
  }
})();
