/**
 * WebSocket client for the navigator API (api/main.py, WS /ws).
 * Contract: docs/UI_API.md. Server events are plain JSON objects with a `type`.
 */

export type ServerEvent =
  | {type: 'status'; tool?: string; text: string; done?: boolean}
  | {type: 'message'; text: string; final: boolean}
  | {type: 'brief'; brief: Record<string, unknown>}
  | {type: 'error'; text: string}
  | {type: 'a2ui'; messages: unknown[]}
  | {type: 'case'; case_id: string; mode: string; transcript: TranscriptTurn[]}
  | {type: 'user_echo'; text: string}
  | {type: 'turn_end'};

export type TranscriptTurn = {role: 'user' | 'agent' | 'status'; text: string; tool?: string | null; citations?: string[]};

export function sessionId(): string {
  const key = 'a4i.session';
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const id = Math.random().toString(36).slice(2, 14);
    window.localStorage.setItem(key, id);
    return id;
  } catch {
    return Math.random().toString(36).slice(2, 14); // storage blocked: one session per page load
  }
}

export class NavigatorSocket {
  private ws?: WebSocket;
  private closed = false;
  private retry = 0;
  readonly sid = sessionId();

  private onEvent: (e: ServerEvent) => void;
  private onConnection: (state: 'connecting' | 'open' | 'closed') => void;
  /** Called before each (re)connect: the renderer must start from an empty surface set. */
  private onReset: () => void;

  constructor(
    onEvent: (e: ServerEvent) => void,
    onConnection: (state: 'connecting' | 'open' | 'closed') => void,
    onReset: () => void,
  ) {
    this.onEvent = onEvent;
    this.onConnection = onConnection;
    this.onReset = onReset;
  }

  connect(): void {
    this.onConnection('connecting');
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.onReset();
      this.onConnection('open');
      this.send({type: 'hello'});
    };
    ws.onmessage = m => {
      try {
        this.onEvent(JSON.parse(m.data));
      } catch (err) {
        console.error('bad frame', err);
      }
    };
    ws.onclose = () => {
      this.onConnection('closed');
      if (!this.closed) setTimeout(() => this.connect(), Math.min(8000, 500 * 2 ** this.retry++));
    };
  }

  send(frame: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({session_id: this.sid, ...frame}));
  }

  say(text: string): void {
    this.send({type: 'user_message', text});
  }

  /** Forward an A2UI v1.0 renderer-to-agent message ({version, action}). */
  action(message: Record<string, unknown>): void {
    this.send({type: 'a2ui_action', message});
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
