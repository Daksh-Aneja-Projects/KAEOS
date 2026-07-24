import { useState, useRef, useEffect, useCallback } from 'react';
import { useTheme } from '../context/ThemeContext';
import KaeosLogo from './KaeosLogo';
import {
  MessageSquare, Send, X, Minimize2,
  CheckCircle, XCircle, Loader2, Bot, Zap
} from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  agent_name?: string;
  confidence?: number;
  sources?: string[];
  action?: { type: string; label: string; status: 'pending' | 'approved' | 'rejected' };
  timestamp: Date;
}

interface ChatCopilotProps {
  /** Controlled open state. If omitted, the component manages its own. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onClose?: () => void;
}

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`;

const GREETING: Message = {
  id: 'greeting',
  role: 'system',
  content:
    "Hi, I'm the KAEOS Copilot. Ask me about your agents, rules, skills, deployments, compliance posture, or anything on this screen.",
  agent_name: 'KAEOS',
  timestamp: new Date(),
};

export default function ChatCopilot({ open, onOpenChange, onClose }: ChatCopilotProps) {
  const { colors } = useTheme();
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? !!open : internalOpen;

  const setOpen = useCallback((v: boolean) => {
    if (!isControlled) setInternalOpen(v);
    onOpenChange?.(v);
    if (!v) onClose?.();
  }, [isControlled, onOpenChange, onClose]);

  const [messages, setMessages] = useState<Message[]>([GREETING]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isOpen, minimized]);

  // Focus the input when the panel opens; close on Escape.
  useEffect(() => {
    if (isOpen && !minimized) {
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
      window.addEventListener('keydown', onKey);
      return () => { clearTimeout(t); window.removeEventListener('keydown', onKey); };
    }
  }, [isOpen, minimized, setOpen]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const pendingCount = messages.filter(m => m.role === 'agent').length;

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || isTyping) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`, role: 'user', content: text, timestamp: new Date(),
    };
    const history = [...messages, userMsg];
    setMessages(history);
    setInput('');
    setIsTyping(true);

    const agentMsgId = `a-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), agent_name: 'Analyzing…',
    }]);

    const controller = new AbortController();
    abortRef.current = controller;
    const token = localStorage.getItem('kaeos-token');

    const patchAgent = (patch: Partial<Message>) =>
      setMessages(prev => prev.map(m => (m.id === agentMsgId ? { ...m, ...patch } : m)));

    try {
      const resp = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          messages: history.map(m => ({
            role: m.role === 'agent' ? 'assistant' : m.role,
            content: m.content,
          })),
        }),
        signal: controller.signal,
      });

      if (resp.status === 401 || resp.status === 403) {
        patchAgent({ agent_name: 'System', content: 'Your session has expired. Please sign in again to use the copilot.' });
        setIsTyping(false);
        return;
      }
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentText = '';

      // SSE frames are separated by a blank line ("\n\n"). Buffer partial
      // frames across chunk boundaries and only parse complete ones.
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const dataStr = line.slice(5).trim();
            if (!dataStr) continue;
            let event: any;
            try { event = JSON.parse(dataStr); } catch { continue; }
            if (event.type === 'metadata') {
              patchAgent({ agent_name: event.agent_name, confidence: event.confidence, sources: event.sources });
            } else if (event.type === 'token') {
              currentText += event.text || '';
              patchAgent({ content: currentText });
            } else if (event.type === 'error') {
              currentText += `\n[error: ${event.message}]`;
              patchAgent({ content: currentText });
            }
          }
        }
      }
      if (!currentText) {
        patchAgent({ content: 'No response was returned. Please try rephrasing your question.' });
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        patchAgent({ agent_name: 'System', content: 'Connection failed. Check that the backend is reachable and try again.' });
      }
    } finally {
      setIsTyping(false);
      abortRef.current = null;
    }
  };

  const handleAction = (msgId: string, status: 'approved' | 'rejected') => {
    setMessages(prev => prev.map(m =>
      (m.id === msgId && m.action ? { ...m, action: { ...m.action, status } } : m)));
  };

  // ── Launcher (persistent, always available when the panel is closed) ────────
  if (!isOpen || minimized) {
    return (
      <button
        onClick={() => { setMinimized(false); setOpen(true); }}
        aria-label="Open KAEOS Copilot"
        className="fixed bottom-6 right-6 w-14 h-14 rounded-full shadow-2xl flex items-center justify-center z-50 transition-all hover:scale-110"
        style={{ background: colors.primary }}
      >
        <MessageSquare className="w-6 h-6 text-white" />
        {pendingCount > 0 && (
          <span
            className="absolute -top-1 -right-1 w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center text-white"
            style={{ background: '#ef4444' }}
          >
            {pendingCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="KAEOS Copilot"
      className="fixed bottom-6 right-6 z-50 flex flex-col shadow-2xl rounded-2xl overflow-hidden"
      style={{ width: 420, maxWidth: 'calc(100vw - 2rem)', height: 560, maxHeight: 'calc(100vh - 3rem)', background: colors.canvas, border: `1px solid ${colors.hairline}` }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: colors.primary }}>
            <KaeosLogo className="w-4 h-4" color="#ffffff" />
          </div>
          <div>
            <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>KAEOS Copilot</div>
            <div className="flex items-center gap-1 text-[10px]" style={{ color: '#22c55e' }}>
              <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> Grounded in your workspace
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setMinimized(true)} aria-label="Minimize" className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
            <Minimize2 className="w-4 h-4" />
          </button>
          <button onClick={() => setOpen(false)} aria-label="Close copilot" className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className="max-w-[85%]">
              {msg.role !== 'user' && (
                <div className="flex items-center gap-1.5 mb-1">
                  {msg.role === 'system'
                    ? <KaeosLogo className="w-3 h-3" color="currentColor" />
                    : <Bot className="w-3 h-3" style={{ color: '#8b5cf6' }} />}
                  <span className="text-[10px] font-semibold" style={{ color: colors.inkSubtle }}>
                    {msg.agent_name || 'System'}
                  </span>
                  {typeof msg.confidence === 'number' && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full font-mono" style={{ background: '#22c55e15', color: '#22c55e' }}>
                      {(msg.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              )}
              <div className="px-3 py-2.5 rounded-xl text-[12px] leading-relaxed whitespace-pre-wrap"
                style={{
                  background: msg.role === 'user' ? colors.primary : colors.surface1,
                  color: msg.role === 'user' ? 'white' : colors.ink,
                  border: msg.role === 'user' ? 'none' : `1px solid ${colors.hairline}`,
                }}>
                {msg.content || (msg.role === 'agent' ? '…' : '')}
              </div>

              {msg.sources && msg.sources.length > 0 && (
                <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                  {msg.sources.map((s, i) => (
                    <span key={i} className="text-[9px] px-1.5 py-0.5 rounded-full"
                      style={{ background: colors.primary + '10', color: colors.primary, border: `1px solid ${colors.primary}20` }}>
                      {s}
                    </span>
                  ))}
                </div>
              )}

              {msg.action && (
                <div className="mt-2 p-2.5 rounded-lg" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Zap className="w-3.5 h-3.5" style={{ color: colors.primary }} />
                      <span className="text-[11px] font-medium">{msg.action.label}</span>
                    </div>
                    {msg.action.status === 'pending' ? (
                      <div className="flex gap-1.5">
                        <button onClick={() => handleAction(msg.id, 'approved')} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium" style={{ background: '#22c55e15', color: '#22c55e' }}>
                          <CheckCircle className="w-3 h-3" /> Approve
                        </button>
                        <button onClick={() => handleAction(msg.id, 'rejected')} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium" style={{ background: '#ef444415', color: '#ef4444' }}>
                          <XCircle className="w-3 h-3" /> Reject
                        </button>
                      </div>
                    ) : (
                      <span className="text-[10px] font-bold" style={{ color: msg.action.status === 'approved' ? '#22c55e' : '#ef4444' }}>
                        {msg.action.status === 'approved' ? 'Approved' : 'Rejected'}
                      </span>
                    )}
                  </div>
                </div>
              )}

              <div className="text-[9px] mt-1" style={{ color: colors.inkSubtle }}>
                {msg.timestamp.toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex items-center gap-2 text-[11px]" style={{ color: colors.inkSubtle }}>
            <Loader2 className="w-3 h-3 animate-spin" /> Copilot is thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        className="px-4 py-3 border-t"
        style={{ borderColor: colors.hairline, background: colors.surface1 }}
        onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
      >
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask KAEOS anything…"
            aria-label="Ask the KAEOS copilot a question"
            className="flex-1 px-3 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
            style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
          />
          <button
            type="submit"
            disabled={!input.trim() || isTyping}
            aria-label="Send message"
            className="p-2 rounded-lg transition-all"
            style={{ background: input.trim() && !isTyping ? colors.primary : colors.hairline, color: input.trim() && !isTyping ? 'white' : colors.inkSubtle }}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
}
