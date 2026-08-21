import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Brain, Sparkles, Check, X, Loader2, TrendingDown, DollarSign,
  GitBranch, XCircle, BookOpen, RefreshCw, ShieldCheck, PlugZap,
  Hourglass, Dna,
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useVisiblePoll } from '../hooks/useLiveRefresh';

/**
 * Company Brain — the surface where KAEOS proposes its OWN missions.
 *
 * The brain reflects on operational reality (safe-autonomy decline, cost spikes,
 * systems-of-record drift, recurring mission failures, a knowledge backlog) and
 * proposes a governed mission. A proposal carries no authority: an operator
 * approves it (which spawns a mission through the same 7 gates) or rejects it
 * (which the brain remembers as a 'no'). This panel is that human review.
 *
 * onApproved refreshes the host's mission list so the spawned mission appears.
 */

type Kind = 'AUTONOMY_DECLINE' | 'COST_SPIKE' | 'SOR_DRIFT' | 'MISSION_FAILURES'
  | 'KNOWLEDGE_BACKLOG' | 'CONNECTOR_STALE' | 'KNOWLEDGE_DECAY' | 'STRATEGIC_FITNESS';

// Exported: the Brain page shares this vocabulary for its history + learning views.
export const KIND: Record<Kind, { label: string; color: string; Icon: any }> = {
  AUTONOMY_DECLINE: { label: 'Autonomy declining', color: '#f59e0b', Icon: TrendingDown },
  COST_SPIKE: { label: 'Cost spiking', color: '#ef4444', Icon: DollarSign },
  SOR_DRIFT: { label: 'Systems drifted', color: '#8b5cf6', Icon: GitBranch },
  MISSION_FAILURES: { label: 'Missions failing', color: '#ef4444', Icon: XCircle },
  KNOWLEDGE_BACKLOG: { label: 'Knowledge backlog', color: '#3b82f6', Icon: BookOpen },
  CONNECTOR_STALE: { label: 'Connectors stalled', color: '#f97316', Icon: PlugZap },
  KNOWLEDGE_DECAY: { label: 'Knowledge expiring', color: '#eab308', Icon: Hourglass },
  STRATEGIC_FITNESS: { label: 'Structural opportunity', color: '#10b981', Icon: Dna },
};

export const kindMeta = (k: string, fallbackColor: string) =>
  KIND[k as Kind] || { label: k, color: fallbackColor, Icon: Sparkles };

// rAF count-up so the priority reads as a live meter, not a static number.
function useCountUp(target: number, ms = 700) {
  const [v, setV] = useState(0);
  const raf = useRef<number | undefined>(undefined);
  useEffect(() => {
    const start = performance.now();
    const from = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      setV(from + (target - from) * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [target, ms]);
  return v;
}

function PriorityRing({ value, color }: { value: number; color: string }) {
  const pct = useCountUp(value);
  const R = 15, C = 2 * Math.PI * R;
  return (
    <div className="relative shrink-0" style={{ width: 40, height: 40 }} aria-label={`Priority ${Math.round(value * 100)} percent`}>
      <svg width="40" height="40" viewBox="0 0 40 40">
        <circle cx="20" cy="20" r={R} fill="none" stroke="currentColor" strokeWidth="3" opacity="0.15" />
        <circle cx="20" cy="20" r={R} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct)} transform="rotate(-90 20 20)" />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums">
        {Math.round(pct * 100)}
      </div>
    </div>
  );
}

