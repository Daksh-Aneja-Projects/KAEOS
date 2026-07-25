import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { History, Loader2, Undo2, Check, X, AlertTriangle } from 'lucide-react';

/**
 * Enterprise Time Machine (IP-3). Scrub the real decision history: a slider
 * reconstructs the safe-autonomy-rate AS OF any past moment, and selecting a
 * decision runs a real counterfactual — recomputing the north-star with that one
 * decision flipped (approve / fail / escalate). All from real execution rows.
 */
const KLASS_COLOR: Record<string, string> = {
  safe_autonomous: '#22c55e', routed_to_human: '#f59e0b', overridden: '#ef4444',
  failed: '#ef4444', edited: '#8b5cf6', other: '#6b7280',
};

const TimeMachinePanel: React.FC<{ colors: any; onImpact?: (event: any, cf?: any) => void }> = ({ colors, onImpact }) => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [idx, setIdx] = useState(0);              // scrubber position over chronological events
  const [asOf, setAsOf] = useState<any>(null);
  const [selected, setSelected] = useState<any>(null);
  const [cf, setCf] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.getDecisionTimeline(60, 300)
      .then(d => { setData(d); setIdx((d.events || []).length); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  // Events come newest-first; build a chronological copy for the scrubber.
  const chrono = useMemo(() => [...(data?.events || [])].reverse(), [data]);

  const scrubTo = async (n: number) => {
    setIdx(n);
    const point = chrono[Math.max(0, n - 1)];
    if (point?.at) {
      try { setAsOf(await api.getStateAsOf(point.at, 60)); } catch { /* ignore */ }
    } else {
      setAsOf(null);
    }
  };

  const runCf = async (flip: 'approve' | 'fail' | 'escalate') => {
    if (!selected) return;
    setBusy(flip);
    try {
      const cfResult = await api.runCounterfactual(selected.execution_id, flip, 60);
      setCf(cfResult);
      onImpact?.(selected, { ...cfResult, flip });
    }
    catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  if (loading) return <div className="flex items-center gap-2 text-[12px] py-6" style={{ color: colors.inkSubtle }}><Loader2 className="w-4 h-4 animate-spin" /> Loading decision history…</div>;
  if (!data || data.total === 0) return <div className="text-[12px] py-6" style={{ color: colors.inkSubtle }}>No decision history yet. Run some governed executions and replay them here.</div>;

  const total = chrono.length;
  const rate = asOf?.safe_autonomy_rate ?? data.current_rate;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <History className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[13px] font-semibold" style={{ color: colors.ink }}>Time Machine</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: colors.primary + '18', color: colors.primary }}>{data.total} decisions</span>
      </div>

      {/* Scrubber: reconstruct the north-star as of any moment */}
      <div className="rounded-lg p-3" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Rewind the org</span>
          <span className="text-[18px] font-bold" style={{ color: rate == null ? colors.inkSubtle : rate >= 0.7 ? '#22c55e' : rate >= 0.4 ? '#f59e0b' : '#ef4444' }}>
            {rate == null ? '--' : `${(rate * 100).toFixed(0)}%`}
          </span>
        </div>
        <input type="range" min={1} max={total} value={idx} onChange={e => scrubTo(parseInt(e.target.value))}
          className="w-full" style={{ accentColor: colors.primary }} />
        <div className="flex justify-between text-[10px]" style={{ color: colors.inkTertiary }}>
          <span>oldest</span>
          <span>{asOf?.decisions_so_far != null ? `${asOf.decisions_so_far} of ${data.total} decisions` : 'now'}</span>
          <span>now</span>
        </div>
        <p className="text-[10px] mt-1" style={{ color: colors.inkSubtle }}>
          Safe-autonomy-rate reconstructed from every decision up to this point in time.
        </p>
      </div>

      {/* Recent decisions — click one to run a counterfactual */}
      <div>
        <div className="text-[11px] uppercase tracking-wide font-semibold mb-1.5" style={{ color: colors.inkSubtle }}>Decisions (pick one to rewrite)</div>
        <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
          {(data.events || []).slice(0, 40).map((e: any) => (
            <button key={e.execution_id} onClick={() => { setSelected(e); setCf(null); onImpact?.(e); }}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left"
              style={{ background: selected?.execution_id === e.execution_id ? colors.surface2 : 'transparent', border: `1px solid ${selected?.execution_id === e.execution_id ? colors.hairline : 'transparent'}` }}>
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: KLASS_COLOR[e.klass] || '#6b7280' }} />
              <span className="text-[11px] flex-1 truncate" style={{ color: colors.ink }}>{e.skill_id}</span>
              <span className="text-[9px]" style={{ color: colors.inkSubtle }}>{e.department}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Counterfactual */}
      {selected && (
        <div className="rounded-lg p-3" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
          <div className="text-[12px] font-medium mb-1" style={{ color: colors.ink }}>{selected.skill_id}</div>
          <div className="text-[10px] mb-2" style={{ color: colors.inkSubtle }}>
            was <span style={{ color: KLASS_COLOR[selected.klass] }}>{selected.klass.replace('_', ' ')}</span>. What if it…
          </div>
          <div className="flex gap-1.5">
            <button onClick={() => runCf('approve')} disabled={busy === 'approve'}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold" style={{ background: '#22c55e18', color: '#22c55e' }}>
              <Check className="w-3 h-3" /> ran clean
            </button>
            <button onClick={() => runCf('escalate')} disabled={busy === 'escalate'}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold" style={{ background: '#f59e0b18', color: '#f59e0b' }}>
              <AlertTriangle className="w-3 h-3" /> escalated
            </button>
            <button onClick={() => runCf('fail')} disabled={busy === 'fail'}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold" style={{ background: '#ef444418', color: '#ef4444' }}>
              <X className="w-3 h-3" /> failed
            </button>
          </div>
          {cf && (
            <div className="mt-3 flex items-center gap-3">
              <div className="text-center">
                <div className="text-[16px] font-bold" style={{ color: colors.inkSubtle }}>{cf.before_rate == null ? '--' : `${(cf.before_rate * 100).toFixed(0)}%`}</div>
                <div className="text-[9px]" style={{ color: colors.inkTertiary }}>actual</div>
              </div>
              <Undo2 className="w-4 h-4" style={{ color: colors.inkSubtle }} />
              <div className="text-center">
                <div className="text-[16px] font-bold" style={{ color: (cf.delta ?? 0) > 0 ? '#22c55e' : (cf.delta ?? 0) < 0 ? '#ef4444' : colors.ink }}>
                  {cf.after_rate == null ? '--' : `${(cf.after_rate * 100).toFixed(0)}%`}
                </div>
                <div className="text-[9px]" style={{ color: colors.inkTertiary }}>counterfactual</div>
              </div>
              {cf.delta != null && (
                <span className="text-[11px] font-semibold" style={{ color: cf.delta > 0 ? '#22c55e' : cf.delta < 0 ? '#ef4444' : colors.inkSubtle }}>
                  {cf.delta > 0 ? '+' : ''}{(cf.delta * 100).toFixed(1)} pts
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default TimeMachinePanel;
