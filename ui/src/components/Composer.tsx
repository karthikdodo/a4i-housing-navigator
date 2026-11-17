/**
 * The chat composer: type, attach tenant photos, or talk.
 *  - Paperclip: pick photos (or drop them on the chat). On phones it offers the camera.
 *  - Mic: record a voice message. On stop it is transcribed and sent; the chat history shows
 *    the clip and its transcript.
 */
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {AnimatePresence, motion} from 'motion/react';
import {ImagePlus, Loader2, Mic, Send, X} from 'lucide-react';
import {transcribe, uploadPhoto, type UploadRef} from '../api/media';
import {useRecorder} from '../voice/useRecorder';
import {RecordingBar} from './Voice';

type Props = {
  sid: string;
  busy: boolean;
  onSend: (text: string, extra: {attachments?: string[]; voice?: {id: string; duration: number; source: string}}) => void;
  onError: (msg: string) => void;
  pendingFiles: File[];
  clearPendingFiles: () => void;
};

type Pending = {key: string; preview: string; upload?: UploadRef; error?: string};

export function Composer({sid, busy, onSend, onError, pendingFiles, clearPendingFiles}: Props) {
  const [draft, setDraft] = useState('');
  const [photos, setPhotos] = useState<Pending[]>([]);
  const [transcribing, setTranscribing] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const rec = useRecorder();

  const addFiles = async (files: File[]) => {
    const imgs = files.filter(f => f.type.startsWith('image/')).slice(0, 6 - photos.length);
    if (files.length && !imgs.length) onError('Only photos can be attached (JPEG, PNG, WebP, HEIC).');
    for (const f of imgs) {
      const key = `${f.name}-${f.size}-${Math.random()}`;
      setPhotos(p => [...p, {key, preview: URL.createObjectURL(f)}]);
      try {
        const up = await uploadPhoto(sid, f);
        setPhotos(p => p.map(x => (x.key === key ? {...x, upload: up} : x)));
      } catch (e) {
        setPhotos(p => p.filter(x => x.key !== key));
        onError(`Couldn't upload ${f.name}: ${(e as Error).message}`);
      }
    }
  };

  // Photos dropped onto the chat panel arrive through props.
  useEffect(() => {
    if (!pendingFiles.length) return;
    const files = pendingFiles;
    clearPendingFiles();
    void addFiles(files);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFiles]);

  const uploading = photos.some(p => !p.upload);
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (busy || uploading) return;
    const ids = photos.map(p => p.upload!.id);
    if (!draft.trim() && !ids.length) return;
    onSend(draft, ids.length ? {attachments: ids} : {});
    setDraft('');
    photos.forEach(p => URL.revokeObjectURL(p.preview));
    setPhotos([]);
  };

  const startVoice = async () => {
    await rec.start();
  };
  const finishVoice = async () => {
    const clip = await rec.stop();
    if (!clip || clip.blob.size < 800) {
      onError("Didn't catch any audio. Try again, or type instead.");
      return;
    }
    setTranscribing(true);
    try {
      const t = await transcribe(sid, clip);
      if (!t.text) {
        onError("Couldn't transcribe that clip. This browser has no live transcript, and Gemini transcription needs live mode. Please type it.");
        return;
      }
      const ids = photos.filter(p => p.upload).map(p => p.upload!.id);
      onSend(t.text, {voice: {id: t.audio.id, duration: t.audio.duration, source: t.source}, ...(ids.length ? {attachments: ids} : {})});
      setPhotos([]);
    } catch (e) {
      onError(`Voice message failed: ${(e as Error).message}`);
    } finally {
      setTranscribing(false);
    }
  };

  const micTitle =
    rec.state === 'unsupported' ? 'This browser cannot record audio' : rec.state === 'denied' ? 'Microphone permission was denied' : 'Talk to the navigator';

  return (
    <div className="nv-composer-wrap">
      <AnimatePresence>
        {photos.length ? (
          <motion.div className="nv-attach-row" initial={{opacity: 0, height: 0}} animate={{opacity: 1, height: 'auto'}} exit={{opacity: 0, height: 0}}>
            {photos.map(p => (
              <motion.div layout key={p.key} className="nv-attach" initial={{scale: 0.8, opacity: 0}} animate={{scale: 1, opacity: 1}}>
                <img src={p.preview} alt="Photo to send" />
                {!p.upload ? <Loader2 className="nv-spin" size={16} aria-label="Uploading" /> : null}
                <button type="button" onClick={() => setPhotos(ps => ps.filter(x => x.key !== p.key))} aria-label="Remove photo">
                  <X size={12} />
                </button>
              </motion.div>
            ))}
            <span className="nv-small nv-muted">Tenant photos are filed as tenant-provided, not public record.</span>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence mode="wait" initial={false}>
        {rec.state === 'recording' ? (
          <RecordingBar
            key="rec"
            seconds={rec.seconds}
            levels={rec.levels}
            interim={rec.interim}
            liveTranscript={rec.liveTranscript}
            onStop={finishVoice}
            onCancel={rec.cancel}
          />
        ) : (
          <motion.form key="type" className="nv-composer" onSubmit={submit} initial={{opacity: 0}} animate={{opacity: 1}}>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              capture="environment"
              multiple
              hidden
              onChange={e => {
                void addFiles(Array.from(e.target.files ?? []));
                e.target.value = '';
              }}
            />
            <button type="button" className="nv-icon-btn" onClick={() => fileInput.current?.click()} aria-label="Attach tenant photos" title="Attach tenant photos">
              <ImagePlus size={20} />
            </button>
            <button
              type="button"
              className="nv-icon-btn nv-mic"
              onClick={startVoice}
              disabled={busy || transcribing || rec.state === 'unsupported'}
              aria-label={micTitle}
              title={micTitle}
            >
              {transcribing ? <Loader2 className="nv-spin" size={20} /> : <Mic size={20} />}
            </button>
            <label htmlFor="ask" className="nv-sr">
              Ask the navigator
            </label>
            <input
              id="ask"
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder={transcribing ? 'Transcribing your voice message…' : 'Ask, or press the mic and talk — new facts update the panel…'}
              autoComplete="off"
              disabled={transcribing}
            />
            <motion.button whileTap={{scale: 0.95}} type="submit" className="nv-send" disabled={busy || uploading || (!draft.trim() && !photos.length)}>
              <Send size={16} aria-hidden="true" /> Send
            </motion.button>
          </motion.form>
        )}
      </AnimatePresence>
      {rec.state === 'denied' ? <p className="nv-small nv-warn">Microphone blocked. Allow it in the browser's site settings to talk.</p> : null}
    </div>
  );
}
