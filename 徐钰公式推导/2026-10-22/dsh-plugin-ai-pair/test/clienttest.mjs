/**
 * Offline self-test for the client half: loads client.js through a fake module
 * loader, runs the factory with a stub React and a stub slot registry, and
 * checks that the pair_review card registers on `tool.call.toolview`.
 *
 * Run: node test/clienttest.mjs
 */
import { readFile } from 'node:fs/promises';

let spec = null;
globalThis.window = {
  __ModuleLoader__: {
    load(value) {
      spec = value;
    },
  },
};

await import('../client.js');

if (spec === null) throw new Error('client module did not call __ModuleLoader__.load');
if (spec.id !== '@local/ai-pair') throw new Error(`unexpected module id: ${spec.id}`);

const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState: (initial) => [initial, () => {}],
  useMemo: (factory) => factory(),
  useEffect: () => undefined,
};

const registered = [];
const injected = [];
const ctx = {
  get: (service) => (service === 'locale' ? { getSnapshot: () => ({ active: 'zh' }) } : undefined),
  slots: {
    inject(slot, callback) {
      injected.push(slot);
      return callback();
    },
    register(options, component) {
      registered.push({ options, component });
      return () => {};
    },
  },
};

const module = spec.factory((id) => {
  if (id === 'react') return React;
  throw new Error(`unexpected require: ${id}`);
});
module.apply(ctx);

const entry = registered.find((item) => item.options && item.options.key === 'pair_review');
if (entry === undefined) throw new Error('pair_review toolview was not registered');
if (typeof entry.component !== 'function') throw new Error('registered view is not a component');

const sidebarEntry = registered.find((item) => item.options && item.options.id === 'ai-pair');
if (sidebarEntry === undefined) throw new Error('sidebar.panellist entry was not registered');
if (sidebarEntry.options.name !== 'sidebar.panellist') throw new Error('sidebar entry registered on the wrong slot');
if (sidebarEntry.options.order !== 40) throw new Error('sidebar entry order changed');
if (typeof sidebarEntry.options.label !== 'function') throw new Error('sidebar label must be a thunk for live locale');
if (typeof sidebarEntry.component !== 'function') throw new Error('sidebar icon is not a component');

const panelEntry = registered.find((item) => item.options && item.options.name === 'main' && item.options.key === 'ai-pair');
if (panelEntry === undefined) throw new Error('main panel was not registered for ai-pair');
if (typeof panelEntry.component !== 'function') throw new Error('panel is not a component');

const panelText = texts(panelEntry.component({})).join('\n');
const panelChecks = {
  'panel title': panelText.includes('AI 协作 · 一改一审'),
  'panel subtitle': panelText.includes('审不过会把问题退回重改'),
  'panel roles': panelText.includes('实现者') && panelText.includes('审查者'),
  'panel default models': panelText.includes('deepseek-flash') && panelText.includes('deepseek-v4-pro'),
  'panel steps': panelText.includes('pair_review'),
  'panel sample': panelText.includes('用一改一审实现'),
  'panel actions': panelText.includes('复制指令') && panelText.includes('回到对话'),
};
for (const [label, ok] of Object.entries(panelChecks)) console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`);
const panelFailed = Object.entries(panelChecks).filter(([, ok]) => !ok);
if (panelFailed.length > 0) {
  console.log('--- panel text ---');
  console.log(panelText);
  throw new Error(`panel checks failed: ${panelFailed.map(([label]) => label).join(', ')}`);
}


const rendered = entry.component({
  toolName: 'pair_review',
  phase: 'result',
  block: {
    content: [
      {
        type: 'text',
        text: [
          '## AI 一改一审 · 未通过（2 轮）',
          '实现 `deepseek-account/deepseek-flash`　审查 `deepseek-account/deepseek-v4-pro`',
          '',
          '### 第 1 轮',
          '',
          '**实现**（deepseek-flash，completed）',
          '改了 a.txt。',
          '',
          '**审查**（deepseek-v4-pro）→ ❌ 不通过',
          '第二行缺失。',
          '- [blocker] a.txt — 缺少第二行',
          '',
          '### 第 2 轮',
          '',
          '**实现**（deepseek-flash，completed）',
          '补齐第二行。',
          '',
          '**审查**（deepseek-v4-pro）→ ✅ 通过',
          '现在正确。',
        ].join('\n'),
      },
    ],
  },
});

/** Walk the stub element tree (invoking function components) and collect every text leaf. */
function texts(node, out = []) {
  if (node === null || node === undefined) return out;
  if (typeof node === 'string' || typeof node === 'number') {
    out.push(String(node));
    return out;
  }
  if (Array.isArray(node)) {
    for (const child of node) texts(child, out);
    return out;
  }
  if (typeof node === 'object') {
    if (node.type === 'style') return out;
    if (typeof node.type === 'function') {
      texts(node.type(node.props || {}), out);
      return out;
    }
    if (node.children) texts(node.children, out);
  }
  return out;
}

const all = texts(rendered).join('\n');
const checks = {
  'slot injected': injected.includes('tool.call.toolview'),
  'headline title': all.includes('AI 一改一审'),
  'fail badge': all.includes('未通过'),
  'round 1': all.includes('#1'),
  'round 2': all.includes('#2'),
  'implementer note': all.includes('改了 a.txt。'),
  'issue severity': all.includes('blocker'),
  'issue text': all.includes('缺少第二行'),
  'pass on round 2': all.includes('通过'),
};
for (const [label, ok] of Object.entries(checks)) console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`);
const failed = Object.entries(checks).filter(([, ok]) => !ok);
if (failed.length > 0) {
  console.log('--- rendered text ---');
  console.log(all);
  console.log('--- end ---');
  throw new Error(`client render checks failed: ${failed.map(([label]) => label).join(', ')}`);
}

// A running call has no content yet and must still render something.
const running = texts(entry.component({ toolName: 'pair_review', phase: 'start', block: { call: { name: 'pair_review', argsRaw: '{}' } } })).join('\n');
if (!running.includes('进行中') && !running.includes('running')) throw new Error('running state did not render');

// Unparseable content falls back to the raw text instead of crashing.
const fallback = texts(entry.component({ toolName: 'pair_review', phase: 'result', block: { content: [{ type: 'text', text: 'Error: boom' }] } })).join('\n');
if (!fallback.includes('Error: boom')) throw new Error('fallback text missing');

console.log('clienttest ok');
