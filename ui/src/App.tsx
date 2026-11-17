import {useCallback, useEffect, useRef, useState, type DragEvent} from 'react';
import {AnimatePresence, motion} from 'motion/react';
import {A2uiSurface, MarkdownContext} from '@a2ui/react';
import {
  Briefcase, FileStack, Home, LayoutGrid, ListTodo, MapPinned, MessagesSquare, UserPlus, Volume2, VolumeX, X,
} from 'lucide-react';
import {useNavigator} from './a2ui/useNavigator';
import {renderMarkdown} from './a2ui/markdown';
import {Board, DEFAULT_LAYOUT, loadLayout, type Layout, type SectionDef} from './components/Board';
import {ChatMessage, Typing} from './components/ChatMessage';
import {Composer} from './components/Composer';
import {VoiceIntake} from './components/VoiceIntake';
import {AgentTeam} from './AgentRun';
import type {ChatItem} from './a2ui/useNavigator';

function Surface({s}: {s?: Parameters<typeof A2uiSurface>[0]['surface']}) {
  return s ? <A2uiSurface surface={s} /> : <div className="nv-skeleton" aria-hidden="true" />;
}

export default function App() {
  const nav = useNavigator();
  const [layout, setLayout] = useState<Layout>(loadLayout);
  const [dropFiles, setDropFiles] = useState<File[]>([]);
  const [dragOverChat, setDragOverChat] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  // Follow new messages only while the reader is at the bottom. If they scrolled up to read an
  // agent's details, live updates must not yank the view (or the page) away.
  const stickToBottom = useRef(true);
  const onChatScroll = () => {
    const b = chatRef.current;
    if (b) stickToBottom.current = b.scrollHeight - b.scrollTop - b.clientHeight < 80;
  };

  useEffect(() => {
    const b = chatRef.current;
    // A new user turn (typed, suggestion chip, or voice) always brings the view back to the bottom.
    if (nav.chat[nav.chat.length - 1]?.role === 'user') stickToBottom.current = true;
    // Scroll the chat panel only, never the page (scrollIntoView would move every scrolling ancestor).
    if (b && stickToBottom.current) b.scrollTo({top: b.scrollHeight, behavior: 'smooth'});
  }, [nav.chat]);
  const send = useCallback(
    (...args: Parameters<typeof nav.ask>) => {
      stickToBottom.current = true; // your own new message always brings you back to the bottom
      nav.ask(...args);
    },
    [nav],
  );
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') nav.setOverlay('none');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [nav]);

  const onDropChat = (e: DragEvent) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    setDragOverChat(false);
    setDropFiles(Array.from(e.dataTransfer.files));
  };
  const clearDrop = useCallback(() => setDropFiles([]), []);

  const s = nav.surfaces;
  // Turns with a live agent run show it instead of the one-line status messages.
  const visibleChat = (() => {
    const out: ChatItem[] = [];
    let seg: ChatItem[] = [];
    const flush = () => {
      const hasRun = seg.some(m => m.role === 'run');
      out.push(...seg.filter(m => !(hasRun && m.role === 'status' && !m.text.startsWith('⚠'))));
      seg = [];
    };
    for (const m of nav.chat) {
      if (m.role === 'user') flush();
      seg.push(m);
    }
    flush();
    return out;
  })();
  const runLive = !!nav.lastRun && nav.lastRun.endedAt === null;
  const sections: Record<string, SectionDef> = {
    queue: {title: 'Intake queue', icon: ListTodo, className: 'nv-sec-queue', body: <Surface s={s['intake_queue']} />},
    map: {title: 'Location', icon: MapPinned, className: 'nv-sec-map', body: <Surface s={s['case_map']} />},
    header: {title: 'Case', icon: Briefcase, className: 'nv-sec-header', body: <Surface s={s['case_header']} />},
    chat: {
      title: 'Conversation',
      icon: MessagesSquare,
      className: `nv-sec-chat${dragOverChat ? ' is-drop' : ''}`,
      actions: (
        <>
          <span className="nv-small nv-muted nv-hide-sm">{nav.caseId} · ADK multi-agent + Gemini</span>
          <button
            type="button"
            className={`nv-icon-btn${nav.readAloud ? ' is-on' : ''}`}
            onClick={() => nav.setReadAloud(!nav.readAloud)}
            aria-pressed={nav.readAloud}
            title={nav.readAloud ? 'Stop reading replies aloud' : 'Read replies aloud'}
            aria-label="Read replies aloud"
          >
            {nav.readAloud ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
        </>
      ),
      body: (
        <div
          className="nv-chat"
          onDragOver={e => {
            if (e.dataTransfer.types.includes('Files')) {
              e.preventDefault();
              setDragOverChat(true);
            }
          }}
          onDragLeave={() => setDragOverChat(false)}
          onDrop={onDropChat}
        >
          <AgentTeam run={nav.lastRun} />
          <div className="nv-chat-body" aria-live="polite" ref={chatRef} onScroll={onChatScroll}>
            {nav.chat.length === 0 ? (
              <motion.div className="nv-empty" initial={{opacity: 0}} animate={{opacity: 1}}>
                <MessagesSquare size={28} aria-hidden="true" />
                <p>
                  Ask about this case, press the <strong>mic</strong> and talk, or drop the tenant's <strong>photos</strong> here. Every record the navigator
                  cites opens in the documents panel.
                </p>
              </motion.div>
            ) : null}
            {visibleChat.map(m => (
              <ChatMessage key={m.id} m={m} onChip={nav.focusRecord} />
            ))}
            <AnimatePresence>{nav.busy && !runLive ? <Typing /> : null}</AnimatePresence>
            <div ref={endRef} />
          </div>
          <div className="nv-suggestions">
            <Surface s={s['suggested_questions']} />
          </div>
          <Composer
            sid={nav.sid}
            busy={nav.busy}
            onSend={send}
            onError={nav.flash}
            pendingFiles={dropFiles}
            clearPendingFiles={clearDrop}
          />
          <AnimatePresence>
            {dragOverChat ? (
              <motion.div className="nv-dropzone" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}}>
                Drop photos to attach them to this case
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      ),
    },
    docs: {title: 'Case documents', icon: FileStack, className: 'nv-sec-docs', body: <Surface s={s['case_documents']} />},
  };

  return (
    <MarkdownContext.Provider value={renderMarkdown}>
      <div className="nv-app">
        <header className="nv-topbar">
          <div className="nv-brand">
            <Home size={22} aria-hidden="true" />
            <span>Tenant Voice</span>
          </div>
          <span className="nv-pill">San Francisco · CA · FIPS 06</span>
          {nav.mode === 'mock' ? (
            <span className="nv-pill nv-pill-warn" title="A4I_AGENT_MODE=mock">
              Demo replay · not live BigQuery
            </span>
          ) : null}
          <span className="nv-spacer" />
          <motion.button whileHover={{y: -1}} whileTap={{scale: 0.96}} type="button" className="nv-top-btn is-primary" onClick={() => nav.setOverlay('intake')}>
            <UserPlus size={16} aria-hidden="true" /> New intake
          </motion.button>
          <button
            type="button"
            className="nv-top-btn"
            onClick={() => {
              setLayout(DEFAULT_LAYOUT);
              try {
                window.localStorage.removeItem('a4i.layout.v1');
              } catch {
                /* ignore */
              }
            }}
            title="Put every section back where it started"
          >
            <LayoutGrid size={16} aria-hidden="true" /> Reset layout
          </button>
          <span className={`nv-conn nv-conn-${nav.connection}`}>{nav.connection === 'open' ? 'Connected' : nav.connection === 'connecting' ? 'Connecting…' : 'Reconnecting…'}</span>
        </header>

        <Board sections={sections} layout={layout} setLayout={setLayout} />

        {/* Both sheets stay mounted and only fade out: unmounting an A2UI surface while the
            server is still updating it races the web components' update cycle. */}
        {(['brief', 'intake'] as const).map(kind => {
          const open = nav.overlay === kind;
          return (
            <motion.div
              key={kind}
              className="nv-overlay"
              initial={false}
              animate={open ? {opacity: 1, display: 'flex'} : {opacity: 0, transitionEnd: {display: 'none'}}}
              transition={{duration: 0.2}}
              role="dialog"
              aria-modal="true"
              aria-hidden={!open}
              aria-label={kind === 'brief' ? 'Tenant Stabilization Brief' : 'New intake'}
              onClick={e => e.target === e.currentTarget && nav.setOverlay('none')}
            >
              <motion.div
                className={`nv-sheet ${kind === 'brief' ? 'nv-sheet-brief' : 'nv-sheet-form'}`}
                initial={false}
                animate={open ? {y: 0, scale: 1} : {y: 24, scale: 0.97}}
                transition={{type: 'spring', stiffness: 320, damping: 30}}
              >
                <button type="button" className="nv-sheet-close" onClick={() => nav.setOverlay('none')} aria-label="Close">
                  <X size={18} />
                </button>
                {kind === 'intake' ? <VoiceIntake sid={nav.sid} onApply={nav.applyA2ui} onError={nav.flash} /> : null}
                <Surface s={s[kind === 'brief' ? 'stabilization_brief' : 'new_intake_form']} />
              </motion.div>
            </motion.div>
          );
        })}
        <AnimatePresence>
          {nav.toast ? (
            <motion.div className="nv-toast" role="status" initial={{opacity: 0, y: 16, x: '-50%'}} animate={{opacity: 1, y: 0, x: '-50%'}} exit={{opacity: 0, y: 16, x: '-50%'}}>
              {nav.toast}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </MarkdownContext.Provider>
  );
}
