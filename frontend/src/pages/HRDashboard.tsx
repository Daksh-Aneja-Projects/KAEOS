/**
 * KAEOS - HR Dashboard
 * Department-level overview for the HR pack.
 * Shows real HR data from workforce layer + HR module.
 * 
 * API: GET /workforce/departments/{slug=hr} + HR API endpoints
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';
import {
  Users, Briefcase, Clock, TrendingUp, Heart, Shield,
  BarChart3, Building2, Bot, Zap, ArrowRight, UserPlus,
  Award, CheckCircle
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize, measured, NOT_MEASURED } from '../lib/format';

// Small chart renderers fed only by the /hr/analytics computed payload.
const CHART_PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7', '#14b8a6', '#f43f5e'];

function MiniBars({ items, colors }: { items: { label: string; value: number }[]; colors: any }) {
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <div className="space-y-1.5">
      {items.map((it, idx) => (
        <div key={it.label} className="flex items-center gap-2">
          <span className="text-[11px] w-28 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{it.label}</span>
          <div className="flex-1 h-3.5 rounded" style={{ background: colors.canvas }}>
            <div className="h-3.5 rounded transition-all duration-500" style={{
              width: `${Math.max((it.value / max) * 100, it.value > 0 ? 2 : 0)}%`,
              background: CHART_PALETTE[idx % CHART_PALETTE.length],
            }} />
          </div>
          <span className="text-[11px] font-mono w-8 shrink-0 text-right" style={{ color: colors.ink }}>{it.value.toLocaleString()}</span>
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

export default function HRDashboard({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [hrStats, setHRStats] = useState<any>(null);
  const [hrAnalytics, setHRAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.all([
      api.getWorkforceDepartment('hr').catch(() => null),
      api.getHRDashboard().catch(() => null),
      api.getDomainAnalytics('hr').catch(() => null),
    ]).then(([d, hr, an]) => {
      setDept(d);
      setHRStats(hr);
      setHRAnalytics(an);
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, { intervalMs: 20000 });

  if (loading) return <BrainLoading message="Loading HR intelligence..." />;

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };
  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  // If HR department isn't deployed yet
  if (!dept && !hrStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className="max-w-7xl mx-auto p-6">
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: '#22c55e15' }}>
              <Briefcase className="w-10 h-10" style={{ color: '#22c55e' }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">HR Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Human Resources pack to manage talent acquisition, employee lifecycle,
                benefits administration, and performance management with AI-powered agents.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: '#22c55e' }}>
              Deploy HR Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Recruiting', path: '/departments/hr/recruiting', icon: UserPlus, color: '#8b5cf6' },
    { label: 'Employees', path: '/departments/hr/employees', icon: Users, color: colors.primary },
    { label: 'Time & Leave', path: '/departments/hr/time', icon: Clock, color: '#f59e0b' },
    { label: 'Performance', path: '/departments/hr/performance', icon: Award, color: '#22c55e' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <DomainIcon hint="hr" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Human Resources'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'AI-powered HR operations - talent, benefits, performance, compliance.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>
                    {humanize(dept.status)}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                    <Shield className="w-2.5 h-2.5" /> {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2">
              <Heart className="w-5 h-5" style={{ color: healthColor(dept.health_score || 0) }} />
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                <CountUp value={Math.round((dept.health_score || 0) * 100)} suffix="%" />
              </span>
            </div>
          )}
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-6 gap-3">
          {[
            { label: 'Employees', value: (dept?.employee_count || hrStats?.total_employees || 0).toLocaleString(), icon: Users, color: colors.primary },
            { label: 'Agents', value: dept?.agent_count || 0, icon: Bot, color: '#8b5cf6' },
            { label: 'Capabilities', value: dept?.capability_count || 0, icon: Zap, color: '#06b6d4' },
            { label: 'Tasks Done', value: (dept?.tasks_completed_total || 0).toLocaleString(), icon: CheckCircle, color: '#22c55e' },
            // Null unless a human baseline is configured; never render a bare 0.
            { label: 'Hours Saved', value: measured(dept?.hours_saved_total, v => `${v}h`), icon: Clock, color: '#f59e0b' },
            { label: 'Automation', value: `${Math.round((dept?.automation_coverage || 0) * 100)}%`, icon: BarChart3, color: '#ec4899' },
          ].map(kpi => (
            <div key={kpi.label} className="p-3 rounded-xl text-center" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <kpi.icon className="w-5 h-5 mx-auto mb-1" style={{ color: kpi.color }} />
              <div
                className={kpi.value === NOT_MEASURED ? 'text-[11px] font-semibold leading-[24px]' : 'text-[18px] font-bold'}
                style={{ color: kpi.value === NOT_MEASURED ? colors.inkSubtle : kpi.color }}
              >{kpi.value}</div>
              <div className="text-[11px] uppercase tracking-wider" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
            </div>
          ))}
        </div>

        {/* Quick Navigation */}
        <div className="grid grid-cols-4 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-md group"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1">
                <div className="text-[14px] font-semibold group-hover:text-primary transition-colors">{link.label}</div>
                <div className="text-[11px]" style={{ color: colors.inkSubtle }}>View module →</div>
              </div>
              <ArrowRight className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: colors.primary }} />
            </button>
          ))}
        </div>

        {/* Capabilities Overview (from workforce) */}
        {(dept?.capabilities || []).length > 0 && (
          <div style={card}>
            <h3 className="text-[15px] font-semibold mb-4">HR Capabilities</h3>
            <div className="grid grid-cols-3 gap-4">
              {dept.capabilities.map((cap: any) => (
                <div key={cap.id} className="p-4 rounded-xl" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={28} />
                      <span className="text-[13px] font-semibold">{cap.name}</span>
                    </div>
                    <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                      style={{ background: cap.status === 'ACTIVE' ? '#22c55e20' : '#f59e0b20', color: cap.status === 'ACTIVE' ? '#22c55e' : '#f59e0b' }}>
                      {humanize(cap.status)}
                    </span>
                  </div>
                  <p className="text-[11px] mb-2 line-clamp-2" style={{ color: colors.inkSubtle }}>{cap.description}</p>
                  <div className="flex items-center gap-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                    <span>{Math.round((cap.automation_pct || 0) * 100)}% automated</span>
                    <span>{cap.active_agents || 0} agents</span>
                    <span>{cap.tasks_completed || 0} tasks</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Live HR insights computed by /hr/analytics from the actual records */}
        {(hrAnalytics?.insights || []).length > 0 && (
          <div className="space-y-2">
            {hrAnalytics.insights.map((ins: any, i: number) => {
              const color = ins.severity === 'critical' ? '#ef4444' : ins.severity === 'warning' ? '#f59e0b' : '#3b82f6';
              return (
                <div key={i} className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg text-[12px]" style={{ background: `${color}12` }}>
                  <TrendingUp className="w-4 h-4 shrink-0" style={{ color }} />
                  <span style={{ color: colors.ink }}>{ins.message}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* HR-specific metrics from HR module + /hr/analytics charts */}
        {hrStats && (() => {
          const chartByKey = (k: string) => (hrAnalytics?.charts || []).find((c: any) => c.key === k);
          const kpiByKey = (k: string) => (hrAnalytics?.kpis || []).find((x: any) => x.key === k);
          const funnel = chartByKey('funnel');
          const empStatus = chartByKey('emp_status');
          const pendingTO = kpiByKey('pending_to');
          const toApproval = kpiByKey('to_approval');
          return (
            <div className="grid grid-cols-2 gap-4">
              <div style={card}>
                <h3 className="text-[14px] font-semibold mb-3">Recruiting Pipeline</h3>
                <div className="space-y-2">
                  {[
                    { label: 'Open Positions', value: hrStats.open_positions ?? '-' },
                    { label: 'Applications This Month', value: hrStats.applications_this_month ?? '-' },
                    { label: 'Avg Time-to-Fill', value: hrStats.avg_time_to_fill != null ? `${hrStats.avg_time_to_fill}d` : '-' },
                    { label: 'Offer Acceptance Rate', value: hrStats.offer_acceptance_rate != null ? `${hrStats.offer_acceptance_rate}%` : '-' },
                  ].map(m => (
                    <div key={m.label} className="flex items-center justify-between text-[12px]">
                      <span style={{ color: colors.inkSubtle }}>{m.label}</span>
                      <span className="font-mono font-bold">{m.value}</span>
                    </div>
                  ))}
                </div>
                {/* Candidates by stage, computed live from the requisition funnel */}
                {funnel && funnel.items.length > 0 && (
                  <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                    <div className="text-[11px] uppercase tracking-wider font-semibold mb-2" style={{ color: colors.inkSubtle }}>
                      {funnel.title}
                    </div>
                    <MiniBars items={funnel.items} colors={colors} />
                  </div>
                )}
              </div>
              <div style={card}>
                <h3 className="text-[14px] font-semibold mb-3">Employee Health</h3>
                <div className="space-y-2">
                  {[
                    { label: 'Employee Satisfaction', value: hrStats.satisfaction_score != null ? `${hrStats.satisfaction_score}/5` : '-' },
                    { label: 'Turnover Rate', value: hrStats.turnover_rate != null ? `${hrStats.turnover_rate}%` : '-' },
                    { label: 'Training Completion', value: hrStats.training_completion != null ? `${hrStats.training_completion}%` : '-' },
                    { label: 'Compliance Score', value: hrStats.compliance_score != null ? `${hrStats.compliance_score}%` : '-' },
                    ...(pendingTO?.value != null ? [{ label: 'Pending Time-Off Requests', value: pendingTO.value.toLocaleString() }] : []),
                    ...(toApproval?.value != null ? [{ label: 'Time-Off Approval Rate', value: `${toApproval.value.toFixed(0)}%` }] : []),
                  ].map(m => (
                    <div key={m.label} className="flex items-center justify-between text-[12px]">
                      <span style={{ color: colors.inkSubtle }}>{m.label}</span>
                      <span className="font-mono font-bold">{m.value}</span>
                    </div>
                  ))}
                </div>
                {/* Real headcount split from employee records */}
                {empStatus && empStatus.items.length > 0 && (
                  <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                    <div className="text-[11px] uppercase tracking-wider font-semibold mb-2" style={{ color: colors.inkSubtle }}>
                      {empStatus.title}
                    </div>
                    <MiniDonut items={empStatus.items} colors={colors} />
                  </div>
                )}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
