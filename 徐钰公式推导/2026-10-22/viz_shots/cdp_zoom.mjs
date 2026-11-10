import fs from 'fs';

const port = 9333;
const base = `http://127.0.0.1:${port}`;
const sleep = ms => new Promise(r => setTimeout(r, ms));

let page = null;
for (let i = 0; i < 40; i++) {
  try {
    const list = await (await fetch(base + '/json/list')).json();
    page = list.find(t => t.type === 'page' && t.url.startsWith('file:'));
    if (page) break;
  } catch {}
  await sleep(300);
}
if (!page) { console.log('NO PAGE'); process.exit(1); }
console.log('target', page.url);

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pend = new Map();
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
};
await new Promise(r => ws.onopen = r);

const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id;
  pend.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params }));
  setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error('timeout ' + method)); } }, 8000);
});

const ev = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
  return r.result.result.value;
};

await send('Page.enable');
await sleep(1500);

const info = async () => await ev('JSON.stringify({iw:innerWidth, cw:document.documentElement.clientWidth, dpr:devicePixelRatio})');
const shot = async f => {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(f, Buffer.from(r.result.data, 'base64'));
};

const box = JSON.parse(await ev('JSON.stringify(document.getElementById("c").getBoundingClientRect())'));
const x = Math.round(box.x + box.width / 2);
const y = Math.round(box.y + box.height / 2);

const out = process.argv[2];
console.log('before', await info(), 'center', x, y);
await shot(out + '_before.png');

async function wheel(mods, dy) {
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY: dy, modifiers: mods, pointerType: 'mouse' });
  await sleep(600);
}

await wheel(2, -240);   // Ctrl + 滚轮
console.log('after ctrl+wheel', await info());
await shot(out + '_ctrl.png');

await wheel(0, -240);   // 普通滚轮
console.log('after plain wheel', await info());
await shot(out + '_wheel.png');

ws.close();
console.log('done');
