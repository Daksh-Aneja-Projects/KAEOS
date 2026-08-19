/**
 * KAEOS - Engineering Dashboard
 * Department-level overview for the Engineering & IT Ops domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError } from '../components/BrainStates';
import {
  Code2, Server, GitPullRequest, Rocket, Siren, FileText, PhoneCall,
  Bot, Zap, ArrowRight, RefreshCw, ShieldAlert,
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';

const ACCENT = DEPARTMENT_COLORS.engineering;

// Small chart renderers fed only by the /engineering/analytics computed payload.
const CHART_PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7'];

function MiniBars({ items, colors }: { items: { label: string; value: number }[]; colors: any }) {
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <div className="space-y-2">
      {items.map((it, idx) => (
        <div key={it.label} className="flex items-center gap-2">
          <span className="text-[11px] w-28 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{humanize(it.label)}</span>
          <div className="flex-1 h-3.5 rounded" style={{ background: colors.canvas }}>
            <div className="h-3.5 rounded transition-all duration-500" style={{
              width: `${Math.max((it.value / max) * 100, it.value > 0 ? 2 : 0)}%`,
              background: CHART_PALETTE[idx % CHART_PALETTE.length],
            }} />
          </div>
          <span className="text-[11px] font-mono w-10 shrink-0 text-right" style={{ color: colors.ink }}>
            {it.value.toLocaleString()}
          </span>
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
      <div className="w-24 h-24 rounded-full shrink-0 relative" style={{ background: total > 0 ? `conic-gradient(${segs.join(', ')})` : colors.canvas }}>
        <div className="absolute inset-[12px] rounded-full flex flex-col items-center justify-center" style={{ background: colors.surface1 }}>
          <span className="text-[16px] font-bold leading-none">{total.toLocaleString()}</span>
          <span className="text-[11px] uppercase tracking-wide mt-0.5" style={{ color: colors.inkSubtle }}>total</span>
        </div>
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        {items.map((it, idx) => (
          <div key={it.label} className="flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: CHART_PALETTE[idx % CHART_PALETTE.length] }} />
            <span className="truncate" style={{ color: colors.inkSubtle }}>{humanize(it.label)}</span>
            <span className="font-mono ml-auto pl-2" style={{ color: colors.ink }}>{it.value.toLocaleString()}</span>
            <span className="w-8 text-right shrink-0" style={{ color: colors.inkSubtle }}>{total ? Math.round((it.value / total) * 100) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function EngineeringDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [engStats, setEngStats] = useState<any>(null);
  const [engAnalytics, setEngAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.allSettled([
      api.getWorkforceDepartment('engineering'),
      api.getEngineeringDashboard(),
      api.getDomainAnalytics('engineering'),
    ]).then(([d, e, a]) => {
      if (d.status === 'fulfilled') setDept(d.value);
      if (e.status === 'fulfilled') { setEngStats(e.value); setError(null); }
      // Both requests failing is an outage, not an undeployed department.
      else if (d.status === 'rejected') setError((e.reason as any)?.message || 'Failed to load Engineering');
      if (a.status === 'fulfilled') setEngAnalytics(a.value);
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, { intervalMs: 20000 });

  if (loading) return <BrainLoading message="Loading Engineering Intelligence..." />;
  if (error && !dept && !engStats) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  if (!dept && !engStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className={`${PAGE_PAD}`}>
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: ACCENT + '15' }}>
              <Code2 className="w-10 h-10" style={{ color: ACCENT }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Engineering Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Engineering & IT Ops pack to manage the service catalog, code review,
                deployment risk, and incident response with active AI-powered agents.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: ACCENT }}>
              Deploy Engineering Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Service Catalog', path: '/departments/engineering/services', icon: Server, color: '#6366f1' },
    { label: 'Pull Requests', path: '/departments/engineering/pull-requests', icon: GitPullRequest, color: '#8b5cf6' },
    { label: 'Deployments', path: '/departments/engineering/deployments', icon: Rocket, color: '#ec4899' },
    { label: 'Incidents', path: '/departments/engineering/incidents', icon: Siren, color: '#ef4444' },
    { label: 'Postmortems', path: '/departments/engineering/postmortems', icon: FileText, color: '#f59e0b' },
    { label: 'On-Call', path: '/departments/engineering/oncall', icon: PhoneCall, color: '#22c55e' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <DomainIcon hint="engineering" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Engineering & IT Ops'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Autonomous code review, deployment risk scoring, and incident response.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: ACCENT + '20', color: ACCENT }}>
                    {humanize(dept.status)}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2">
              <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Department Health:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                <CountUp value={Math.round((dept.health_score || 0) * 100)} suffix="%" />
              </span>
            </div>
          )}
        </div>

        {/* DORA-flavoured operational indicators */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: 'Services', value: engStats?.total_services, icon: Server, color: '#6366f1', sub: engStats?.unhealthy_services ? `${engStats.unhealthy_services} unhealthy` : '' },
            { label: 'Open PRs', value: engStats?.open_pull_requests, icon: GitPullRequest, color: '#8b5cf6', sub: engStats?.prs_awaiting_review != null ? `${engStats.prs_awaiting_review} awaiting review` : '' },
            { label: 'Change Fail Rate', value: engStats?.change_failure_rate_pct != null ? `${engStats.change_failure_rate_pct}%` : '-', icon: Rocket, color: '#ec4899', sub: engStats?.deployments_total != null ? `${engStats.deployments_total} deploys tracked` : '' },
            { label: 'Open Incidents', value: engStats?.open_incidents, icon: Siren, color: (engStats?.sev1_open || 0) > 0 ? '#ef4444' : '#f59e0b', sub: engStats?.sev1_open ? `${engStats.sev1_open} SEV1` : '' },
            { label: 'MTTR', value: engStats?.mttr_minutes != null ? `${engStats.mttr_minutes}m` : '-', icon: RefreshCw, color: '#06b6d4', sub: engStats?.postmortems_due ? `${engStats.postmortems_due} postmortem(s) due` : '' },
            { label: 'On Call', value: engStats?.engineers_on_call, icon: ShieldAlert, color: '#22c55e', sub: '' },
          ].map(kpi => (
            <div key={kpi.label} className="p-3 rounded-xl text-center" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <kpi.icon className="w-5 h-5 mx-auto mb-1" style={{ color: kpi.color }} />
              <div className="text-[16px] font-bold" style={{ color: kpi.color }}>{kpi.value ?? '-'}</div>
              <div className="text-[11px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              {kpi.sub && <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>{kpi.sub}</div>}
            </div>
          ))}
        </div>

        {/* Delivery posture - incident severity mix, deployment outcomes, PR
            flow, computed server-side by /engineering/analytics. */}
        {(engAnalytics?.charts || []).length > 0 && (() => {
          const chartByKey = (k: string) => (engAnalytics.charts || []).find((c: any) => c.key === k);
          const severity = chartByKey('severity');
          const deploys = chartByKey('deploys');
          const prsChart = chartByKey('prs');
          const deploySuccessKpi = (engAnalytics.kpis || []).find((k: any) => k.key === 'deploy_success');
          const openIncidentsKpi = (engAnalytics.kpis || []).find((k: any) => k.key === 'open_incidents');
          return (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {severity && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <Siren className="w-4 h-4" style={{ color: '#ef4444' }} /> {severity.title}
                    </h3>
                    {openIncidentsKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#ef444418', color: '#ef4444' }}>
                        {openIncidentsKpi.value} open
                      </span>
                    )}
                  </div>
                  {severity.items.length > 0
                    ? <MiniBars items={severity.items} colors={colors} />
                    : <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No incidents recorded.</p>}
                </div>
              )}
              {deploys && (
                <div style={card}>
                  <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-1.5">
                    <Rocket className="w-4 h-4" style={{ color: '#ec4899' }} /> {deploys.title}
                  </h3>
                  <MiniDonut items={deploys.items} colors={colors} />
                </div>
              )}
              {prsChart && (
                <div style={card}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold flex items-center gap-1.5">
                      <GitPullRequest className="w-4 h-4" style={{ color: '#8b5cf6' }} /> {prsChart.title}
                    </h3>
                    {deploySuccessKpi?.value != null && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: '#22c55e18', color: '#22c55e' }}>
                        {deploySuccessKpi.value.toFixed(0)}% deploy success
                      </span>
                    )}
                  </div>
                  {prsChart.items.length > 0
                    ? <MiniBars items={prsChart.items} colors={colors} />
                    : <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No pull requests recorded.</p>}
                </div>
              )}
            </div>
          );
        })()}

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-sm group"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1">
                <div className="text-[13px] font-semibold group-hover:text-primary transition-colors">{link.label}</div>
                <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Explore delivery &amp; workflows &rarr;</div>
              </div>
              <ArrowRight className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: colors.primary }} />
            </button>
          ))}
        </div>

        {/* Bottom Section: Left (Capabilities/Agents) | Right (Active Agents) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            {/* Capabilities */}
            {(dept?.capabilities || []).length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-4 flex items-center gap-1.5">
                  <Zap className="w-4 h-4 text-amber-500" /> Engineering Capabilities
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
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Engineering Agents
            </h3>
            <div className="space-y-3">
              {(dept?.agents || []).length === 0 && (
                <p className="text-[11px]" style={{ color: colors.inkSubtle }}>No agents deployed yet.</p>
              )}
              {(dept?.agents || []).map((agent: any) => (
                <div key={agent.id} className="flex items-center justify-between p-2.5 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-md flex items-center justify-center text-[11px] font-bold" style={{ background: colors.primary + '18', color: colors.primary }}>{(agent.agent_name || '?').charAt(0)}</div>
                    <div>
                      <div className="text-[12px] font-bold">{agent.agent_name}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{agent.role_in_department}</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-green-500/10 text-green-500">{agent.status ? humanize(agent.status) : 'Active'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
