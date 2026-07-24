import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, HeartPulse, Hourglass, Loader2, OctagonAlert, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import type { OrgPulse as OrgPulsePayload, SLABreach, WorkflowEvent } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainIcon from '../components/DomainIcon';
import LiveBadge from '../components/LiveBadge';
import { timeAgo } from '../lib/time';

/**
 * Org Pulse - the cross-domain layer above the 7 department views.
 * One screen answering "how is the whole company doing right now":
 * org health ring, per-domain health grid (click-through), unified
 * severity-ranked insight feed, and the live workflow activity stream.
 * Live: every workflow transition broadcast re-loads this page.
 */

const healthColor = (h: number | null) =>
  h === null ? '#6b7280' : h >= 80 ? '#22c55e' : h >= 50 ? '#f59e0b' : '#ef4444';

const DOMAIN_LABEL: Record<string, string> = {
  finance: 'Finance', hr: 'Human Resources', sales: 'Sales & CRM',
  support: 'Customer Support', operations: 'Operations', legal: 'Legal',
  engineering: 'Engineering',
};

const DOMAIN_ROUTE: Record<string, string> = {
  finance: '/departments/finance', hr: '/departments/hr', sales: '/departments/sales',
  support: '/departments/support', operations: '/departments/operations',
  legal: '/departments/legal', engineering: '/departments/engineering',
};

const fmtKpi = (v: number | null, format: string) => {
  if (v === null || v === undefined) return '-';
  if (format === 'currency') return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : v >= 10_000 ? `$${(v / 1_000).toFixed(0)}K` : `$${Math.round(v).toLocaleString()}`;
  if (format === 'percent') return `${v.toFixed(0)}%`;
  if (format === 'hours') return v >= 48 ? `${(v / 24).toFixed(1)}d` : `${v.toFixed(1)}h`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
};

/**
 * Precog forecast chart: the safe-autonomy history line, the projected trend, and
 * a 95% confidence band, drawn from the real /metrics/forecast series. Honest about
 * thin history (shows an insufficient-data note instead of a fabricated curve).
 */
