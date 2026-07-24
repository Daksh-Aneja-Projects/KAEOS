/**
 * KAEOS - Workforce Dashboard
 * The home page. The first thing a CIO sees.
 * 
 * If no departments deployed: "Your Enterprise Brain is ready. Deploy a department to begin."
 * If departments exist: Grid of department cards with enterprise-wide KPIs.
 * 
 * API: GET /workforce/overview + GET /workforce/departments
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';
import {
  Building2, Users, Clock, Zap, BarChart3, ArrowRight, Rocket,
  Activity, CheckCircle, AlertTriangle, Heart, TrendingUp
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import LiveValue from '../components/LiveValue';
import LiveBadge from '../components/LiveBadge';
import Sparkline from '../components/Sparkline';

export default function WorkforceDashboard({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<any>(null);
  const [departments, setDepartments] = useState<any[]>([]);
  const [recentActivity, setRecentActivity] = useState<any[]>([]);
  const [trend, setTrend] = useState<any>(null);
  const [graduations, setGraduations] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const { lastMessage } = useWebSocket();
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [sar, setSar] = useState<any>(null);

  // Color encodes autonomy posture: green = mostly autonomous, amber = humans
  // carrying the load, red = the fleet is effectively manual.
  const autonomyRate: number | null = overview?.safe_autonomy_rate_pct ?? null;
  const autonomyColor =
    autonomyRate === null ? colors.inkSubtle
      : autonomyRate >= 70 ? '#22c55e'
        : autonomyRate >= 40 ? '#f59e0b'
          : '#ef4444';
  const trendSeries: number[] = (trend?.series || [])
    .map((p: any) => p.safe_autonomy_rate_pct)
    .filter((v: any) => v !== null && v !== undefined);
  const trendDelta: number | null = trend?.trend_delta_pct ?? null;

  const load = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    const [ov, deps, activity, trendData, grads, sarData] = await Promise.all([
      api.getWorkforceOverview().catch(() => null),
      api.getWorkforceDepartments().catch(() => ({ departments: [] })),
      api.getOODAEvents().catch(() => ({ events: [] })),
      api.getAutonomyTrend(30).catch(() => null),
      api.getGraduations().catch(() => null),
      api.getSafeAutonomy(30).catch(() => null),
    ]);
    setOverview(ov);
    setDepartments(deps?.departments || []);
    setRecentActivity(activity?.events?.slice(0, 8) || []);
    setTrend(trendData);
    setGraduations(grads);
    setSar(sarData);
    setSyncedAt(Date.now());
    setLoading(false);
  }, []);

  useEffect(() => { load(true); }, [load]);

  // Any tenant event re-reads the KPIs. The old handler only reacted to three
  // exact message types (`overview_update`, `departments_update`, ...) that
  // the backend never emits - so the dashboard sat frozen while agents ran.
  useEffect(() => {
    if (lastMessage) load(false);
  }, [lastMessage, load]);

  if (loading) return <BrainLoading message="Loading Enterprise Workforce..." />;

  const hasDepartments = departments.length > 0;
  const statusColor = (s: string) => {
    if (s === 'ACTIVE') return '#22c55e';
    if (s === 'DEPLOYING') return '#f59e0b';
    if (s === 'DEGRADED') return '#ef4444';
    if (s === 'PAUSED') return colors.inkSubtle;
    return colors.inkSubtle;
  };
  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-[24px] font-bold tracking-tight">Enterprise Workforce</h1>
              {/* Say it out loud when the page is self-updating - a live number
                  is otherwise indistinguishable from a stale one. */}
              <LiveBadge lastSync={syncedAt} />
            </div>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              {hasDepartments
                ? `${overview?.departments_active || 0} departments active · ${overview?.agents_active || 0} agents deployed`
                : 'Your Enterprise Brain is ready. Deploy your first department to begin.'}
            </p>
          </div>
          <button onClick={() => navigate('/deploy')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
            <Rocket className="w-4 h-4" /> Deploy Department
          </button>
        </div>

        {!hasDepartments ? (
          /* Empty State - No Departments */
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center"
              style={{ background: colors.primary + '15' }}>
              <Building2 className="w-10 h-10" style={{ color: colors.primary }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Your Enterprise Brain is Ready</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy a digital department to transform how your enterprise operates.
                Start with HR, Finance, Legal, or any domain pack from the marketplace.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={() => navigate('/deploy')}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
                style={{ background: colors.primary }}>
                <Rocket className="w-4 h-4" /> Deploy Your First Department
              </button>
              <button onClick={() => navigate('/marketplace')}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-medium border"
                style={{ borderColor: colors.hairline, color: colors.ink }}>
                Browse Marketplace <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Hero metric + supporting stats.
                One number dominates: the share of real work that completed
                with no human gate. Five equal tiles emphasised nothing, and
                two of them (hours saved, automation) were fabricated. */}
            <div className="grid grid-cols-3 gap-4">
              <div className="p-5 rounded-xl relative overflow-hidden" style={{
                background: colors.surface1,
                border: `1px solid ${autonomyRate === null ? colors.hairline : autonomyColor + '55'}`,
              }}>
                <div className="flex items-center gap-2 mb-1">
                  <Zap className="w-4 h-4" style={{ color: autonomyRate === null ? colors.inkSubtle : autonomyColor }} />
                  <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>
                    Safe Autonomy Rate
                  </span>
                </div>
                <LiveValue
                  value={autonomyRate === null ? '--' : `${autonomyRate}%`}
                  className="text-[44px] leading-none font-bold tabular-nums block"
                  style={{ color: autonomyRate === null ? colors.inkSubtle : autonomyColor }}
                  flashColor={autonomyColor}
                />
                {/* Direction of travel. A number is a status; a rising line is
                    the product's thesis - agents EARN autonomy over time. */}
                {trendDelta !== null && (
                  <div className="flex items-center gap-1 mt-1.5 text-[11px] font-semibold"
                    style={{ color: trendDelta >= 0 ? '#22c55e' : '#ef4444' }}>
                    <TrendingUp className="w-3 h-3" style={{
                      transform: trendDelta >= 0 ? 'none' : 'scaleY(-1)',
                    }} />
                    {trendDelta >= 0 ? '+' : ''}{trendDelta} pts vs earlier this month
                  </div>
                )}
                <div className="text-[11px] mt-2" style={{ color: colors.inkSubtle }}>
                  {overview?.total_executions
                    ? `${overview.autonomous_executions ?? 0} of ${overview.total_executions} executions ran without a human gate`
                    : 'No executions recorded yet'}
                </div>
                {trendSeries.length > 1 && (
                  <div className="mt-2">
                    <Sparkline points={trendSeries} color={autonomyColor} width={240} height={30} />
                  </div>
                )}
                {/* the bar IS the metric - color encodes autonomy posture */}
                <div className="mt-2 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                  <div className="h-full rounded-full transition-all duration-700" style={{
                    width: `${autonomyRate ?? 0}%`, background: autonomyColor,
                  }} />
                </div>
              </div>

              <div className="col-span-2 grid grid-cols-2 gap-4">
                {[
                  { label: 'Departments Active', value: overview?.departments_active ?? 0, icon: Building2, color: colors.primary },
                  { label: 'Agents Deployed', value: overview?.agents_active ?? 0, icon: Users, color: '#8b5cf6' },
                  { label: 'Tasks Completed', value: (overview?.tasks_completed ?? 0).toLocaleString(), icon: CheckCircle, color: '#22c55e' },
                  { label: 'Avg Health', value: `${overview?.avg_health_score ?? 0}%`, icon: Activity, color: '#06b6d4' },
                ].map(kpi => (
                  <div key={kpi.label} className="p-4 rounded-xl flex items-center gap-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: kpi.color + '15' }}>
                      <kpi.icon className="w-4 h-4" style={{ color: kpi.color }} />
                    </div>
                    <div>
                      <LiveValue value={kpi.value} className="text-[20px] font-bold leading-none tabular-nums block" flashColor={kpi.color} />
                      <div className="text-[10px] uppercase tracking-wider mt-1" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Why work fell out of autonomy - the explainable breakdown behind
                the rate (folded in from the safe-autonomy detail; not a separate
                page). Shows exactly where a human was needed, edited, or a run
                failed. */}
            {sar?.fallout && (sar.total_executions || 0) > 0 && (
              <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <div className="text-[11px] uppercase tracking-wider font-semibold mb-3" style={{ color: colors.inkSubtle }}>
                  Where autonomy fell out (last {sar.window_days}d)
                </div>
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Routed to human', value: sar.fallout.routed_to_human, color: '#3b82f6' },
                    { label: 'Human overridden', value: sar.fallout.human_overridden, color: '#f59e0b' },
                    { label: 'Human edited', value: sar.fallout.human_edited, color: '#8b5cf6' },
                    { label: 'Failed', value: sar.fallout.failed, color: '#ef4444' },
                  ].map(f => (
                    <div key={f.label} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="text-[20px] font-bold" style={{ color: f.color }}>{f.value ?? 0}</div>
                      <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{f.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Earned autonomy.
                The aha moment: a skill starts below the confidence gate (every
                run needs a human), succeeds repeatedly, and crosses the
                threshold - it EARNED the right to run alone. That happened in
                the data all along and was never surfaced. */}
            {(graduations?.graduated?.length > 0 || graduations?.earning_trust?.length > 0) && (
              <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="text-[16px] font-semibold">Earned Autonomy</h2>
                    <p className="text-[11px]" style={{ color: colors.inkSubtle }}>
                      Skills run themselves once confidence clears {graduations?.threshold ?? 0.82} - and not before.
                    </p>
                  </div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
                    <span style={{ color: '#22c55e', fontWeight: 700 }}>{graduations?.graduated_count ?? 0}</span> autonomous ·{' '}
                    <span style={{ color: '#f59e0b', fontWeight: 700 }}>{graduations?.earning_count ?? 0}</span> earning trust
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {(graduations?.graduated || []).map((g: any) => (
                    <div key={g.skill_id} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: '#22c55e0d' }}>
                      <CheckCircle className="w-4 h-4 shrink-0" style={{ color: '#22c55e' }} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px] font-semibold truncate">{g.skill_id}</div>
                        <div className="text-[10px]" style={{ color: colors.inkSubtle }}>
                          {g.executions.toLocaleString()} runs · {Math.round(g.success_rate * 100)}% success · confidence {g.confidence}
                        </div>
                      </div>
                      <span className="text-[9px] font-bold uppercase tracking-wider shrink-0" style={{ color: '#22c55e' }}>
                        Autonomous
                      </span>
                    </div>
                  ))}
                  {(graduations?.earning_trust || []).map((g: any) => (
                    <div key={g.skill_id} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: '#f59e0b0d' }}>
                      <Clock className="w-4 h-4 shrink-0" style={{ color: '#f59e0b' }} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px] font-semibold truncate">{g.skill_id}</div>
                        <div className="text-[10px]" style={{ color: colors.inkSubtle }}>
                          {g.executions.toLocaleString()} runs · {g.to_threshold} from autonomy
                        </div>
                      </div>
                      <span className="text-[9px] font-bold uppercase tracking-wider shrink-0" style={{ color: '#f59e0b' }}>
                        Earning
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Departments Grid */}
            <div>
              <h2 className="text-[16px] font-semibold mb-3">Active Departments</h2>
              <div className="grid grid-cols-3 gap-4">
                {departments.map(dept => (
                  <div key={dept.id} onClick={() => navigate(`/departments/${dept.slug || dept.id}`)}
                    className="cursor-pointer transition-all hover:shadow-lg group" style={card}>
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <DomainIcon hint={dept.slug || dept.icon} fallbackHint={dept.name} size={44} />
                        <div>
                          <h3 className="text-[15px] font-bold group-hover:text-primary transition-colors">{dept.name}</h3>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="px-2 py-0.5 rounded-full text-[9px] font-bold"
                              style={{ background: statusColor(dept.status) + '20', color: statusColor(dept.status) }}>
                              {dept.status}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <Heart className="w-3.5 h-3.5" style={{ color: healthColor(dept.health_score || 0) }} />
                        <span className="text-[11px] font-mono font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                          {Math.round((dept.health_score || 0) * 100)}%
                        </span>
                      </div>
                    </div>
                    <p className="text-[11px] mb-3 line-clamp-2" style={{ color: colors.inkSubtle }}>
                      {dept.description || `Digital ${dept.name} department serving ${dept.employee_count || 0} employees`}
                    </p>
                    <div className="grid grid-cols-4 gap-2 text-center">
                      {[
                        // Short labels: 'Capabilities'/'Processes' collided in
                        // a 4-column card grid and rendered as one word.
                        { label: 'Agents', value: dept.agent_count },
                        { label: 'Caps', value: dept.capability_count },
                        { label: 'Procs', value: dept.process_count ?? 0 },
                        // 'Hrs Saved' was tasks x 0.5 - invented. Tasks are real.
                        { label: 'Tasks', value: (dept.tasks_completed_total || 0).toLocaleString() },
                      ].map(m => (
                        <div key={m.label} className="min-w-0">
                          <div className="text-[14px] font-bold tabular-nums">{m.value}</div>
                          <div className="text-[9px] truncate" style={{ color: colors.inkSubtle }}>{m.label}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Activity */}
            {recentActivity.length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-semibold mb-3 flex items-center gap-2">
                  <Activity className="w-4 h-4" style={{ color: colors.primary }} />
                  Recent Brain Activity
                </h3>
                <div className="space-y-1">
                  {recentActivity.map((evt: any, i: number) => (
                    <div key={evt.id || i} className="flex items-center gap-3 px-3 py-1.5 rounded text-[11px]"
                      style={{ background: i === 0 ? colors.primary + '08' : 'transparent' }}>
                      <span className="font-mono text-[10px]" style={{ color: colors.inkSubtle }}>
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '-'}
                      </span>
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold"
                        style={{ background: colors.primary + '20', color: colors.primary }}>
                        {evt.loop_phase || evt.event_type || 'EVENT'}
                      </span>
                      <span style={{ color: colors.inkSubtle }}>
                        {evt.summary || evt.description || 'Cognitive activity recorded'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
