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
 * Org Pulse — the cross-domain layer above the 7 department views.
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
  if (v === null || v === undefined) return '—';
  if (format === 'currency') return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : v >= 10_000 ? `$${(v / 1_000).toFixed(0)}K` : `$${Math.round(v).toLocaleString()}`;
  if (format === 'percent') return `${v.toFixed(0)}%`;
  if (format === 'hours') return v >= 48 ? `${(v / 24).toFixed(1)}d` : `${v.toFixed(1)}h`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
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

  const load = useCallback(async () => {
    const [p, a, s] = await Promise.allSettled([
      api.getOrgPulse(), api.getOrgActivity(30), api.getOrgStale(),
    ]);
    if (p.status === 'fulfilled') setPulse(p.value);
    if (a.status === 'fulfilled') setActivity(a.value || []);
    if (s.status === 'fulfilled') setStale(s.value?.breaches || []);
    setLastSync(Date.now());
    setLoading(false);
  }, []);

  const escalateAll = async () => {
    setEscalating(true); setEscalateMsg('');
    try {
      const res = await api.escalateStale();
      setEscalateMsg(res.escalated > 0
        ? `Escalated ${res.escalated} breach${res.escalated === 1 ? '' : 'es'} to the activity feed${res.skipped_open ? ` (${res.skipped_open} already open)` : ''}.`
        : `Nothing new to escalate — ${res.skipped_open} breach${res.skipped_open === 1 ? '' : 'es'} already have open alerts.`);
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
                {orgHealth ?? '—'}
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
                  {d.health ?? '—'}
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
                Nothing needs attention — all domains are clear.
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
                No workflow transitions yet — actions taken in any department appear here.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* SLA breaches — entities sitting past their state's target */}
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
            Nothing is sitting past its SLA — every workflow state is inside target.
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
