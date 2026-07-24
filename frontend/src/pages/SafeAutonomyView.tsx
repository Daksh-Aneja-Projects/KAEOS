/**
 * KAEOS - Safe Autonomy
 * The north-star metric, in detail: the safe-autonomy-rate, an explainable
 * fallout breakdown (why work fell out of autonomy), a per-skill split showing
 * where autonomy leaks, and a daily trend. All from GET /metrics/safe-autonomy
 * (computed live from real executions - never seeded).
 */
import { useEffect, useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { ShieldCheck, UserCheck, Pencil, XCircle, Loader2, RefreshCw } from 'lucide-react';

const WINDOWS = [7, 30, 90];

export default function SafeAutonomyView() {
  const { colors } = useTheme();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = (d: number) => {
    setLoading(true);
    api.getSafeAutonomy(d).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  };
  useEffect(() => { load(days); }, [days]);

  const pct = (r: number | null | undefined) =>
    r == null ? '--' : `${(r * 100).toFixed(1)}%`;
  const rateColor = (r: number | null | undefined) =>
    r == null ? colors.inkSubtle : r >= 0.8 ? '#22c55e' : r >= 0.5 ? '#f59e0b' : '#ef4444';

  const card = { background: colors.surface1, borderRadius: 12, border: `1px solid ${colors.hairline}`, padding: 20 };

  const fallout = data?.fallout || {};
  const falloutCards = [
    { key: 'routed_to_human', label: 'Routed to human', icon: UserCheck, color: '#3b82f6' },
    { key: 'human_overridden', label: 'Human overridden', icon: XCircle, color: '#f59e0b' },
    { key: 'human_edited', label: 'Human edited', icon: Pencil, color: '#8b5cf6' },
    { key: 'failed', label: 'Failed', icon: XCircle, color: '#ef4444' },
  ];

  const ts: any[] = data?.timeseries || [];
  const maxTotal = Math.max(1, ...ts.map(t => t.total || 0));

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[24px] font-bold tracking-tight flex items-center gap-2">
              <ShieldCheck className="w-6 h-6" style={{ color: colors.primary }} /> Safe Autonomy
            </h1>
            <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
              The share of work completed safely without a human, computed live from real executions.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 p-1 rounded-lg" style={{ background: colors.surface1 }}>
              {WINDOWS.map(w => (
                <button key={w} onClick={() => setDays(w)}
                  className="px-2.5 py-1 rounded-md text-[12px] font-medium"
                  style={{ background: days === w ? colors.canvas : 'transparent', color: days === w ? colors.primary : colors.inkSubtle }}>
                  {w}d
                </button>
              ))}
            </div>
            <button onClick={() => load(days)} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {loading && !data ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
          </div>
        ) : !data || (data.total_executions || 0) === 0 ? (
          <div style={card} className="text-center py-16">
            <div className="text-[15px] font-semibold mb-1">No executions in this window</div>
            <div className="text-[13px]" style={{ color: colors.inkSubtle }}>
              Safe-autonomy-rate appears once agents have run. Try a wider window.
            </div>
          </div>
        ) : (
          <>
            {/* Headline + counts */}
            <div className="grid grid-cols-4 gap-4">
              <div style={{ ...card, gridColumn: 'span 2' }}>
                <div className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Safe Autonomy Rate</div>
                <div className="text-[56px] font-bold leading-tight" style={{ color: rateColor(data.safe_autonomy_rate) }}>
                  {pct(data.safe_autonomy_rate)}
                </div>
                <div className="text-[12px]" style={{ color: colors.inkSubtle }}>
                  {data.safe_autonomous} of {data.total_executions} executions ran safely without a human
                </div>
              </div>
              <div style={card}>
                <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Total Executions</div>
                <div className="text-[28px] font-bold">{data.total_executions}</div>
              </div>
              <div style={card}>
                <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Safe Autonomous</div>
                <div className="text-[28px] font-bold" style={{ color: '#22c55e' }}>{data.safe_autonomous}</div>
              </div>
            </div>

            {/* Fallout breakdown */}
            <div>
              <h3 className="text-[14px] font-bold mb-3">Where autonomy fell out</h3>
              <div className="grid grid-cols-4 gap-4">
                {falloutCards.map(f => (
                  <div key={f.key} style={card} className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: f.color + '18' }}>
                      <f.icon className="w-5 h-5" style={{ color: f.color }} />
                    </div>
                    <div>
                      <div className="text-[22px] font-bold">{fallout[f.key] ?? 0}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{f.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Per-skill split */}
            <div style={card}>
              <h3 className="text-[14px] font-bold mb-3">Per-skill safe autonomy</h3>
              <div className="space-y-2">
                {(data.by_skill || []).slice(0, 12).map((s: any) => (
                  <div key={s.skill} className="flex items-center gap-3">
                    <div className="text-[12px] font-medium w-56 truncate">{s.skill}</div>
                    <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full" style={{
                        width: `${(s.safe_autonomy_rate ?? 0) * 100}%`,
                        background: rateColor(s.safe_autonomy_rate),
                      }} />
                    </div>
                    <div className="text-[12px] font-mono w-14 text-right" style={{ color: rateColor(s.safe_autonomy_rate) }}>
                      {pct(s.safe_autonomy_rate)}
                    </div>
                    <div className="text-[11px] w-16 text-right" style={{ color: colors.inkSubtle }}>{s.total} runs</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Daily trend */}
            {ts.length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-3">Daily trend</h3>
                <div className="flex items-end gap-1 h-28">
                  {ts.map((t: any, i: number) => (
                    <div key={i} className="flex-1 flex flex-col items-center justify-end gap-1" title={`${t.date}: ${pct(t.safe_autonomy_rate)} (${t.total} runs)`}>
                      <div className="w-full rounded-t" style={{
                        height: `${Math.max(4, ((t.total || 0) / maxTotal) * 100)}%`,
                        background: rateColor(t.safe_autonomy_rate),
                        opacity: 0.85,
                      }} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{data.note}</p>
          </>
        )}
      </div>
    </div>
  );
}
