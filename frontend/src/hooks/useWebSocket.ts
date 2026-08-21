import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface WebSocketMessage {
  type: string;
  [key: string]: any;
}

/**
 * M12: ONE shared WebSocket per (tenant) endpoint, fanned out to every hook.
 *
 * useWebSocket used to open a fresh socket per hook instance; with 32 call sites
 * (several per page) that was 32 sockets to the same endpoint. A SharedSocket now
 * multiplexes: the first subscriber opens the connection, the last one closes it,
 * every message fans out to all subscribers, and reconnection backoff is shared.
 * The hook's public contract ({ status, lastMessage, sendMessage }) is unchanged,
 * so no call site changes.
 */
type Sub = {
  onMessage: (m: WebSocketMessage) => void;
  onStatus: (s: WebSocketStatus) => void;
};

class SharedSocket {
  private ws: WebSocket | null = null;
  private subs = new Set<Sub>();
  private status: WebSocketStatus = 'disconnected';
  private reconnectTimer: number | null = null;
  private retry = 0;
  private url: string;
  private protocols: string[];

  constructor(url: string, protocols: string[]) {
    this.url = url;
    this.protocols = protocols;
  }

  private setStatus(s: WebSocketStatus) {
    this.status = s;
    this.subs.forEach((x) => x.onStatus(s));
  }

  private connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    this.setStatus('connecting');
    try {
      this.ws = new WebSocket(this.url, this.protocols);
      this.ws.onopen = () => { this.retry = 0; this.setStatus('connected'); };
      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.subs.forEach((x) => x.onMessage(data));
        } catch {
          console.warn('Failed to parse WebSocket message', event.data);
        }
      };
      this.ws.onclose = () => { this.setStatus('disconnected'); this.scheduleReconnect(); };
      // Do NOT console.error on error: a transient/unavailable socket would spam
      // the console on every retry. onclose handles reconnection; live data falls
      // back to polling. Status still reflects the failure for any UI that shows it.
      this.ws.onerror = () => this.setStatus('error');
    } catch (e) {
      console.error('Failed to create WebSocket', e);
      this.setStatus('error');
    }
  }

  private scheduleReconnect() {
    // Never reconnect while nobody is listening — a closed page must not keep a
    // socket (or its backoff timer) alive.
    if (this.reconnectTimer || this.subs.size === 0) return;
    const delay = Math.min(30000, 3000 * Math.pow(2, this.retry));
    this.retry = Math.min(this.retry + 1, 4);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.subs.size > 0) this.connect();
    }, delay);
  }

  subscribe(sub: Sub): () => void {
    this.subs.add(sub);
    sub.onStatus(this.status);
    if (this.subs.size === 1) this.connect();
    return () => {
      this.subs.delete(sub);
      if (this.subs.size === 0) {
        if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
        this.ws?.close();
        this.ws = null;
      }
    };
  }

  send(message: object): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }
}

const _sockets = new Map<string, SharedSocket>();
function getSharedSocket(url: string, protocols: string[]): SharedSocket {
  let s = _sockets.get(url);
  if (!s) { s = new SharedSocket(url, protocols); _sockets.set(url, s); }
  return s;
}

export function useWebSocket(tenantIdOverride?: string) {
  const { user } = useAuth();
  const tenantId = tenantIdOverride || user?.tenant_id;
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const socketRef = useRef<SharedSocket | null>(null);

  useEffect(() => {
    if (!tenantId) return;
    // The bearer token rides in Sec-WebSocket-Protocol, not the query string
    // (which leaks into logs/history). VITE_WS_URL still wins when configured.
    const explicitBase = import.meta.env.VITE_WS_URL;
    const url = explicitBase ? `${explicitBase}/${tenantId}` : api.getWebSocketUrl(`/ws/${tenantId}`);
    const socket = getSharedSocket(url, api.getWebSocketProtocols() ?? []);
    socketRef.current = socket;
    return socket.subscribe({ onMessage: setLastMessage, onStatus: setStatus });
  }, [tenantId]);

  const sendMessage = useCallback((message: object) => socketRef.current?.send(message) ?? false, []);

  return { status, lastMessage, sendMessage };
}
