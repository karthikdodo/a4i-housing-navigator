/**
 * "Speak the intake": record the paralegal describing the tenant, transcribe it, and let the server
 * fill the New intake form (A2UI updateDataModel on the new_intake_form surface). The paralegal
 * checks the fields before submitting. Names are turned into initials on the server.
 */
import {useState} from 'react';
import {AnimatePresence, motion} from 'motion/react';
import {CheckCircle2, Loader2, Mic} from 'lucide-react';
import {transcribe, voiceIntake} from '../api/media';
import {useRecorder} from '../voice/useRecorder';
import {RecordingBar, VoiceClipPlayer} from './Voice';

const LABELS: Record<string, string> = {
  client: 'Initials', block: 'Block', issue: 'Issue', hearing: 'Hearing', notice: 'Notice', household: 'Household', ami: '% AMI',
};

export function VoiceIntake({sid, onApply, onError}: {sid: string; onApply: (msgs: unknown[]) => void; onError: (m: string) => void}) {
  const rec = useRecorder();
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<{fields: Record<string, string>; transcript: string; audio?: {url: string; duration: number; source: string}} | null>(null);

  const done = async () => {
    const clip = await rec.stop();
    if (!clip || clip.blob.size < 800) {
      onError("Didn't catch any audio. Try again.");
      return;
    }
    setWorking(true);
    try {
      const t = await transcribe(sid, clip);
      if (!t.text) {
        onError("Couldn't transcribe the clip here. Type the intake instead.");
        return;
      }
      const r = await voiceIntake(sid, t.text);
      onApply(r.a2ui);
      setResult({fields: r.fields, transcript: r.transcript, audio: {url: t.audio.url, duration: t.audio.duration, source: t.source}});
    } catch (e) {
      onError(`Voice intake failed: ${(e as Error).message}`);
    } finally {
      setWorking(false);
    }
  };

  const filled = result ? Object.keys(result.fields).filter(k => LABELS[k]) : [];
  return (
    <div className="nv-voice-intake">
      <AnimatePresence mode="wait" initial={false}>
        {rec.state === 'recording' ? (
          <RecordingBar
            key="rec"
            label="Listening to the intake"
            seconds={rec.seconds}
            levels={rec.levels}
            interim={rec.interim}
            liveTranscript={rec.liveTranscript}
            onStop={done}
            onCancel={rec.cancel}
          />
        ) : (
          <motion.div key="idle" className="nv-voice-intake-row" initial={{opacity: 0}} animate={{opacity: 1}}>
            <motion.button
              type="button"
              className="nv-voice-big"
              onClick={() => void rec.start()}
              disabled={working || rec.state === 'unsupported'}
              whileHover={{scale: 1.04}}
              whileTap={{scale: 0.96}}
              aria-label="Speak the intake"
            >
              {working ? <Loader2 className="nv-spin" size={22} /> : <Mic size={22} />}
            </motion.button>
            <div>
              <strong>{working ? 'Filling the form from your voice…' : 'Speak the intake'}</strong>
              <p className="nv-small nv-muted">
                Say initials, block, conditions, hearing date and time, notice, household size and income. For example: “Tenant M R, 600 block of
                John Muir Drive, mold and no heat, hearing Monday 9 AM, household of three.”
              </p>
              {rec.state === 'denied' ? <p className="nv-small nv-warn">Microphone blocked: allow it in the site settings.</p> : null}
              {rec.state === 'unsupported' ? <p className="nv-small nv-warn">This browser can't record audio. Type the intake below.</p> : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {result ? (
          <motion.div className="nv-voice-result" initial={{opacity: 0, y: -6}} animate={{opacity: 1, y: 0}} exit={{opacity: 0}}>
            <div className="nv-voice-result-head">
              <CheckCircle2 size={16} aria-hidden="true" />
              <strong>
                Filled {filled.length} field{filled.length === 1 ? '' : 's'} from your voice
              </strong>
              <span className="nv-small nv-muted">check them before submitting</span>
            </div>
            <div className="nv-wrap">
              {filled.map((k, i) => (
                <motion.span key={k} className="nv-badge nv-tone-eligible" initial={{scale: 0.6, opacity: 0}} animate={{scale: 1, opacity: 1}} transition={{delay: i * 0.06}}>
                  ✓ {LABELS[k]}
                </motion.span>
              ))}
            </div>
            {result.audio ? <VoiceClipPlayer {...result.audio} /> : null}
            <p className="nv-small nv-transcript">
              <span className="nv-muted">Transcript: </span>
              {result.transcript}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
