#!/usr/bin/env node
/**
 * vidframes — يستخرجُ إطاراتٍ من فيديو بكرومِ نفسِه.
 *
 * لماذا: ffmpeg المرفقُ في هذا الصندوقِ **لا يفكّ H.264 إطلاقاً**
 * (`-decoders` يعطي mjpeg وvp8 وحدَهما، و`-i 1.mp4` يسقط بـ
 * `Invalid data found`). وكرومُ الموجودُ أصلاً يفكّه — مُتحقَّقٌ:
 * `{"state":"ok","w":576,"h":1024,"dur":15.07}` على `intake/01-videos/1.mp4`.
 *
 * ثلاثةُ قراراتٍ مقصودة:
 *   · `--allow-file-access-from-files` لازمةٌ لأنّ الفيديو يُحمَّل `file://`
 *     ثمّ يُرسَم على لوحةٍ — وبلا هذه العلامةِ تتلوّثُ اللوحةُ ويسقط
 *     `toDataURL` بـ`SecurityError`.
 *   · **الصفحةُ تُنقَل إلى `file://` حقيقيٍّ قبل إنشاءِ الفيديو.** صفحةُ
 *     `about:blank` لا تُحمّل `file://` ولو مع العلامةِ أعلاه، فيسقط
 *     بـ`decode_failed code=4` (`SRC_NOT_SUPPORTED`) — وهو خطأٌ يُقرأ
 *     «الصيغةُ غيرُ مدعومة» وليست الصيغةُ، بل أصلُ الصفحة. مقيسٌ:
 *     نفسُ الملفِّ نجح من صفحةِ `file://` وسقط من `about:blank`.
 *   · يُنتظَر `seeked` **ثمّ** إطارُ رسمٍ — الرسمُ قبل اكتمالِ النقلةِ
 *     يُعطي الإطارَ السابقَ بصمت.
 *   · كلُّ مُخرَجٍ ≤ 2000 بكسل لكلِّ بُعدٍ (حدُّ هذا المشروع)، ويُرفَض
 *     الطلبُ قبل تشغيلِ المتصفّحِ لا بعده.
 *
 * الاستخدام:
 *   node vidframes.js <فيديو> <مجلّد-الخرج> [عدد=6] [عرض=720] [جودة=.88]
 *   node vidframes.js <فيديو> <مجلّد> --at 0.5,2,4.25   # أزمنةٌ بعينها
 */

const fs = require('fs'), os = require('os'), path = require('path');
const { spawn } = require('child_process');

const SHELL = '/inner_container/opt/playwright/chromium_headless_shell-1232/'
  + 'chrome-headless-shell-linux64/chrome-headless-shell';
const MAX_DIM = 2000;

function usage(msg) {
  if (msg) console.error('خطأ: ' + msg);
  console.error('الاستخدام: node vidframes.js <فيديو> <مجلّد> [عدد] [عرض] [جودة]');
  console.error('           node vidframes.js <فيديو> <مجلّد> --at 0.5,2,4.25');
  process.exit(2);
}

const argv = process.argv.slice(2);
if (argv.length < 2) usage();
const video = path.resolve(argv[0]);
const outDir = path.resolve(argv[1]);
if (!fs.existsSync(video)) usage('لا يوجد ملفّ: ' + video);

let atList = null, count = 6, width = 720, quality = 0.88;
const atIdx = argv.indexOf('--at');
if (atIdx !== -1) {
  atList = String(argv[atIdx + 1] || '').split(',').map(Number).filter(n => !isNaN(n));
  if (!atList.length) usage('--at يحتاج أزمنةً مفصولةً بفواصل');
  const rest = argv.slice(2).filter((_, i) => i + 2 !== atIdx && i + 2 !== atIdx + 1);
  if (rest[0]) width = parseInt(rest[0], 10) || width;
} else {
  if (argv[2]) count = parseInt(argv[2], 10) || count;
  if (argv[3]) width = parseInt(argv[3], 10) || width;
  if (argv[4]) quality = parseFloat(argv[4]) || quality;
}
if (width > MAX_DIM) usage(`العرض ${width} يتجاوز الحدّ ${MAX_DIM} بكسل`);

fs.mkdirSync(outDir, { recursive: true });

