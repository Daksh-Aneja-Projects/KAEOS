import React, { useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { metricsApi } from '../api/endpoints/metrics';
import { useParallelApi } from '../hooks/useApi';
import { usePolling } from '../hooks/usePolling';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { CountUp } from '../components/CountUp';
import Sparkline from '../components/Sparkline';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { BrainLoading, BrainEmpty, BrainError, LiveIndicator } from '../components/BrainStates';
import { STREAM_INTERVALS } from '../services/realtime';
import {
  Activity, TrendingUp, TrendingDown, Minus, Shield, Users, Zap, DollarSign,
  BarChart3, MessageSquare, Globe, Target,
  ArrowUpRight, ArrowDownRight, Brain, Hourglass, HelpCircle, Ghost
} from 'lucide-react';

// Shape of the aggregated /dashboard/cockpit payload (only the fields the
// cockpit renders; backend may include more).
interface DebateQueueItem { id?: string; action: string; status?: string; confidence?: number | null }
interface PioneerAlert { type?: string; time?: string; title: string; source?: string; severity?: string }
interface OrgReadinessItem { bu: string; score?: number; status?: string; rule_count?: number | null }
interface CockpitData {
  pioneer_alerts?: PioneerAlert[];
  debate_queue?: DebateQueueItem[];
  org_readiness?: OrgReadinessItem[];
}

export default function ExecutiveCockpit({ domain }: { domain?: string }) {
  const { colors } = useTheme();

  // ── LIVE DATA - ALL FROM BACKEND, ZERO MOCK ──
  // Parallel query: health + activity feed + cost telemetry
  const { results, loading: initialLoading, anyError, refetchAll } = useParallelApi({
    health: () => api.getHealth(),
    feed: () => api.getActivityFeed(15),
    cost: () => api.getCostTelemetry(24),
    // Ghost executions: the zero-prompt runs KAEOS initiated on its own. This
    // engine was fully built but headless - nothing in the UI surfaced what the
    // org was about to do without being asked.
    ghosts: () => api.getGhostExecutions(),
    // The STORED metric series + model-call latency - a real shipped surface
    // (app/models/metrics_ts.py MetricSample, app/api/routes/safe_autonomy.py)
    // that had zero UI reader until now.
    timeseries: () => metricsApi.getTimeseries('safe_autonomy_rate', { interval: 'day' }),
    latency: () => metricsApi.getLatency(24),
  });

  // Cockpit-specific data - separate stream for live executive intelligence
  const {
    data: cockpit, isLive, staleness,
  } = usePolling<CockpitData>(
    () => api.getCockpit(),
    STREAM_INTERVALS.COCKPIT,
    { emptyCheck: (d) => !d }
  );

  // The health / feed / cost panels load once via useParallelApi; re-pull them
  // on a timer (and on any tenant event) so the KPIs never sit frozen.
  useLiveRefresh(refetchAll, { intervalMs: 20000 });

  const health = results.health;
  const feed = results.feed?.events || [];
  const costData = results.cost;
  const ghostExecutions = results.ghosts?.ghost_executions || [];

  // ── Derived values - ALL from API, ZERO fallbacks ──
  const score = health?.overall_score ?? 0;
  const scoreColor = score >= 80 ? '#22c55e' : score >= 60 ? '#f59e0b' : score > 0 ? '#ef4444' : colors.inkSubtle;
  const scoreTrend = health?.score_trend || 'stable';
  const trendIcon = scoreTrend === 'up' ? TrendingUp : scoreTrend === 'down' ? TrendingDown : Minus;
  const trendColor = scoreTrend === 'up' ? '#22c55e' : scoreTrend === 'down' ? '#ef4444' : colors.inkSubtle;

  const pioneerAlerts = cockpit?.pioneer_alerts || [];
  const debateQueue = cockpit?.debate_queue || [];
  const orgReadiness = cockpit?.org_readiness || [];

  const metricSeries = results.timeseries?.series || [];
  const latency = results.latency;
  const latencyTiers = latency ? Object.entries(latency.model_calls || {}) : [];

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px',
  };

  // ── COGNITIVE LOADING STATE ──
  if (initialLoading) {
    return <BrainLoading message="Aggregating executive intelligence…" />;
  }

  // A backend outage must read as an error with a retry, not a silent "No data yet".
  if (anyError && !results.health) {
    return <BrainError message={anyError} onRetry={refetchAll} />;
  }

  return (
    <div className={`${PAGE_PAD} space-y-5`} style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Executive Cockpit</h1>
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>KAEOS Enterprise Brain - Live intelligence from DB</p>
        </div>
        <LiveIndicator isLive={isLive} staleness={staleness} />
      </div>

      {/* Row 1: System Health Score + KPIs - ALL from health API */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {/* Health Score */}
        <div style={{ ...card, gridColumn: 'span 1' }} className="flex flex-col items-center justify-center">
          <span className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>System Health</span>
          <div className="relative w-20 h-20">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="42" fill="none" stroke={colors.hairline} strokeWidth="8" />
              <circle cx="50" cy="50" r="42" fill="none" stroke={scoreColor} strokeWidth="8"
                strokeDasharray={`${score * 2.64} 264`} strokeLinecap="round"
                style={{ transition: 'stroke-dasharray 0.7s cubic-bezier(0.16, 1, 0.3, 1)' }} />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-[22px] font-bold" style={{ color: scoreColor }}><CountUp value={score} /></span>
            </div>
          </div>
          <div className="flex items-center gap-1 mt-2 text-[11px]" style={{ color: trendColor }}>
            {React.createElement(trendIcon, { className: 'w-3 h-3' })}
            {scoreTrend === 'up' ? 'Trending up' : scoreTrend === 'down' ? 'Trending down' : 'Stable'}
          </div>
        </div>

        {/* KPI Cards - values come from health API, show 0 when no data */}
        {[
          { label: 'Total Rules', value: health?.total_rules ?? 0, icon: Shield, color: '#8b5cf6', sub: health?.total_executions != null ? `${health.total_executions.toLocaleString()} executions all-time` : null },
          { label: 'Active Skills', value: health?.total_skills ?? 0, icon: Zap, color: '#3b82f6', sub: health?.agent_metrics?.skills_used != null ? `${health.agent_metrics.skills_used} used in 7d` : null },
          { label: 'Executions (7d)', value: health?.agent_metrics?.total_executions_7d ?? 0, icon: Activity, color: '#22c55e', sub: health?.agent_metrics?.avg_duration_ms != null ? `avg ${(health.agent_metrics.avg_duration_ms / 1000).toFixed(1)}s per run` : null },
          { label: 'Success Rate', value: health?.agent_metrics?.success_rate != null ? `${(health.agent_metrics.success_rate * 100).toFixed(1)}%` : '-', icon: Target, color: '#f59e0b', sub: health?.agent_metrics?.human_overrides != null ? `${health.agent_metrics.human_overrides} human overrides` : null },
        ].map((kpi, i) => (
          <div key={i} style={card} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wider truncate" style={{ color: colors.inkSubtle }}>{kpi.label}</span>
              {React.createElement(kpi.icon, { className: 'w-4 h-4 flex-shrink-0', style: { color: kpi.color } })}
            </div>
            <div className="text-[24px] font-bold tracking-tight" style={{ color: colors.ink }}>{typeof kpi.value === 'number' ? <CountUp value={kpi.value} /> : kpi.value}</div>
            {kpi.sub && (
              <div className="text-[11px] truncate" style={{ color: colors.inkSubtle }} title={kpi.sub}>{kpi.sub}</div>
            )}
          </div>
        ))}
      </div>

      {/* Row 2: Agent Feed + Pioneer Intelligence + Cost */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Active Agent Feed - from api.getActivityFeed() */}
        <div style={card} className="flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Activity className="w-4 h-4" style={{ color: colors.primary }} /> Agent Consciousness Stream
            </h3>
            <span className="text-[11px] px-2 py-0.5 rounded-full font-bold"
              style={{ background: '#22c55e15', color: '#22c55e' }}>LIVE</span>
          </div>
          <div className="space-y-2 flex-1 min-h-0 overflow-y-auto">
            {feed.slice(0, 8).map((e: any, i: number) => {
              const sevColor = e.severity === 'critical' ? '#ef4444' : e.severity === 'warning' ? '#f59e0b' : colors.primary;
              return (
                <div key={e.id || i} className="flex items-start gap-2 py-1.5 border-b" style={{ borderColor: colors.hairline }}>
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ background: sevColor }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] font-medium truncate">{e.title || 'Agent activity'}</div>
                    <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{humanize(e.event_type || 'execution')}</div>
                  </div>
                  <span className="text-[11px] font-mono flex-shrink-0" style={{ color: colors.inkSubtle }}>
                    {e.created_at ? new Date(e.created_at).toLocaleTimeString() : ''}
                  </span>
                </div>
              );
            })}
            {feed.length === 0 && (
              <BrainEmpty title="No agent activity yet." action="Deploy an agent to begin." icon={Activity} />
            )}
          </div>
        </div>

        {/* Pioneer Intelligence - FROM cockpit API, NOT HARDCODED */}
        <div style={card} className="flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Globe className="w-4 h-4" style={{ color: '#f59e0b' }} /> Pioneer Intelligence
            </h3>
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
              {pioneerAlerts.length > 0 ? `${pioneerAlerts.length} signals` : 'No signals'}
            </span>
          </div>
          <div className="space-y-3 flex-1 min-h-0 overflow-y-auto">
            {pioneerAlerts.length === 0 ? (
              <BrainEmpty
                title="No external intelligence signals."
                action="Connect a signal source to detect regulatory, vendor, and threat intel."
                icon={Globe}
              />
            ) : (
              pioneerAlerts.map((item: PioneerAlert, i: number) => {
                const sevColor = item.severity === 'critical' ? '#ef4444' : item.severity === 'warning' ? '#f59e0b' : '#3b82f6';
                return (
                  <div key={i} className="p-2.5 rounded-lg" style={{ background: sevColor + '08', border: `1px solid ${sevColor}20` }}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-bold" style={{ background: sevColor + '20', color: sevColor }}>
                        {humanize(item.type || 'Signal')}
                      </span>
                      <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{item.time || ''}</span>
                    </div>
                    <div className="text-[11px]">{item.title}</div>
                    {item.source && (
                      <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>Source: {item.source}</div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Ghost Executions - what KAEOS started on its own, no prompt. */}
        <div className="p-5 flex flex-col" style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Ghost className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Ghost Executions
            </h3>
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
              {ghostExecutions.length > 0 ? `${ghostExecutions.length} zero-prompt runs` : 'None'}
            </span>
          </div>
          <div className="space-y-3 flex-1 min-h-0 overflow-y-auto">
            {ghostExecutions.length === 0 ? (
              <BrainEmpty
                title="No zero-prompt executions yet."
                action="KAEOS acts on its own when a signal carries clear latent intent."
                icon={Ghost}
              />
            ) : (
              ghostExecutions.slice(0, 8).map((g: any) => {
                const gated = g.hitl_required;
                const tone = gated ? '#f59e0b' : '#8b5cf6';
                return (
                  <div key={g.id} className="p-2.5 rounded-lg" style={{ background: tone + '08', border: `1px solid ${tone}20` }}>
                    <div className="flex items-center justify-between mb-1 gap-2">
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-bold whitespace-nowrap" style={{ background: tone + '20', color: tone }}>
                        {gated ? 'Awaiting Approval' : humanize(g.status || 'Running')}
                      </span>
                      <span className="text-[11px] truncate" style={{ color: colors.inkSubtle }}>{g.skill_name || ''}</span>
                    </div>
                    <div className="text-[11px]">{g.task_intent || 'Zero-prompt execution'}</div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Cost Governor / ROI - FROM cost API, NO FALLBACK NUMBERS */}
        <div style={card} className="flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <DollarSign className="w-4 h-4" style={{ color: '#22c55e' }} /> Cost & ROI Tracker
            </h3>
          </div>
          {!costData ? (
            <div className="flex-1 flex items-center justify-center">
              <BrainEmpty title="No cost telemetry available." action="Execute agents to generate cost data." icon={DollarSign} />
            </div>
          ) : (
            <div className="flex-1 flex flex-col justify-between gap-3">
              {/* Budget ring + headline token/call volume */}
              <div className="flex items-center justify-between p-3 rounded-lg" style={{ background: colors.canvas }}>
                <div>
                  <div className="text-[11px] uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Token Budget Used</div>
                  <div className="text-[22px] font-bold" style={{ color: colors.ink }}>
                    {costData.budget?.usage_pct ?? 0}%
                  </div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
                    {(costData.budget?.token_used ?? 0).toLocaleString()} / {(costData.budget?.token_limit ?? 0).toLocaleString()} tokens
                  </div>
                </div>
                <div className="w-16 h-16 relative">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke={colors.hairline} strokeWidth="6" />
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#22c55e" strokeWidth="6"
                      strokeDasharray={`${Math.max(1.5, (costData.budget?.usage_pct ?? 0) * 2.64)} 264`} strokeLinecap="round"
                      style={{ transition: 'stroke-dasharray 0.7s cubic-bezier(0.16, 1, 0.3, 1)' }} />
                  </svg>
                </div>
              </div>

              {/* Live volume: tokens + LLM calls (last 24h) */}
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[18px] font-bold">{(costData.total_tokens ?? 0).toLocaleString()}</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Tokens (24h)</div>
                </div>
                <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[18px] font-bold">{(costData.total_events ?? 0).toLocaleString()}</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>LLM Calls (24h)</div>
                </div>
              </div>

              {/* Per-tier live breakdown — where the model spend goes */}
              {costData.by_tier && Object.keys(costData.by_tier).length > 0 && (() => {
                const tiers = Object.entries(costData.by_tier as Record<string, any>)
                  .filter(([, v]) => (v?.tokens ?? 0) > 0)
                  .sort((a, b) => (b[1]?.tokens ?? 0) - (a[1]?.tokens ?? 0));
                const maxTok = Math.max(1, ...tiers.map(([, v]) => v?.tokens ?? 0));
                const tierColor: Record<string, string> = { reasoning: '#8b5cf6', fast: '#3b82f6', classification: '#f59e0b', embedding: '#22c55e', unspecified: colors.inkSubtle };
                return (
                  <div className="p-2.5 rounded-lg space-y-1.5" style={{ background: colors.canvas }}>
                    <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>Model tiers (calls · avg latency)</div>
                    {tiers.map(([name, v]) => (
                      <div key={name} className="flex items-center gap-2">
                        <span className="text-[11px] w-20 truncate" style={{ color: colors.ink }}>{humanize(name)}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                          <div className="h-full rounded-full" style={{ width: `${((v?.tokens ?? 0) / maxTok) * 100}%`, background: tierColor[name] || colors.primary }} />
                        </div>
                        <span className="text-[11px] font-mono w-28 text-right" style={{ color: colors.inkSubtle }}>
                          {v?.calls ?? 0} · {v?.avg_latency_ms ? `${(v.avg_latency_ms / 1000).toFixed(1)}s` : '--'}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })()}

              {/* Spend (local models run free — honest $0, not a fabricated cost) */}
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[15px] font-bold">${(costData.total_cost_usd ?? 0).toFixed(2)}</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Cost (24h)</div>
                </div>
                <div className="p-2 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[15px] font-bold">${(costData.avg_cost_per_task ?? 0).toFixed(3)}</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Avg/Task</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Debate Queue + Org Readiness + Confidence Distribution */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Debate Queue - FROM cockpit API, NOT HARDCODED */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <MessageSquare className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Debate Engine
            </h3>
            {debateQueue.length > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                style={{ background: '#f59e0b20', color: '#f59e0b' }}>{debateQueue.length} pending</span>
            )}
          </div>
          <div className="space-y-2">
            {debateQueue.length === 0 ? (
              <BrainEmpty
                title="No active debates."
                action="Debates are triggered when agents face conflicting rules."
                icon={MessageSquare}
              />
            ) : (
              debateQueue.map((d: DebateQueueItem, i: number) => (
                <div key={d.id || i} className="p-2.5 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[11px] font-medium mb-1">{d.action}</div>
                  <div className="flex items-center justify-between">
                    <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
                      {humanize(d.status || 'Open')}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-mono" style={{ color: '#f59e0b' }}>
                        {d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : '-'}
                      </span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Org Readiness - FROM cockpit API, NOT HARDCODED */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Users className="w-4 h-4" style={{ color: '#3b82f6' }} /> Org Readiness Index
            </h3>
          </div>
          <div className="space-y-2">
            {orgReadiness.length === 0 ? (
              <BrainEmpty
                title="No department data yet."
                action="Add rules with domain tags to see organizational readiness."
                icon={Users}
              />
            ) : (
              orgReadiness.map((bu: OrgReadinessItem) => {
                const buScore = bu.score ?? 0;
                const color = bu.status === 'green' ? '#22c55e' : bu.status === 'red' ? '#ef4444' : '#f59e0b';
                // Coverage trend for this department, from health.coverage
                const cov = (health?.coverage || []).find((c: any) => c.department === bu.bu);
                const TrendGlyph = cov?.trend === 'up' ? TrendingUp : cov?.trend === 'down' ? TrendingDown : Minus;
                const trendCol = cov?.trend === 'up' ? '#22c55e' : cov?.trend === 'down' ? '#ef4444' : colors.inkSubtle;
                return (
                  <div key={bu.bu} className="flex items-center gap-3">
                    <span className="text-[11px] w-20 truncate" title={humanize(bu.bu)}>{humanize(bu.bu)}</span>
                    <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full transition-all" style={{ width: `${buScore}%`, background: color }} />
                    </div>
                    <span className="text-[11px] font-mono w-10 text-right" style={{ color }}>{buScore}%</span>
                    {cov && (
                      <TrendGlyph className="w-3 h-3 flex-shrink-0" style={{ color: trendCol }} aria-label={`coverage ${cov.trend}`} />
                    )}
                    {bu.rule_count != null && (
                      <span className="text-[11px] w-6 text-right" style={{ color: colors.inkSubtle }}>{bu.rule_count}r</span>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Confidence Distribution - FROM health API, dynamic total */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <BarChart3 className="w-4 h-4" style={{ color: '#f59e0b' }} /> Confidence Distribution
            </h3>
          </div>
          {(() => {
            const cd = health?.confidence_distribution;
            if (!cd) {
              return <BrainEmpty title="No confidence data yet." action="Add rules to build distribution." icon={BarChart3} />;
            }
            const tiers = [
              { tier: 'VERIFIED', range: '≥0.95', count: cd.verified ?? 0, color: '#22c55e' },
              { tier: 'ENDORSED', range: '0.75-0.94', count: cd.validated_dh ?? 0, color: '#3b82f6' },
              { tier: 'VALIDATED', range: '0.60-0.74', count: cd.validated_peer ?? 0, color: '#8b5cf6' },
              { tier: 'CANDIDATE', range: '0.29-0.59', count: cd.inferred ?? 0, color: '#f59e0b' },
              { tier: 'SPECULATIVE', range: '<0.29', count: cd.speculative ?? 0, color: '#ef4444' },
            ];
            // API returns fractional shares (0..1), not counts - render as percentages
            const total = tiers.reduce((s, t) => s + t.count, 0) || 1;
            return (
              <div className="space-y-2">
                {tiers.map(t => (
                  <div key={t.tier} className="flex items-center gap-2">
                    <span className="text-[11px] font-mono w-20 truncate" style={{ color: t.color }}>{t.tier}</span>
                    <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full" style={{ width: `${(t.count / total) * 100}%`, background: t.color + '80' }} />
                    </div>
                    <span className="text-[11px] font-mono w-9 text-right">{((t.count / total) * 100).toFixed(0)}%</span>
                  </div>
                ))}
                <div className="text-[11px] text-center pt-1" style={{ color: colors.inkSubtle }}>
                  {health?.total_rules ?? 0} total rules
                </div>
                {/* Knowledge freshness - from health.freshness */}
                {health?.freshness && (() => {
                  const f = health.freshness as any;
                  const segs = [
                    { key: 'within_half_life', label: 'Fresh', value: f.within_half_life ?? 0, color: '#22c55e' },
                    { key: 'decaying', label: 'Decaying', value: f.decaying ?? 0, color: '#f59e0b' },
                    { key: 'expired', label: 'Expired', value: f.expired ?? 0, color: '#ef4444' },
                  ];
                  const sum = segs.reduce((s, x) => s + x.value, 0);
                  if (sum <= 0) return null;
                  return (
                    <div className="pt-2 mt-1 border-t" style={{ borderColor: colors.hairline }}>
                      <div className="text-[11px] uppercase tracking-wider mb-1.5" style={{ color: colors.inkSubtle }}>Knowledge Freshness</div>
                      <div className="flex h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        {segs.map(s => s.value > 0 && (
                          <div key={s.key} style={{ width: `${(s.value / sum) * 100}%`, background: s.color }} />
                        ))}
                      </div>
                      <div className="flex items-center gap-3 mt-1.5">
                        {segs.map(s => (
                          <span key={s.key} className="flex items-center gap-1 text-[11px]" style={{ color: colors.inkSubtle }}>
                            <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
                            {s.label} {(s.value * 100).toFixed(0)}%
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            );
          })()}
        </div>
      </div>

      {/* Row 4: Rule Decay Alerts + Elicitation Pulse - both from health API */}
      <div className="grid grid-cols-2 gap-4">
        {/* Rule Decay Alerts - from health.decay_alerts */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Hourglass className="w-4 h-4" style={{ color: '#ef4444' }} /> Rule Decay Alerts
            </h3>
            {(health?.decay_alerts?.length ?? 0) > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                style={{ background: '#ef444415', color: '#ef4444' }}>{health!.decay_alerts.length} at risk</span>
            )}
          </div>
          <div className="space-y-2">
            {(health?.decay_alerts?.length ?? 0) === 0 ? (
              <BrainEmpty title="No decaying rules." action="Rules losing confidence over time appear here." icon={Hourglass} />
            ) : (
              health!.decay_alerts.slice(0, 5).map((a: any) => {
                const urgColor = a.urgency === 'CRITICAL' ? '#ef4444' : a.urgency === 'WARNING' ? '#f59e0b' : '#3b82f6';
                return (
                  <div key={a.rule_id} className="p-2.5 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-bold flex-shrink-0" style={{ background: urgColor + '20', color: urgColor }}>{humanize(a.urgency)}</span>
                      <span className="text-[11px] flex-shrink-0" style={{ color: colors.inkSubtle }}>{humanize(a.domain)}</span>
                      <span className="ml-auto text-[11px] font-mono flex-shrink-0" style={{ color: urgColor }}>
                        {a.current_confidence != null ? `${(a.current_confidence * 100).toFixed(0)}%` : '-'}
                      </span>
                    </div>
                    <div className="text-[11px] truncate" title={a.statement}>{a.statement}</div>
                    <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
                      {a.days_since_validation}d since validation, half-life {a.half_life_days}d
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Elicitation Pulse - from health.elicitation_metrics */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <HelpCircle className="w-4 h-4" style={{ color: '#3b82f6' }} /> Elicitation Pulse (7d)
            </h3>
          </div>
          {!health?.elicitation_metrics ? (
            <BrainEmpty title="No elicitation activity." action="Questions sent to experts appear here." icon={HelpCircle} />
          ) : (() => {
            const em = health.elicitation_metrics as any;
            return (
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {[
                    { label: 'Questions Sent', value: em.questions_sent_7d ?? 0 },
                    { label: 'Response Rate', value: em.response_rate != null ? `${(em.response_rate * 100).toFixed(0)}%` : '-' },
                    { label: 'Entries Created', value: em.entries_created ?? 0 },
                  ].map(s => (
                    <div key={s.label} className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                      <div className="text-[16px] font-bold">{s.value}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                {(em.top_contributors?.length ?? 0) > 0 && (
                  <div>
                    <div className="text-[11px] uppercase tracking-wider mb-1.5" style={{ color: colors.inkSubtle }}>Top Contributors</div>
                    <div className="space-y-1.5">
                      {em.top_contributors.slice(0, 4).map((c: any) => (
                        <div key={c.name} className="flex items-center gap-2">
                          <span className="text-[11px] flex-1 truncate" title={c.name}>{c.name}</span>
                          <div className="w-24 h-1.5 rounded-full overflow-hidden flex-shrink-0" style={{ background: colors.hairline }}>
                            <div className="h-full rounded-full" style={{ width: `${(c.score ?? 0) * 100}%`, background: '#3b82f6' }} />
                          </div>
                          <span className="text-[11px] font-mono w-8 text-right flex-shrink-0" style={{ color: colors.inkSubtle }}>{c.contributions}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>

      {/* Row 5: Recorded Metric Trend + Latency - from the stored MetricSample
          series (app/models/metrics_ts.py), not reconstructed on every read */}
      <div style={card}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[13px] font-semibold flex items-center gap-2">
            <BarChart3 className="w-4 h-4" style={{ color: '#3b82f6' }} /> Recorded Metric Trend
          </h3>
          <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Safe-autonomy rate, stored daily series</span>
        </div>
        <div className="flex items-center gap-8 flex-wrap">
          <div className="flex-1 min-w-[220px]">
            {metricSeries.length >= 2 ? (
              <Sparkline points={metricSeries.map(p => p.value)} color="#3b82f6" width={320} height={52} />
            ) : (
              <BrainEmpty
                title="No stored trend yet."
                action={results.timeseries?.note || 'The hourly rollup has not produced a sample for this window yet.'}
                icon={BarChart3}
              />
            )}
          </div>
          {latencyTiers.length > 0 && (
            <div className="flex gap-4 flex-wrap">
              {latencyTiers.slice(0, 3).map(([tier, stats]) => (
                <div key={tier} className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas, minWidth: '84px' }}>
                  <div className="text-[16px] font-bold" style={{ color: colors.ink }}>{(stats.p50_ms / 1000).toFixed(1)}s</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{humanize(tier)} p50</div>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{stats.calls} calls (24h)</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
