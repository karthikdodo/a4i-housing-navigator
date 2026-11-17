/** Voice UI pieces: live waveform, recording bar, and the clip player shown in chat history. */
import {useEffect, useRef, useState} from 'react';
import {motion} from 'motion/react';
import {Mic, Pause, Play, Square, X} from 'lucide-react';
import {fmtTime} from '../voice/useRecorder';

export function Waveform({levels, active = true}: {levels: number[]; active?: boolean}) {
  return (
    <div className={`nv-wave${active ? ' is-live' : ''}`} aria-hidden="true">
      {levels.map((v, i) => (
        <motion.span key={i} animate={{scaleY: 0.12 + v * 0.88}} transition={{type: 'spring', stiffness: 420, damping: 26}} />
      ))}
    </div>
  );
}

/** Shown in place of the text box while the mic is on. */
export function RecordingBar({
  seconds, levels, interim, liveTranscript, onStop, onCancel, label = 'Listening',
}: {
  seconds: number; levels: number[]; interim: string; liveTranscript: boolean;
  onStop: () => void; onCancel: () => void; label?: string;
}) {
  return (
    <motion.div className="nv-recbar" initial={{opacity: 0, y: 6}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: 6}}>
      <div className="nv-recbar-row">
        <span className="nv-rec-dot" aria-hidden="true" />
        <span className="nv-rec-label">
          {label} · <span className="nv-mono">{fmtTime(seconds)}</span>
        </span>
        <Waveform levels={levels} />
        <button type="button" className="nv-icon-btn" onClick={onCancel} aria-label="Cancel recording">
          <X size={18} />
        </button>
        <button type="button" className="nv-rec-stop" onClick={onStop} aria-label="Stop and send">
          <Square size={14} fill="currentColor" /> Done
        </button>
      </div>
      <p className="nv-rec-live" aria-live="polite">
        {interim || (liveTranscript ? 'Start speaking…' : 'Recording… the transcript appears when you stop.')}
      </p>
    </motion.div>
  );
}

/** A recorded clip in the chat history: play/pause, a static waveform and the length. */
export function VoiceClipPlayer({url, duration, source}: {url: string; duration: number; source?: string}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const bars = useRef(Array.from({length: 28}, (_, i) => 0.3 + 0.7 * Math.abs(Math.sin(i * 1.7 + url.length))));
  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    const onTime = () => setPos(a.duration ? a.currentTime / a.duration : 0);
    const onEnd = () => {
      setPlaying(false);
      setPos(0);
    };
    a.addEventListener('timeupdate', onTime);
    a.addEventListener('ended', onEnd);
    return () => {
      a.removeEventListener('timeupdate', onTime);
      a.removeEventListener('ended', onEnd);
    };
  }, []);
  const toggle = () => {
    const a = audio.current;
    if (!a) return;
    if (playing) a.pause();
    else void a.play();
    setPlaying(!playing);
  };
  return (
    <div className="nv-clip">
      <button type="button" className="nv-clip-play" onClick={toggle} aria-label={playing ? 'Pause voice message' : 'Play voice message'}>
        {playing ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
      </button>
      <div className="nv-clip-bars" aria-hidden="true">
        {bars.current.map((h, i) => (
          <span key={i} style={{height: `${h * 100}%`}} className={i / bars.current.length <= pos ? 'is-played' : ''} />
        ))}
      </div>
      <span className="nv-mono nv-clip-time">{fmtTime(duration)}</span>
      <span className="nv-clip-tag" title={source === 'gemini' ? 'Transcribed by Gemini' : 'Transcribed by the browser'}>
        <Mic size={11} aria-hidden="true" /> {source === 'gemini' ? 'Gemini' : 'voice'}
      </span>
      <audio ref={audio} src={url} preload="none" />
    </div>
  );
}
