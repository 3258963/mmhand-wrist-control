/**
 * Host half of `@local/ai-pair`.
 *
 * Registers one model-facing tool, `pair_review`, which runs an
 * implementer/reviewer loop across two *different* LLM routes inside the
 * calling Session's workspace:
 *
 *   1. an implementer child agent edits the workspace,
 *   2. a reviewer child agent (another provider/model) inspects the real files
 *      and returns a structured verdict,
 *   3. a failed verdict feeds its issues back into the next implementer round.
 *
 * The children are ordinary subagents, so they share the parent's workspace,
 * sandbox policy and tool composition. Cross-model review is expressed through
 * `request.agentOptions`; nothing here hardcodes a transport.
 */

export const name = 'ai-pair';
export const inject = ['tools'];

/** Wire tool name; also the key the Web Client dispatches its card by. */
const TOOL_NAME = 'pair_review';

/** Default routes: cheap fast implementer, stronger reviewer. */
const DEFAULT_IMPLEMENTER = 'deepseek-account/deepseek-flash';
const DEFAULT_REVIEWER = 'deepseek-account/deepseek-v4-pro';

/** Hard cap on rounds, so one call cannot run away. */
const MAX_ROUND_CAP = 4;

/** Cap on how much implementer prose is echoed back into the report. */
const SUMMARY_LIMIT = 1400;

/** One review finding, shared by the reviewer schema and the tool output. */
const ISSUE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
    file: { type: 'string' },
    detail: { type: 'string' },
  },
  required: ['severity', 'detail'],
};

/** Canonical shape of one tool result: what the model and PTC callers receive. */
const OUTPUT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ok: { type: 'boolean' },
    implementer: { type: 'string' },
    reviewer: { type: 'string' },
    rounds: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          implementer: {
            type: 'object',
            additionalProperties: false,
            properties: {
              model: { type: 'string' },
              stopReason: { type: 'string' },
              summary: { type: 'string' },
            },
            required: ['model', 'stopReason', 'summary'],
          },
          reviewer: {
            type: 'object',
            additionalProperties: false,
            properties: {
              model: { type: 'string' },
              verdict: { type: 'string', enum: ['pass', 'fail', 'error'] },
              summary: { type: 'string' },
              issues: { type: 'array', items: ISSUE_SCHEMA },
            },
            required: ['model', 'verdict', 'summary', 'issues'],
          },
        },
        required: ['implementer', 'reviewer'],
      },
    },
  },
  required: ['ok', 'implementer', 'reviewer', 'rounds'],
};

/** Structured verdict the reviewer must submit. */
const REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    summary: { type: 'string' },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          file: { type: 'string' },
          detail: { type: 'string' },
        },
        required: ['severity', 'detail'],
      },
    },
  },
  required: ['verdict', 'summary', 'issues'],
};

/**
 * Split a `provider/model` route. Model ids may themselves contain slashes, so
 * only the first separator is structural.
 * @param value - the raw route text, possibly empty.
 * @param fallback - route used when the value is absent.
 * @param field - parameter name for the error message.
 */
function parseRoute(value, fallback, field) {
  const raw = typeof value === 'string' && value.trim() !== '' ? value.trim() : fallback;
  const slash = raw.indexOf('/');
  if (slash <= 0 || slash === raw.length - 1) {
    throw new Error(`${field} 必须是 "provider/model" 形式，收到 "${raw}"`);
  }
  return { provider: raw.slice(0, slash), model: raw.slice(slash + 1) };
}

/** Join the text blocks of a settled subagent result. */
function textOf(result) {
  const blocks = Array.isArray(result?.output) ? result.output : [];
  return blocks
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim();
}

/** Clip long prose for the tool result without losing the head. */
function clip(text, limit = SUMMARY_LIMIT) {
  const value = String(text ?? '').trim();
  return value.length <= limit ? value : `${value.slice(0, limit)}\n…（已截断，原文 ${value.length} 字）`;
}

/** Render one issue line. */
function issueLine(issue) {
  const where = [issue?.file, issue?.detail].filter((part) => typeof part === 'string' && part !== '');
  const severity = typeof issue?.severity === 'string' ? issue.severity : 'major';
  return `- [${severity}] ${where.join(' — ')}`;
}

/** Best-effort verdict when the child refused or could not submit structure. */
function verdictFromText(text) {
  const match = /VERDICT\s*[:：]\s*(pass|fail)/i.exec(String(text ?? ''));
  if (match === null) return null;
  return { verdict: match[1].toLowerCase(), summary: clip(text, 400), issues: [] };
}

