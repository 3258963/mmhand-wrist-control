const port = 9333;
const sleep = ms => new Promise(r => setTimeout(r, ms));
let page = null;
for (let i = 0; i < 40; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    page = list.find(t => t.type === 'page' && t.url.startsWith('file:'));
    if (page) break;
  } catch {}
  await sleep(300);
}
if (!page) { console.log('NO PAGE'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0; const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
await new Promise(r => ws.onopen = r);
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params }));
  setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error('timeout')); } }, 6000);
});
const ev = async e => (await send('Runtime.evaluate', { expression: e, returnByValue: true })).result.result.value;

await ev(`window.__w=0; document.getElementById('c').addEventListener('wheel', function(e){ window.__w++; window.__last = {dy:e.deltaY, ctrl:e.ctrlKey}; }, {passive:false}); 'ok'`);
const box = JSON.parse(await ev('JSON.stringify(document.getElementById("c").getBoundingClientRect())'));
const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2);

await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY: -120, modifiers: 0, pointerType: 'mouse' });
await sleep(300);
console.log('plain wheel count', await ev('window.__w'), await ev('JSON.stringify(window.__last)'));

await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY: -120, modifiers: 2, pointerType: 'mouse' });
await sleep(300);
console.log('ctrl wheel count', await ev('window.__w'), await ev('JSON.stringify(window.__last)'));
ws.close();
