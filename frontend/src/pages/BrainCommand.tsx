import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Brain, Scale, History, CheckCircle2, XCircle, Clock3, Rocket, Layers,
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useVisiblePoll } from '../hooks/useLiveRefresh';
import BrainProposals, { kindMeta } from '../components/BrainProposals';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

/**
 * The Company Brain's own command surface: pending decisions (the live panel),
 * how the meta-learning currently weighs each kind of idea, and the full
 * decision history with outcomes. Everything here is read from real rows; the
 * only actions are the governed approve / reject the panel already carries.
 */

interface LearningKind {
  signal_kind: string;
  total: number;
  approved: number;
  rejected: number;
  pending: number;
  succeeded: number;
  failed: number;
  acceptance: number | null;
  weight: number;
}

const STATUS_META: Record<string, { label: string; color: string; Icon: any }> = {
  PENDING: { label: 'Awaiting decision', color: '#f59e0b', Icon: Clock3 },
  APPROVED: { label: 'Approved', color: '#22c55e', Icon: CheckCircle2 },
  REJECTED: { label: 'Dismissed', color: '#94a3b8', Icon: XCircle },
  SUPERSEDED: { label: 'Superseded', color: '#94a3b8', Icon: Layers },
};

const FILTERS = ['ALL', 'PENDING', 'APPROVED', 'REJECTED'] as const;

