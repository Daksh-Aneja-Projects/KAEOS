/**
 * KAEOS - Workforce Analytics
 * ROI dashboard: tasks automated, hours saved, cost savings.
 * Per-department breakdown with bar charts.
 * 
 * API: GET /workforce/analytics
 */
import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';
import {
  Clock, DollarSign, Building2,
  Users, Zap, Heart, AlertTriangle, CheckCircle
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import LiveBadge from '../components/LiveBadge';
import Sparkline from '../components/Sparkline';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { measured, NOT_MEASURED } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

export default function WorkforceAnalytics(_props: { domain?: string }) {
  const { colors } = useTheme();
  const [data, setData] = useState<any>(null);
  const [trend, setTrend] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);

  const loadAnalytics = React.useCallback(() => {
    let anchorFailed: any = null;
    return Promise.all([
      api.getWorkforceAnalytics().catch((e) => { anchorFailed = e; return null; }),
      api.getAutonomyTrend(30).catch(() => null),
    ]).then(([d, t]) => {
      // Distinguish a real outage (anchor rejected) from a genuinely empty
      // tenant (call succeeded, no data) so the two render differently.
      setError(anchorFailed ? (anchorFailed?.message || 'Analytics services are unreachable') : null);
      if (d) { setData(d); setSyncedAt(Date.now()); }
      if (t) setTrend(t);
      setLoading(false);
    });
  }, []);

  useEffect(() => { loadAnalytics(); }, [loadAnalytics]);
  useLiveRefresh(loadAnalytics);

  if (loading) return <BrainLoading message="Computing ROI analytics..." />;
  if (error && !data) return <BrainError message={error} onRetry={() => { setLoading(true); loadAnalytics(); }} />;
  if (!data) return <BrainEmpty title="No analytics data yet" action="Deploy a department and complete tasks to generate analytics" />;

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };
  const healthColor = (h: number) => h > 70 ? '#22c55e' : h > 40 ? '#f59e0b' : '#ef4444';

  // Calculate max for bar sizing
  const maxTasks = Math.max(...(data.departments || []).map((d: any) => d.tasks_completed || 0), 1);
  const maxHours = Math.max(...(data.departments || []).map((d: any) => d.hours_saved || 0), 1);
  const maxCost = Math.max(...(data.departments || []).map((d: any) => d.cost_saved || 0), 1);

  // Daily governed-execution volume, straight from the autonomy-trend series.
  const dailyExecutions: number[] = (trend?.series || []).map((p: any) => p.total).filter((v: any) => v != null);

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-[24px] font-bold tracking-tight">Workforce Analytics</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              Enterprise ROI - real-time metrics from all deployed departments.
            </p>
            {data.hours_saved_note && (
              <p className="text-[11px] mt-1.5 max-w-2xl leading-relaxed" style={{ color: colors.inkSubtle, opacity: 0.8 }}>
                Hours and cost saved are not shown because they cannot be measured
                from your data alone. They need the time each task took a person
                before automation, and that person's loaded hourly cost. Set those
                per skill and these tiles fill in.
              </p>
            )}
          </div>
          <LiveBadge lastSync={syncedAt} />
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {[
            // Deltas were hardcoded ("+12%", "+8.2%", "+15%") and presented as real
            // trends. There is no period-over-period series behind them, so they are
            // omitted rather than fabricated.
            { label: 'Tasks Completed', value: (data.total_tasks_completed || 0).toLocaleString(), icon: CheckCircle, color: '#22c55e', sub: '', spark: true },
            // Hours and cost saved are null unless the tenant configured a human
            // baseline. They used to render `|| 0`, which turned "we cannot
            // measure this" into a confident "0h / $0". Show the reason instead.
            {
              label: 'Hours Saved', icon: Clock, color: '#f59e0b',
              value: measured(data.total_hours_saved, v => `${v}h`),
              sub: data.total_hours_saved == null
                ? 'Needs a human baseline per skill'
                : 'From your configured baseline',
            },
            {
              label: 'Cost Saved', icon: DollarSign, color: '#22c55e',
              value: measured(data.total_cost_saved, v => `$${v.toLocaleString()}`),
              sub: data.total_cost_saved == null
                ? 'Follows from hours saved'
                : (data.loaded_hourly_rate_usd ? `@ $${data.loaded_hourly_rate_usd}/hr loaded` : ''),
            },
            { label: 'Automation', value: `${data.automation_coverage_pct || 0}%`, icon: Zap, color: '#8b5cf6', sub: data.automation_execution_count ? `${data.automation_execution_count.toLocaleString()} governed executions` : '' },
            { label: 'Health Score', value: `${data.avg_health_score || 0}%`, icon: Heart, color: healthColor(data.avg_health_score || 0), sub: '' },
          ].map((kpi: any) => (
            <div key={kpi.label} style={card} className="relative overflow-hidden">
              <div className="flex items-center justify-between mb-2">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                  <kpi.icon className="w-4.5 h-4.5" style={{ color: kpi.color }} />
                </div>
              </div>
              {/* "Not measured" is copy, not a figure: at 24px bold it overran
                  the tile. Render the unmeasured state small and muted so the
                  numeric tiles stay the visual anchors. */}
              <div
                className={kpi.value === NOT_MEASURED
                  ? 'text-[13px] font-semibold mt-2 leading-[32px] whitespace-nowrap'
                  : 'text-[24px] font-bold mt-2'}
                style={{ color: kpi.value === NOT_MEASURED ? colors.inkSubtle : kpi.color }}
              >{kpi.value}</div>
              <div className="text-[11px] uppercase tracking-wider mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              {kpi.sub && <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>{kpi.sub}</div>}
              {/* Real per-day execution volume from the autonomy-trend series */}
              {kpi.spark && dailyExecutions.length > 1 && (
                <div className="mt-1.5">
                  <Sparkline points={dailyExecutions} color={kpi.color} width={150} height={24} />
                  <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>daily governed executions, 30d</div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Operational Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <Users className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Agent Fleet
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Active Agents</span>
                <span className="text-[16px] font-bold">{data.agents_active || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Utilization</span>
                <span className="text-[16px] font-bold" style={{ color: colors.primary }}>{data.agent_utilization_pct || 0}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Agent Health</span>
                <span className="text-[16px] font-bold" style={{ color: healthColor(data.avg_agent_health || 0) }}>{data.avg_agent_health || 0}%</span>
              </div>
            </div>
          </div>

          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} /> Escalation
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Human Escalation Rate</span>
                <span className="text-[16px] font-bold" style={{ color: (data.human_escalation_rate_pct || 0) < 15 ? '#22c55e' : '#f59e0b' }}>
                  {data.human_escalation_rate_pct || 0}%
                </span>
              </div>
              <div className="h-2 rounded-full" style={{ background: colors.hairline }}>
                <div className="h-full rounded-full transition-all duration-500" style={{
                  width: `${Math.min(data.human_escalation_rate_pct || 0, 100)}%`,
                  background: (data.human_escalation_rate_pct || 0) < 15 ? '#22c55e' : '#f59e0b',
                }} />
              </div>
              <div className="text-[11px] inline-flex items-center gap-1" style={{ color: colors.inkSubtle }}>
                {(data.human_escalation_rate_pct || 0) < 15
                  ? <><CheckCircle className="w-3 h-3" style={{ color: '#22c55e' }} /> Within target - below 15% threshold</>
                  : <><AlertTriangle className="w-3 h-3" style={{ color: '#f59e0b' }} /> Above 15% target - review agent capabilities</>}
              </div>
            </div>
          </div>

          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <Building2 className="w-4 h-4" style={{ color: colors.primary }} /> Departments
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Active</span>
                <span className="text-[16px] font-bold" style={{ color: colors.primary }}>{data.departments_active || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Avg Automation</span>
                <span className="text-[16px] font-bold">{data.automation_coverage_pct || 0}%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Per-Department Breakdown */}
        {(data.departments || []).length > 0 && (
          <div style={card}>
            <h3 className="text-[15px] font-semibold mb-4">Per-Department Breakdown</h3>
            <div className="space-y-4">
              {data.departments.map((dept: any) => (
                <div key={dept.id} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <DomainIcon hint={dept.slug || dept.icon} fallbackHint={dept.name} size={26} />
                      <span className="text-[14px] font-semibold">{dept.name}</span>
                      <span className="text-[11px] font-mono px-1.5 py-0.5 rounded-full" style={{ background: healthColor(dept.health_score) + '15', color: healthColor(dept.health_score) }}>
                        {dept.health_score}% health
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <span>{dept.agent_count} agents</span>
                      <span>{dept.automation_coverage}% automated</span>
                    </div>
                  </div>
                  {/* Task / hours / cost bars - all real per-department fields */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    <div>
                      <div className="flex items-center justify-between text-[11px] mb-0.5" style={{ color: colors.inkSubtle }}>
                        <span>Tasks Completed</span>
                        <span className="font-mono">{(dept.tasks_completed || 0).toLocaleString()}</span>
                      </div>
                      <div className="h-2.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full transition-all" style={{
                          width: `${((dept.tasks_completed || 0) / maxTasks) * 100}%`,
                          background: `linear-gradient(90deg, ${colors.primary}, #22c55e)`,
                        }} />
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-[11px] mb-0.5" style={{ color: colors.inkSubtle }}>
                        <span>Hours Saved</span>
                        <span className="font-mono">{measured(dept.hours_saved, v => `${v}h`)}</span>
                      </div>
                      {/* No bar when there is nothing measured to draw: a
                          zero-width track still implies a real zero. */}
                      <div className="h-2.5 rounded-full overflow-hidden" style={{
                        background: colors.hairline,
                        opacity: dept.hours_saved == null ? 0.35 : 1,
                      }}>
                        {dept.hours_saved != null && (
                          <div className="h-full rounded-full transition-all" style={{
                            width: `${(dept.hours_saved / maxHours) * 100}%`,
                            background: `linear-gradient(90deg, #f59e0b, #ec4899)`,
                          }} />
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-[11px] mb-0.5" style={{ color: colors.inkSubtle }}>
                        <span>Cost Saved</span>
                        <span className="font-mono">{measured(dept.cost_saved, v => `$${v.toLocaleString()}`)}</span>
                      </div>
                      <div className="h-2.5 rounded-full overflow-hidden" style={{
                        background: colors.hairline,
                        opacity: dept.cost_saved == null ? 0.35 : 1,
                      }}>
                        {dept.cost_saved != null && (
                          <div className="h-full rounded-full transition-all" style={{
                            width: `${(dept.cost_saved / maxCost) * 100}%`,
                            background: `linear-gradient(90deg, #22c55e, #06b6d4)`,
                          }} />
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