/** Human-readable report rendered into the conversation. */
function renderReport(report) {
  const head = report.ok
    ? `## AI 一改一审 · 通过（${report.rounds.length} 轮）`
    : `## AI 一改一审 · 未通过（${report.rounds.length} 轮）`;
  const routes = `实现 \`${report.implementer}\`　审查 \`${report.reviewer}\``;
  const body = report.rounds.map((entry, index) => {
    const impl = entry.implementer;
    const reviewer = entry.reviewer;
    const verdict = reviewer.verdict === 'pass' ? '✅ 通过' : reviewer.verdict === 'fail' ? '❌ 不通过' : '⚠️ 未能审查';
    const lines = [`### 第 ${index + 1} 轮`, ''];
    lines.push(`**实现**（${impl.model}，${impl.stopReason}）`);
    lines.push(impl.summary === '' ? '_没有交付说明_' : impl.summary);
    lines.push('');
    lines.push(`**审查**（${reviewer.model}）→ ${verdict}`);
    if (reviewer.summary !== '') lines.push(reviewer.summary);
    if (reviewer.issues.length > 0) {
      lines.push('');
      lines.push(...reviewer.issues.map(issueLine));
    }
    return lines.join('\n');
  });
  const tail = report.ok
    ? ''
    : '\n\n> 仍有未修复的审查意见；可以把它们贴回对话继续修，或调大 `max_rounds` 重跑。';
  return [head, routes, '', ...body].join('\n') + tail;
}

/**
 * Run one child agent to completion in the caller's workspace.
 * @param ctx - plugin context.
 * @param exec - tool execution (agent, signal).
 * @param options - prompt, label, model route and optional output schema.
 */
async function runChild(ctx, exec, options) {
  const subagents = ctx.get('subagents');
  if (subagents === undefined) {
    throw new Error('pair_review 需要 subagents 服务；当前 Host 作用域没有挂载它');
  }
  const providers = subagents.list();
  if (providers.length === 0) throw new Error('pair_review 没有可用的 subagent provider');
  const provider = providers.includes('spawn') ? 'spawn' : providers[0];
  const activation = await subagents.startActivation({
    provider,
    label: options.label,
    request: {
      prompt: [{ type: 'text', text: options.prompt }],
      parent: exec.agent,
      agentOptions: { provider: options.route.provider, model: options.route.model },
      ...(options.outputSchema === undefined ? {} : { outputSchema: options.outputSchema }),
    },
    signal: exec.signal,
    delivery: 'caller',
  });
  try {
    const result = await activation.result;
    return { result, text: textOf(result) };
  } finally {
    try {
      await activation.dispose();
    } catch {
      /* a settled activation may already be released; the result is what matters */
    }
  }
}

/** Build the implementer prompt for one round. */
function implementerPrompt(args, round, issues) {
  const focus = Array.isArray(args.files) && args.files.length > 0
    ? `\n重点文件：${args.files.join('、')}\n`
    : '';
  const lines = [
    '你是「实现者」。你在一个共享工作区里工作，当前目录就是工作区根目录；另一个模型作为审查者会在你之后检查同样的文件。',
    '',
    '目标：',
    String(args.task),
    focus,
    '工作方式：',
    '1. 先读相关文件，确认真实结构后再改；只做达成目标所需的最小修改。',
    '2. 改完必须自检：能运行或能静态检查的，跑一次并看结果；不能跑的说明原因。',
    '3. 结束时用中文给出交付说明（≤20 行）：逐文件说明改了什么；列出你运行过的验证及结果；列出仍然存在的风险或未完成项。',
    '4. 不要在回复里粘贴大段代码或整份文件。',
  ];
  if (round > 1) {
    lines.push(
      '',
      `注意：这是第 ${round} 轮。上一轮审查未通过，审查者（另一个模型）提出的问题如下。请先逐条确认，再修复；不要辩解、不要跳过：`,
      issues,
      '',
      '修复后重新给出完整交付说明（不是只写增量）。',
    );
  }
  return lines.filter((line) => line !== undefined).join('\n');
}

/** Build the reviewer prompt for one round. */
function reviewerPrompt(args, implementation) {
  const focus = Array.isArray(args.files) && args.files.length > 0
    ? `\n重点文件：${args.files.join('、')}\n`
    : '';
  return [
    '你是「审查者」，与实现者使用不同的模型（交叉审查）。你在同一个共享工作区里，必须亲自打开文件核对，不要只相信实现者的描述。',
    '',
    '目标：',
    String(args.task),
    focus,
    '实现者本轮的交付说明：',
    implementation === '' ? '_（实现者没有给出说明）_' : implementation,
    '',
    '审查清单：',
    '- 目标是否真的达成？有没有只改说明不改代码、或改了但没生效？',
    '- 是否引入回归、明显错误、边界条件缺失或自相矛盾？',
    '- 是否有该改而未改的调用点、引用、文档？',
    '- 数字、公式、路径等硬事实是否前后一致、可核对？',
    '',
    '规则：',
    '- 只报告有证据的问题，每条给出文件与具体位置（行号或可定位的片段）以及为什么错。',
    '- 不要提风格偏好，不要要求与目标无关的重构。',
    '- 没有实质问题时必须判 pass；不要为了显得严格而挑刺。',
    '- 最后调用结构化结果工具提交：verdict（pass/fail）、summary（一句话结论）、issues（每条 severity/file/detail）。',
  ].join('\n');
}

