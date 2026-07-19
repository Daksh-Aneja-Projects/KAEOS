import React, { useCallback, useEffect, useState } from 'react';
import { ShieldAlert, CheckCircle2, XCircle, Clock, Search, Bot, GitBranch, AlertTriangle, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import type { PendingHITLItem } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError } from '../components/BrainStates';

interface ReasoningStep { step: number | string; action: string; confidence?: number }

export default function HITLQueue({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [items, setItems] = useState<PendingHITLItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  // Load failure - without this a failed fetch shows an empty "queue is clear".
  const [loadError, setLoadError] = useState<string | null>(null);
  // Per-item in-flight guard + surfaced failure for approve/reject.
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { lastMessage } = useWebSocket();

  const fetchData = useCallback(async (showSpinner = true) => {
    try {
      if (showSpinner) setLoading(true);
      // One queue: the DB holds every pending approval, including Gate-3
      // pipeline pauses (route_type GATED_AGENT).
      const data = await api.getPendingHITL();
      setItems(data);
      setLoadError(null);
    } catch (error: any) {
      console.error('Failed to load HITL items', error);
      setLoadError(error?.message || 'Failed to load pending approvals.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Live refresh: an agent pausing or a decision landing pushes an activity
  // event over the tenant WebSocket - no polling.
  useEffect(() => {
    const t = JSON.stringify(lastMessage || {});
    if (t.includes('HITL')) fetchData(false);
  }, [lastMessage, fetchData]);

  const runDecision = async (id: string, fn: () => Promise<unknown>) => {
    setActionError(null);
    setBusyId(id);
    try {
      await fn();
      await fetchData(false);
    } catch (e: any) {
      setActionError(e?.message || 'Decision failed. Please retry.');
    } finally {
      setBusyId(null);
    }
  };

  const handleApprove = (id: string) => runDecision(id, () => api.approveHITL(id));

  const handleReject = (id: string) => runDecision(id, () => api.rejectHITL(id));

  const filteredItems = items.filter(i =>
    i.skill_id_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    i.task_intent.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const card: React.CSSProperties = {
    background: colors.surface1,
    border: `1px solid ${colors.hairline}`,
    borderRadius: '14px',
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.warning}, ${colors.warning}99)` }}>
              <ShieldAlert className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Human-In-The-Loop Queue</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                Manage paused agent executions requiring human approval.
              </p>
            </div>
          </div>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input
              type="text"
              placeholder="Search intents…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 pr-4 py-2 rounded-lg text-[13px] w-64 focus:outline-none transition-colors"
              style={{ background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` }}
            />
          </div>
        </div>

        {actionError && (
          <div className="flex items-center justify-between gap-3 rounded-xl px-4 py-3 text-[13px]"
            style={{ background: colors.error + '14', border: `1px solid ${colors.error}33`, color: colors.error }}>
            <span className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 shrink-0" /> {actionError}</span>
            <button onClick={() => setActionError(null)} className="text-[12px] font-medium hover:opacity-70">Dismiss</button>
          </div>
        )}

        <div className="grid gap-4">
          {loading ? (
            <BrainLoading message="Loading pending approvals…" />
          ) : loadError ? (
            <BrainError message={loadError} onRetry={() => fetchData()} />
          ) : filteredItems.length === 0 ? (
            <div style={card} className="text-center py-16">
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3"
                style={{ background: colors.success + '15' }}>
                <Bot className="w-7 h-7" style={{ color: colors.success }} />
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: colors.ink }}>Queue is clear</h3>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                No agents are currently paused for HITL approval.
              </p>
            </div>
          ) : (
            filteredItems.map(item => (
              <div key={item.id} style={card} className="p-6 group">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2.5 mb-2 flex-wrap">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center gap-1"
                        style={{ background: colors.warning + '18', color: colors.warning }}>
                        <Clock className="w-3 h-3" /> Pending Review
                      </span>
                      {item.route_type === 'GATED_AGENT' && (
                        <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center gap-1"
                          style={{ background: colors.primary + '18', color: colors.primary }}>
                          <GitBranch className="w-3 h-3" /> Pipeline Gate
                        </span>
                      )}
                      <span className="text-[12px] font-mono" style={{ color: colors.inkSubtle }}>{item.id.split('-')[0]}</span>
                    </div>
                    <h3 className="text-[18px] font-bold" style={{ color: colors.ink }}>{item.task_intent}</h3>
                    <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                      Skill: <span className="font-mono px-1 rounded" style={{ background: colors.surface2, color: colors.inkMuted }}>{item.skill_id_name}</span>
                      {item.route_type === 'GATED_AGENT' && (
                        <span className="ml-2" style={{ color: colors.primary }}>approving resumes the paused execution</span>
                      )}
                    </p>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => handleReject(item.id)} disabled={busyId === item.id}
                      className="px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-80 flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{ background: colors.error + '15', color: colors.error }}>
                      {busyId === item.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />} Reject
                    </button>
                    <button onClick={() => handleApprove(item.id)} disabled={busyId === item.id}
                      className="px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
                      {busyId === item.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Approve Execution
                    </button>
                  </div>
                </div>

                <div className="mt-6 p-4 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                  <h4 className="text-[11px] font-bold uppercase tracking-wider mb-3" style={{ color: colors.inkSubtle }}>Agent Reasoning Chain</h4>
                  <div className="space-y-2">
                    {(item.reasoning_chain as ReasoningStep[]).map((step, idx: number) => (
                      <div key={idx} className="flex items-center gap-3 text-[13px]">
                        <div className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] shrink-0"
                          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                          {step.step}
                        </div>
                        <span style={{ color: colors.inkMuted }}>{step.action}</span>
                        <span className="font-mono text-[11px] ml-auto" style={{ color: colors.inkTertiary }}>CONF: {step.confidence?.toFixed(2)}</span>
                      </div>
                    ))}
                    <div className="flex items-center gap-3 text-[13px] mt-4 pt-3 border-t" style={{ borderColor: colors.hairline }}>
                      <div className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                        style={{ background: colors.warning + '20', border: `1px solid ${colors.warning}40` }}>
                        <AlertTriangle className="w-3 h-3" style={{ color: colors.warning }} />
                      </div>
                      <span className="font-medium" style={{ color: colors.warning }}>Confidence threshold missed. Human verification required.</span>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
