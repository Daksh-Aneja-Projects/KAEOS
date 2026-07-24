import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Info, Loader2, OctagonAlert, RefreshCw, TrendingUp } from 'lucide-react';
import { api } from '../api/client';
import type { DomainAnalytics as DomainAnalyticsPayload, DomainChart, DomainKPI } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import LiveBadge from './LiveBadge';

/**
 * Shared analytics layer for the 7 department views.
 * Renders whatever the backend's /{domain}/analytics endpoint computes:
 * KPI cards, bar/funnel/donut charts and severity-ranked insights.
 * Pure CSS visuals - no chart library, theme-aware in both modes.
 */

const PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7', '#14b8a6', '#f43f5e'];

function formatValue(kpi: DomainKPI): string {
  if (kpi.value === null || kpi.value === undefined) return '-';
  switch (kpi.format) {
    case 'currency':
      return kpi.value >= 1_000_000 ? `$${(kpi.value / 1_000_000).toFixed(1)}M`
        : kpi.value >= 10_000 ? `$${(kpi.value / 1_000).toFixed(0)}K`
        : `$${kpi.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    case 'percent':
      return `${kpi.value.toFixed(kpi.value < 10 ? 1 : 0)}%`;
    case 'hours':
      return kpi.value >= 48 ? `${(kpi.value / 24).toFixed(1)}d` : `${kpi.value.toFixed(1)}h`;
    default:
      return kpi.value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
}

const BarChart: React.FC<{ chart: DomainChart }> = ({ chart }) => {
  const { colors } = useTheme();
  const max = Math.max(...chart.items.map(i => i.value), 1);
  return (
    <div className="space-y-2">
      {chart.items.map((item, idx) => (
        <div key={item.label} className="flex items-center gap-2">
          <span className="text-[11px] w-28 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={item.label}>
            {item.label}
          </span>
          <div className="flex-1 h-4 rounded" style={{ background: colors.canvas }}>
            <div className="h-4 rounded transition-all" style={{
              width: `${Math.max((item.value / max) * 100, item.value > 0 ? 2 : 0)}%`,
              background: PALETTE[idx % PALETTE.length],
            }} />
          </div>
          <span className="text-[11px] font-mono w-16 shrink-0" style={{ color: colors.ink }}>
            {item.value >= 10_000 ? `${(item.value / 1000).toFixed(0)}K` : item.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
      ))}
      {chart.items.length === 0 && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No data yet</p>}
    </div>
  );
};

const FunnelChart: React.FC<{ chart: DomainChart }> = ({ chart }) => {
  const { colors } = useTheme();
  const max = Math.max(...chart.items.map(i => i.value), 1);
  return (
    <div className="space-y-1.5">
      {chart.items.map((item, idx) => {
        const pct = (item.value / max) * 100;
        return (
          <div key={item.label} className="flex items-center gap-2">
            <div className="flex-1 flex justify-center">
              <div className="h-6 rounded flex items-center justify-center transition-all"
                style={{
                  width: `${Math.max(pct, 8)}%`,
                  background: `${PALETTE[idx % PALETTE.length]}${pct > 50 ? 'ff' : 'aa'}`,
                }}>
                <span className="text-[10px] font-semibold text-white px-1 truncate">{item.value.toLocaleString()}</span>
              </div>
            </div>
            <span className="text-[11px] w-32 truncate shrink-0" style={{ color: colors.inkSubtle }} title={item.label}>{item.label}</span>
          </div>
        );
      })}
      {chart.items.length === 0 && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No data yet</p>}
    </div>
  );
};

const DonutChart: React.FC<{ chart: DomainChart }> = ({ chart }) => {
  const { colors } = useTheme();
  const total = chart.items.reduce((s, i) => s + i.value, 0);
  let acc = 0;
  const segments = chart.items.map((item, idx) => {
    const start = (acc / (total || 1)) * 360;
    acc += item.value;
    const end = (acc / (total || 1)) * 360;
    return `${PALETTE[idx % PALETTE.length]} ${start}deg ${end}deg`;
  });
  return (
    <div className="flex items-center gap-4">
      <div className="w-24 h-24 rounded-full shrink-0 relative" style={{
        background: total > 0 ? `conic-gradient(${segments.join(', ')})` : colors.canvas,
      }}>
        <div className="absolute inset-3 rounded-full flex items-center justify-center" style={{ background: colors.surface1 }}>
          <span className="text-[13px] font-bold" style={{ color: colors.ink }}>{total.toLocaleString()}</span>
        </div>
      </div>
      <div className="space-y-1 min-w-0">
        {chart.items.map((item, idx) => (
          <div key={item.label} className="flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: PALETTE[idx % PALETTE.length] }} />
            <span className="truncate" style={{ color: colors.inkSubtle }}>{item.label}</span>
            <span className="font-mono ml-auto pl-2" style={{ color: colors.ink }}>{item.value.toLocaleString()}</span>
          </div>
        ))}
        {chart.items.length === 0 && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No data yet</p>}
      </div>
    </div>
  );
};

const DomainAnalytics: React.FC<{ domain: string }> = ({ domain }) => {
  const { colors } = useTheme();
  const [data, setData] = useState<DomainAnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.getDomainAnalytics(domain));
      setError('');
      setLastSync(Date.now());
    } catch (e: any) {
      setError(e?.message || 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  useLiveRefresh(load);

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>;
  }
  if (error || !data) {
    return (
      <div className="rounded-xl p-8 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <AlertTriangle className="w-8 h-8 mx-auto mb-2" style={{ color: '#f59e0b' }} />
        <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{error || 'No analytics available'}</p>
        <button onClick={() => { setLoading(true); load(); }} className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold"
          style={{ background: '#6366f115', color: '#6366f1' }}>
          <RefreshCw className="w-3 h-3" /> Retry
        </button>
      </div>
    );
  }

  const severityStyle = (s: string) =>
    s === 'critical' ? { icon: OctagonAlert, color: '#ef4444' }
      : s === 'warning' ? { icon: AlertTriangle, color: '#f59e0b' }
      : { icon: Info, color: '#3b82f6' };

  return (
    <div className="space-y-5">
      <div className="flex justify-end"><LiveBadge lastSync={lastSync} /></div>
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {data.kpis.map(kpi => (
          <div key={kpi.key} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <p className="text-[10px] font-medium uppercase tracking-wide truncate" style={{ color: colors.inkSubtle }} title={kpi.label}>
              {kpi.label}
            </p>
            <p className="text-[20px] font-bold mt-1 tracking-tight" style={{ color: colors.ink }}>{formatValue(kpi)}</p>
          </div>
        ))}
      </div>

      {/* Insights */}
      <div className="space-y-2">
        {data.insights.map((ins, i) => {
          const { icon: Icon, color } = severityStyle(ins.severity);
          return (
            <div key={i} className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg text-[12px]"
              style={{ background: `${color}12`, color }}>
              <Icon className="w-4 h-4 shrink-0" />
              <span style={{ color: colors.ink }}>{ins.message}</span>
            </div>
          );
        })}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {data.charts.map(chart => (
          <div key={chart.key} className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <h3 className="text-[12px] font-semibold mb-4 flex items-center gap-1.5" style={{ color: colors.ink }}>
              <TrendingUp className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
              {chart.title}
            </h3>
            {chart.type === 'funnel' ? <FunnelChart chart={chart} />
              : chart.type === 'donut' ? <DonutChart chart={chart} />
              : <BarChart chart={chart} />}
          </div>
        ))}
      </div>
    </div>
  );
};

export default DomainAnalytics;
