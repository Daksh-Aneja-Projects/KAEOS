/**
 * KAEOS - Sales Dashboard
 * Department-level overview for the Sales domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError } from '../components/BrainStates';
import {
  TrendingUp, Compass, Target, DollarSign, Award,
  ArrowRight, Bot, Zap, Shield, Sparkles, BarChart3, Briefcase
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';

const ACCENT = DEPARTMENT_COLORS.sales;

// Small chart renderers fed only by the /sales/analytics computed payload,
// mirroring FinanceDashboard's ledger-composition section.
const CHART_PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7'];
const fmtMoney = (v: number) =>
  v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M`
    : v >= 1_000 ? `$${(v / 1_000).toFixed(0)}k`
      : `$${Math.round(v).toLocaleString()}`;

function MiniBars({ items, colors, money }: { items: { label: string; value: number }[]; colors: any; money?: boolean }) {
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <div className="space-y-2">
      {items.map((it, idx) => (
        <div key={it.label} className="flex items-center gap-2">
          <span className="text-[11px] w-24 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{it.label}</span>
          <div className="flex-1 h-3.5 rounded" style={{ background: colors.canvas }}>
            <div className="h-3.5 rounded transition-all duration-500" style={{
              width: `${Math.max((it.value / max) * 100, it.value > 0 ? 2 : 0)}%`,
              background: CHART_PALETTE[idx % CHART_PALETTE.length],
            }} />
          </div>
          <span className="text-[11px] font-mono w-14 shrink-0 text-right" style={{ color: colors.ink }}>
            {money ? fmtMoney(it.value) : it.value.toLocaleString()}
          </span>
        </div>
      ))}
      {items.length === 0 && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No data yet</p>}
    </div>
  );
}

export default function SalesDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [salesStats, setSalesStats] = useState<any>(null);
  const [salesAnalytics, setSalesAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.allSettled([
      api.getWorkforceDepartment('sales'),
      api.getSalesDashboard(),
      api.getDomainAnalytics('sales'),
    ]).then(([d, s, a]) => {
      if (d.status === 'fulfilled') setDept(d.value);
      if (s.status === 'fulfilled') { setSalesStats(s.value); setError(null); }
      else if (d.status === 'rejected') setError((s.reason as any)?.message || 'Failed to load Sales');
      if (a.status === 'fulfilled') setSalesAnalytics(a.value);
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, { intervalMs: 20000 });

  if (loading) return <BrainLoading message="Gathering Sales Pipeline Statistics..." />;
  if (error && !dept && !salesStats) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 80 ? '#22c55e' : h > 50 ? '#f59e0b' : '#ef4444';

  if (!dept && !salesStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className={`${PAGE_PAD}`}>
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: ACCENT + '15' }}>
              <Target className="w-10 h-10" style={{ color: ACCENT }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Sales Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Sales & CRM pack to manage opportunities, qualify inbound leads,
                forecast bookings, and calculate compensation plans with digital twins.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: ACCENT }}>
              Deploy Sales Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Deals Pipeline', path: '/departments/sales/pipeline', icon: Compass, color: '#f59e0b' },
    { label: 'Leads Inbox', path: '/departments/sales/leads', icon: Target, color: '#ec4899' },
    { label: 'Revenue Forecast', path: '/departments/sales/forecasts', icon: TrendingUp, color: '#3b82f6' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <DomainIcon hint="sales" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Sales & CRM'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Active opportunities, lead ICP scoring, quota attainment, and revenue forecasting.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: ACCENT + '20', color: ACCENT }}>
                    {humanize(dept.status)}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: ACCENT + '15', color: ACCENT }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {salesStats && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[12px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>Quota Attainment:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(salesStats.attainment_pct || 0) }}>
                <CountUp value={salesStats.attainment_pct || 0} suffix="%" />
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Active Pipeline', value: salesStats ? `$${(salesStats.pipeline_total / 1000).toFixed(0)}k` : '-', icon: TrendingUp, color: '#3b82f6' },
            { label: 'Deals Won YTD', value: salesStats ? `$${(salesStats.total_won / 1000).toFixed(0)}k` : '-', icon: Award, color: '#22c55e' },
            { label: 'Open Inbound Leads', value: salesStats?.open_leads ?? '0', icon: Target, color: '#ec4899' },
            { label: 'Sales Target Quota', value: salesStats ? `$${(salesStats.quota / 1000).toFixed(0)}k` : '-', icon: DollarSign, color: '#f59e0b' },
          ].map(kpi => (
            <div key={kpi.label} className="p-4 rounded-xl flex items-center justify-between" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <div>
                <div className="text-[22px] font-bold" style={{ color: kpi.color }}>{kpi.value}</div>
                <div className="text-[11px] font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
              </div>
            </div>
          ))}
        </div>

        {/* Pipeline composition - funnel counts, funnel value and top accounts,
            computed server-side by /sales/analytics from the real pipeline. */}
        {(salesAnalytics?.charts || []).length > 0 && (() => {
          const chartByKey = (k: string) => (salesAnalytics.charts || []).find((c: any) => c.key === k);
          const funnelCount = chartByKey('funnel_count');
          const funnelValue = chartByKey('funnel_value');
          const topAccounts = chartByKey('top_accounts');
          const winRateKpi = (salesAnalytics.kpis || []).find((k: any) => k.key === 'win_rate');
          const weightedKpi = (salesAnalytics.kpis || []).find((k: any) => k.key === 'weighted');
          return (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {funnelCount && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <BarChart3 className="w-4 h-4" style={{ color: '#6366f1' }} /> {funnelCount.title}
                    </h3>
                    {winRateKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#22c55e18', color: '#22c55e' }}>
                        {winRateKpi.value.toFixed(0)}% win rate
                      </span>
                    )}
                  </div>
                  <MiniBars items={funnelCount.items} colors={colors} />
                </div>
              )}
              {funnelValue && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <DollarSign className="w-4 h-4" style={{ color: '#f59e0b' }} /> {funnelValue.title}
                    </h3>
                    {weightedKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#f59e0b18', color: '#f59e0b' }}>
                        {fmtMoney(weightedKpi.value)} weighted
                      </span>
                    )}
                  </div>
                  <MiniBars items={funnelValue.items} colors={colors} money />
                </div>
              )}
              {topAccounts && (
                <div style={card}>
                  <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-1.5">
                    <Briefcase className="w-4 h-4" style={{ color: '#3b82f6' }} /> {topAccounts.title}
                  </h3>
                  <MiniBars items={topAccounts.items} colors={colors} money />
                </div>
              )}
            </div>
          );
        })()}

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-sm group border"
              style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-bold group-hover:text-primary transition-colors truncate" title={link.label}>{link.label}</div>
                <div className="text-[11px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>View operations →</div>
              </div>
            </button>
          ))}
        </div>

        {/* Bottom Section */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            {/* Capabilities */}
            {(dept?.capabilities || []).length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-4 flex items-center gap-1.5">
                  <Zap className="w-4 h-4 text-amber-500" /> Sales Capabilities
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {dept.capabilities.map((cap: any) => (
                    <div key={cap.id} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] font-semibold flex items-center gap-1.5">
                          <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={24} /> {cap.name}
                        </span>
                        <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: cap.status === 'ACTIVE' ? '#22c55e20' : '#f59e0b20', color: cap.status === 'ACTIVE' ? '#22c55e' : '#f59e0b' }}>
                          {humanize(cap.status)}
                        </span>
                      </div>
                      <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{cap.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div style={card} className="space-y-4">
            <h3 className="text-[14px] font-bold flex items-center gap-1.5">
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Sales Agents
            </h3>
            <div className="space-y-3">
              {(dept?.agents || []).length === 0 && (
                <p className="text-[11px]" style={{ color: colors.inkSubtle }}>No agents deployed yet.</p>
              )}
              {(dept?.agents || []).map((agent: any) => (
                <div key={agent.id} className="flex items-center justify-between p-2.5 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <div className="w-6 h-6 rounded-md flex items-center justify-center text-[11px] font-bold flex-shrink-0" style={{ background: colors.primary + '18', color: colors.primary }}>{(agent.agent_name || '?').charAt(0)}</div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-bold truncate" title={agent.agent_name}>{agent.agent_name}</div>
                      <div className="text-[11px] truncate" title={agent.role_in_department} style={{ color: colors.inkSubtle }}>{agent.role_in_department}</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-green-500/10 text-green-500 flex-shrink-0 whitespace-nowrap ml-2">{agent.status ? humanize(agent.status) : 'Active'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
