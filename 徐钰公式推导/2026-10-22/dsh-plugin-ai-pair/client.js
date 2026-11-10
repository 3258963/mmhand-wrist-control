/**
 * Client half of `@local/ai-pair`.
 *
 * Registers a keyed `tool.call.toolview` entry for the `pair_review` tool so one
 * collaboration run renders as a compact card: verdict badge, the two model
 * routes, and one section per 改—审 round with the implementer's delivery note,
 * the reviewer's conclusion and its findings.
 *
 * The card derives everything from the rendered result text, which is the only
 * per-call material this slot receives; anything it cannot recognize falls back
 * to the plain text instead of hiding the run.
 */

window.__ModuleLoader__.load({
  id: '@local/ai-pair',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const TOOL_KEY = 'pair_review';

    const TEXT = {
      zh: {
        title: 'AI 一改一审',
        running: '进行中',
        runningHint: '实现者正在改，随后由另一个模型审查…',
        pass: '通过',
        fail: '未通过',
        unknown: '已完成',
        impl: '改',
        review: '审',
        empty: '没有可显示的交付说明',
        noIssues: '没有遗留问题',
        expand: '展开完整文本',
        collapse: '收起',
        nav: 'AI 协作',
        pageTitle: 'AI 协作 · 一改一审',
        pageSubtitle: '同一个工作区里，一个模型改、另一个模型审；审不过会把问题退回重改。',
        rolesTitle: '两个角色',
        implRole: '实现者',
        implRoleHint: '读文件、改文件、跑验证，最后给出逐文件交付说明。',
        reviewRole: '审查者',
        reviewRoleHint: '换一个模型，亲自打开文件核对，只报有证据的问题。',
        flowTitle: '怎么发起',
        step1: '在对话里说：用一改一审改「文件或目标」，并写清验收标准。',
        step2: '我调用 pair_review：实现 → 审查 → 未通过就带着审查意见重改。',
        step3: '每轮结论出现在对话卡片里；默认 2 轮，调用时可加大。',
        sampleTitle: '可直接复制的指令',
        sample:
          '用一改一审实现：<写清目标与验收标准>。重点文件：<文件路径>。审查从严：数字、边界条件、调用点是否一致。',
        copy: '复制指令',
        copied: '已复制，粘到输入框发送即可',
        copyFailed: '复制失败，请手动选中文本',
        backToChat: '回到对话',
        foot: '运行记录保存在发起它的那个会话的对话卡片里；这里放入口和默认设置。',
      },
      en: {
        title: 'AI pair review',
        running: 'running',
        runningHint: 'The implementer is editing; another model reviews next…',
        pass: 'passed',
        fail: 'not passed',
        unknown: 'done',
        impl: 'edit',
        review: 'review',
        empty: 'No delivery note to show',
        noIssues: 'No open findings',
        expand: 'Show full text',
        collapse: 'Collapse',
        nav: 'AI collaboration',
        pageTitle: 'AI collaboration · one edits, one reviews',
        pageSubtitle: 'In one workspace one model edits and another model reviews; failed findings are fed back for rework.',
        rolesTitle: 'Roles',
        implRole: 'Implementer',
        implRoleHint: 'Reads, edits, runs the checks, then reports what changed per file.',
        reviewRole: 'Reviewer',
        reviewRoleHint: 'A different model opens the files itself and reports only evidence-backed problems.',
        flowTitle: 'How to start',
        step1: 'Ask in the conversation: pair-review <file or goal>, with the acceptance criteria.',
        step2: 'I call pair_review: edit → review → rework with the findings when it fails.',
        step3: 'Each round appears in the chat card; two rounds by default, more on request.',
        sampleTitle: 'Prompt you can copy',
        sample:
          'Pair-review this: <goal and acceptance criteria>. Focus files: <paths>. Review strictly for numbers, boundaries, and call sites.',
        copy: 'Copy prompt',
        copied: 'Copied — paste it into the composer',
        copyFailed: 'Copy failed; select the text manually',
        backToChat: 'Back to conversation',
        foot: 'Each run is recorded in the chat card of the session that started it; this page holds the entry point and defaults.',
      },
    };

    const CSS = [
      '.dsh-ap-card{box-sizing:border-box;display:flex;flex-direction:column;gap:10px;margin:4px 0;padding:14px 16px;border:1px solid var(--dsw-alias-border-l1);border-radius:12px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font-size:13px;line-height:1.55;}',
      '.dsh-ap-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}',
      '.dsh-ap-title{font-size:13px;font-weight:600;letter-spacing:0.01em;}',
      '.dsh-ap-badge{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:0.02em;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);}',
      '.dsh-ap-badge[data-state="pass"]{background:rgba(16,185,129,0.16);color:var(--dsw-alias-state-success-primary);}',
      '.dsh-ap-badge[data-state="fail"]{background:rgba(239,68,68,0.16);color:var(--dsw-alias-state-error-primary);}',
      '.dsh-ap-routes{margin:0;font-size:11px;color:var(--dsw-alias-label-secondary);}',
      '.dsh-ap-round{display:flex;flex-direction:column;gap:6px;padding-top:10px;border-top:1px solid var(--dsw-alias-border-l1);}',
      '.dsh-ap-round:first-child{padding-top:0;border-top:0;}',
      '.dsh-ap-roundHead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;font-weight:600;}',
      '.dsh-ap-sec{display:flex;flex-direction:column;gap:3px;}',
      '.dsh-ap-tag{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;border-radius:2px;font-size:11px;font-weight:600;letter-spacing:0.06em;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);flex:0 0 auto;}',
      '.dsh-ap-sec[data-kind="impl"] .dsh-ap-tag{background:rgba(37,99,235,0.14);color:var(--dsw-alias-brand-primary);}',
      '.dsh-ap-sec[data-kind="review"] .dsh-ap-tag{background:rgba(245,158,11,0.16);color:var(--dsw-alias-label-primary);}',
      '.dsh-ap-secHead{display:flex;align-items:center;gap:6px;}',
      '.dsh-ap-model{font-size:11px;color:var(--dsw-alias-label-secondary);font-variant-numeric:tabular-nums;}',
      '.dsh-ap-body{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-primary);}',
      '.dsh-ap-issues{margin:2px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:3px;}',
      '.dsh-ap-issue{display:flex;gap:6px;align-items:flex-start;font-size:12px;line-height:1.55;color:var(--dsw-alias-label-primary);}',
      '.dsh-ap-sev{flex:0 0 auto;padding:0 5px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);}',
      '.dsh-ap-sev[data-sev="blocker"]{background:rgba(239,68,68,0.18);color:var(--dsw-alias-state-error-primary);}',
      '.dsh-ap-sev[data-sev="major"]{background:rgba(245,158,11,0.18);color:var(--dsw-alias-label-primary);}',
      '.dsh-ap-toggle{align-self:flex-start;margin:0;padding:2px 0;border:0;background:transparent;color:var(--dsw-alias-brand-primary);font-family:inherit;font-size:11px;cursor:pointer;}',
      '.dsh-ap-toggle:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px;border-radius:4px;}',
      '.dsh-ap-clip{max-height:240px;overflow:hidden;position:relative;}',
      '.dsh-ap-raw{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary);}',
    ].join('');

    const PAGE_CSS = [
      '.dsh-ai-page{box-sizing:border-box;display:flex;flex-direction:column;gap:18px;height:100%;min-height:0;overflow-y:auto;padding:28px 32px;color:var(--dsw-alias-label-primary);font-family:inherit;font-size:14px;line-height:1.5;}',
      '.dsh-ai-head{display:flex;flex-direction:column;gap:6px;}',
      '.dsh-ai-title{margin:0;font-size:18px;font-weight:600;line-height:1.3;letter-spacing:0.01em;}',
      '.dsh-ai-sub{margin:0;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary);}',
      '.dsh-ai-group{display:flex;flex-direction:column;gap:8px;}',
      '.dsh-ai-label{margin:0;font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--dsw-alias-label-secondary);}',
      '.dsh-ai-card{box-sizing:border-box;overflow:hidden;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:12px;}',
      '.dsh-ai-row{box-sizing:border-box;display:flex;align-items:flex-start;gap:12px;padding:12px 16px;border-top:1px solid var(--dsw-alias-border-l1);}',
      '.dsh-ai-card > .dsh-ai-row:first-child{border-top:0;}',
      '.dsh-ai-role{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0;}',
      '.dsh-ai-role-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}',
      '.dsh-ai-role-name{font-size:14px;font-weight:600;}',
      '.dsh-ai-model{display:inline-flex;align-items:center;padding:0 6px;border-radius:4px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);font-size:11px;line-height:18px;font-variant-numeric:tabular-nums;}',
      '.dsh-ai-hint{font-size:12px;line-height:1.55;color:var(--dsw-alias-label-secondary);}',
      '.dsh-ai-steps{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.6;}',
      '.dsh-ai-sample{margin:0;padding:10px 12px;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);font-family:inherit;font-size:12px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere;}',
      '.dsh-ai-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}',
      '.dsh-ai-btn{box-sizing:border-box;margin:0;padding:5px 12px;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;background:transparent;color:var(--dsw-alias-label-primary);font-family:inherit;font-size:12px;line-height:1.4;cursor:pointer;}',
      '.dsh-ai-btn:hover{background:var(--dsw-alias-bg-layer-2);}',
      '.dsh-ai-btn:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px;}',
      '.dsh-ai-btn-primary{border-color:transparent;background:var(--dsw-alias-brand-primary);color:var(--dsw-alias-label-on-brand, #ffffff);}',
      '.dsh-ai-btn-primary:hover{opacity:0.92;background:var(--dsw-alias-brand-primary);}',
      '.dsh-ai-status{display:flex;align-items:center;gap:8px;margin:0;font-size:12px;line-height:1.5;color:var(--dsw-alias-label-secondary);}',
      '.dsh-ai-dot{width:6px;height:6px;border-radius:999px;flex:0 0 auto;background:var(--dsw-alias-state-success-primary);}',
      '.dsh-ai-dot[data-kind="error"]{background:var(--dsw-alias-state-error-primary);}',
      '.dsh-ai-foot{margin:auto 0 0;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary);}',
    ].join('');

    /** Joined text content of a settled tool result, or '' while it is still running. */
    function resultText(block) {
      const content = block && Array.isArray(block.content) ? block.content : [];
      return content
        .filter((part) => part && part.type === 'text' && typeof part.text === 'string')
        .map((part) => part.text)
        .join('\n')
        .trim();
    }

    /** Parse one rendered report into { state, routes, rounds }. Tolerant by design. */
    function parseReport(text) {
      const lines = String(text || '').split('\n');
      const header = lines.find((line) => line.indexOf('## ') === 0) || '';
      const state = /未通过/.test(header) ? 'fail' : /通过/.test(header) ? 'pass' : 'unknown';
      const routeLine = lines.find((line) => line.indexOf('实现 `') !== -1) || '';
      const routes = routeLine.replace(/`/g, '').replace(/　/g, ' · ').trim();

      const rounds = [];
      let current = null;
      let section = null;
      for (const line of lines) {
        const roundHead = /^### 第\s*(\d+)\s*轮\s*$/.exec(line);
        if (roundHead) {
          current = { index: roundHead[1], implementer: { model: '', verdict: '', lines: [] }, reviewer: { model: '', verdict: '', lines: [], issues: [] } };
          rounds.push(current);
          section = null;
          continue;
        }
        if (current === null) continue;

        const implHead = /^\*\*实现\*\*（([^,，）]+)[,，]?\s*([^）]*)）\s*$/.exec(line);
        if (implHead) {
          current.implementer.model = implHead[1].trim();
          section = 'impl';
          continue;
        }
        const reviewHead = /^\*\*审查\*\*（([^）]+)）\s*→\s*(.+)$/.exec(line);
        if (reviewHead) {
          current.reviewer.model = reviewHead[1].trim();
          const verdict = reviewHead[2];
          current.reviewer.verdict = /不通过/.test(verdict) ? 'fail' : /通过/.test(verdict) ? 'pass' : 'unknown';
          section = 'review';
          continue;
        }
        if (line.indexOf('> ') === 0) continue;
        if (section === 'impl') current.implementer.lines.push(line);
        else if (section === 'review') {
          const issue = /^-\s*\[([^\]]+)\]\s*(.*)$/.exec(line);
          if (issue) current.reviewer.issues.push({ severity: issue[1].trim(), text: issue[2].trim() });
          else current.reviewer.lines.push(line);
        }
      }

      return {
        state,
        routes,
        rounds: rounds.map((round) => ({
          index: round.index,
          implementer: {
            model: round.implementer.model,
            text: round.implementer.lines.join('\n').replace(/^_+|_+$/g, '').trim(),
          },
          reviewer: {
            model: round.reviewer.model,
            verdict: round.reviewer.verdict,
            text: round.reviewer.lines.join('\n').replace(/^_+|_+$/g, '').trim(),
            issues: round.reviewer.issues,
          },
        })),
      };
    }

    /** Active UI language: locale service, then the <html lang> the shell keeps in sync. */
    function languageTagOf(ctx) {
      try {
        const locale = ctx.get('locale');
        const snapshot = typeof locale.getSnapshot === 'function' ? locale.getSnapshot() : undefined;
        let active = snapshot && typeof snapshot.active === 'string' ? snapshot.active : '';
        if (!active && locale && typeof locale.getLocale === 'function') {
          const current = locale.getLocale();
          if (current && typeof current.active === 'string') active = current.active;
        }
        if (!active && typeof document !== 'undefined' && document.documentElement) {
          active = document.documentElement.lang || '';
        }
        if (!active && typeof navigator !== 'undefined' && typeof navigator.language === 'string') {
          active = navigator.language;
        }
        return active.toLowerCase();
      } catch (error) {
        return '';
      }
    }

    /** The plugin ships zh + en: an English tag selects en, everything else reads zh. */
    function languageOf(ctx) {
      return languageTagOf(ctx).indexOf('en') === 0 ? 'en' : 'zh';
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        /** Dynamic dictionary: every property read resolves the language at that moment. */
        const t = new Proxy(
          {},
          {
            get(target, key) {
              if (typeof key !== 'string') return undefined;
              const dictionary = TEXT[languageOf(ctx)] || TEXT.en;
              return dictionary[key];
            },
          },
        );

        /** Follow language switches: ride the locale service when it appears, else watch <html lang>. */
        function watchLanguage(setLanguage) {
          let stop;
          let timer;
          let observer;
          const attach = () => {
            const locale = ctx.get('locale');
            if (!locale || typeof locale.subscribe !== 'function') return false;
            stop = locale.subscribe(() => setLanguage(languageOf(ctx)));
            setLanguage(languageOf(ctx));
            return true;
          };
          if (!attach()) {
            let tries = 0;
            timer = window.setInterval(() => {
              tries += 1;
              if (attach() || tries >= 10) {
                window.clearInterval(timer);
                timer = undefined;
              }
            }, 200);
            if (
              typeof MutationObserver === 'function' &&
              typeof document !== 'undefined' &&
              document.documentElement
            ) {
              observer = new MutationObserver(() => setLanguage(languageOf(ctx)));
              observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
            }
          }
          return () => {
            if (timer !== undefined) window.clearInterval(timer);
            if (observer) observer.disconnect();
            if (typeof stop === 'function') stop();
          };
        }

        /** Snapshot of the panel dictionary for the active language. */
        function copy() {
          return TEXT[languageOf(ctx)] || TEXT.en;
        }

        /** Live dictionary; re-renders when the user switches language. */
        function useCopy() {
          const [language, setLanguage] = React.useState(() => languageOf(ctx));
          React.useEffect(() => watchLanguage(setLanguage), []);
          return TEXT[language] || TEXT.en;
        }

        /** The sidebar button artwork: a page being edited plus a passed check. */
        function PanelIcon(props) {
          const size = typeof props.size === 'number' && props.size > 0 ? props.size : 20;
          return h(
            'svg',
            {
              viewBox: '0 0 24 24',
              width: size,
              height: size,
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: 1.7,
              strokeLinecap: 'round',
              strokeLinejoin: 'round',
              'aria-hidden': true,
              focusable: false,
              style: { display: 'block' },
            },
            h('rect', { x: 3, y: 4.5, width: 10, height: 13, rx: 2.2 }),
            h('path', { d: 'M6 8.5h4M6 11h3' }),
            h('path', { d: 'M13.8 15.8l2.4 2.4 4.6-5' }),
          );
        }

        /** One role row: name, current default model, and what that role does. */
        function RoleRow(props) {
          return h(
            'div',
            { className: 'dsh-ai-row' },
            h(
              'div',
              { className: 'dsh-ai-role' },
              h(
                'div',
                { className: 'dsh-ai-role-head' },
                h('span', { className: 'dsh-ai-role-name' }, props.name),
                h('span', { className: 'dsh-ai-model' }, props.model),
              ),
              h('span', { className: 'dsh-ai-hint' }, props.hint),
            ),
          );
        }

        /** The sidebar page: roles, how to start, and a copyable prompt. */
        function Panel() {
          const text = useCopy();
          const [status, setStatus] = React.useState(null);

          React.useEffect(() => {
            if (!status) return undefined;
            const timer = window.setTimeout(() => setStatus(null), 2600);
            return () => window.clearTimeout(timer);
          }, [status]);

          const copyPrompt = () => {
            const sample = text.sample;
            try {
              if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                navigator.clipboard.writeText(sample).then(
                  () => setStatus({ kind: 'ok', text: text.copied }),
                  () => setStatus({ kind: 'error', text: text.copyFailed }),
                );
                return;
              }
            } catch (error) {
              /* fall through to the manual hint */
            }
            setStatus({ kind: 'error', text: text.copyFailed });
          };

          const backToChat = () => {
            const layout = ctx.get('layout');
            if (layout && typeof layout.selectPanel === 'function') layout.selectPanel(null);
          };

          return h(
            'div',
            { className: 'dsh-ai-page' },
            h('style', { key: 'styles' }, PAGE_CSS),
            h(
              'header',
              { className: 'dsh-ai-head' },
              h('h1', { className: 'dsh-ai-title' }, text.pageTitle),
              h('p', { className: 'dsh-ai-sub' }, text.pageSubtitle),
            ),
            h(
              'section',
              { className: 'dsh-ai-group' },
              h('h2', { className: 'dsh-ai-label' }, text.rolesTitle),
              h(
                'div',
                { className: 'dsh-ai-card' },
                h(RoleRow, {
                  name: text.implRole,
                  model: 'deepseek-account/deepseek-flash',
                  hint: text.implRoleHint,
                }),
                h(RoleRow, {
                  name: text.reviewRole,
                  model: 'deepseek-account/deepseek-v4-pro',
                  hint: text.reviewRoleHint,
                }),
              ),
            ),
            h(
              'section',
              { className: 'dsh-ai-group' },
              h('h2', { className: 'dsh-ai-label' }, text.flowTitle),
              h(
                'ol',
                { className: 'dsh-ai-steps' },
                [text.step1, text.step2, text.step3].map((step, index) => h('li', { key: index }, step)),
              ),
            ),
            h(
              'section',
              { className: 'dsh-ai-group' },
              h('h2', { className: 'dsh-ai-label' }, text.sampleTitle),
              h('pre', { className: 'dsh-ai-sample' }, text.sample),
              h(
                'div',
                { className: 'dsh-ai-actions' },
                h(
                  'button',
                  { type: 'button', className: 'dsh-ai-btn dsh-ai-btn-primary', onClick: copyPrompt },
                  text.copy,
                ),
                h('button', { type: 'button', className: 'dsh-ai-btn', onClick: backToChat }, text.backToChat),
              ),
            ),
            status
              ? h(
                  'p',
                  { className: 'dsh-ai-status', role: 'status', 'aria-live': 'polite' },
                  h('span', { className: 'dsh-ai-dot', 'data-kind': status.kind }),
                  h('span', null, status.text),
                )
              : null,
            h('p', { className: 'dsh-ai-foot' }, text.foot),
          );
        }

        function RoundSection(props) {
          const kind = props.kind;
          const label = kind === 'impl' ? t.impl : t.review;
          const model = props.model;
          const verdict = props.verdict;
          return h(
            'div',
            { className: 'dsh-ap-sec', 'data-kind': kind },
            h(
              'div',
              { className: 'dsh-ap-secHead' },
              h('span', { className: 'dsh-ap-tag' }, label),
              model ? h('span', { className: 'dsh-ap-model' }, model) : null,
              kind === 'review' && verdict
                ? h(
                    'span',
                    {
                      className: 'dsh-ap-badge',
                      'data-state': verdict === 'pass' ? 'pass' : verdict === 'fail' ? 'fail' : 'unknown',
                    },
                    verdict === 'pass' ? t.pass : verdict === 'fail' ? t.fail : t.unknown,
                  )
                : null,
            ),
            h('p', { className: 'dsh-ap-body' }, props.text === '' ? t.empty : props.text),
            props.issues && props.issues.length > 0
              ? h(
                  'ul',
                  { className: 'dsh-ap-issues' },
                  props.issues.map((issue, index) =>
                    h(
                      'li',
                      { className: 'dsh-ap-issue', key: index },
                      h('span', { className: 'dsh-ap-sev', 'data-sev': issue.severity }, issue.severity),
                      h('span', null, issue.text),
                    ),
                  ),
                )
              : null,
          );
        }

        function Card(props) {
          const [expanded, setExpanded] = React.useState(false);
          const text = resultText(props.block);
          const running = text === '';
          const report = React.useMemo(() => parseReport(text), [text]);
          const state = running ? 'running' : report.state;
          const badge = running
            ? t.running
            : state === 'pass'
              ? t.pass
              : state === 'fail'
                ? t.fail
                : t.unknown;

          return h(
            'div',
            { className: 'dsh-ap-card' },
            h('style', { key: 'css' }, CSS),
            h(
              'div',
              { className: 'dsh-ap-head' },
              h('span', { className: 'dsh-ap-title' }, t.title),
              h('span', { className: 'dsh-ap-badge', 'data-state': state }, badge),
            ),
            report.routes !== '' ? h('p', { className: 'dsh-ap-routes' }, report.routes) : null,
            running
              ? h('p', { className: 'dsh-ap-body' }, t.runningHint)
              : report.rounds.length === 0
                ? h(
                    'div',
                    null,
                    h('div', { className: expanded ? null : 'dsh-ap-clip' }, h('pre', { className: 'dsh-ap-raw' }, text)),
                    h(
                      'button',
                      { type: 'button', className: 'dsh-ap-toggle', onClick: () => setExpanded(!expanded) },
                      expanded ? t.collapse : t.expand,
                    ),
                  )
                : report.rounds.map((round) =>
                    h(
                      'div',
                      { className: 'dsh-ap-round', key: round.index },
                      h(
                        'div',
                        { className: 'dsh-ap-roundHead' },
                        h('span', null, `#${round.index}`),
                      ),
                      h(RoundSection, {
                        kind: 'impl',
                        model: round.implementer.model,
                        text: round.implementer.text,
                      }),
                      h(RoundSection, {
                        kind: 'review',
                        model: round.reviewer.model,
                        verdict: round.reviewer.verdict,
                        text: round.reviewer.text,
                        issues: round.reviewer.issues,
                      }),
                    ),
                  ),
          );
        }

        ctx.slots.inject('tool.call.toolview', () =>
          ctx.slots.register({ name: 'tool.call.toolview', key: TOOL_KEY }, Card),
        );

        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            { name: 'sidebar.panellist', id: 'ai-pair', order: 40, label: () => copy().nav },
            PanelIcon,
          ),
        );

        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'ai-pair' }, Panel));
      },
    };
  },
});