const ForecastSection: React.FC<{ forecast: any; colors: any }> = ({ forecast, colors }) => {
  const sar = forecast?.safe_autonomy;
  const headline = forecast?.headline;
  const W = 720, H = 180, PAD = 24;
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  if (!forecast || !sar || sar.insufficient) {
    return (
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <h2 className="text-[13px] font-bold mb-1 flex items-center gap-1.5">
          <Activity className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Precog — Safe-Autonomy Forecast
        </h2>
        <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
          {sar?.reason ? `Not enough history yet to forecast (${sar.reason}). Run more governed executions across a few days and a trend will appear here.`
            : 'Forecast will appear once there is enough daily history.'}
        </p>
      </div>
    );
  }

  const hist = (sar.history || []).filter((p: any) => p.y !== null);
  const fc = sar.forecast || [];
  const lastHist = hist[hist.length - 1];
  const allT = [...hist.map((p: any) => p.t), ...fc.map((p: any) => p.t)];
  const tMin = Math.min(...allT), tMax = Math.max(...allT);
  const yVals = [...hist.map((p: any) => p.y), ...fc.flatMap((p: any) => [p.lo, p.hi])];
  const yMin = Math.max(0, Math.min(...yVals) - 0.05);
  const yMax = Math.min(1, Math.max(...yVals) + 0.05);
  const sx = (t: number) => PAD + ((t - tMin) / Math.max(1, tMax - tMin)) * (W - 2 * PAD);
  const sy = (y: number) => H - PAD - ((y - yMin) / Math.max(0.001, yMax - yMin)) * (H - 2 * PAD);

  // Unified, hover-addressable point set with real date labels.
  const dates: string[] = forecast.dates || [];
  const lastDate = dates.length ? new Date(dates[dates.length - 1]) : null;
  const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const points = [
    ...hist.map((p: any) => ({ t: p.t, val: p.y, lo: null, hi: null, kind: 'observed',
      label: dates[p.t] ? fmtDate(new Date(dates[p.t])) : `day ${p.t}` })),
    ...fc.map((p: any) => {
      let label = `+${p.t - lastHist.t}d`;
      if (lastDate) { const d = new Date(lastDate); d.setDate(d.getDate() + (p.t - lastHist.t)); label = fmtDate(d); }
      return { t: p.t, val: p.yhat, lo: p.lo, hi: p.hi, kind: 'forecast', label };
    }),
  ];

  const histPath = hist.map((p: any, i: number) => `${i ? 'L' : 'M'}${sx(p.t)},${sy(p.y)}`).join(' ');
  const fcLine = [lastHist, ...fc].map((p: any, i: number) => `${i ? 'L' : 'M'}${sx(p.t)},${sy(p.yhat ?? p.y)}`).join(' ');
  const bandTop = [lastHist, ...fc].map((p: any, i: number) => `${i ? 'L' : 'M'}${sx(p.t)},${sy(p.hi ?? p.y)}`).join(' ');
  const bandBot = [...fc].reverse().map((p: any) => `L${sx(p.t)},${sy(p.lo)}`).join(' ') + ` L${sx(lastHist.t)},${sy(lastHist.y)}`;

  const dirColor = headline?.direction === 'improving' ? '#22c55e' : headline?.direction === 'declining' ? '#ef4444' : '#f59e0b';

  const onMove = (e: React.MouseEvent) => {
    const el = wrapRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const fracX = (e.clientX - rect.left) / rect.width;            // 0..1 across svg width
    const targetT = tMin + fracX * (tMax - tMin);
    let best = 0, bestD = Infinity;
    points.forEach((p, i) => { const d = Math.abs(p.t - targetT); if (d < bestD) { bestD = d; best = i; } });
    setHover(best);
  };

  const hp = hover != null ? points[hover] : null;
  const hx = hp ? sx(hp.t) : 0;
  const hy = hp ? sy(hp.val) : 0;

  return (
    <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <style>{`
        @keyframes precogDraw { from { stroke-dashoffset: 1200; } to { stroke-dashoffset: 0; } }
        @keyframes precogFade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes precogPulse { 0%,100% { r: 4; opacity: .9 } 50% { r: 7; opacity: .35 } }
        .precog-hist { stroke-dasharray: 1200; animation: precogDraw 1.1s ease-out forwards; }
        .precog-band { animation: precogFade 1.2s ease-out both; }
        .precog-now { animation: precogPulse 1.8s ease-in-out infinite; }
      `}</style>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h2 className="text-[13px] font-bold flex items-center gap-1.5">
            <Activity className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Precog — Safe-Autonomy Forecast
            <span className="flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full ml-1"
              style={{ background: '#8b5cf618', color: '#8b5cf6' }}>
              <span className="w-1.5 h-1.5 rounded-full precog-now inline-block" style={{ background: '#8b5cf6' }} /> LIVE
            </span>
          </h2>
          <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
            Projected {forecast.horizon_days} days out, with a 95% confidence band. Trend fit R² {(headline?.confidence_r2 ?? 0).toFixed(2)}. Hover the line to inspect any day.
          </p>
        </div>
        {headline?.projected_rate != null && (
          <div className="text-right">
            <div className="text-[20px] font-bold" style={{ color: dirColor }}>
              {(headline.projected_rate * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
              {headline.direction || 'projected'}{headline.current_rate != null ? ` from ${(headline.current_rate * 100).toFixed(0)}%` : ''}
            </div>
          </div>
        )}
      </div>
      <div className="relative" ref={wrapRef} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        style={{ cursor: 'crosshair' }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full block" style={{ minWidth: 480 }}>
          <path className="precog-band" d={`${bandTop} ${bandBot} Z`} fill="#8b5cf6" opacity={0.14} />
          <path className="precog-hist" d={histPath} fill="none" stroke={colors.primary} strokeWidth={2} strokeLinejoin="round" />
          <path d={fcLine} fill="none" stroke="#8b5cf6" strokeWidth={2} strokeDasharray="5 4" opacity={0.9} />
          <line x1={sx(lastHist.t)} y1={PAD} x2={sx(lastHist.t)} y2={H - PAD} stroke={colors.hairline} strokeDasharray="2 3" />
          {/* the pulsing "now" marker at the history/forecast boundary */}
          <circle className="precog-now" cx={sx(lastHist.t)} cy={sy(lastHist.y)} r={4} fill="#8b5cf6" />
          {hist.map((p: any) => <circle key={`h${p.t}`} cx={sx(p.t)} cy={sy(p.y)} r={2.5} fill={colors.primary} />)}
          {/* hover crosshair + highlighted point */}
          {hp && (
            <g>
              <line x1={hx} y1={PAD} x2={hx} y2={H - PAD} stroke={colors.inkSubtle} strokeOpacity={0.5} strokeDasharray="3 3" />
              <circle cx={hx} cy={hy} r={4.5} fill={hp.kind === 'forecast' ? '#8b5cf6' : colors.primary}
                stroke={colors.surface1} strokeWidth={2} />
            </g>
          )}
        </svg>
        {/* tooltip, positioned as a % of container width so it tracks the responsive svg */}
        {hp && (
          <div className="absolute pointer-events-none px-2.5 py-1.5 rounded-lg text-[11px] shadow-lg"
            style={{
              left: `${(hx / W) * 100}%`, top: `${(hy / H) * 100}%`,
              transform: `translate(${hx > W * 0.7 ? '-110%' : '12px'}, -50%)`,
              background: colors.canvas, border: `1px solid ${colors.hairline}`, whiteSpace: 'nowrap', zIndex: 5,
            }}>
            <div className="font-semibold" style={{ color: colors.ink }}>{hp.label}</div>
            <div style={{ color: hp.kind === 'forecast' ? '#8b5cf6' : colors.primary }}>
              {(hp.val * 100).toFixed(1)}% {hp.kind === 'forecast' ? 'projected' : 'observed'}
            </div>
            {hp.kind === 'forecast' && hp.lo != null && (
              <div className="text-[10px]" style={{ color: colors.inkSubtle }}>
                95% band {(hp.lo * 100).toFixed(0)}–{(hp.hi * 100).toFixed(0)}%
              </div>
            )}
          </div>
        )}
      </div>
      <div className="flex items-center gap-4 mt-2 text-[10px]" style={{ color: colors.inkSubtle }}>
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 inline-block" style={{ background: colors.primary }} /> observed</span>
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 inline-block" style={{ background: '#8b5cf6' }} /> forecast</span>
        <span className="flex items-center gap-1"><span className="w-3 h-2 inline-block rounded-sm" style={{ background: '#8b5cf6', opacity: 0.2 }} /> 95% band</span>
      </div>
    </div>
  );
};

const OrgPulse: React.FC<{ domain?: string }> = () => {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [pulse, setPulse] = useState<OrgPulsePayload | null>(null);
  const [activity, setActivity] = useState<WorkflowEvent[]>([]);
  const [stale, setStale] = useState<SLABreach[]>([]);
  const [loading, setLoading] = useState(true);
  const [escalating, setEscalating] = useState(false);
  const [escalateMsg, setEscalateMsg] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [forecast, setForecast] = useState<any>(null);

  const load = useCallback(async () => {
    const [p, a, s, f] = await Promise.allSettled([
      api.getOrgPulse(), api.getOrgActivity(30), api.getOrgStale(), api.getForecast(45, 14),
    ]);
    if (p.status === 'fulfilled') setPulse(p.value);
    if (a.status === 'fulfilled') setActivity(a.value || []);
    if (s.status === 'fulfilled') setStale(s.value?.breaches || []);
    if (f.status === 'fulfilled') setForecast(f.value);
    setLastSync(Date.now());
    setLoading(false);
  }, []);

  const escalateAll = async () => {
    setEscalating(true); setEscalateMsg('');
    try {
      const res = await api.escalateStale();
      setEscalateMsg(res.escalated > 0
        ? `Escalated ${res.escalated} breach${res.escalated === 1 ? '' : 'es'} to the activity feed${res.skipped_open ? ` (${res.skipped_open} already open)` : ''}.`
        : `Nothing new to escalate - ${res.skipped_open} breach${res.skipped_open === 1 ? '' : 'es'} already have open alerts.`);
      await load();
    } catch (e: any) {
      setEscalateMsg(`Escalation failed: ${e?.message || e}`);
    } finally {
      setEscalating(false);
    }
  };

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load);

  if (loading) {
    return <div className="flex items-center justify-center py-24"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>;
  }

  const orgHealth = pulse?.org_health ?? null;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6" style={{ color: colors.ink }}>
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight flex items-center gap-2">
            <HeartPulse className="w-6 h-6" style={{ color: healthColor(orgHealth) }} />
            Org Pulse
          </h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
            Live cross-domain health, computed from every department's real operational data
          </p>
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge lastSync={lastSync} />
          <button onClick={load} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Org health hero + domain grid */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl p-6 flex flex-col items-center justify-center"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="relative w-32 h-32 rounded-full flex items-center justify-center"
            style={{ background: `conic-gradient(${healthColor(orgHealth)} ${(orgHealth ?? 0) * 3.6}deg, ${colors.canvas} 0deg)` }}>
            <div className="absolute inset-2.5 rounded-full flex flex-col items-center justify-center"
              style={{ background: colors.surface1 }}>
              <span className="text-[30px] font-bold" style={{ color: healthColor(orgHealth) }}>
                {orgHealth ?? '-'}
              </span>
              <span className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>health</span>
            </div>
          </div>
          <p className="text-[11px] mt-4 text-center" style={{ color: colors.inkSubtle }}>
            Mean of the 7 domain health scores (insight-severity weighted)
          </p>
        </div>

        <div className="lg:col-span-3 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {(pulse?.domains || []).map(d => (
            <div key={d.domain} onClick={() => navigate(DOMAIN_ROUTE[d.domain] || '/pulse')}
              className="rounded-xl p-4 block transition-transform hover:-translate-y-0.5 cursor-pointer"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="flex items-center justify-between mb-2">
                <DomainIcon hint={d.domain} size={22} />
                <span className="text-[16px] font-bold" style={{ color: healthColor(d.health) }}>
                  {d.health ?? '-'}
                </span>
              </div>
              <p className="text-[12px] font-semibold truncate">{DOMAIN_LABEL[d.domain] || d.domain}</p>
              <div className="mt-2 space-y-0.5">
                {(d.kpis || []).slice(0, 2).map(k => (
                  <div key={k.key} className="flex justify-between text-[10px]">
                    <span className="truncate" style={{ color: colors.inkSubtle }}>{k.label}</span>
                    <span className="font-mono ml-1">{fmtKpi(k.value, k.format)}</span>
                  </div>
                ))}
              </div>
              {(d.critical_count || d.warning_count) ? (
                <div className="flex gap-2 mt-2 text-[10px] font-semibold">
                  {d.critical_count ? <span style={{ color: '#ef4444' }}>{d.critical_count} critical</span> : null}
                  {d.warning_count ? <span style={{ color: '#f59e0b' }}>{d.warning_count} warning</span> : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      {/* Precog — safe-autonomy forecast with confidence bands */}
      <ForecastSection forecast={forecast} colors={colors} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Unified insight feed */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h2 className="text-[13px] font-bold mb-3 flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} /> Needs Attention
          </h2>
          <div className="space-y-2">
            {(pulse?.insights || []).map((ins, i) => {
              const color = ins.severity === 'critical' ? '#ef4444' : '#f59e0b';
              const Icon = ins.severity === 'critical' ? OctagonAlert : AlertTriangle;
              return (
                <div key={i}
                  onClick={() => navigate(DOMAIN_ROUTE[ins.domain] || '/pulse')}
                  className="flex items-start gap-2.5 px-3 py-2 rounded-lg text-[12px] cursor-pointer transition-colors hover:brightness-110"
                  style={{ background: `${color}10` }}
                  title={`Open ${ins.domain} department`}>
                  <Icon className="w-4 h-4 shrink-0 mt-0.5" style={{ color }} />
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-wide mr-1.5" style={{ color }}>
                      {ins.domain}
                    </span>
                    <span style={{ color: colors.ink }}>{ins.message}</span>
                  </div>
                </div>
              );
            })}
            {(pulse?.insights || []).length === 0 && (
              <p className="text-[12px] py-6 text-center" style={{ color: colors.inkTertiary }}>
                Nothing needs attention - all domains are clear.
              </p>
            )}
          </div>
        </div>

        {/* Live workflow activity */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h2 className="text-[13px] font-bold mb-3 flex items-center gap-1.5">
            <Activity className="w-4 h-4" style={{ color: colors.primary }} /> Workflow Activity
          </h2>
          <div className="space-y-1.5 max-h-[420px] overflow-y-auto">
            {activity.map(e => (
              <div key={e.id} className="flex items-center gap-2 text-[11px] px-2 py-1.5 rounded"
                style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded"
                  style={{ background: `${colors.primary}15`, color: colors.primary }}>
                  {e.domain}
                </span>
                <span style={{ color: colors.inkSubtle }}>{e.entity_type.replace(/_/g, ' ')}</span>
                <span className="font-mono" style={{ color: colors.ink }}>
                  {e.from_state} → {e.to_state}
                </span>
                <span className="ml-auto whitespace-nowrap" style={{ color: colors.inkTertiary }}>
                  {e.actor ? `${e.actor} · ` : ''}{timeAgo(e.at)}
                </span>
              </div>
            ))}
            {activity.length === 0 && (
              <p className="text-[12px] py-6 text-center" style={{ color: colors.inkTertiary }}>
                No workflow transitions yet - actions taken in any department appear here.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* SLA breaches - entities sitting past their state's target */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[13px] font-bold flex items-center gap-1.5">
            <Hourglass className="w-4 h-4" style={{ color: '#f59e0b' }} /> SLA Breaches
            {stale.length > 0 && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                style={{ background: '#ef444418', color: '#ef4444' }}>{stale.length}</span>
            )}
          </h2>
          {stale.length > 0 && (
            <div className="flex items-center gap-2">
              {escalateMsg && <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{escalateMsg}</span>}
              <button onClick={escalateAll} disabled={escalating}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-50 text-white"
                style={{ background: '#f59e0b' }}>
                {escalating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                Escalate all
              </button>
            </div>
          )}
        </div>
        {stale.length === 0 ? (
          <p className="text-[12px] py-4 text-center" style={{ color: colors.inkTertiary }}>
            Nothing is sitting past its SLA - every workflow state is inside target.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                {['Domain', 'Item', 'Stuck In', 'SLA', 'Age', 'Over By'].map(h => (
                  <th key={h} className="text-left px-3 py-2 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {stale.slice(0, 15).map(b => (
                  <tr key={`${b.entity_type}-${b.entity_id}`}
                    onClick={() => navigate(DOMAIN_ROUTE[b.domain] || '/pulse')}
                    className="cursor-pointer transition-colors hover:brightness-110"
                    style={{ borderBottom: `1px solid ${colors.hairline}` }}
                    title={`Open ${b.domain} department`}>
                    <td className="px-3 py-2">
                      <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded"
                        style={{ background: `${colors.primary}15`, color: colors.primary }}>{b.domain}</span>
                    </td>
                    <td className="px-3 py-2 font-medium max-w-[240px]">
                      <span className="block truncate" title={b.title}>
                        {b.title}
                        <span className="ml-1.5 font-normal" style={{ color: colors.inkTertiary }}>
                          {b.entity_type.replace(/_/g, ' ')}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono">{b.state.replace(/_/g, ' ')}</td>
                    <td className="px-3 py-2 font-mono" style={{ color: colors.inkSubtle }}>{b.sla_hours}h</td>
                    <td className="px-3 py-2 font-mono" style={{ color: colors.inkSubtle }}>
                      {b.age_hours >= 48 ? `${(b.age_hours / 24).toFixed(1)}d` : `${b.age_hours.toFixed(1)}h`}
                    </td>
                    <td className="px-3 py-2 font-mono font-bold" style={{ color: b.over_by_hours > 24 ? '#ef4444' : '#f59e0b' }}>
                      +{b.over_by_hours >= 48 ? `${(b.over_by_hours / 24).toFixed(1)}d` : `${b.over_by_hours.toFixed(1)}h`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default OrgPulse;
