/**
 * KAEOS - Operations Dashboard
 * Department-level overview for the Operations domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError } from '../components/BrainStates';
import {
  Wrench, CheckSquare, Clipboard, Users, ShieldAlert,
  ArrowRight, Bot, Zap, Shield, Sparkles, BarChart3, PieChart
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';

const ACCENT = DEPARTMENT_COLORS.operations;

// Small chart renderers fed only by the /operations/analytics computed
// payload (po_funnel + resources) — matches the Finance/HR dashboard pattern.
const CHART_PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7'];

function MiniBars({ items, colors }: { items: { label: string; value: number }[]; colors: any }) {
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <div className="space-y-2">
      {items.map((it, idx) => (
        <div key={it.label} className="flex items-center gap-2">
          <span className="text-[11px] w-28 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{it.label}</span>
          <div className="flex-1 h-3.5 rounded" style={{ background: colors.canvas }}>
            <div className="h-3.5 rounded transition-all duration-500" style={{
              width: `${Math.max((it.value / max) * 100, it.value > 0 ? 2 : 0)}%`,
              background: CHART_PALETTE[idx % CHART_PALETTE.length],
            }} />
          </div>
          <span className="text-[11px] font-mono w-10 shrink-0 text-right" style={{ color: colors.ink }}>{it.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function MiniDonut({ items, colors }: { items: { label: string; value: number }[]; colors: any }) {
  const total = items.reduce((s, i) => s + i.value, 0);
  let acc = 0;
  const segs = items.map((it, idx) => {
    const start = (acc / (total || 1)) * 360; acc += it.value;
    const end = (acc / (total || 1)) * 360;
    return `${CHART_PALETTE[idx % CHART_PALETTE.length]} ${start}deg ${end}deg`;
  });
  return (
    <div className="flex items-center gap-4">
      <div className="w-20 h-20 rounded-full shrink-0 relative" style={{ background: total > 0 ? `conic-gradient(${segs.join(', ')})` : colors.canvas }}>
        <div className="absolute inset-[10px] rounded-full flex flex-col items-center justify-center" style={{ background: colors.surface1 }}>
          <span className="text-[14px] font-bold leading-none">{total.toLocaleString()}</span>
          <span className="text-[11px] uppercase tracking-wide mt-0.5" style={{ color: colors.inkSubtle }}>total</span>
        </div>
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        {items.map((it, idx) => (
          <div key={it.label} className="flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: CHART_PALETTE[idx % CHART_PALETTE.length] }} />
            <span className="truncate" style={{ color: colors.inkSubtle }}>{it.label}</span>
            <span className="font-mono ml-auto pl-2" style={{ color: colors.ink }}>{it.value.toLocaleString()}</span>
            <span className="w-8 text-right shrink-0" style={{ color: colors.inkSubtle }}>{total ? Math.round((it.value / total) * 100) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function OperationsDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [opsStats, setOpsStats] = useState<any>(null);
  const [opsAnalytics, setOpsAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.allSettled([
      api.getWorkforceDepartment('operations'),
      api.getOperationsDashboard(),
      api.getDomainAnalytics('operations'),
    ]).then(([d, o, a]) => {
      if (d.status === 'fulfilled') setDept(d.value);
      if (o.status === 'fulfilled') { setOpsStats(o.value); setError(null); }
      else if (d.status === 'rejected') setError((o.reason as any)?.message || 'Failed to load Operations');
      if (a.status === 'fulfilled') setOpsAnalytics(a.value);
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, { intervalMs: 20000 });

  if (loading) return <BrainLoading message="Loading Operational Infrastructure status..." />;
  if (error && !dept && !opsStats) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  if (!dept && !opsStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className={`${PAGE_PAD}`}>
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: ACCENT + '15' }}>
              <Wrench className="w-10 h-10" style={{ color: ACCENT }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Operations Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Operations & PMO pack to track project progress, audit developer
                utilization, manage subcontracts, and perform QA inspections with digital twins.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: ACCENT }}>
              Deploy Operations Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Project Portfolio', path: '/departments/operations/projects', icon: CheckSquare, color: '#10b981' },
    { label: 'Team Allocations', path: '/departments/operations/resources', icon: Users, color: '#8b5cf6' },
    { label: 'Supplier Operations', path: '/departments/operations/vendors', icon: Clipboard, color: '#3b82f6' },
    { label: 'Procurements', path: '/departments/operations/procurement', icon: Wrench, color: '#f59e0b' },
    { label: 'QA Inspections', path: '/departments/operations/quality', icon: ShieldAlert, color: '#ef4444' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <DomainIcon hint="operations" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Operations & PMO'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Project deliverables, team capacities, supplier scorecards, and QA conformance auditing.'}
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
          {dept && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[12px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>PMO Health:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                <CountUp value={Math.round((dept.health_score || 0) * 100)} suffix="%" />
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Active Projects', value: opsStats?.active_projects ?? 0, icon: CheckSquare, color: '#10b981' },
            { label: 'Warning tasks', value: opsStats?.blocked_tasks ?? 0, icon: ShieldAlert, color: '#ef4444' },
            { label: 'Pending Purchases', value: opsStats?.pending_purchases ?? 0, icon: Wrench, color: '#f59e0b' },
            { label: 'Failed QA Checks', value: opsStats?.failed_inspections ?? 0, icon: Clipboard, color: '#ec4899' },
          ].map(kpi => (
            <div key={kpi.label} className="p-4 rounded-xl flex items-center justify-between" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <div>
                <div className="text-[22px] font-bold" style={{ color: kpi.color }}>{typeof kpi.value === 'number' ? <CountUp value={kpi.value} /> : kpi.value}</div>
                <div className="text-[11px] font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
              </div>
            </div>
          ))}
        </div>

        {/* Procurement pipeline + resource mix, computed live by
            /operations/analytics from the real PO/resource rows. */}
        {(opsAnalytics?.charts || []).length > 0 && (() => {
          const chartByKey = (k: string) => (opsAnalytics.charts || []).find((c: any) => c.key === k);
          const kpiByKey = (k: string) => (opsAnalytics.kpis || []).find((x: any) => x.key === k);
          const funnel = chartByKey('po_funnel');
          const resourceMix = chartByKey('resources');
          const pendingKpi = kpiByKey('pending_prs');
          const utilKpi = kpiByKey('utilization');
          return (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {funnel && funnel.items.length > 0 && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <BarChart3 className="w-4 h-4" style={{ color: '#10b981' }} /> {funnel.title}
                    </h3>
                    {pendingKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#f59e0b18', color: '#f59e0b' }}>
                        {pendingKpi.value.toLocaleString()} pending
                      </span>
                    )}
                  </div>
                  <MiniBars items={funnel.items} colors={colors} />
                </div>
              )}
              {resourceMix && resourceMix.items.length > 0 && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <PieChart className="w-4 h-4" style={{ color: '#8b5cf6' }} /> {resourceMix.title}
                    </h3>
                    {utilKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#22c55e18', color: '#22c55e' }}>
                        {utilKpi.value.toFixed(0)}% avg utilization
                      </span>
                    )}
                  </div>
                  <MiniDonut items={resourceMix.items} colors={colors} />
                </div>
              )}
            </div>
          );
        })()}

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex flex-col items-center p-4 rounded-xl text-center transition-all hover:shadow-sm group border"
              style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center mb-2.5" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="text-[12px] font-bold group-hover:text-primary transition-colors">{link.label}</div>
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
                  <Zap className="w-4 h-4 text-amber-500" /> Operations Capabilities
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
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Ops Agents
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
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-green-500/10 text-green-500 flex-shrink-0 whitespace-nowrap ml-2">{agent.status === 'ACTIVE' || !agent.status ? 'Active' : humanize(agent.status)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
