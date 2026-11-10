/**
 * Offline self-test for the pair_review loop: no LLM calls, a fake subagents
 * service replays one failed review and one passing review.
 *
 * Run: node test/selftest.mjs
 */
import { apply, name } from '../index.js';

const calls = [];
let round = 0;

const fakeSubagents = {
  list: () => ['spawn'],
  async startActivation(spec) {
    calls.push(spec);
    round += 1;
    const isReviewer = spec.request.outputSchema !== undefined;
    const result = isReviewer
      ? round === 2
        ? { stopReason: 'completed', output: [{ type: 'text', text: '审查完成' }], structured: { verdict: 'fail', summary: '第一版有问题', issues: [{ severity: 'blocker', file: 'a.txt', detail: '缺少第二行' }] } }
        : { stopReason: 'completed', output: [{ type: 'text', text: '通过' }], structured: { verdict: 'pass', summary: '已修复', issues: [] } }
      : { stopReason: 'completed', output: [{ type: 'text', text: `实现第 ${round} 轮说明` }] };
    return {
      childId: `child-${round}`,
      result: Promise.resolve(result),
      dispose: async () => {},
    };
  },
};

const ctx = {
  tools: { register: (definition) => { ctx.definition = definition; return () => {}; } },
  get: (service) => (service === 'subagents' ? fakeSubagents : undefined),
};

apply(ctx);
const definition = ctx.definition;
if (!definition || definition.name !== 'pair_review') throw new Error('tool was not registered');

const exec = { agent: { id: 'session-test' }, signal: new AbortController().signal };
const value = await definition.execute({ task: '把 a.txt 写成两行', max_rounds: 2 }, exec);

// The tool's render path must work on the canonical value.
const rendered = definition.output.render({ task: 'x' }, value)[0].text;

const report = [];
report.push(`name: ${name}`);
report.push(`ok: ${value.ok}`);
report.push(`rounds: ${value.rounds.length}`);
report.push(`verdicts: ${value.rounds.map((r) => r.reviewer.verdict).join(',')}`);
report.push(`child calls: ${calls.length} (${calls.map((c) => c.label).join(' | ')})`);
report.push(`delivery: ${[...new Set(calls.map((c) => c.delivery))].join(',')}`);
report.push(`models: ${[...new Set(calls.map((c) => `${c.request.agentOptions.provider}/${c.request.agentOptions.model}`))].join(',')}`);
report.push(`rework prompt carries findings: ${calls[2].request.prompt[0].text.includes('缺少第二行')}`);
report.push(`rendered has badge: ${rendered.includes('未通过') || rendered.includes('通过')}`);
console.log(report.join('\n'));

if (value.ok !== true) throw new Error('expected ok');
if (value.rounds.length !== 2) throw new Error('expected two rounds');
if (value.rounds[0].reviewer.verdict !== 'fail' || value.rounds[1].reviewer.verdict !== 'pass') throw new Error('unexpected verdict sequence');
if (!calls.every((c) => c.delivery === 'caller')) throw new Error('expected caller delivery');
if (!calls[2].request.prompt[0].text.includes('缺少第二行')) throw new Error('review findings were not fed back');
console.log('selftest ok');
