/**
 * Refresh the inlined sandbox page inside client.js.
 *
 * Usage: node scripts/embed-page.cjs
 *
 * Reads ../腕部公式_可视化沙盘.html (the source page) and rewrites the
 * SANDBOX-PAGE block in ../client.js. Run this after editing the page.
 */
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const clientPath = path.join(root, 'client.js');
const pagePath = path.join(root, '..', '腕部公式_可视化沙盘.html');

let page = fs.readFileSync(pagePath, 'utf8');
if (page.charCodeAt(0) === 0xfeff) page = page.slice(1);

const block =
  '    /* ==== SANDBOX-PAGE:BEGIN — 整页内嵌，生成自 腕部公式_可视化沙盘.html，勿手改 ==== */\n' +
  '    const PAGE_HTML = ' + JSON.stringify(page) + ';\n' +
  '    /* ==== SANDBOX-PAGE:END ==== */\n\n';

const client = fs.readFileSync(clientPath, 'utf8');
const a = client.indexOf('    /* ==== SANDBOX-PAGE:BEGIN');
const b = client.indexOf('    /* ==== SANDBOX-PAGE:END ==== */');
if (a < 0 || b < 0) throw new Error('SANDBOX-PAGE markers not found in client.js');

const next = client.slice(0, a) + block + client.slice(b + '    /* ==== SANDBOX-PAGE:END ==== */\n\n'.length);
fs.writeFileSync(clientPath, next, 'utf8');

console.log('embedded', page.length, 'chars of page; client is now', next.length, 'chars');
