import React, { useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { useParallelApi } from '../hooks/useApi';
import { usePolling } from '../hooks/usePolling';
import { BrainLoading, BrainEmpty, LiveIndicator } from '../components/BrainStates';
import { STREAM_INTERVALS } from '../services/realtime';
import {
  Activity, TrendingUp, TrendingDown, Minus, Shield, Users, Zap, DollarSign,
  BarChart3, MessageSquare, Globe, Target,
  ArrowUpRight, ArrowDownRight, Brain
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
  const { results, loading: initialLoading } = useParallelApi({
    health: () => api.getHealth(),
    feed: () => api.getActivityFeed(15),
    cost: () => api.getCostTelemetry(24),
  });

  // Cockpit-specific data - separate stream for live executive intelligence
  const {
    data: cockpit, isLive, staleness,
  } = usePolling<CockpitData>(
    () => api.getCockpit(),
    STREAM_INTERVALS.COCKPIT,
    { emptyCheck: (d) => !d }
  );

  const health = results.health;
  const feed = results.feed?.events || [];
  const costData = results.cost;

  // ── Derived values - ALL from API, ZERO fallbacks ──
  const score = health?.overall_score ?? 0;
  const scoreColor = score >= 80 ? '#22c55e' : score >= 60 ? '#f59e0b' : score > 0 ? '#ef4444' : colors.inkSubtle;
  const scoreTrend = health?.score_trend || 'stable';
  const trendIcon = scoreTrend === 'up' ? TrendingUp : scoreTrend === 'down' ? TrendingDown : Minus;
  const trendColor = scoreTrend === 'up' ? '#22c55e' : scoreTrend === 'down' ? '#ef4444' : colors.inkSubtle;

  const pioneerAlerts = cockpit?.pioneer_alerts || [];
  const debateQueue = cockpit?.debate_queue || [];
  const orgReadiness = cockpit?.org_readiness || [];

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

  return (
    <div className="p-6 space-y-5" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Executive Cockpit</h1>
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>KAEOS Enterprise Brain - Live intelligence from DB</p>
        </div>
        <LiveIndicator isLive={isLive} staleness={staleness} />
      </div>

      {/* Row 1: System Health Score + KPIs - ALL from health API */}
      <div className="grid grid-cols-5 gap-4">
        {/* Health Score */}
        <div style={{ ...card, gridColumn: 'span 1' }} className="flex flex-col items-center justify-center">
          <span className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>System Health</span>
          <div className="relative w-20 h-20">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="42" fill="none" stroke={colors.hairline} strokeWidth="8" />
              <circle cx="50" cy="50" r="42" fill="none" stroke={scoreColor} strokeWidth="8"
                strokeDasharray={`${score * 2.64} 264`} strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-[22px] font-bold" style={{ color: scoreColor }}>{score}</span>
            </div>
          </div>
          <div className="flex items-center gap-1 mt-2 text-[10px]" style={{ color: trendColor }}>
            {React.createElement(trendIcon, { className: 'w-3 h-3' })}
            {scoreTrend === 'up' ? 'Trending up' : scoreTrend === 'down' ? 'Trending down' : 'Stable'}
          </div>
        </div>

        {/* KPI Cards - values come from health API, show 0 when no data */}
        {[
          { label: 'Total Rules', value: health?.total_rules ?? 0, icon: Shield, color: '#8b5cf6' },
          { label: 'Active Skills', value: health?.total_skills ?? 0, icon: Zap, color: '#3b82f6' },
          { label: 'Executions (7d)', value: health?.agent_metrics?.total_executions_7d ?? 0, icon: Activity, color: '#22c55e' },
          { label: 'Success Rate', value: health?.agent_metrics?.success_rate != null ? `${(health.agent_metrics.success_rate * 100).toFixed(1)}%` : '-', icon: Target, color: '#f59e0b' },
        ].map((kpi, i) => (
          <div key={i} style={card} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: colors.inkSubtle }}>{kpi.label}</span>
              {React.createElement(kpi.icon, { className: 'w-4 h-4', style: { color: kpi.color } })}
            </div>
            <div className="text-[24px] font-bold tracking-tight" style={{ color: colors.ink }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* Row 2: Agent Feed + Pioneer Intelligence + Cost */}
      <div className="grid grid-cols-3 gap-4">
        {/* Active Agent Feed - from api.getActivityFeed() */}
        <div style={card} className="flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Activity className="w-4 h-4" style={{ color: colors.primary }} /> Agent Consciousness Stream
            </h3>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
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
                    <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{e.event_type || 'execution'}</div>
                  </div>
                  <span className="text-[9px] font-mono flex-shrink-0" style={{ color: colors.inkSubtle }}>
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
            <span className="text-[10px]" style={{ color: colors.inkSubtle }}>
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
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: sevColor + '20', color: sevColor }}>
                        {item.type || 'SIGNAL'}
                      </span>
                      <span className="text-[9px]" style={{ color: colors.inkSubtle }}>{item.time || ''}</span>
                    </div>
                    <div className="text-[11px]">{item.title}</div>
                    {item.source && (
                      <div className="text-[9px] mt-1" style={{ color: colors.inkSubtle }}>Source: {item.source}</div>
                    )}
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
                  <div className="text-[10px] uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Token Budget Used</div>
                  <div className="text-[22px] font-bold" style={{ color: colors.ink }}>
                    {costData.budget?.usage_pct ?? 0}%
                  </div>
                  <div className="text-[10px]" style={{ color: colors.inkSubtle }}>
                    {(costData.budget?.token_used ?? 0).toLocaleString()} / {(costData.budget?.token_limit ?? 0).toLocaleString()} tokens
                  </div>
                </div>
                <div className="w-16 h-16 relative">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke={colors.hairline} strokeWidth="6" />
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#22c55e" strokeWidth="6"
                      strokeDasharray={`${Math.max(1.5, (costData.budget?.usage_pct ?? 0) * 2.64)} 264`} strokeLinecap="round" />
                  </svg>
                </div>
              </div>

              {/* Live volume: tokens + LLM calls (last 24h) */}
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[18px] font-bold">{(costData.total_tokens ?? 0).toLocaleString()}</div>
                  <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Tokens (24h)</div>
                </div>
                <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[18px] font-bold">{(costData.total_events ?? 0).toLocaleString()}</div>
                  <div className="text-[9px]" style={{ color: colors.inkSubtle }}>LLM Calls (24h)</div>
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
                    <div className="text-[9px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>Model tiers (tokens · calls)</div>
                    {tiers.map(([name, v]) => (
                      <div key={name} className="flex items-center gap-2">
                        <span className="text-[10px] w-20 truncate capitalize" style={{ color: colors.ink }}>{name}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                          <div className="h-full rounded-full" style={{ width: `${((v?.tokens ?? 0) / maxTok) * 100}%`, background: tierColor[name] || colors.primary }} />
                        </div>
                        <span className="text-[9px] font-mono w-24 text-right" style={{ color: colors.inkSubtle }}>
                          {(v?.tokens ?? 0).toLocaleString()} · {v?.calls ?? 0}
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
                  <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Cost (24h)</div>
                </div>
                <div className="p-2 rounded-lg text-center" style={{ background: colors.canvas }}>
                  <div className="text-[15px] font-bold">${(costData.avg_cost_per_task ?? 0).toFixed(3)}</div>
                  <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Avg/Task</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Debate Queue + Org Readiness + Confidence Distribution */}
      <div className="grid grid-cols-3 gap-4">
        {/* Debate Queue - FROM cockpit API, NOT HARDCODED */}
        <div style={card}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <MessageSquare className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Debate Engine
            </h3>
            {debateQueue.length > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold"
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
                    <span className="text-[10px]" style={{ color: colors.inkSubtle }}>
                      {d.status || 'OPEN'}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono" style={{ color: '#f59e0b' }}>
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
                return (
                  <div key={bu.bu} className="flex items-center gap-3">
                    <span className="text-[11px] w-20 truncate capitalize">{bu.bu}</span>
                    <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full transition-all" style={{ width: `${buScore}%`, background: color }} />
                    </div>
                    <span className="text-[11px] font-mono w-10 text-right" style={{ color }}>{buScore}%</span>
                    {bu.rule_count != null && (
                      <span className="text-[9px]" style={{ color: colors.inkSubtle }}>{bu.rule_count}r</span>
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
            const total = tiers.reduce((s, t) => s + t.count, 0) || 1;
            return (
              <div className="space-y-2">
                {tiers.map(t => (
                  <div key={t.tier} className="flex items-center gap-2">
                    <span className="text-[9px] font-mono w-20 truncate" style={{ color: t.color }}>{t.tier}</span>
                    <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full" style={{ width: `${(t.count / total) * 100}%`, background: t.color + '80' }} />
                    </div>
                    <span className="text-[10px] font-mono w-6 text-right">{t.count}</span>
                  </div>
                ))}
                <div className="text-[10px] text-center pt-1" style={{ color: colors.inkSubtle }}>
                  {total} total rules
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