const PAGE_FN = `
(async (src, times, width, quality, maxDim) => {
  const v = document.createElement('video');
  v.muted = true; v.preload = 'auto'; v.src = src;
  document.body.appendChild(v);
  await new Promise((res, rej) => {
    v.addEventListener('loadeddata', res, { once: true });
    v.addEventListener('error', () => rej(new Error('decode_failed code=' +
      (v.error && v.error.code))), { once: true });
    setTimeout(() => rej(new Error('load_timeout')), 20000);
  });
  const dur = v.duration;
  const list = times && times.length ? times
    : Array.from({ length: window.__count }, (_, i) => (dur * (i + 0.5)) / window.__count);
  const scale = Math.min(1, width / v.videoWidth);
  let w = Math.round(v.videoWidth * scale), h = Math.round(v.videoHeight * scale);
  if (w > maxDim || h > maxDim) {
    const k = maxDim / Math.max(w, h); w = Math.floor(w * k); h = Math.floor(h * k);
  }
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  const out = [];
  for (const t of list) {
    const tt = Math.max(0, Math.min(dur - 0.02, t));
    v.currentTime = tt;
    await new Promise(res => v.addEventListener('seeked', res, { once: true }));
    await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
    g.drawImage(v, 0, 0, w, h);
    out.push({ t: +tt.toFixed(3), data: c.toDataURL('image/jpeg', quality).split(',')[1] });
  }
  return { dur, srcW: v.videoWidth, srcH: v.videoHeight, w, h, frames: out };
})`;

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'vidframes-'));
const proc = spawn(SHELL, ['--no-sandbox', '--disable-gpu', '--headless',
  '--disable-dev-shm-usage', '--force-color-profile=srgb',
  '--allow-file-access-from-files', '--autoplay-policy=no-user-gesture-required',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--remote-allow-origins=*', 'about:blank'], { stdio: ['ignore', 'pipe', 'pipe'] });

let sbuf = '', started = false;
proc.stderr.on('data', async (d) => {
  sbuf += d.toString();
  const m = sbuf.match(/ws:\/\/[^\s]+/);
  if (!m || started) return;
  started = true;
  const sock = new WebSocket(m[0]);
  let id = 0; const pend = new Map();
  const send = (method, params = {}, sessionId) => new Promise((res) => {
    const i = ++id; pend.set(i, res);
    sock.send(JSON.stringify({ id: i, method, params, sessionId }));
  });
  sock.onmessage = (e) => {
    const r = JSON.parse(e.data);
    if (r.id && pend.has(r.id)) { pend.get(r.id)(r.result); pend.delete(r.id); }
  };
  sock.onerror = () => { console.error('تعذّر الاتصال بالمتصفّح'); proc.kill(); process.exit(1); };
  sock.onopen = async () => {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Runtime.enable', {}, sessionId);
    await send('Page.enable', {}, sessionId);
    // مرساةُ أصلٍ: صفحةٌ `file://` في نفسِ مجلّدِ الفيديو، وإلّا رُفض المصدر.
    const stage = path.join(path.dirname(video), '.__vidframes.html');
    fs.writeFileSync(stage, '<!doctype html><meta charset=utf-8><body style="margin:0;background:#000">');
    await send('Page.navigate', { url: 'file://' + stage }, sessionId);
    await new Promise(r => setTimeout(r, 400));
    process.on('exit', () => { try { fs.unlinkSync(stage); } catch (_) {} });
    await send('Runtime.evaluate',
      { expression: `window.__count = ${count};`, returnByValue: true }, sessionId);
    const expr = `${PAGE_FN}(${JSON.stringify('file://' + video)},`
      + `${JSON.stringify(atList)}, ${width}, ${quality}, ${MAX_DIM})`;
    const r = await send('Runtime.evaluate',
      { expression: expr, awaitPromise: true, returnByValue: true }, sessionId);
    if (r && r.exceptionDetails) {
      const d2 = r.exceptionDetails;
      console.error('سقط الاستخراج: '
        + ((d2.exception && (d2.exception.description || d2.exception.value)) || d2.text));
      proc.kill(); process.exit(1);
    }
    const val = r && r.result && r.result.value;
    if (!val || !val.frames) { console.error('لا نتيجة من المتصفّح'); proc.kill(); process.exit(1); }
    const base = path.basename(video).replace(/\.[^.]+$/, '');
    const written = [];
    for (const f of val.frames) {
      const name = `${base}-t${String(f.t).replace('.', '_')}.jpg`;
      const p = path.join(outDir, name);
      fs.writeFileSync(p, Buffer.from(f.data, 'base64'));
      written.push({ file: p, t: f.t, bytes: fs.statSync(p).size });
    }
    console.log(JSON.stringify({
      video: path.basename(video), duration: val.dur,
      source: `${val.srcW}x${val.srcH}`, frame: `${val.w}x${val.h}`,
      wrote: written.length, files: written.map(w => path.relative(process.cwd(), w.file)),
    }, null, 2));
    proc.kill(); process.exit(0);
  };
});
setTimeout(() => { console.error('انتهت المهلة'); proc.kill(); process.exit(1); }, 90000);
