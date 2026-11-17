import {useState, type MouseEvent} from 'react';
import {motion} from 'motion/react';
import {Search} from 'lucide-react';
import {toHtml} from '../a2ui/markdown';
import type {ChatItem} from '../a2ui/useNavigator';
import {VoiceClipPlayer} from './Voice';
import {AgentRunCard} from '../AgentRun';

const pop = {initial: {opacity: 0, y: 10, scale: 0.98}, animate: {opacity: 1, y: 0, scale: 1}, transition: {type: 'spring' as const, stiffness: 380, damping: 30}};

export function ChatMessage({m, onChip}: {m: ChatItem; onChip: (id: string) => void}) {
  const [zoom, setZoom] = useState<string | null>(null);
  const click = (e: MouseEvent<HTMLDivElement>) => {
    const id = (e.target as HTMLElement).closest<HTMLElement>('[data-record]')?.dataset.record;
    if (id) onChip(id);
  };

  if (m.role === 'run' && m.run)
    return (
      <motion.div className="nv-ar-wrap" initial={{opacity: 0, y: 6}} animate={{opacity: 1, y: 0}}>
        <AgentRunCard run={m.run} />
      </motion.div>
    );

  if (m.role === 'status')
    return (
      <motion.div className="nv-trace" initial={{opacity: 0, x: -6}} animate={{opacity: 1, x: 0}}>
        <Search size={14} aria-hidden="true" />
        <span>{m.text}</span>
      </motion.div>
    );

  if (m.role === 'user')
    return (
      <motion.div {...pop} className={`nv-msg nv-msg-user${m.voice ? ' is-voice' : ''}`}>
        {m.voice ? <VoiceClipPlayer url={m.voice.url} duration={m.voice.duration} source={m.voice.source} /> : null}
        {m.attachments?.length ? (
          <div className="nv-msg-photos">
            {m.attachments.map(a => (
              <button key={a.id} type="button" onClick={() => setZoom(a.url)} aria-label="Open photo">
                <img src={a.url} alt={a.name ?? 'Tenant photo'} loading="lazy" />
              </button>
            ))}
          </div>
        ) : null}
        {m.voice ? <span className="nv-transcript-label">Transcript</span> : null}
        <span className="nv-msg-text">{m.text}</span>
        {zoom ? (
          <div className="nv-lightbox" role="dialog" aria-modal="true" aria-label="Photo" onClick={() => setZoom(null)}>
            <motion.img initial={{scale: 0.92, opacity: 0}} animate={{scale: 1, opacity: 1}} src={zoom} alt="Tenant photo, enlarged" />
          </div>
        ) : null}
      </motion.div>
    );

  return (
    <motion.div
      {...pop}
      className={`nv-msg nv-msg-agent${m.streaming ? ' is-streaming' : ''}`}
      onClick={click}
      dangerouslySetInnerHTML={{__html: toHtml(m.text, {chips: true})}}
    />
  );
}

export function Typing() {
  return (
    <motion.div className="nv-typing" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} aria-label="Navigator is working">
      <span />
      <span />
      <span />
      <em>Navigator is working…</em>
    </motion.div>
  );
}
