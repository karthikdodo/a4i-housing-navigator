/**
 * Connects the A2UI MessageProcessor to the navigator WebSocket.
 *
 *  server {type:"a2ui", messages}  -> processor.processMessages(messages)  -> surfaces re-render
 *  user clicks an A2UI component   -> actionHandler -> local UI command, or {version, action} to the server
 *  server status/message/brief      -> chat state
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {MessageProcessor, type ActionPayload, type SurfaceModel} from '@a2ui/web_core';
import type {ReactCatalogComponent} from '@a2ui/react';
import {navigatorCatalog} from './catalog';
import {NavigatorSocket, sessionId, type ServerEvent, type TranscriptTurn} from '../api/client';
import {speak} from '../api/media';

export type Attachment = {id: string; url: string; kind: string; name?: string};
export type VoiceClip = {id: string; url: string; duration: number; source?: string};
export type ChatItem = {
  id: number;
  role: 'user' | 'agent' | 'status';
  text: string;
  tool?: string | null;
  streaming?: boolean;
  attachments?: Attachment[];
  voice?: VoiceClip | null;
};

const toItem = (t: TranscriptTurn): ChatItem => ({
  id: nextId++, role: t.role, text: t.text, tool: t.tool, attachments: t.attachments ?? [], voice: t.voice ?? null,
});

// Actions the browser handles itself (they change only this screen).
const LOCAL = new Set(['open_brief', 'close_brief', 'print_brief', 'copy_memo', 'open_intake_form', 'close_intake_form']);

type Surfaces = Record<string, SurfaceModel<ReactCatalogComponent>>;

let nextId = 1;

export function useNavigator() {
  const [surfaces, setSurfaces] = useState<Surfaces>({});
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [mode, setMode] = useState('');
  const [caseId, setCaseId] = useState('');
  const [overlay, setOverlay] = useState<'none' | 'brief' | 'intake'>('none');
  const [toast, setToast] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [readAloud, setReadAloudState] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('a4i.readAloud') === '1';
    } catch {
      return false;
    }
  });
  const readAloudRef = useRef(readAloud);
  const setReadAloud = useCallback((on: boolean) => {
    readAloudRef.current = on;
    setReadAloudState(on);
    if (!on) window.speechSynthesis?.cancel();
    try {
      window.localStorage.setItem('a4i.readAloud', on ? '1' : '0');
    } catch {
      /* storage blocked */
    }
  }, []);
  const [sid] = useState(sessionId);

  const processorRef = useRef<MessageProcessor<ReactCatalogComponent> | null>(null);
  const socketRef = useRef<NavigatorSocket | null>(null);

  const flash = useCallback((t: string) => {
    setToast(t);
    window.setTimeout(() => setToast(''), 4500);
  }, []);

  const handleLocal = useCallback(
    async (a: ActionPayload) => {
      switch (a.name) {
        case 'open_brief':
          setOverlay('brief');
          break;
        case 'close_brief':
        case 'close_intake_form':
          setOverlay('none');
          break;
        case 'open_intake_form':
          setOverlay('intake');
          break;
        case 'print_brief':
          window.print();
          break;
        case 'copy_memo': {
          const docs = processorRef.current?.model.surfacesMap.get('case_documents');
          const url = docs?.dataModel.get('/memo_url') as string | undefined;
          try {
            const text = url ? await (await fetch(url)).text() : '';
            await navigator.clipboard.writeText(text);
            flash(text ? 'Memo copied' : 'No memo yet');
          } catch {
            flash('Copy failed: use Download instead');
          }
          break;
        }
      }
    },
    [flash],
  );

  const newProcessor = useCallback(() => {
    const p = new MessageProcessor<ReactCatalogComponent>(
      [navigatorCatalog as never],
      (a: ActionPayload) => {
        if (LOCAL.has(a.name)) return handleLocal(a);
        if (a.name === 'submit_intake') setOverlay('none'); // the server clears the form (updateDataModel)
        socketRef.current?.action({version: '1.0', action: a});
      },
      {
        version: '1.0' as never,
        reportErrorsOnly: true,
        errorHandler: e => {
          console.warn('A2UI', e);
          setErrors(prev => [...prev.slice(-4), JSON.stringify(e)]);
          socketRef.current?.send({type: 'a2ui_error', message: e as unknown as Record<string, unknown>});
        },
      },
    );
    const sync = () => setSurfaces(Object.fromEntries(p.model.surfacesMap.entries()));
    p.onSurfaceCreated(sync);
    p.onSurfaceDeleted(sync);
    processorRef.current = p;
    sync();
    return p;
  }, [handleLocal]);

  const onEvent = useCallback((e: ServerEvent) => {
    switch (e.type) {
      case 'a2ui':
        processorRef.current?.processMessages(e.messages as never);
        break;
      case 'case':
        setCaseId(e.case_id);
        setMode(e.mode);
        setChat(e.transcript.map(toItem));
        break;
      case 'user_echo':
        setBusy(true); // the user_turn that follows carries the bubble
        break;
      case 'user_turn':
        setBusy(true);
        setChat(c => [...c, toItem(e.turn)]);
        break;
      case 'status':
        setChat(c => [...c, {id: nextId++, role: 'status', text: e.text, tool: e.tool}]);
        break;
      case 'message':
        setChat(c => {
          const last = c[c.length - 1];
          if (e.final && readAloudRef.current) speak(e.text);
          if (last?.role === 'agent' && last.streaming) {
            // `final` carries the whole reply again: replace the streamed chunks with it.
            const text = e.final ? e.text : last.text + e.text;
            return [...c.slice(0, -1), {...last, text, streaming: !e.final}];
          }
          return [...c, {id: nextId++, role: 'agent', text: e.text, streaming: !e.final}];
        });
        break;
      case 'error':
        setChat(c => [...c, {id: nextId++, role: 'status', text: `⚠ ${e.text}`}]);
        break;
      case 'turn_end':
        setBusy(false);
        setChat(c => c.map(m => (m.streaming ? {...m, streaming: false} : m)));
        break;
      case 'brief':
        break; // surfaces already carry it; kept for clients that only want the JSON
    }
  }, []);

  useEffect(() => {
    const s = new NavigatorSocket(onEvent, setConnection, newProcessor);
    socketRef.current = s;
    s.connect();
    return () => s.close();
  }, [onEvent, newProcessor]);

  /** Sends a chat turn. The server echoes it back as `user_turn` (with photo and voice links). */
  const ask = useCallback((text: string, extra: {attachments?: string[]; voice?: {id: string; duration: number; source: string}} = {}) => {
    const t = text.trim();
    if (!t && !extra.attachments?.length) return;
    setBusy(true);
    socketRef.current?.send({type: 'user_message', text: t, ...extra});
  }, []);

  /** Applies A2UI messages that came back from a REST call (voice intake fills the form this way). */
  const applyA2ui = useCallback((messages: unknown[]) => {
    processorRef.current?.processMessages(messages as never);
  }, []);

  /** Clicking a citation chip in chat: open its tab and highlight the record (server-side state). */
  const focusRecord = useCallback((requestId: string) => {
    socketRef.current?.action({
      version: '1.0',
      action: {name: 'focus_record', surfaceId: 'case_documents', sourceComponentId: 'chat', timestamp: new Date().toISOString(), context: {request_id: requestId}},
    });
  }, []);

  return useMemo(
    () => ({surfaces, chat, busy, connection, mode, caseId, overlay, setOverlay, toast, flash, errors, ask, focusRecord, applyA2ui, readAloud, setReadAloud, sid}),
    [surfaces, chat, busy, connection, mode, caseId, overlay, toast, flash, errors, ask, focusRecord, applyA2ui, readAloud, setReadAloud, sid],
  );
}
