import React, { useEffect, useState } from 'react';
import { Activity, Zap, ShieldCheck, Clock, AlertTriangle, CheckCircle2, XCircle, ArrowUpRight, ArrowDownRight, TrendingUp, RefreshCw, Eye } from 'lucide-react';
import { api } from '../api/client';
import type { KBHealth } from '../api/client';
import { useTheme } from '../context/ThemeContext';

interface FeedEvent {
  id: string; event_type: string; title: string; description?: string;
  severity: string; created_at: string; is_read: boolean; requires_action: boolean;
  source_type?: string; source_id?: string;
}

const FEED_LIMIT_DEFAULT = 30;
const FEED_LIMIT_ALL = 100;

const CommandCenter: React.FC<{ domain?: string }> = ({ domain = 'All Domains' }) => {
  const { colors } = useTheme();
  const [health, setHealth] = useState<KBHealth | null>(null);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [actions, setActions] = useState<FeedEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedLimit, setFeedLimit] = useState(FEED_LIMIT_DEFAULT);
  // Every source failing is a real load error (partial success still renders).
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = async (limit = feedLimit) => {
    setLoading(true);
    const [h, f, a] = await Promise.allSettled([
      api.getHealth(),
      api.getActivityFeed(limit, false),
      api.getActionRequired(),
    ]);
    if (h.status === 'fulfilled') setHealth(h.value);
    if (f.status === 'fulfilled') setFeed(f.value?.events || []);
    if (a.status === 'fulfilled') setActions(a.value?.events || []);
    if (h.status === 'rejected' && f.status === 'rejected' && a.status === 'rejected') {
      const reason: any = h.reason;
      setLoadError(reason?.message || 'Failed to load operational intelligence.');
    } else {
      setLoadError(null);
    }
    setLoading(false);
    setFeedLoading(false);
  };

  // "View all" toggles how many feed events we pull, then re-queries.
  const toggleFeedView = () => {
    const next = feedLimit === FEED_LIMIT_DEFAULT ? FEED_LIMIT_ALL : FEED_LIMIT_DEFAULT;
    setFeedLimit(next);
    refresh(next);
  };

  useEffect(() => { refresh(); const i = setInterval(() => refresh(), 30000); return () => clearInterval(i); }, []);

  const severityColor = (s: string) => {
    if (s === 'CRITICAL') return colors.error;
    if (s === 'ACTION_REQUIRED' || s === 'WARNING') return colors.warning;
    return colors.success;
  };

  const timeAgo = (iso: string) => {
    const d = Date.now() - new Date(iso).getTime();
    if (d < 60000) return 'just now';
    if (d < 3600000) return `${Math.floor(d / 60000)}m ago`;
    if (d < 86400000) return `${Math.floor(d / 3600000)}h ago`;
    return `${Math.floor(d / 86400000)}d ago`;
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>Command Center</h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>Live operational intelligence - auto-refreshes every 30s</p>
        </div>
        <button onClick={() => refresh()} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Load failure - every source is down; offer a retry, not a blank screen */}
      {loadError && (
        <div className="flex items-center justify-between gap-3 rounded-xl px-4 py-3 text-[13px]"
          style={{ background: colors.error + '10', border: `1px solid ${colors.error}33`, color: colors.error }}>
          <span className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 shrink-0" /> {loadError}</span>
          <button onClick={() => refresh()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium hover:opacity-80"
            style={{ background: colors.error + '18' }}>
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      )}

      {/* Metric Cards Row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Overall KB Score', value: health?.overall_score ?? '-', suffix: '/ 100', trend: health?.score_trend, icon: TrendingUp, accent: colors.primary },
          { label: 'Total Rules', value: health?.total_rules ?? '-', icon: ShieldCheck, accent: colors.info },
          { label: 'Active Skills', value: health?.total_skills ?? '-', icon: Zap, accent: colors.primaryHover },
          { label: 'Success Rate', value: health?.agent_metrics?.success_rate != null ? `${Math.round(health.agent_metrics.success_rate * 100)}%` : '-', icon: CheckCircle2, accent: colors.success },
        ].map((m, i) => (
          <div key={i} className="rounded-xl p-5 transition-all duration-300" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: colors.inkSubtle, letterSpacing: '0.5px' }}>{m.label}</span>
              <m.icon className="w-4 h-4" style={{ color: m.accent }} />
            </div>
            <div className="flex items-end gap-2">
              <span className="text-[32px] font-bold tracking-tight" style={{ letterSpacing: '-1.2px', color: colors.ink, fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
              {m.suffix && <span className="text-[14px] mb-1" style={{ color: colors.inkTertiary }}>{m.suffix}</span>}
              {m.trend && (
                <span className="flex items-center gap-0.5 text-[12px] font-medium mb-1" style={{ color: m.trend.startsWith('+') ? colors.success : colors.error }}>
                  {m.trend.startsWith('+') ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}{m.trend}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Two Column: Activity Feed + Agent Performance */}
      <div className="grid grid-cols-3 gap-4">
        {/* Activity Feed - 2 cols */}
        <div className="col-span-2 rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: colors.hairline }}>
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Activity Feed</span>
              {actions.length > 0 && (
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full" style={{ background: 'rgba(229,83,75,0.12)', color: '#f87171', border: '1px solid rgba(229,83,75,0.2)' }}>
                  {actions.length} action{actions.length > 1 ? 's' : ''} required
                </span>
              )}
            </div>
            <button onClick={toggleFeedView} disabled={loading} className="text-[12px] transition-opacity hover:opacity-70 disabled:opacity-40"
              style={{ color: colors.primary }}>
              {feedLimit === FEED_LIMIT_DEFAULT ? 'View all' : 'Show less'}
            </button>
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            {feed.length === 0 && !feedLoading && (
              <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No activity yet. Deploy an agent to start.</div>
            )}
            {feed.map((ev, i) => (
              <div key={ev.id || i} className="flex gap-3 px-5 py-3 border-b transition-colors duration-150" 
                style={{ borderColor: colors.hairline, borderLeft: !ev.is_read ? `2px solid ${colors.primary}` : '2px solid transparent' }}
                onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: severityColor(ev.severity), boxShadow: `0 0 6px ${severityColor(ev.severity)}60` }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium truncate" style={{ color: colors.ink }}>{ev.title}</span>
                    {ev.requires_action && <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(245,166,35,0.12)', color: '#fbbf24' }}>Action</span>}
                  </div>
                  {ev.description && <p className="text-[12px] mt-0.5 truncate" style={{ color: colors.inkSubtle }}>{ev.description}</p>}
                </div>
                <span className="text-[11px] flex-shrink-0" style={{ color: colors.inkTertiary }}>{timeAgo(ev.created_at)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: Confidence + Agent Perf */}
        <div className="space-y-4">
          {/* Confidence Distribution */}
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-4">
              <Eye className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Confidence</span>
            </div>
            {health?.confidence_distribution && (
              <div className="space-y-2.5">
                {[
                  { label: 'Verified', key: 'verified', color: colors.success },
                  { label: 'Validated', key: 'validated_dh', color: colors.info },
                  { label: 'Inferred', key: 'inferred', color: colors.warning },
                  { label: 'Speculative', key: 'speculative', color: colors.error },
                ].map(t => {
                  const cd = health.confidence_distribution as unknown as Record<string, number>;
                  const val = Math.round((cd[t.key] || 0) * 100);
                  return (
                    <div key={t.key}>
                      <div className="flex justify-between text-[12px] mb-1">
                        <span style={{ color: colors.inkSubtle }}>{t.label}</span>
                        <span style={{ color: t.color }} className="font-medium">{val}%</span>
                      </div>
                      <div className="h-1.5 rounded-full" style={{ background: colors.surface3 }}>
                        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${val}%`, background: t.color }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {!health?.confidence_distribution && <div className="text-[12px]" style={{ color: colors.inkTertiary }}>Loading…</div>}
          </div>

          {/* Agent Performance */}
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-4">
              <Zap className="w-4 h-4" style={{ color: colors.primaryHover }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Agent Performance</span>
            </div>
            {health?.agent_metrics ? (
              <div className="space-y-2">
                {[
                  { label: 'Executions (7d)', val: health.agent_metrics.total_executions_7d?.toLocaleString() },
                  { label: 'RAG Fallback', val: `${Math.round((health.agent_metrics.rag_fallback_rate || 0) * 100)}%` },
                  { label: 'Human Overrides', val: health.agent_metrics.human_overrides },
                  { label: 'Avg Duration', val: `${health.agent_metrics.avg_duration_ms || 0}ms` },
                ].map(r => (
                  <div key={r.label} className="flex justify-between text-[12px]">
                    <span style={{ color: colors.inkSubtle }}>{r.label}</span>
                    <span className="font-medium" style={{ color: colors.ink }}>{r.val}</span>
                  </div>
                ))}
              </div>
            ) : <div className="text-[12px]" style={{ color: colors.inkTertiary }}>Loading…</div>}
          </div>

          {/* Decay Alerts */}
          {(health?.decay_alerts?.length ?? 0) > 0 && (
            <div className="rounded-xl p-4" style={{ background: 'rgba(229,83,75,0.06)', border: '1px solid rgba(229,83,75,0.15)' }}>
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4" style={{ color: colors.error }} />
                <span className="text-[13px] font-medium" style={{ color: colors.error }}>Decay Alerts</span>
              </div>
              <p className="text-[12px]" style={{ color: colors.inkMuted }}>{health?.decay_alerts?.length ?? 0} rules need urgent revalidation</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CommandCenter;
