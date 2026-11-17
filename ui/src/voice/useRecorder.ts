/**
 * Microphone capture for voice chat and voice intake.
 *
 *  - MediaRecorder records the clip (Opus/WebM in Chrome and Firefox, MP4/AAC in Safari).
 *  - An AnalyserNode drives the live waveform (`levels`, 0..1, newest last).
 *  - The Web Speech API, where the browser has it, gives a live transcript while you talk
 *    (`interim`). The server prefers Gemini's transcript of the clip; this is the fallback.
 *
 * Nothing records until the user presses the mic button, and the browser asks for permission first.
 */
import {useCallback, useEffect, useRef, useState} from 'react';

export type Recording = {blob: Blob; mime: string; duration: number; browserText: string};
export type RecorderState = 'idle' | 'recording' | 'unsupported' | 'denied';

const MAX_SECONDS = 120;
const BARS = 32;

/* eslint-disable @typescript-eslint/no-explicit-any */
const SpeechRecognitionCtor: any =
  typeof window !== 'undefined' ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : undefined;

function pickMime(): string {
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return options.find(m => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(m)) ?? '';
}

export function useRecorder() {
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
  const [state, setState] = useState<RecorderState>(supported ? 'idle' : 'unsupported');
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));
  const [interim, setInterim] = useState('');

  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef<number>(0);
  const timer = useRef<number>(0);
  const started = useRef(0);
  const speech = useRef<any>(null);
  const finalText = useRef('');
  const resolveStop = useRef<((r: Recording | null) => void) | null>(null);
  const cancelled = useRef(false);

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    clearInterval(timer.current);
    stream.current?.getTracks().forEach(t => t.stop());
    stream.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    try {
      speech.current?.stop();
    } catch {
      /* already stopped */
    }
    speech.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    if (!supported || rec.current) return;
    try {
      const s = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}});
      stream.current = s;
      const mime = pickMime();
      const r = new MediaRecorder(s, mime ? {mimeType: mime} : undefined);
      chunks.current = [];
      cancelled.current = false;
      r.ondataavailable = e => e.data.size && chunks.current.push(e.data);
      r.onstop = () => {
        const type = r.mimeType || mime || 'audio/webm';
        const out: Recording = {
          blob: new Blob(chunks.current, {type}),
          mime: type,
          duration: Math.round(((performance.now() - started.current) / 1000) * 10) / 10,
          browserText: finalText.current.trim(),
        };
        rec.current = null;
        cleanup();
        setState('idle');
        resolveStop.current?.(cancelled.current ? null : out);
        resolveStop.current = null;
      };
      r.start(250);
      rec.current = r;
      started.current = performance.now();
      setSeconds(0);
      setInterim('');
      finalText.current = '';
      setState('recording');

      // Live level meter for the waveform.
      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      let last = 0;
      const tick = (t: number) => {
        if (t - last > 70) {
          last = t;
          analyser.getByteTimeDomainData(buf);
          let peak = 0;
          for (const v of buf) peak = Math.max(peak, Math.abs(v - 128) / 128);
          setLevels(prev => [...prev.slice(1), Math.min(1, peak * 2.2)]);
        }
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
      timer.current = window.setInterval(() => {
        const sec = (performance.now() - started.current) / 1000;
        setSeconds(sec);
        if (sec >= MAX_SECONDS) rec.current?.stop();
      }, 200);

      // Live transcript where the browser supports it (Chrome, Edge, Safari).
      if (SpeechRecognitionCtor) {
        const sr = new SpeechRecognitionCtor();
        sr.continuous = true;
        sr.interimResults = true;
        sr.lang = navigator.language || 'en-US';
        sr.onresult = (e: any) => {
          let partial = '';
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const txt = e.results[i][0].transcript;
            if (e.results[i].isFinal) finalText.current += txt + ' ';
            else partial += txt;
          }
          setInterim((finalText.current + partial).trim());
        };
        sr.onerror = () => undefined;
        try {
          sr.start();
          speech.current = sr;
        } catch {
          /* no speech service: the server transcribes the clip instead */
        }
      }
    } catch (err) {
      cleanup();
      setState((err as DOMException)?.name === 'NotAllowedError' ? 'denied' : 'unsupported');
    }
  }, [supported, cleanup]);

  /** Stops and resolves with the clip (or null when nothing was recorded). */
  const stop = useCallback((): Promise<Recording | null> => {
    if (!rec.current) return Promise.resolve(null);
    return new Promise(resolve => {
      resolveStop.current = resolve;
      // Give the speech service a moment to deliver its last final result.
      try {
        speech.current?.stop();
      } catch {
        /* ignore */
      }
      window.setTimeout(() => rec.current?.state === 'recording' && rec.current.stop(), 350);
    });
  }, []);

  const cancel = useCallback(() => {
    cancelled.current = true;
    if (rec.current?.state === 'recording') rec.current.stop();
    else cleanup();
    setState(supported ? 'idle' : 'unsupported');
  }, [cleanup, supported]);

  return {state, seconds, levels, interim, start, stop, cancel, liveTranscript: !!SpeechRecognitionCtor};
}

export function fmtTime(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