/** Turn structured issues (or a fallback text) into the next round's brief. */
function issuesBrief(issues) {
  if (!Array.isArray(issues) || issues.length === 0) return '_（审查者没有给出具体问题，请自行复核目标是否真的达成）_';
  return issues.map(issueLine).join('\n');
}

/**
 * The implement → review → rework loop.
 * @param ctx - plugin context.
 * @param args - validated tool arguments.
 * @param exec - tool execution.
 */
async function pairReview(ctx, args, exec) {
  if (!exec.agent) throw new Error('pair_review 需要一个调用它的 agent');
  const implementerRoute = parseRoute(args.implementer, DEFAULT_IMPLEMENTER, 'implementer');
  const reviewerRoute = parseRoute(args.reviewer, DEFAULT_REVIEWER, 'reviewer');
  if (implementerRoute.provider === reviewerRoute.provider && implementerRoute.model === reviewerRoute.model) {
    throw new Error('实现者和审查者不能是同一个模型；请换一个 reviewer（交叉审查才有意义）');
  }
  const requested = Number.isInteger(args.max_rounds) ? args.max_rounds : 2;
  const maxRounds = Math.min(Math.max(requested, 1), MAX_ROUND_CAP);

  const rounds = [];
  let issues = null;
  let ok = false;

  for (let round = 1; round <= maxRounds; round += 1) {
    exec.signal.throwIfAborted();
    const implementation = await runChild(ctx, exec, {
      label: `实现 · 第${round}轮 · ${implementerRoute.model}`,
      route: implementerRoute,
      prompt: implementerPrompt(args, round, issuesBrief(issues)),
    });

    const implEntry = {
      model: implementerRoute.model,
      stopReason: implementation.result.stopReason ?? 'unknown',
      summary: clip(implementation.text),
    };
    if (implementation.result.stopReason !== 'completed') {
      rounds.push({
        implementer: implEntry,
        reviewer: {
          model: reviewerRoute.model,
          verdict: 'error',
          summary: `实现者本轮没有正常完成（${implementation.result.stopReason}），未进入审查。`,
          issues: [],
        },
      });
      break;
    }

    const review = await runChild(ctx, exec, {
      label: `审查 · 第${round}轮 · ${reviewerRoute.model}`,
      route: reviewerRoute,
      prompt: reviewerPrompt(args, implementation.text),
      outputSchema: REVIEW_SCHEMA,
    });

    const structured = review.result.structured ?? verdictFromText(review.text);
    const reviewerEntry = {
      model: reviewerRoute.model,
      verdict: structured?.verdict === 'pass' ? 'pass' : structured?.verdict === 'fail' ? 'fail' : 'error',
      summary: clip(typeof structured?.summary === 'string' ? structured.summary : review.text, 600),
      issues: Array.isArray(structured?.issues) ? structured.issues.slice(0, 40) : [],
    };
    rounds.push({ implementer: implEntry, reviewer: reviewerEntry });

    if (reviewerEntry.verdict === 'pass') {
      ok = true;
      break;
    }
    if (reviewerEntry.verdict === 'error') break;
    issues = reviewerEntry.issues;
  }

  return {
    ok,
    implementer: `${implementerRoute.provider}/${implementerRoute.model}`,
    reviewer: `${reviewerRoute.provider}/${reviewerRoute.model}`,
    rounds,
  };
}

/** Register the model-facing tool. */
export function apply(ctx) {
  ctx.tools.register({
    name: TOOL_NAME,
    description:
      '让两个不同的 AI 在同一个工作区里「一改一审」：实现者按目标修改文件，另一个模型的审查者亲自核对文件并给出结构化结论；审查不通过时，问题会自动回灌给下一轮实现者，直到通过或用完轮数。适合需要交叉验证的代码/文档/公式修改。执行可能持续数分钟。',
    parameters: {
      task: {
        type: 'string',
        required: true,
        description: '要实现或修改的目标，写清楚验收标准；实现者和审查者都会看到它。',
      },
      files: {
        type: 'array',
        items: { type: 'string' },
        description: '重点文件（工作区相对路径），缩小双方的注意力范围。',
      },
      implementer: {
        type: 'string',
        description: `实现者模型，格式 provider/model。默认 ${DEFAULT_IMPLEMENTER}。`,
      },
      reviewer: {
        type: 'string',
        description: `审查者模型，格式 provider/model，必须与实现者不同。默认 ${DEFAULT_REVIEWER}。`,
      },
      max_rounds: {
        type: 'integer',
        description: `最多几轮「改—审」，默认 2，最多 ${MAX_ROUND_CAP}。`,
      },
    },
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => [{ type: 'text', text: renderReport(value) }],
    },
    execute: (args, exec) => pairReview(ctx, args, exec),
  });
}
