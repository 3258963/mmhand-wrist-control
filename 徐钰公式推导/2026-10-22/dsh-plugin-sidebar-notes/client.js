window.__ModuleLoader__.load({
  id: '@local/sidebar-notes',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const PANEL_KEY = 'sidebar-notes';
    const STORAGE_KEY = 'dsh.sidebar-notes.text.v1';

    const TEXT = {
      en: {
        nav: 'Notes',
        title: 'Notes',
        subtitle: 'Autosaved in this browser — nothing is uploaded.',
        placeholder: 'Jot down a thought, a formula, or a reminder…',
        saved: 'Saved',
        saving: 'Saving…',
        empty: 'Empty',
        clear: 'Clear',
        undo: 'Undo',
        chars: (count) => count + (count === 1 ? ' character' : ' characters'),
      },
      zh: {
        nav: '便签',
        title: '便签',
        subtitle: '自动保存在本机浏览器，不会上传。',
        placeholder: '随手记下想法、公式或待办…',
        saved: '已保存',
        saving: '保存中…',
        empty: '空',
        clear: '清空',
        undo: '撤销',
        chars: (count) => count + ' 个字符',
      },
    };

    function readStored() {
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        return typeof stored === 'string' ? stored : '';
      } catch (error) {
        return '';
      }
    }

    function writeStored(value) {
      try {
        window.localStorage.setItem(STORAGE_KEY, value);
      } catch (error) {
        /* Private mode or a full quota: the panel keeps working in memory. */
      }
    }

    const S = {
      page: {
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        height: '100%',
        minHeight: 0,
        padding: '28px 32px 24px',
        color: 'var(--dsw-alias-label-primary)',
        fontFamily: 'inherit',
      },
      header: { display: 'flex', flexDirection: 'column', gap: '6px' },
      title: {
        margin: 0,
        fontSize: '18px',
        fontWeight: 600,
        lineHeight: 1.3,
        letterSpacing: '0.01em',
      },
      subtitle: {
        margin: 0,
        fontSize: '12px',
        lineHeight: 1.6,
        color: 'var(--dsw-alias-label-secondary)',
      },
      card: {
        boxSizing: 'border-box',
        flex: '1 1 auto',
        display: 'flex',
        flexDirection: 'column',
        minHeight: '240px',
        overflow: 'hidden',
        background: 'var(--dsw-alias-bg-layer-1)',
        border: '1px solid var(--dsw-alias-border-l1)',
        borderRadius: '12px',
        transition: 'box-shadow 120ms ease',
      },
      cardFocused: { boxShadow: '0 0 0 2px var(--dsw-alias-brand-primary)' },
      input: {
        boxSizing: 'border-box',
        flex: '1 1 auto',
        width: '100%',
        minHeight: '180px',
        margin: 0,
        padding: '16px 18px',
        border: 'none',
        outline: 'none',
        background: 'transparent',
        color: 'inherit',
        fontFamily: 'inherit',
        fontSize: '14px',
        lineHeight: 1.7,
        resize: 'none',
      },
      footer: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '10px 16px',
        borderTop: '1px solid var(--dsw-alias-border-l1)',
      },
      meta: {
        fontSize: '12px',
        color: 'var(--dsw-alias-label-secondary)',
        fontVariantNumeric: 'tabular-nums',
      },
      actions: { display: 'flex', alignItems: 'center', gap: '8px' },
      status: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '12px',
        color: 'var(--dsw-alias-label-secondary)',
      },
      dot: { width: '6px', height: '6px', borderRadius: '999px', display: 'inline-block' },
    };

    return {
      inject: ['slots'],
      apply(ctx) {
        const locale = ctx.get('locale');

        /** The active UI language, derived from the locale service snapshot. */
        function activeLanguage() {
          try {
            if (!locale) return 'en';
            const snapshot =
              typeof locale.getSnapshot === 'function' ? locale.getSnapshot() : undefined;
            let active = snapshot && typeof snapshot.active === 'string' ? snapshot.active : '';
            if (!active && typeof locale.getLocale === 'function') {
              const current = locale.getLocale();
              if (current && typeof current.active === 'string') active = current.active;
            }
            return active.toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
          } catch (error) {
            return 'en';
          }
        }

        function copy() {
          return TEXT[activeLanguage()];
        }

        function useCopy() {
          const [language, setLanguage] = React.useState(activeLanguage);
          React.useEffect(() => {
            if (!locale || typeof locale.subscribe !== 'function') return undefined;
            return locale.subscribe(() => setLanguage(activeLanguage()));
          }, []);
          return TEXT[language];
        }

        function TextButton(props) {
          const [hover, setHover] = React.useState(false);
          return h(
            'button',
            {
              type: 'button',
              onClick: props.onClick,
              onMouseEnter: () => setHover(true),
              onMouseLeave: () => setHover(false),
              style: {
                appearance: 'none',
                border: '1px solid var(--dsw-alias-border-l1)',
                background: hover ? 'var(--dsw-alias-bg-layer-2)' : 'transparent',
                color: 'var(--dsw-alias-label-secondary)',
                borderRadius: '6px',
                padding: '4px 10px',
                fontFamily: 'inherit',
                fontSize: '12px',
                lineHeight: 1.4,
                cursor: 'pointer',
              },
            },
            props.children,
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
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: 1.6,
              strokeLinecap: 'round',
              strokeLinejoin: 'round',
              'aria-hidden': true,
              focusable: false,
              style: { display: 'block' },
            },
            h('rect', { x: 4, y: 3, width: 16, height: 18, rx: 2.5 }),
            h('path', { d: 'M8 8h8' }),
            h('path', { d: 'M8 12h8' }),
            h('path', { d: 'M8 16h5' }),
          );
        }

        function Panel() {
          const text = useCopy();
          const [value, setValue] = React.useState(readStored);
          const [status, setStatus] = React.useState('saved');
          const [restore, setRestore] = React.useState(null);
          const [focused, setFocused] = React.useState(false);

          React.useEffect(() => {
            if (status !== 'saving') return undefined;
            const timer = window.setTimeout(() => {
              writeStored(value);
              setStatus('saved');
            }, 400);
            return () => window.clearTimeout(timer);
          }, [value, status]);

          const change = (event) => {
            setValue(event.target.value);
            setRestore(null);
            setStatus('saving');
          };

          const clear = () => {
            const previous = value;
            writeStored('');
            setValue('');
            setRestore(previous);
            setStatus('saved');
          };

          const undo = () => {
            if (restore === null) return;
            setValue(restore);
            setRestore(null);
            setStatus('saving');
          };

          const savedColor =
            status === 'saved'
              ? 'var(--dsw-alias-state-success-primary)'
              : 'var(--dsw-alias-state-idle-primary)';

          return h(
            'div',
            { style: S.page },
            h(
              'style',
              { key: 'placeholder-style' },
              '.dsh-sidebar-notes-input::placeholder{color:var(--dsw-alias-label-secondary);opacity:0.85;}',
            ),
            h(
              'header',
              { style: S.header },
              h('h1', { style: S.title }, text.title),
              h('p', { style: S.subtitle }, text.subtitle),
            ),
            h(
              'section',
              { style: Object.assign({}, S.card, focused ? S.cardFocused : null) },
              h('textarea', {
                className: 'dsh-sidebar-notes-input',
                style: S.input,
                value: value,
                placeholder: text.placeholder,
                spellCheck: false,
                onFocus: () => setFocused(true),
                onBlur: () => setFocused(false),
                onChange: change,
              }),
              h(
                'footer',
                { style: S.footer },
                h('span', { style: S.meta }, value.length > 0 ? text.chars(value.length) : text.empty),
                h(
                  'div',
                  { style: S.actions },
                  h(
                    'span',
                    { style: S.status },
                    h('span', { style: Object.assign({}, S.dot, { background: savedColor }) }),
                    status === 'saved' ? text.saved : text.saving,
                  ),
                  restore === null
                    ? null
                    : h(TextButton, { key: 'undo', onClick: undo }, text.undo),
                  value.length === 0 && restore === null
                    ? null
                    : h(TextButton, { key: 'clear', onClick: clear }, text.clear),
                ),
              ),
            ),
          );
        }

        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            {
              name: 'sidebar.panellist',
              id: PANEL_KEY,
              order: 20,
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
