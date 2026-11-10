window.__ModuleLoader__.load({
  id: '@local/quick-actions',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const PANEL_KEY = 'quick-actions';
    const GROUPS = ['session', 'interface'];
    const ACTIONS = [
      { id: 'newSession', group: 'session' },
      { id: 'backToConversation', group: 'session' },
      { id: 'toggleSidebar', group: 'interface' },
      { id: 'openPlugins', group: 'interface' },
    ];

    const TEXT = {
      en: {
        nav: 'Quick actions',
        title: 'Quick actions',
        subtitle: 'The few Harness actions you reach for most often, in one place.',
        groups: { session: 'Session', interface: 'Interface' },
        items: {
          newSession: {
            title: 'New conversation',
            hint: 'Open the blank draft of the current workspace.',
          },
          backToConversation: {
            title: 'Back to conversation',
            hint: 'Show the conversation of the current session again.',
          },
          toggleSidebar: {
            title: 'Collapse or expand the sidebar',
            hint: 'Toggle the left column of this window.',
          },
          openPlugins: {
            title: 'Manage plugins',
            hint: 'Open the Plugins page.',
          },
        },
        ran: (title) => 'Ran “' + title + '”',
        unavailable: 'That action is not available in this build.',
        failed: 'That action could not run: ',
        foot: 'These buttons only change what this window shows. Nothing is sent to the model.',
      },
      zh: {
        nav: '快捷操作',
        title: '快捷操作',
        subtitle: '把最常用的几个操作集中到一处。',
        groups: { session: '会话', interface: '界面' },
        items: {
          newSession: { title: '新建对话', hint: '打开当前工作区的空白草稿。' },
          backToConversation: { title: '回到对话', hint: '重新显示当前会话的对话内容。' },
          toggleSidebar: { title: '收起 / 展开侧栏', hint: '切换左侧栏的显示状态。' },
          openPlugins: { title: '管理插件', hint: '打开“插件”设置页。' },
        },
        ran: (title) => '已执行“' + title + '”',
        unavailable: '当前版本没有这个操作。',
        failed: '操作未能执行：',
        foot: '这些按钮只改变本窗口的显示，不会向模型发送任何内容。',
      },
    };

    const GLYPH_PATHS = {
      newSession: ['M12 5v14', 'M5 12h14'],
      backToConversation: ['M19 12H5', 'M11 6l-6 6 6 6'],
      toggleSidebar: ['M4.5 5.5h15v13h-15z', 'M10 5.5v13'],
      openPlugins: [
        'M4.5 4.5h6v6h-6z',
        'M13.5 4.5h6v6h-6z',
        'M4.5 13.5h6v6h-6z',
        'M13.5 13.5h6v6h-6z',
      ],
    };

    const PANEL_CSS = [
      '.dsh-qa-page{box-sizing:border-box;display:flex;flex-direction:column;gap:20px;height:100%;min-height:0;overflow-y:auto;padding:28px 32px 28px;color:var(--dsw-alias-label-primary);font-family:inherit;font-size:14px;line-height:1.5;}',
      '.dsh-qa-header{display:flex;flex-direction:column;gap:6px;}',
      '.dsh-qa-title{margin:0;font-size:18px;font-weight:600;line-height:1.3;letter-spacing:0.01em;}',
      '.dsh-qa-subtitle{margin:0;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary);}',
      '.dsh-qa-status{display:flex;align-items:center;gap:8px;min-height:18px;margin:0;font-size:12px;line-height:1.5;color:var(--dsw-alias-label-secondary);}',
      '.dsh-qa-dot{width:6px;height:6px;border-radius:999px;flex:0 0 auto;background:var(--dsw-alias-state-success-primary);}',
      '.dsh-qa-dot-error{background:var(--dsw-alias-state-error-primary);}',
      '.dsh-qa-group{display:flex;flex-direction:column;gap:8px;}',
      '.dsh-qa-group-label{margin:0;font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--dsw-alias-label-secondary);}',
      '.dsh-qa-card{box-sizing:border-box;overflow:hidden;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:12px;}',
      '.dsh-qa-row{box-sizing:border-box;display:flex;align-items:center;gap:12px;width:100%;margin:0;padding:11px 16px;border:0;background:transparent;color:inherit;font-family:inherit;font-size:14px;text-align:left;cursor:pointer;transition:background 120ms ease;}',
      '.dsh-qa-card > .dsh-qa-row{border-top:1px solid var(--dsw-alias-border-l1);}',
      '.dsh-qa-card > .dsh-qa-row:first-child{border-top:0;}',
      '.dsh-qa-row:hover{background:var(--dsw-alias-bg-layer-2);}',
      '.dsh-qa-row:active{background:var(--dsw-alias-bg-layer-2);}',
      '.dsh-qa-row:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px;}',
      '.dsh-qa-glyph{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;width:28px;height:28px;border-radius:8px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);}',
      '.dsh-qa-row:hover .dsh-qa-glyph{color:var(--dsw-alias-brand-primary);}',
      '.dsh-qa-text{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0;}',
      '.dsh-qa-row-title{font-size:14px;font-weight:500;}',
      '.dsh-qa-row-hint{font-size:12px;line-height:1.5;color:var(--dsw-alias-label-secondary);}',
      '.dsh-qa-chevron{flex:0 0 auto;color:var(--dsw-alias-label-secondary);opacity:0.75;}',
      '.dsh-qa-foot{margin:auto 0 0;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-secondary);}',
    ].join('');

    /** One small line-art glyph per action, drawn in the current text color. */
    function Glyph(props) {
      const paths = GLYPH_PATHS[props.id] || GLYPH_PATHS.openPlugins;
      return h(
        'svg',
        {
          viewBox: '0 0 24 24',
          width: 16,
          height: 16,
          fill: 'none',
          stroke: 'currentColor',
          strokeWidth: 1.7,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          'aria-hidden': true,
          focusable: false,
          style: { display: 'block' },
        },
        paths.map((d, index) => h('path', { key: index, d: d })),
      );
    }

    /** The sidebar button artwork; the sidebar supplies the square edge and active state. */
    function PanelIcon(props) {
      const size = typeof props.size === 'number' && props.size > 0 ? props.size : 20;
      return h(
        'svg',
        {
          viewBox: '0 0 24 24',
          width: size,
          height: size,
          'aria-hidden': true,
          focusable: false,
          style: { display: 'block' },
        },
        h('path', {
          d: 'M13 2 3 14h9l-1 8 10-12h-9l1-8z',
          fill: 'currentColor',
          stroke: 'currentColor',
          strokeWidth: 1,
          strokeLinejoin: 'round',
        }),
      );
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        /** The locale client service; it can mount after this plugin, so never cache it. */
        function localeService() {
          try {
            return ctx.get('locale');
          } catch (error) {
            return undefined;
          }
        }

        /** Active language tag: locale service first, then the <html lang> the shell keeps in sync. */
        function languageTag() {
          try {
            const locale = localeService();
            const snapshot =
              locale && typeof locale.getSnapshot === 'function' ? locale.getSnapshot() : undefined;
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
        function activeLanguage() {
          return languageTag().indexOf('en') === 0 ? 'en' : 'zh';
        }

        /** Follow language switches: ride the locale service when it appears, else watch <html lang>. */
        function watchLanguage(setLanguage) {
          let stop;
          let timer;
          let observer;
          const attach = () => {
            const locale = localeService();
            if (!locale || typeof locale.subscribe !== 'function') return false;
            stop = locale.subscribe(() => setLanguage(activeLanguage()));
            setLanguage(activeLanguage());
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
              observer = new MutationObserver(() => setLanguage(activeLanguage()));
              observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
            }
          }
          return () => {
            if (timer !== undefined) window.clearInterval(timer);
            if (observer) observer.disconnect();
            if (typeof stop === 'function') stop();
          };
        }

        function copy() {
          return TEXT[activeLanguage()];
        }

        function useCopy() {
          const [language, setLanguage] = React.useState(activeLanguage);
          React.useEffect(() => watchLanguage(setLanguage), []);
          return TEXT[language];
        }

        /** Runs one action through the Client services; 'unavailable' when this build lacks one. */
        function run(id) {
          if (id === 'newSession') {
            const uiWorkspace = ctx.get('uiWorkspace');
            if (!uiWorkspace || typeof uiWorkspace.startSession !== 'function') return 'unavailable';
            uiWorkspace.startSession();
            return 'ok';
          }
          const layout = ctx.get('layout');
          if (!layout) return 'unavailable';
          if (id === 'backToConversation') {
            layout.selectPanel(null);
            return 'ok';
          }
          if (id === 'toggleSidebar') {
            layout.toggleSidebar();
            return 'ok';
          }
          if (id === 'openPlugins') {
            layout.selectPanel('plugins');
            return 'ok';
          }
          return 'unavailable';
        }

        function Row(props) {
          const item = props.item;
          const itemText = props.text.items[item.id];
          return h(
            'button',
            {
              type: 'button',
              className: 'dsh-qa-row',
              title: itemText.title,
              onClick: () => props.onRun(item.id),
            },
            h('span', { className: 'dsh-qa-glyph' }, h(Glyph, { id: item.id })),
            h(
              'span',
              { className: 'dsh-qa-text' },
              h('span', { className: 'dsh-qa-row-title' }, itemText.title),
              h('span', { className: 'dsh-qa-row-hint' }, itemText.hint),
            ),
            h(
              'svg',
              {
                className: 'dsh-qa-chevron',
                viewBox: '0 0 24 24',
                width: 14,
                height: 14,
                fill: 'none',
                stroke: 'currentColor',
                strokeWidth: 1.7,
                strokeLinecap: 'round',
                strokeLinejoin: 'round',
                'aria-hidden': true,
                focusable: false,
                style: { display: 'block' },
              },
              h('path', { d: 'M9 5l7 7-7 7' }),
            ),
          );
        }

        function Panel() {
          const text = useCopy();
          const [status, setStatus] = React.useState(null);

          React.useEffect(() => {
            if (!status) return undefined;
            const timer = window.setTimeout(() => setStatus(null), 2600);
            return () => window.clearTimeout(timer);
          }, [status]);

          const runAction = (id) => {
            const itemText = text.items[id];
            const title = itemText ? itemText.title : id;
            try {
              const outcome = run(id);
              if (outcome === 'ok') setStatus({ kind: 'ok', text: text.ran(title) });
              else setStatus({ kind: 'error', text: text.unavailable });
            } catch (error) {
              const message = error && error.message ? String(error.message) : '';
              setStatus({
                kind: 'error',
                text: message.length > 0 ? text.failed + message : text.failed,
              });
            }
          };

          return h(
            'div',
            { className: 'dsh-qa-page' },
            h('style', { key: 'styles' }, PANEL_CSS),
            h(
              'header',
              { className: 'dsh-qa-header' },
              h('h1', { className: 'dsh-qa-title' }, text.title),
              h('p', { className: 'dsh-qa-subtitle' }, text.subtitle),
            ),
            h(
              'div',
              { className: 'dsh-qa-status', role: 'status', 'aria-live': 'polite' },
              status
                ? h(
                    'span',
                    { key: 'status', style: { display: 'inline-flex', alignItems: 'center', gap: '8px' } },
                    h('span', {
                      className:
                        'dsh-qa-dot' + (status.kind === 'error' ? ' dsh-qa-dot-error' : ''),
                    }),
                    h('span', null, status.text),
                  )
                : h('span', { key: 'idle' }, '\u00A0'),
            ),
            GROUPS.map((group) =>
              h(
                'section',
                { key: group, className: 'dsh-qa-group' },
                h('h2', { className: 'dsh-qa-group-label' }, text.groups[group]),
                h(
                  'div',
                  { className: 'dsh-qa-card' },
                  ACTIONS.filter((item) => item.group === group).map((item) =>
                    h(Row, { key: item.id, item: item, text: text, onRun: runAction }),
                  ),
                ),
              ),
            ),
            h('p', { className: 'dsh-qa-foot' }, text.foot),
          );
        }

        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            {
              name: 'sidebar.panellist',
              id: PANEL_KEY,
              order: 30,
              label: () => copy().nav,
            },
            PanelIcon,
          ),
        );

        ctx.slots.inject('main', () =>
          ctx.slots.register({ name: 'main', key: PANEL_KEY }, Panel),
        );
      },
    };
  },
});
