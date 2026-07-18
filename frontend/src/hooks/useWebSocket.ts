import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface WebSocketMessage {
  type: string;
  [key: string]: any;
}

export function useWebSocket(tenantIdOverride?: string) {
  const { user } = useAuth();
  const tenantId = tenantIdOverride || user?.tenant_id || 'tenant_acme';
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<number | null>(null);
  const isComponentMounted = useRef<boolean>(true);
  const retryRef = useRef<number>(0);

  const connect = useCallback(() => {
    if (!isComponentMounted.current) return;
    
    setStatus('connecting');
    // Derive the WS endpoint from the API base via the shared client helper -
    // VITE_WS_URL still wins when explicitly configured.
    const explicitBase = import.meta.env.VITE_WS_URL;
    const token = localStorage.getItem('kaeos-token');
    const connectionUrl = explicitBase
      ? `${explicitBase}/${tenantId}${token ? `?token=${encodeURIComponent(token)}` : ''}`
      : api.getWebSocketUrl(`/ws/${tenantId}`);
    
    try {
      ws.current = new WebSocket(connectionUrl);
      
      ws.current.onopen = () => {
        if (!isComponentMounted.current) return;
        setStatus('connected');
        console.log('WebSocket connected');
      };
      
      ws.current.onmessage = (event) => {
        if (!isComponentMounted.current) return;
        try {
          const data = JSON.parse(event.data);
          setLastMessage(data);
        } catch (e) {
          console.warn('Failed to parse WebSocket message', event.data);
        }
      };
      
      ws.current.onclose = () => {
        if (!isComponentMounted.current) return;
        setStatus('disconnected');
        // Reconnect with exponential backoff (capped), so an unreachable WS
        // endpoint doesn't spam reconnects. Live data also polls as a fallback,
        // so a missing socket degrades gracefully rather than breaking the UI.
        if (!reconnectTimeout.current) {
          const delay = Math.min(30000, 3000 * Math.pow(2, retryRef.current));
          retryRef.current = Math.min(retryRef.current + 1, 4);
          reconnectTimeout.current = window.setTimeout(() => {
            reconnectTimeout.current = null;
            connect();
          }, delay);
        }
      };

      // Reset backoff once a connection actually opens.
      const prevOpen = ws.current.onopen;
      ws.current.onopen = (ev) => { retryRef.current = 0; (prevOpen as any)?.call(ws.current, ev); };

      ws.current.onerror = () => {
        if (!isComponentMounted.current) return;
        // Do NOT console.error here: a transient/unavailable socket would spam
        // the console on every retry. onclose handles reconnection; live data
        // falls back to polling. Status still reflects the failure for any UI
        // that wants to show it.
        setStatus('error');
      };
    } catch (e) {
      console.error('Failed to create WebSocket', e);
      setStatus('error');
    }
  }, [tenantId]);

  useEffect(() => {
    isComponentMounted.current = true;
    connect();
    
    return () => {
      isComponentMounted.current = false;
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((message: object) => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  return { status, lastMessage, sendMessage };
}