export default function BrainCommand() {
  const { colors } = useTheme();
  const [kinds, setKinds] = useState<LearningKind[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('ALL');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [learning, hist] = await Promise.all([
        api.brainLearning(),
        api.listBrainProposals(filter === 'ALL' ? undefined : filter, 50),
      ]);
      setKinds(learning.kinds || []);
      setHistory(hist.proposals || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { void load(); }, [load]);
  useVisiblePoll(load, 30000);

  const decidedTotal = useMemo(
    () => kinds.reduce((n, k) => n + k.approved + k.rejected, 0), [kinds]);

  return (
    <div className={`${PAGE_PAD} h-full flex flex-col gap-5 overflow-hidden`}
      style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header */}
      <div className="flex items-start gap-3 shrink-0">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
          <Brain className="w-6 h-6 text-white" />
        </div>
        <div className="min-w-0">
          <h1 className="text-[24px] font-bold tracking-tight">Company Brain</h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
            KAEOS proposes its own missions from live operational signals. Nothing runs until you approve it,
            and every approval still passes the seven gates. The brain learns from each decision you make.
          </p>
        </div>
      </div>

      {/* Two columns: pending decisions + how it learns. Inner scrollers only. */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 flex-1 min-h-0">
        <div className="xl:col-span-3 min-h-0 flex flex-col gap-5">
          <BrainProposals onApproved={() => void load()} />

          {/* Decision history */}
          <div className="rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
            style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between gap-3 px-4 py-3 border-b shrink-0 flex-wrap"
              style={{ borderColor: colors.hairline }}>
              <div className="flex items-center gap-2">
                <History className="w-4 h-4" style={{ color: colors.primary }} />
                <span className="text-[14px] font-semibold">Decision history</span>
                <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
                  {decidedTotal} decided so far
                </span>
              </div>
              <div className="flex gap-1.5">
                {FILTERS.map(f => (
                  <button key={f} onClick={() => setFilter(f)}
                    className="px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors"
                    style={{
                      background: filter === f ? colors.primary : colors.surface2,
                      color: filter === f ? '#fff' : colors.inkSubtle,
                      border: `1px solid ${filter === f ? colors.primary : colors.hairline}`,
                    }}>
                    {f === 'ALL' ? 'Everything' : humanize(f)}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto divide-y" style={{ borderColor: colors.hairline }}>
              {loading && history.length === 0 ? (
                <div className="p-6 text-center text-[12px]" style={{ color: colors.inkTertiary }}>
                  Loading the brain's history...
                </div>
              ) : history.length === 0 ? (
                <div className="p-6 text-center text-[12px]" style={{ color: colors.inkTertiary }}>
                  No proposals yet in this view. The brain reflects every few hours, or on demand from the panel above.
                </div>
              ) : history.map(p => {
                const k = kindMeta(p.signal_kind, colors.primary);
                const s = STATUS_META[p.status] || STATUS_META.PENDING;
                return (
                  <div key={p.id} className="px-4 py-3 flex items-start gap-3" style={{ borderColor: colors.hairline }}>
                    <span className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                      style={{ background: `${k.color}18` }}>
                      <k.Icon className="w-3.5 h-3.5" style={{ color: k.color }} />
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[13px] font-semibold truncate">{p.title}</span>
                        <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded"
                          style={{ color: s.color, background: `${s.color}18` }}>
                          <s.Icon className="w-3 h-3" /> {s.label}
                        </span>
                        {p.outcome && (
                          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                            style={{
                              color: p.outcome === 'SUCCEEDED' ? '#22c55e' : '#ef4444',
                              background: p.outcome === 'SUCCEEDED' ? '#22c55e18' : '#ef444418',
                            }}>
                            {p.outcome === 'SUCCEEDED' ? 'Mission succeeded' : 'Mission failed'}
                          </span>
                        )}
                        {p.mission_id && !p.outcome && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded"
                            style={{ color: colors.info, background: `${colors.info}18` }}>
                            <Rocket className="w-3 h-3" /> Mission running
                          </span>
                        )}
                      </div>
                      <p className="text-[12px] mt-0.5 leading-snug line-clamp-2" style={{ color: colors.inkSubtle }}>
                        {p.rationale}
                      </p>
                      {p.decided_by && (
                        <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
                          Decided by {p.decided_by}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* How the brain learns */}
        <div className="xl:col-span-2 rounded-xl overflow-hidden flex flex-col min-h-0"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0" style={{ borderColor: colors.hairline }}>
            <Scale className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-semibold">How it learns</span>
          </div>
          <p className="px-4 pt-3 text-[12px] leading-relaxed shrink-0" style={{ color: colors.inkSubtle }}>
            Each kind of idea earns a weight from your decisions and from how its missions turn out.
            Ideas you keep approving, whose missions succeed, get louder. Ideas you dismiss go quiet.
          </p>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {kinds.length === 0 ? (
              <div className="text-center text-[12px] py-8" style={{ color: colors.inkTertiary }}>
                No learning signal yet. Weights appear once the brain has proposed and you have decided.
              </div>
            ) : kinds.map(k => {
              const meta = kindMeta(k.signal_kind, colors.primary);
              // Weight lives in [0.5, 1.5]; render as a bar with 1.0 marked.
              const pct = Math.max(0, Math.min(1, (k.weight - 0.5)));
              return (
                <div key={k.signal_kind}>
                  <div className="flex items-center gap-2">
                    <meta.Icon className="w-3.5 h-3.5 shrink-0" style={{ color: meta.color }} />
                    <span className="text-[12px] font-semibold flex-1 truncate">{meta.label}</span>
                    <span className="text-[12px] font-mono tabular-nums"
                      style={{ color: k.weight > 1 ? '#22c55e' : k.weight < 1 ? '#f59e0b' : colors.inkSubtle }}>
                      {k.weight.toFixed(2)}x
                    </span>
                  </div>
                  <div className="relative h-1.5 rounded-full mt-1.5 overflow-hidden" style={{ background: colors.surface3 }}>
                    <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-700"
                      style={{ width: `${pct * 100}%`, background: meta.color }} />
                    {/* the neutral 1.0 marker */}
                    <div className="absolute inset-y-0 w-px" style={{ left: '50%', background: colors.hairlineStrong }} />
                  </div>
                  <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
                    {k.approved + k.rejected === 0
                      ? `${k.pending} awaiting a first decision`
                      : `Approved ${k.approved} of ${k.approved + k.rejected}`
                        + (k.succeeded + k.failed > 0
                          ? ` · missions: ${k.succeeded} succeeded, ${k.failed} failed`
                          : '')
                        + (k.pending ? ` · ${k.pending} open` : '')}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
