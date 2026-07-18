import React, { useState, useRef, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import KaeosLogo from './KaeosLogo';
import {
  MessageSquare, Send, X, Minimize2, Maximize2,
  ChevronDown, CheckCircle, XCircle, AlertTriangle, Loader2,
  Bot, User, Shield, Zap
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

export default function ChatCopilot({ onClose }: { onClose?: () => void }) {
  const { colors } = useTheme();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1', role: 'system', content: 'KAEOS Copilot active. I have access to the full Knowledge Graph, agent fleet, and governance engine. Ask me anything.',
      agent_name: 'KAEOS', timestamp: new Date()
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = () => {
    if (!input.trim()) return;
    const userMsg: Message = {
      id: Date.now().toString(), role: 'user', content: input, timestamp: new Date()
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    // Use Server-Sent Events (SSE) for streaming response
    const fetchStream = async () => {
      try {
        const response = await fetch(`${import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`}/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            // In a real app we would pass Auth token here or use a specific SSE auth method
          },
          body: JSON.stringify({ messages: [...messages, userMsg] })
        });
        
        if (!response.body) throw new Error("No response body");
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        // Add an empty agent message to update as tokens stream in
        const agentMsgId = Date.now().toString();
        let currentText = '';
        
        setMessages(prev => [...prev, {
          id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), agent_name: 'Analyzing...'
        }]);
        
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\\n\\n');
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.replace('data: ', '').trim();
              if (!dataStr) continue;
              
              try {
                const event = JSON.parse(dataStr);
                
                setMessages(prev => prev.map(m => {
                  if (m.id === agentMsgId) {
                    if (event.type === 'metadata') {
                      return {
                        ...m,
                        agent_name: event.agent_name,
                        confidence: event.confidence,
                        sources: event.sources
                      };
                    } else if (event.type === 'token') {
                      currentText += event.text;
                      return { ...m, content: currentText };
                    } else if (event.type === 'done') {
                      setIsTyping(false);
                    }
                  }
                  return m;
                }));
              } catch (e) {
                console.error("SSE parse error", e, dataStr);
              }
            }
          }
        }
      } catch (err) {
        console.error("Chat SSE failed", err);
        setMessages(prev => [...prev, {
          id: Date.now().toString(), role: 'agent', content: 'Connection failed. Please try again.', timestamp: new Date(), agent_name: 'System'
        }]);
        setIsTyping(false);
      }
    };
    
    fetchStream();
  };

  const handleAction = (msgId: string, status: 'approved' | 'rejected') => {
    setMessages(prev => prev.map(m =>
      m.id === msgId && m.action ? { ...m, action: { ...m.action, status } } : m
    ));
  };

  if (minimized) {
    return (
      <button onClick={() => setMinimized(false)}
        className="fixed bottom-6 right-6 w-14 h-14 rounded-full shadow-2xl flex items-center justify-center z-50 transition-all hover:scale-110"
        style={{ background: colors.primary }}>
        <MessageSquare className="w-6 h-6 text-white" />
        <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center text-white" style={{ background: '#ef4444' }}>
          {messages.filter(m => m.role === 'agent').length}
        </span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col shadow-2xl rounded-2xl overflow-hidden"
      style={{ width: 420, height: 560, background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: colors.primary }}>
            <KaeosLogo className="w-4 h-4" color="#ffffff" />
          </div>
          <div>
            <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>KAEOS Copilot</div>
            <div className="flex items-center gap-1 text-[10px]" style={{ color: '#22c55e' }}>
              <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> Connected to Knowledge Graph
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setMinimized(true)} className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
            <Minimize2 className="w-4 h-4" />
          </button>
          {onClose && (
            <button onClick={onClose} className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] ${msg.role === 'user' ? '' : ''}`}>
              {msg.role !== 'user' && (
                <div className="flex items-center gap-1.5 mb-1">
                  {msg.role === 'system' ? (
                    <KaeosLogo className="w-3 h-3" color="currentColor" />
                  ) : (
                    <Bot className="w-3 h-3" style={{ color: '#8b5cf6' }} />
                  )}
                  <span className="text-[10px] font-semibold" style={{ color: colors.inkSubtle }}>
                    {msg.agent_name || 'System'}
                  </span>
                  {msg.confidence && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full font-mono"
                      style={{ background: '#22c55e15', color: '#22c55e' }}>
                      {(msg.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              )}
              <div className="px-3 py-2.5 rounded-xl text-[12px] leading-relaxed"
                style={{
                  background: msg.role === 'user' ? colors.primary : colors.surface1,
                  color: msg.role === 'user' ? 'white' : colors.ink,
                  border: msg.role === 'user' ? 'none' : `1px solid ${colors.hairline}`
                }}>
                {msg.content}
              </div>

              {/* Context Breadcrumbs */}
              {msg.sources && (
                <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                  {msg.sources.map((s, i) => (
                    <span key={i} className="text-[9px] px-1.5 py-0.5 rounded-full"
                      style={{ background: colors.primary + '10', color: colors.primary, border: `1px solid ${colors.primary}20` }}>
                      {s}
                    </span>
                  ))}
                </div>
              )}

              {/* Action Cards */}
              {msg.action && (
                <div className="mt-2 p-2.5 rounded-lg" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Zap className="w-3.5 h-3.5" style={{ color: colors.primary }} />
                      <span className="text-[11px] font-medium">{msg.action.label}</span>
                    </div>
                    {msg.action.status === 'pending' ? (
                      <div className="flex gap-1.5">
                        <button onClick={() => handleAction(msg.id, 'approved')}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium"
                          style={{ background: '#22c55e15', color: '#22c55e' }}>
                          <CheckCircle className="w-3 h-3" /> Approve
                        </button>
                        <button onClick={() => handleAction(msg.id, 'rejected')}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium"
                          style={{ background: '#ef444415', color: '#ef4444' }}>
                          <XCircle className="w-3 h-3" /> Reject
                        </button>
                      </div>
                    ) : (
                      <span className="text-[10px] font-bold"
                        style={{ color: msg.action.status === 'approved' ? '#22c55e' : '#ef4444' }}>
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
            <Loader2 className="w-3 h-3 animate-spin" /> Agent reasoning...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        <div className="flex items-center gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
            placeholder="Ask KAEOS anything..."
            className="flex-1 px-3 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
            style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
          <button onClick={sendMessage}
            className="p-2 rounded-lg transition-all"
            style={{ background: input.trim() ? colors.primary : colors.hairline, color: input.trim() ? 'white' : colors.inkSubtle }}>
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
