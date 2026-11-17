/** REST calls for photos, voice clips and voice intake (api/main.py). */
import type {Recording} from '../voice/useRecorder';

export type UploadRef = {id: string; url: string; kind: 'image' | 'audio'; name: string; size: number; mime: string};
export type Transcript = {text: string; source: 'gemini' | 'browser' | 'none'; audio: UploadRef & {duration: number}};
export type VoiceIntake = {fields: Record<string, string>; source: string; transcript: string; a2ui: unknown[]};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export async function uploadPhoto(sid: string, file: File): Promise<UploadRef> {
  const body = new FormData();
  body.append('file', file, file.name);
  return json(await fetch(`/api/sessions/${sid}/uploads`, {method: 'POST', body}));
}

export async function transcribe(sid: string, rec: Recording): Promise<Transcript> {
  const ext = rec.mime.includes('mp4') ? 'm4a' : rec.mime.includes('ogg') ? 'ogg' : 'webm';
  const body = new FormData();
  body.append('audio', new File([rec.blob], `voice.${ext}`, {type: rec.mime.split(';')[0]}));
  body.append('browser_text', rec.browserText);
  body.append('duration', String(rec.duration));
  return json(await fetch(`/api/sessions/${sid}/transcribe`, {method: 'POST', body}));
}

export async function voiceIntake(sid: string, text: string): Promise<VoiceIntake> {
  return json(
    await fetch(`/api/sessions/${sid}/intake/voice`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})}),
  );
}

/** Reads an agent reply aloud (browser speech synthesis); markdown and record ids are tidied first. */
export function speak(markdown: string): void {
  if (!('speechSynthesis' in window)) return;
  const text = markdown
    .replace(/[*_`#>]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\bSF-(\d+)/g, 'record $1')
    .replace(/\s+/g, ' ')
    .trim();
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  window.speechSynthesis.speak(u);
}
