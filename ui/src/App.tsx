import {useEffect, useRef, useState, type FormEvent, type MouseEvent} from 'react';
import {A2uiSurface, MarkdownContext} from '@a2ui/react';
import {useNavigator, type ChatItem} from './a2ui/useNavigator';
import {renderMarkdown, toHtml} from './a2ui/markdown';

function Surface({s}: {s?: Parameters<typeof A2uiSurface>[0]['surface']}) {
  return s ? <A2uiSurface surface={s} /> : <div className="nv-skeleton" aria-hidden="true" />;
}

function ChatLine({m, onChip}: {m: ChatItem; onChip: (id: string) => void}) {
  const click = (e: MouseEvent<HTMLDivElement>) => {
    const id = (e.target as HTMLElement).closest<HTMLElement>('[data-record]')?.dataset.record;
    if (id) onChip(id);
  };
  if (m.role === 'user') return <div className="nv-msg nv-msg-user">{m.text}</div>;
  if (m.role === 'status')
    return (
      <div className="nv-trace">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <span>{m.text}</span>
      </div>
    );
  return (
    <div className={`nv-msg nv-msg-agent${m.streaming ? ' is-streaming' : ''}`} onClick={click} dangerouslySetInnerHTML={{__html: toHtml(m.text, {chips: true})}} />
  );
}

export default function App() {
  const nav = useNavigator();
  const [draft, setDraft] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React rejects as a cleanup.
    endRef.current?.scrollIntoView({block: 'end'});
  }, [nav.chat]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && nav.setOverlay('none');
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [nav]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (nav.busy) return;
    nav.ask(draft);
    setDraft('');
  };

  const s = nav.surfaces;
  return (
    <MarkdownContext.Provider value={renderMarkdown}>
      <div className="nv-app">
        <header className="nv-topbar">
          <div className="nv-brand">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 11l9-7 9 7" />
              <path d="M5 10v10h14V10" />
              <path d="M10 20v-6h4v6" />
            </svg>
            <span>Stabilization Navigator</span>
          </div>
          <span className="nv-pill">San Francisco · CA · FIPS 06</span>
          {nav.mode === 'mock' ? <span className="nv-pill nv-pill-warn" title="A4I_AGENT_MODE=mock">Demo replay · not live BigQuery</span> : null}
          <span className="nv-spacer" />
          <span className={`nv-conn nv-conn-${nav.connection}`}>{nav.connection === 'open' ? 'Connected' : nav.connection === 'connecting' ? 'Connecting…' : 'Reconnecting…'}</span>
          <span className="nv-muted-on-dark">Intake desk · Paralegal</span>
        </header>

        <div className="nv-layout">
          <nav className="nv-panel nv-queue" aria-label="Intake queue">
            <Surface s={s['intake_queue']} />
          </nav>

          <main className="nv-main">
            <section className="nv-panel nv-pad" aria-label="Case header">
              <Surface s={s['case_header']} />
            </section>

            <section className="nv-panel nv-chat" aria-label="Conversation with the navigator">
              <div className="nv-chat-head">
                <h2>Conversation</h2>
                <span className="nv-small nv-muted">{nav.caseId} · Agent: ADK + Gemini · BigQuery vector search</span>
              </div>
              <div className="nv-chat-body" aria-live="polite">
                {nav.chat.length === 0 ? (
                  <p className="nv-muted nv-small">Ask about this case. The navigator searches 311 records, statutes and funds, and every record it cites opens in the panel on the right.</p>
                ) : null}
                {nav.chat.map(m => (
                  <ChatLine key={m.id} m={m} onChip={nav.focusRecord} />
                ))}
                {nav.busy ? <div className="nv-typing">Navigator is working…</div> : null}
                <div ref={endRef} />
              </div>
              <div className="nv-suggestions">
                <Surface s={s['suggested_questions']} />
              </div>
              <form className="nv-composer" onSubmit={submit}>
                <label htmlFor="ask" className="nv-sr">
                  Ask the navigator
                </label>
                <input id="ask" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Ask about this case — new facts update the evidence panel…" autoComplete="off" />
                <button type="submit" disabled={nav.busy || !draft.trim()}>
                  Send
                </button>
              </form>
            </section>
          </main>

          <aside className="nv-panel nv-docs" aria-label="Case documents and evidence">
            <Surface s={s['case_documents']} />
          </aside>
        </div>

        {/* Both sheets stay mounted (hidden when closed): unmounting an A2UI surface while the
            server is still updating it races the web components' update cycle. */}
        {(['brief', 'intake'] as const).map(kind => (
          <div
            key={kind}
            className="nv-overlay"
            hidden={nav.overlay !== kind}
            role="dialog"
            aria-modal="true"
            aria-label={kind === 'brief' ? 'Tenant Stabilization Brief' : 'New intake'}
            onClick={e => e.target === e.currentTarget && nav.setOverlay('none')}
          >
            <div className={`nv-sheet ${kind === 'brief' ? 'nv-sheet-brief' : 'nv-sheet-form'}`}>
              <Surface s={s[kind === 'brief' ? 'stabilization_brief' : 'new_intake_form']} />
            </div>
          </div>
        ))}
        {nav.toast ? <div className="nv-toast" role="status">{nav.toast}</div> : null}
      </div>
    </MarkdownContext.Provider>
  );
}
