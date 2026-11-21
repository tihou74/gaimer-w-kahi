#!/usr/bin/env node
/**
 * pixel — يقرأُ لونَ بكسلٍ بعينِه من صورةٍ، ويحسبُ تباينَ WCAG مع لونٍ آخر.
 *
 * لماذا: حكمتُ على اتّجاهِ تدرّجٍ بالنظرِ مرّتَين وأخطأتُ مرّتَين. زاويةُ
 * `linear-gradient` تُقرأ بالعينِ خطأً على صورةٍ فيها طعامٌ فاتح، والسؤالُ
 * «هل النصُّ مقروء؟» له **جوابٌ رقميّ**: نسبةُ تباينِ لونِ النصِّ إلى لونِ
 * البكسلِ الذي تحتَه. فيُقاس ولا يُقدَّر.
 *
 * الاستخدام:
 *   node pixel.js <صورة> <x,y> [<x,y> ...] [--vs "#FBF7F0"]
 */

const fs = require('fs'), os = require('os'), path = require('path');
const { spawn } = require('child_process');
const SHELL = '/inner_container/opt/playwright/chromium_headless_shell-1232/'
  + 'chrome-headless-shell-linux64/chrome-headless-shell';
const MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };

const args = process.argv.slice(2);
if (args.length < 2) {
  console.error('الاستخدام: node pixel.js <صورة> <x,y> [...] [--vs "#RRGGBB"]');
  process.exit(2);
}
const img = path.resolve(args[0]);
let vs = '#FBF7F0';
const vi = args.indexOf('--vs');
if (vi !== -1) vs = args[vi + 1];
const pts = args.slice(1)
  .filter((a, i) => a !== '--vs' && args[i] !== '--vs')
  .filter(a => /^\d+,\d+$/.test(a))
  .map(a => a.split(',').map(Number));
if (!pts.length) { console.error('لا نقاطَ صالحة (الشكل x,y)'); process.exit(2); }

function lum(r, g, b) {
  const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(a, b) {
  const l1 = lum(...a), l2 = lum(...b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}
const hex2rgb = h => [1, 3, 5].map(i => parseInt(h.replace('#', '').slice(i - 1, i + 1), 16));

const mime = MIME[path.extname(img).toLowerCase()];
if (!mime) { console.error('صيغةٌ غير مدعومة: ' + img); process.exit(2); }
const dataUrl = `data:${mime};base64,` + fs.readFileSync(img).toString('base64');

const EXPR = (src, points) => `(async () => {
  const im = new Image();
  im.src = ${JSON.stringify(src)};
  await im.decode();
  const c = document.createElement('canvas');
  c.width = im.naturalWidth; c.height = im.naturalHeight;
  c.getContext('2d').drawImage(im, 0, 0);
  const g = c.getContext('2d');
  return { w: c.width, h: c.height, px: ${JSON.stringify(points)}.map(([x,y]) => {
    const d = g.getImageData(Math.min(x, c.width-1), Math.min(y, c.height-1), 1, 1).data;
    return [x, y, d[0], d[1], d[2]];
  })};
})()`;

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pixel-'));
const proc = spawn(SHELL, ['--no-sandbox', '--disable-gpu', '--headless',
  '--disable-dev-shm-usage', '--force-color-profile=srgb',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--remote-allow-origins=*', 'about:blank'], { stdio: ['ignore', 'pipe', 'pipe'] });

let buf = '', once = false;
proc.stderr.on('data', async (d) => {
  buf += d.toString();
  const m = buf.match(/ws:\/\/[^\s]+/);
  if (!m || once) return;
  once = true;
  const sock = new WebSocket(m[0]);
  let id = 0; const pend = new Map();
  const send = (method, params = {}, sessionId) => new Promise(res => {
    const i = ++id; pend.set(i, res);
    sock.send(JSON.stringify({ id: i, method, params, sessionId }));
  });
  sock.onmessage = e => {
    const r = JSON.parse(e.data);
    if (r.id && pend.has(r.id)) { pend.get(r.id)(r.result); pend.delete(r.id); }
  };
  sock.onopen = async () => {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Runtime.enable', {}, sessionId);
    const r = await send('Runtime.evaluate',
      { expression: EXPR(dataUrl, pts), awaitPromise: true, returnByValue: true }, sessionId);
    if (r && r.exceptionDetails) {
      console.error('سقط: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
      proc.kill(); process.exit(1);
    }
    const v = r.result.value;
    const ref = hex2rgb(vs);
    console.log(`${path.basename(img)}  ${v.w}x${v.h}   مقابل ${vs}`);
    for (const [x, y, R, G, B] of v.px) {
      const cr = ratio([R, G, B], ref);
      const verdict = cr >= 4.5 ? 'مقروء' : (cr >= 3 ? 'كبيرٌ فقط' : '✗ ساقط');
      const hx = '#' + [R, G, B].map(n => n.toString(16).padStart(2, '0')).join('').toUpperCase();
      console.log(`  (${String(x).padStart(4)},${String(y).padStart(4)})  ${hx}  `
        + `تباين ${cr.toFixed(2)}:1  ${verdict}`);
    }
    proc.kill(); process.exit(0);
  };
});
setTimeout(() => { console.error('انتهت المهلة'); proc.kill(); process.exit(1); }, 30000);
