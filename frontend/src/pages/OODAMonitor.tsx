import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { BrainLoading, BrainEmpty, BrainError, LiveIndicator } from '../components/BrainStates';
import {
  Eye, Compass, Brain, Zap, ArrowRight, CheckCircle, Clock, AlertTriangle,
  Activity, Shield, Users, ChevronRight
} from 'lucide-react';
import { STREAM_INTERVALS } from '../services/realtime';

interface OODAEvent {
  id: string;
  phase: 'OBSERVE' | 'ORIENT' | 'DECIDE' | 'ACT';
  status: 'active' | 'complete' | 'blocked' | 'pending';
  title: string;
  detail: string;
  confidence?: number;
  gate?: string;
  timestamp: string;
}

export default function OODAMonitor({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);

  const [events, setEvents] = useState<OODAEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { status, lastMessage } = useWebSocket();

  // Load initial events from API
  useEffect(() => {
    api.getOODAEvents()
      .then(d => {
        if (d && d.events) {
          setEvents(d.events);
        }
        setLoading(false);
      })
      .catch(e => {
        console.error(e);
        setError("Failed to fetch initial events");
        setLoading(false);
      });
  }, []);

  // Listen to WebSocket for live events
  useEffect(() => {
    if (lastMessage && lastMessage.type === "ooda_event" && lastMessage.event) {
      setEvents(prev => [lastMessage.event as OODAEvent, ...prev].slice(0, 100));
    }
  }, [lastMessage]);

  const empty = events.length === 0;
  const isLive = status === 'connected';
  const staleness = 0;

  const resume = () => { /* WebSocket auto-reconnects */ };

  const phases = [
    { id: 'OBSERVE', label: 'Observe', icon: Eye, color: '#3b82f6', desc: 'Signals + External Intelligence' },
    { id: 'ORIENT', label: 'Orient', icon: Compass, color: '#8b5cf6', desc: 'KG Traversal + Context' },
    { id: 'DECIDE', label: 'Decide', icon: Brain, color: '#f59e0b', desc: 'Strategy + Ethics + Debate' },
    { id: 'ACT', label: 'Act', icon: Zap, color: '#22c55e', desc: 'HITL + Execute + Provenance' },
  ];

  const phaseEvents = (phase: string) => events.filter(e => e.phase === phase);
  const statusColor = (s: string) => s === 'complete' ? '#22c55e' : s === 'active' ? '#f59e0b' : s === 'blocked' ? '#ef4444' : colors.inkSubtle;

  // ── COGNITIVE STATES ──
  if (loading) return <BrainLoading message="Connecting to OODA cognitive loop…" />;
  if (error) return <BrainError message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="p-6 space-y-5" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[18px] font-semibold tracking-tight">OODA Control Loop Monitor</h2>
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
            The cognitive heartbeat of KAEOS - every event flows Observe → Orient → Decide → Act
          </p>
        </div>
        <LiveIndicator isLive={isLive} staleness={staleness} />
      </div>

      {/* OODA Pipeline Visualization */}
      <div className="flex items-center gap-0">
        {phases.map((p, i) => {
          const active = phaseEvents(p.id).some(e => e.status === 'active');
          const count = phaseEvents(p.id).length;
          return (
            <React.Fragment key={p.id}>
              <button onClick={() => setSelectedPhase(selectedPhase === p.id ? null : p.id)}
                className="flex-1 relative rounded-xl p-4 transition-all border"
                style={{
                  background: active ? p.color + '10' : colors.surface1,
                  borderColor: selectedPhase === p.id ? p.color : active ? p.color + '40' : colors.hairline,
                  boxShadow: active ? `0 0 20px ${p.color}15` : 'none'
                }}>
                {active && (
                  <div className="absolute top-2 right-2 w-2 h-2 rounded-full animate-pulse" style={{ background: p.color }} />
                )}
                <div className="flex items-center gap-2 mb-2">
                  {React.createElement(p.icon, { className: 'w-5 h-5', style: { color: p.color } })}
                  <span className="text-[14px] font-bold" style={{ color: p.color }}>{p.label}</span>
                </div>
                <div className="text-[10px] mb-2" style={{ color: colors.inkSubtle }}>{p.desc}</div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                    style={{ background: p.color + '20', color: p.color }}>
                    {count} events
                  </span>
                  {active && (
                    <span className="px-2 py-0.5 rounded-full text-[9px] font-bold animate-pulse"
                      style={{ background: '#f59e0b20', color: '#f59e0b' }}>
                      ACTIVE
                    </span>
                  )}
                </div>
              </button>
              {i < phases.length - 1 && (
                <div className="flex-shrink-0 px-1">
                  <ArrowRight className="w-5 h-5" style={{ color: colors.hairline }} />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Empty State - Brain has no OODA events yet */}
      {empty ? (
        <BrainEmpty
          title="No cognitive loop events yet."
          action="Deploy an agent or connect a signal source to begin the OODA cycle."
          icon={Brain}
        />
      ) : (
        /* Event Timeline */
        <div className="rounded-xl border" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
          <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: colors.hairline }}>
            <h3 className="text-[13px] font-semibold">Event Timeline</h3>
            <div className="flex items-center gap-2 text-[10px]">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: '#22c55e' }} /> Complete</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full animate-pulse" style={{ background: '#f59e0b' }} /> Active</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: colors.inkSubtle }} /> Pending</span>
            </div>
          </div>
          <div className="divide-y" style={{ borderColor: colors.hairline }}>
            {events
              .filter(e => !selectedPhase || e.phase === selectedPhase)
              .map(e => {
                const phase = phases.find(p => p.id === e.phase)!;
                return (
                  <div key={e.id} className="px-4 py-3 flex items-start gap-3 transition-colors hover:bg-canvas/50">
                    {/* Phase Badge */}
                    <div className="flex-shrink-0 mt-0.5">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                        style={{ background: phase.color + '15' }}>
                        {React.createElement(phase.icon, { className: 'w-4 h-4', style: { color: phase.color } })}
                      </div>
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[12px] font-semibold">{e.title}</span>
                        <div className="w-1.5 h-1.5 rounded-full" style={{ background: statusColor(e.status) }} />
                      </div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{e.detail}</div>
                      {/* Gates */}
                      {e.gate && (
                        <div className="flex items-center gap-1.5 mt-1.5">
                          {e.gate === 'DEBATE_REQUIRED' && (
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold" style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                              Debate Engine Active
                            </span>
                          )}
                          {e.gate === 'AUTO_APPROVED' && (
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold" style={{ background: '#22c55e15', color: '#22c55e' }}>
                              ✓ Auto-Approved
                            </span>
                          )}
                          {e.gate === 'HITL_REQUIRED' && (
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>
                              ⚠ Human Review Required
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Confidence + Time */}
                    <div className="flex-shrink-0 text-right">
                      {e.confidence != null && (
                        <div className="text-[12px] font-mono font-bold"
                          style={{ color: e.confidence >= 0.8 ? '#22c55e' : e.confidence >= 0.6 ? '#f59e0b' : '#ef4444' }}>
                          {(e.confidence * 100).toFixed(0)}%
                        </div>
                      )}
                      <div className="text-[9px] font-mono" style={{ color: colors.inkSubtle }}>
                        {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ''}
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