export default function BrainProposals({ onApproved }: { onApproved?: (missionId?: string) => void }) {
  const { colors } = useTheme();
  const [proposals, setProposals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [reflecting, setReflecting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.listBrainProposals('PENDING');
      setProposals(d.proposals || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // The scheduler reflects every 6h in the background; keep the panel live
  // without a second WebSocket (see useLiveRefresh's own guidance).
  useVisiblePoll(load, 30000);

  const reflect = async () => {
    setReflecting(true); setNote(null);
    try {
      const r = await api.brainReflect();
      await load();
      setNote(r.proposed > 0
        ? `The brain raised ${r.proposed} new proposal${r.proposed === 1 ? '' : 's'}.`
        : 'The brain reviewed the signals and had nothing new to propose.');
    } catch (e) { console.error(e); setNote('Reflection failed. Try again.'); }
    finally { setReflecting(false); }
  };

  const approve = async (id: string) => {
    setBusy(id);
    try {
      const r = await api.approveBrainProposal(id);
      setProposals(p => p.filter(x => x.id !== id));
      setNote('Approved. A governed mission is now planned; every step runs through the gates.');
      onApproved?.(r?.mission_id);
    } catch (e) { console.error(e); setNote('Could not approve that proposal.'); }
    finally { setBusy(null); }
  };

  const reject = async (id: string) => {
    setBusy(id);
    try {
      await api.rejectBrainProposal(id);
      setProposals(p => p.filter(x => x.id !== id));
      setNote('Dismissed. The brain will not raise the same idea for a while.');
    } catch (e) { console.error(e); setNote('Could not dismiss that proposal.'); }
    finally { setBusy(null); }
  };

  const kindOf = (k: string) => kindMeta(k, colors.primary);

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b" style={{ borderColor: colors.hairline }}>
        <div className="relative w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}88)` }}>
          <Brain className="w-5 h-5 text-white" />
          {reflecting && (
            <span className="absolute inset-0 rounded-lg animate-ping" style={{ background: colors.primary, opacity: 0.35 }} />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-[15px] font-bold tracking-tight">Company Brain</h2>
            <span className="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
              style={{ color: colors.inkSubtle, background: colors.canvas }}>
              // proposes, you decide
            </span>
          </div>
          <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
            {reflecting ? 'Reflecting on the operational signals...'
              : proposals.length > 0
                ? `${proposals.length} proposal${proposals.length === 1 ? '' : 's'} await your decision. Nothing runs until you approve.`
                : 'No open proposals. The brain reflects on a cadence, or on demand.'}
          </p>
        </div>
        <button onClick={reflect} disabled={reflecting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold shrink-0 transition-opacity"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink, opacity: reflecting ? 0.6 : 1 }}>
          {reflecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Reflect now
        </button>
      </div>

      {note && (
        <div className="px-4 py-2 text-[12px] flex items-center gap-2 border-b"
          style={{ borderColor: colors.hairline, color: colors.inkSubtle, background: colors.canvas }}>
          <ShieldCheck className="w-3.5 h-3.5" style={{ color: colors.primary }} /> {note}
        </div>
      )}

      {/* Proposal list — contained scroller so the page stays single-view */}
      {loading ? (
        <div className="p-6 flex items-center justify-center text-[12px]" style={{ color: colors.inkTertiary }}>
          <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading the brain...
        </div>
      ) : proposals.length === 0 ? (
        <div className="p-6 text-center text-[12px]" style={{ color: colors.inkTertiary }}>
          Nothing to review. When a metric drifts or missions start failing, the brain will propose a fix here.
        </div>
      ) : (
        <div className="max-h-[280px] overflow-y-auto divide-y" style={{ borderColor: colors.hairline }}>
          {proposals.map(p => {
            const k = kindOf(p.signal_kind);
            return (
              <div key={p.id} className="px-4 py-3 flex items-start gap-3" style={{ borderColor: colors.hairline }}>
                <PriorityRing value={p.priority || 0} color={k.color} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded"
                      style={{ color: k.color, background: `${k.color}18` }}>
                      <k.Icon className="w-3 h-3" /> {k.label}
                    </span>
                    <span className="text-[13px] font-semibold truncate">{p.title}</span>
                  </div>
                  <p className="text-[12px] mt-1 leading-snug" style={{ color: colors.inkSubtle }}>{p.rationale}</p>
                  {Array.isArray(p.evidence) && p.evidence.length > 0 && (
                    <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                      {p.evidence.slice(0, 2).map((ev: any, i: number) => (
                        <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                          style={{ color: colors.inkTertiary, background: colors.canvas }}>
                          {ev.detail}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => approve(p.id)} disabled={busy === p.id}
                    title="Approve — plan a governed mission from this proposal"
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[12px] font-semibold text-white transition-opacity"
                    style={{ background: '#22c55e', opacity: busy === p.id ? 0.5 : 1 }}>
                    {busy === p.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                    Approve
                  </button>
                  <button onClick={() => reject(p.id)} disabled={busy === p.id}
                    title="Dismiss — the brain suppresses this idea for a cooldown"
                    className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors"
                    style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
