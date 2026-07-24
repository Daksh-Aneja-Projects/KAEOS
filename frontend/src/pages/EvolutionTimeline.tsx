import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import {
  RefreshCw, TrendingUp, TrendingDown, AlertTriangle, CheckCircle2,
  MessageSquare, Brain, Zap, ChevronRight, ArrowUpRight, ArrowDownRight,
  Clock, BarChart3
} from 'lucide-react';

interface EvolutionEvent {
  id: string;
  type: 'confidence_update' | 'rule_evolved' | 'elicitation_triggered' | 'pattern_detected' | 'drift_alert';
  title: string;
  description: string;
  delta?: number;
  timestamp: string;
  source?: string;
}

export default function EvolutionTimeline({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [health, setHealth] = useState<any>(null);
  const [executions, setExecCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<EvolutionEvent[]>([]);
  const [outcomeImpact, setOutcomeImpact] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [recordingId, setRecordingId] = useState<string | null>(null);

  const recordOutcomeFor = async (executionId: string, outcome: 'GOOD' | 'BAD' | 'NEUTRAL') => {
    setRecordingId(executionId);
    try {
      await api.recordOutcome(executionId, outcome);
      setDecisions(prev => prev.map(d => (d.execution_id === executionId ? { ...d, _recorded: outcome } : d)));
      const impact = await api.getOutcomeImpact(30);
      setOutcomeImpact(impact);
    } catch (e) {
      console.error('Record outcome failed', e);
    } finally {
      setRecordingId(null);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      const [h, feed, impact, dfeed] = await Promise.allSettled([
        api.getHealth(),
        api.getActivityFeed(50, false),
        api.getOutcomeImpact(30),
        api.getDecisionFeed(),
      ]);
      if (impact.status === 'fulfilled') setOutcomeImpact(impact.value);
      if (dfeed.status === 'fulfilled') setDecisions(dfeed.value?.decisions || []);

      if (h.status === 'fulfilled') {
        setHealth(h.value);
        setExecCount(h.value?.total_executions || 0);
      }

      // Synthesize evolution events from activity feed + health data
      const synthesized: EvolutionEvent[] = [];
      const now = new Date();

      if (h.status === 'fulfilled' && h.value) {
        const hv = h.value;
        // Confidence updates from decay alerts
        (hv.decay_alerts || []).forEach((da: any, i: number) => {
          synthesized.push({
            id: `decay-${i}`,
            type: 'drift_alert',
            title: `Confidence decay detected`,
            description: `Rule "${(da.statement || '').slice(0, 60)}…" - confidence dropped to ${(da.current_confidence * 100).toFixed(0)}%. ${da.days_since_validation}d since last validation.`,
            delta: -(1 - da.current_confidence),
            timestamp: new Date(now.getTime() - da.days_since_validation * 86400000).toISOString(),
            source: da.domain,
          });
        });

        // Score trend
        if (hv.score_trend) {
          const trendNum = parseFloat(hv.score_trend);
          const hasDelta = Number.isFinite(trendNum) && trendNum !== 0;
          const title = !hasDelta
            ? 'KB overall score held steady'
            : `KB overall score ${trendNum > 0 ? 'improved' : 'declined'}`;
          synthesized.push({
            id: 'score-trend',
            type: 'confidence_update',
            title,
            description: `Overall knowledge base health is ${hv.overall_score}/100${hasDelta ? ` (moved ${hv.score_trend})` : ' (stable)'}.`,
            delta: hasDelta ? trendNum / 100 : undefined,
            timestamp: now.toISOString(),
          });
        }

        // Agent performance evolution
        if (hv.agent_metrics) {
          const am = hv.agent_metrics;
          if (am.total_executions_7d > 0) {
            synthesized.push({
              id: 'exec-evolution',
              type: 'confidence_update',
              title: `${am.total_executions_7d} executions this week`,
              description: `Success rate: ${(am.success_rate * 100).toFixed(1)}%. RAG fallback: ${(am.rag_fallback_rate * 100).toFixed(1)}%. Human overrides: ${am.human_overrides}.`,
              delta: am.success_rate - 0.9,
              timestamp: now.toISOString(),
            });
          }
          if (am.human_overrides > 0) {
            synthesized.push({
              id: 'overrides',
              type: 'elicitation_triggered',
              title: `${am.human_overrides} human overrides triggered`,
              description: `Agents escalated to human review - elicitation questions generated for domain experts to close knowledge gaps.`,
              timestamp: new Date(now.getTime() - 3600000).toISOString(),
            });
          }
        }

        // Elicitation metrics
        if (hv.elicitation_metrics) {
          const em = hv.elicitation_metrics;
          if (em.entries_created > 0) {
            synthesized.push({
              id: 'elicitation-loop',
              type: 'rule_evolved',
              title: `${em.entries_created} new knowledge entries from expert answers`,
              description: `${em.questions_sent_7d} questions sent, ${(em.response_rate * 100).toFixed(0)}% response rate. Average answer time: ${em.avg_time_to_answer_hours.toFixed(1)}h.`,
              delta: em.response_rate * 0.05,
              timestamp: new Date(now.getTime() - 7200000).toISOString(),
            });
          }
        }

        // Freshness distribution
        if (hv.freshness) {
          if (hv.freshness.expired > 0) {
            synthesized.push({
              id: 'freshness-expired',
              type: 'drift_alert',
              title: `${hv.freshness.expired} rules have expired`,
              description: `${hv.freshness.within_half_life} rules are fresh, ${hv.freshness.decaying} are decaying, ${hv.freshness.expired} need revalidation.`,
              delta: -0.1,
              timestamp: new Date(now.getTime() - 86400000).toISOString(),
            });
          }
        }
      }

      // Add activity feed events as pattern detections
      if (feed.status === 'fulfilled') {
        const feedEvents = feed.value?.events || [];
        feedEvents.slice(0, 5).forEach((fe: any, i: number) => {
          if (fe.event_type === 'EXECUTION_FAILED' || fe.event_type === 'GATE_BLOCKED') {
            synthesized.push({
              id: `feed-${fe.id || i}`,
              type: 'pattern_detected',
              title: fe.title,
              description: fe.description || 'Execution event detected by the feedback loop.',
              timestamp: fe.created_at,
            });
          }
        });
      }

      // Sort by timestamp descending
      synthesized.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      setEvents(synthesized);
      setLoading(false);
    };
    load();
  }, []);

  const eventIcon = (type: string) => {
    switch (type) {
      case 'confidence_update': return <TrendingUp className="w-4 h-4" />;
      case 'rule_evolved': return <Brain className="w-4 h-4" />;
      case 'elicitation_triggered': return <MessageSquare className="w-4 h-4" />;
      case 'pattern_detected': return <Zap className="w-4 h-4" />;
      case 'drift_alert': return <AlertTriangle className="w-4 h-4" />;
      default: return <RefreshCw className="w-4 h-4" />;
    }
  };

  const eventColor = (type: string) => {
    switch (type) {
      case 'confidence_update': return colors.success;
      case 'rule_evolved': return colors.primary;
      case 'elicitation_triggered': return colors.info;
      case 'pattern_detected': return colors.primaryHover;
      case 'drift_alert': return colors.warning;
      default: return colors.inkSubtle;
    }
  };

  const timeAgo = (iso: string) => {
    const d = Date.now() - new Date(iso).getTime();
    if (d < 60000) return 'just now';
    if (d < 3600000) return `${Math.floor(d / 60000)}m ago`;
    if (d < 86400000) return `${Math.floor(d / 3600000)}h ago`;
    return `${Math.floor(d / 86400000)}d ago`;
  };

  if (loading) return <div className="p-8 animate-pulse" style={{ color: colors.inkTertiary }}>Loading Evolution Timeline…</div>;

  const successRate = health?.agent_metrics?.success_rate || 0;
  const totalRules = health?.total_rules || 0;
  const totalSkills = health?.total_skills || 0;

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>
          <RefreshCw className="w-7 h-7 inline-block mr-2" style={{ color: colors.primary }} />
          Intelligence Evolution
        </h1>
        <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
          How your knowledge base is learning and evolving from production outcomes
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Success Rate', value: `${(successRate * 100).toFixed(1)}%`, icon: CheckCircle2, color: colors.success, trend: successRate > 0.9 ? '+' : '-' },
          { label: 'Active Rules', value: totalRules, icon: Brain, color: colors.primary },
          { label: 'Active Skills', value: totalSkills, icon: Zap, color: colors.primaryHover },
          { label: 'Executions', value: executions.toLocaleString(), icon: BarChart3, color: colors.info },
        ].map((m, i) => (
          <div key={i} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: colors.inkTertiary }}>{m.label}</span>
              <m.icon className="w-4 h-4" style={{ color: m.color }} />
            </div>
            <span className="text-[24px] font-bold" style={{ color: colors.ink, fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
          </div>
        ))}
      </div>

      {/* Flywheel Visualization */}
      <div className="rounded-xl p-5" style={{ background: `${colors.primary}06`, border: `1px solid ${colors.primary}15` }}>
        <div className="flex items-center gap-2 mb-3">
          <RefreshCw className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Active Flywheel</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          {[
            { label: 'Execute', desc: `${executions} decisions made` },
            { label: 'Evaluate', desc: `${(successRate * 100).toFixed(0)}% success rate` },
            { label: 'Learn', desc: `${health?.elicitation_metrics?.entries_created || 0} new entries` },
            { label: 'Evolve', desc: `${health?.decay_alerts?.length || 0} rules recalibrating` },
          ].map((step, i) => (
            <React.Fragment key={step.label}>
              <div className="flex-1 text-center p-3 rounded-lg" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <span className="text-[12px] font-semibold block" style={{ color: colors.primary }}>{step.label}</span>
                <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{step.desc}</span>
              </div>
              {i < 3 && <ChevronRight className="w-4 h-4 flex-shrink-0" style={{ color: colors.hairlineStrong }} />}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Outcome Intelligence — the decision → outcome learning loop */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-2 mb-1">
          <BarChart3 className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Outcome Intelligence</span>
        </div>
        <p className="text-[12px] mb-4" style={{ color: colors.inkSubtle }}>
          How decisions turned out in reality, and how autonomous vs human decisions compare. Recording an outcome feeds back into the skill's confidence.
        </p>
        {outcomeImpact && outcomeImpact.total > 0 ? (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Good', value: outcomeImpact.distribution?.good ?? 0, color: '#22c55e' },
                { label: 'Neutral', value: outcomeImpact.distribution?.neutral ?? 0, color: '#8b5cf6' },
                { label: 'Bad', value: outcomeImpact.distribution?.bad ?? 0, color: '#ef4444' },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[22px] font-bold" style={{ color: s.color }}>{s.value}</div>
                  <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Autonomous decisions', d: outcomeImpact.autonomous },
                { label: 'Human-gated decisions', d: outcomeImpact.human },
              ].map(x => (
                <div key={x.label} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{x.label}</div>
                  <div className="text-[18px] font-bold" style={{ color: colors.ink }}>
                    {x.d?.good_rate == null ? '--' : `${(x.d.good_rate * 100).toFixed(0)}%`}
                    <span className="text-[11px] font-normal ml-1" style={{ color: colors.inkSubtle }}>good ({x.d?.total ?? 0})</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="text-[12px] italic" style={{ color: colors.inkSubtle }}>No outcomes recorded yet. Mark a recent decision below to start the loop.</div>
        )}

        {decisions.length > 0 && (
          <div className="mt-5">
            <div className="text-[11px] uppercase tracking-wide font-semibold mb-2" style={{ color: colors.inkSubtle }}>Record an outcome</div>
            <div className="space-y-2">
              {decisions.slice(0, 6).map((d: any) => (
                <div key={d.execution_id} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{d.skill_id || d.task_intent || d.execution_id}</div>
                    <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{d.status}</div>
                  </div>
                  {d._recorded ? (
                    <span className="text-[11px] font-semibold" style={{ color: d._recorded === 'GOOD' ? '#22c55e' : d._recorded === 'BAD' ? '#ef4444' : '#8b5cf6' }}>
                      {d._recorded} recorded
                    </span>
                  ) : (
                    <div className="flex gap-1.5">
                      {(['GOOD', 'NEUTRAL', 'BAD'] as const).map(o => {
                        const c = o === 'GOOD' ? '#22c55e' : o === 'BAD' ? '#ef4444' : '#8b5cf6';
                        return (
                          <button key={o} disabled={recordingId === d.execution_id}
                            onClick={() => recordOutcomeFor(d.execution_id, o)}
                            className="px-2 py-1 rounded text-[10px] font-semibold transition-opacity"
                            style={{ background: c + '18', color: c, opacity: recordingId === d.execution_id ? 0.5 : 1 }}>
                            {o}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-2 px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <Clock className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Evolution Timeline</span>
          <span className="text-[11px] ml-auto" style={{ color: colors.inkTertiary }}>{events.length} events</span>
        </div>
        <div className="max-h-[500px] overflow-y-auto">
          {events.length === 0 && (
            <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>
              No evolution events yet. Deploy agents and execute skills to start the feedback loop.
            </div>
          )}
          {events.map((ev, i) => {
            const ec = eventColor(ev.type);
            return (
              <div key={ev.id} className="flex gap-4 px-5 py-3.5 border-b transition-colors"
                style={{ borderColor: colors.hairline }}
                onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                {/* Timeline dot + line */}
                <div className="flex flex-col items-center">
                  <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
                    style={{ background: `${ec}15`, color: ec }}>
                    {eventIcon(ev.type)}
                  </div>
                  {i < events.length - 1 && <div className="w-px flex-1 mt-1" style={{ background: colors.hairline }} />}
                </div>
                {/* Content */}
                <div className="flex-1 min-w-0 pb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{ev.title}</span>
                    {ev.delta != null && (
                      <span className="flex items-center gap-0.5 text-[11px] font-medium"
                        style={{ color: ev.delta >= 0 ? colors.success : colors.error }}>
                        {ev.delta >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                        {ev.delta >= 0 ? '+' : ''}{(ev.delta * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{ev.description}</p>
                  <div className="flex items-center gap-3 mt-1.5">
                    <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{timeAgo(ev.timestamp)}</span>
                    {ev.source && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{ background: colors.surface3, color: colors.inkTertiary }}>{ev.source}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
