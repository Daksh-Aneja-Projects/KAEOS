import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ExecutionItem } from '../api/client';
import FeedbackCapture from './FeedbackCapture';
import {
  ShieldCheck, Scale, Gauge, Swords, Cpu, Link2, MessageSquare,
  CheckCircle2, XCircle, AlertTriangle, Clock, ChevronDown, ChevronRight,
  ArrowLeft, Loader2, Shield, Eye, Hash, User2, Zap
} from 'lucide-react';

interface Props {
  execution: ExecutionItem;
  onBack: () => void;
  colors: any;
}

interface DebateData {
  proposer_argument?: any;
  advocate_argument?: any;
  arbitrator_decision?: any;
  trigger_reason?: string;
  debate_duration_ms?: number;
  escalated_to_hitl?: boolean;
}

interface FairnessData {
  fairness_score?: number;
  threshold_used?: number;
  passed?: boolean;
  protected_attributes_assessed?: string[];
  attribute_scores?: Record<string, { score: number; flag: boolean }>;
  flagged_attributes?: string[];
  rationale?: string;
}

// ── 7-Gate Pipeline Definition ──────────────────────────────────────────────
const GATES = [
  { id: 'compliance',  label: 'Compliance',     icon: ShieldCheck,    desc: 'SOX / GDPR / PCI pre-check' },
  { id: 'fairness',    label: 'Fairness',       icon: Scale,          desc: 'Demographic impact scoring' },
  { id: 'confidence',  label: 'Confidence',     icon: Gauge,          desc: 'Threshold check + HITL gate' },
  { id: 'debate',      label: 'Debate Engine',  icon: Swords,         desc: 'Adversarial reasoning' },
  { id: 'execution',   label: 'LLM Execution',  icon: Cpu,            desc: 'Step-by-step skill execution' },
  { id: 'provenance',  label: 'Provenance',     icon: Link2,          desc: 'SHA-256 hash chain audit' },
  { id: 'feedback',    label: 'Feedback Loop',  icon: MessageSquare,  desc: 'Bayesian confidence update' },
];

export default function ExecutionDetailView({ execution, onBack, colors }: Props) {
  const [debate, setDebate] = useState<DebateData | null>(null);
  const [fairness, setFairness] = useState<FairnessData[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['pipeline', 'reasoning']));

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      const [d, f] = await Promise.allSettled([
        api.getDebateTranscript(execution.id),
        api.getFairnessLog(10),
      ]);
      if (d.status === 'fulfilled' && d.value) setDebate(d.value);
      if (f.status === 'fulfilled' && f.value) {
        const logs = f.value.logs || f.value || [];
        const matched = Array.isArray(logs) ? logs.filter((l: any) => l.execution_id === execution.id) : [];
        setFairness(matched);
      }
      setLoading(false);
    };
    load();
  }, [execution.id]);

  const toggleSection = (id: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const isSuccess = execution.status.includes('SUCCESS');
  const isHITL = execution.hitl_required || execution.outcome_type === 'HUMAN_OVERRIDDEN';
  const isFailed = execution.status.includes('FAILED');

  // Derive gate statuses from execution data
  const gateStatus = (gateId: string): 'pass' | 'fail' | 'skip' | 'hitl' => {
    if (gateId === 'compliance') return isFailed && execution.status.includes('COMPLIANCE') ? 'fail' : 'pass';
    if (gateId === 'fairness') return fairness.length > 0 && !fairness[0]?.passed ? 'fail' : 'pass';
    if (gateId === 'confidence') return isHITL ? 'hitl' : 'pass';
    if (gateId === 'debate') {
      if (!debate || debate.trigger_reason === 'not_required') return 'skip';
      return debate.arbitrator_decision?.decision === 'BLOCK' ? 'fail' : debate.escalated_to_hitl ? 'hitl' : 'pass';
    }
    if (gateId === 'execution') return isFailed ? 'fail' : 'pass';
    if (gateId === 'provenance') return 'pass';
    if (gateId === 'feedback') return 'pass';
    return 'pass';
  };

  const statusColor = (s: 'pass' | 'fail' | 'skip' | 'hitl') => {
    switch (s) {
      case 'pass': return { bg: 'rgba(39,166,68,0.12)', border: 'rgba(39,166,68,0.3)', text: colors.success, icon: <CheckCircle2 className="w-3.5 h-3.5" /> };
      case 'fail': return { bg: 'rgba(229,83,75,0.12)', border: 'rgba(229,83,75,0.3)', text: colors.error, icon: <XCircle className="w-3.5 h-3.5" /> };
      case 'hitl': return { bg: 'rgba(245,166,35,0.12)', border: 'rgba(245,166,35,0.3)', text: colors.warning, icon: <AlertTriangle className="w-3.5 h-3.5" /> };
      case 'skip': return { bg: 'rgba(138,143,152,0.08)', border: colors.hairline, text: colors.inkTertiary, icon: <Clock className="w-3.5 h-3.5" /> };
    }
  };

  // ── Section Wrapper ────────────────────────────────────────────────────────
  const renderSection = ({ id, title, icon: Icon, badge, children }: { id: string; title: string; icon: any; badge?: React.ReactNode; children: React.ReactNode }) => {
    const open = expandedSections.has(id);
    return (
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <button onClick={() => toggleSection(id)}
          className="w-full flex items-center gap-3 px-5 py-3.5 text-left transition-colors"
          style={{ borderBottom: open ? `1px solid ${colors.hairline}` : 'none' }}
          onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
          onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
          <Icon className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium flex-1" style={{ color: colors.ink }}>{title}</span>
          {badge}
          {open ? <ChevronDown className="w-4 h-4" style={{ color: colors.inkTertiary }} /> : <ChevronRight className="w-4 h-4" style={{ color: colors.inkTertiary }} />}
        </button>
        {open && <div className="px-5 py-4">{children}</div>}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center gap-3" style={{ color: colors.inkSubtle }}>
        <Loader2 className="w-5 h-5 animate-spin" /> Loading execution details…
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-5">
      {/* ── Back + Header ───────────────────────────────────────────────── */}
      <button onClick={onBack} className="flex items-center gap-1.5 text-[13px] font-medium transition-colors"
        style={{ color: colors.primary }}
        onMouseEnter={e => (e.currentTarget.style.opacity = '0.8')}
        onMouseLeave={e => (e.currentTarget.style.opacity = '1')}>
        <ArrowLeft className="w-4 h-4" /> Back to executions
      </button>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-[24px] font-semibold tracking-tight" style={{ letterSpacing: '-0.5px', color: colors.ink }}>
            {execution.task_intent || 'Execution Detail'}
          </h1>
          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-[12px] font-mono" style={{ color: colors.inkTertiary }}>{execution.id.slice(0, 12)}…</span>
            <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{new Date(execution.started_at).toLocaleString()}</span>
            <span className="text-[12px] font-mono" style={{ color: colors.inkSubtle }}>{execution.duration_ms}ms</span>
          </div>
        </div>
        <span className="text-[12px] font-semibold px-3 py-1 rounded-full"
          style={{
            background: isSuccess ? 'rgba(39,166,68,0.12)' : isFailed ? 'rgba(229,83,75,0.12)' : 'rgba(245,166,35,0.12)',
            color: isSuccess ? colors.success : isFailed ? colors.error : colors.warning,
            border: `1px solid ${isSuccess ? 'rgba(39,166,68,0.25)' : isFailed ? 'rgba(229,83,75,0.25)' : 'rgba(245,166,35,0.25)'}`,
          }}>
          {execution.status.replace(/_/g, ' ')}
        </span>
      </div>

      {/* ── 7-Gate Pipeline ─────────────────────────────────────────────── */}
      {renderSection({ id: "pipeline", title: "7-Gate Trust Pipeline", icon: Shield,
        badge: (
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
            style={{ background: isSuccess ? 'rgba(39,166,68,0.1)' : 'rgba(229,83,75,0.1)', color: isSuccess ? colors.success : colors.error }}>
            {isSuccess ? 'All Gates Passed' : isFailed ? 'Gate Failed' : 'HITL Triggered'}
          </span>
        ),
        children: (
        <div className="flex items-center gap-1 overflow-x-auto pb-2">
          {GATES.map((gate, i) => {
            const status = gateStatus(gate.id);
            const sc = statusColor(status);
            return (
              <React.Fragment key={gate.id}>
                <div className="flex flex-col items-center gap-2 min-w-[120px] p-3 rounded-lg transition-all"
                  style={{ background: sc.bg, border: `1px solid ${sc.border}` }}>
                  <div className="flex items-center gap-1.5">
                    <gate.icon className="w-4 h-4" style={{ color: sc.text }} />
                    <span className="text-[11px] font-semibold" style={{ color: sc.text }}>{gate.label}</span>
                  </div>
                  <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{gate.desc}</span>
                  <div className="flex items-center gap-1" style={{ color: sc.text }}>
                    {sc.icon}
                    <span className="text-[10px] font-bold uppercase">
                      {status === 'pass' ? 'Passed' : status === 'fail' ? 'Failed' : status === 'hitl' ? 'HITL' : 'Skipped'}
                    </span>
                  </div>
                </div>
                {i < GATES.length - 1 && (
                  <div className="flex-shrink-0 w-6 h-px" style={{ background: `linear-gradient(90deg, ${sc.text}40, ${colors.hairline})` }} />
                )}
              </React.Fragment>
            );
          })}
        </div>
        )
      })}

      {/* ── Reasoning Chain ──────────────────────────────────────────────── */}
      {renderSection({ id: "reasoning", title: "Reasoning Chain", icon: Zap,
        badge: <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{execution.reasoning_chain?.length || 0} steps</span>,
        children: (
        execution.reasoning_chain?.length > 0 ? (
          <div className="space-y-2">
            {execution.reasoning_chain.map((step: any, i: number) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-lg transition-all"
                style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-[11px] font-bold"
                  style={{
                    background: step.status === 'SUCCESS' ? 'rgba(39,166,68,0.12)' : step.status === 'FAILED' ? 'rgba(229,83,75,0.12)' : 'rgba(138,143,152,0.12)',
                    color: step.status === 'SUCCESS' ? colors.success : step.status === 'FAILED' ? colors.error : colors.inkSubtle,
                    border: `1px solid ${step.status === 'SUCCESS' ? 'rgba(39,166,68,0.25)' : step.status === 'FAILED' ? 'rgba(229,83,75,0.25)' : colors.hairline}`,
                  }}>
                  {step.step || i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{step.action || step.step_id || `Step ${i + 1}`}</span>
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                      style={{
                        background: step.status === 'SUCCESS' ? 'rgba(39,166,68,0.1)' : 'rgba(229,83,75,0.1)',
                        color: step.status === 'SUCCESS' ? colors.success : colors.error,
                      }}>
                      {step.status}
                    </span>
                    {step.confidence != null && (
                      <span className="text-[10px] font-mono" style={{ color: colors.inkTertiary }}>conf: {typeof step.confidence === 'number' ? step.confidence.toFixed(2) : step.confidence}</span>
                    )}
                  </div>
                  {step.decision && <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>{step.decision}</p>}
                  {step.tool_called && (
                    <span className="inline-flex items-center gap-1 text-[10px] mt-1 px-1.5 py-0.5 rounded font-mono"
                      style={{ background: 'rgba(94,106,210,0.08)', color: colors.primary }}>
                      <Cpu className="w-3 h-3" /> {step.tool_called}
                    </span>
                  )}
                  {step.error && <p className="text-[11px] mt-1 font-mono" style={{ color: colors.error }}>{step.error}</p>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px]" style={{ color: colors.inkTertiary }}>No reasoning chain recorded for this execution.</p>
        )
        )
      })}

      {/* ── Debate Transcript ────────────────────────────────────────────── */}
      {debate && debate.trigger_reason !== 'not_required' && (
        renderSection({ id: "debate", title: "Debate Transcript", icon: Swords,
          badge: (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
              style={{
                background: debate.arbitrator_decision?.decision === 'PROCEED' ? 'rgba(39,166,68,0.1)' : 'rgba(229,83,75,0.1)',
                color: debate.arbitrator_decision?.decision === 'PROCEED' ? colors.success : colors.error,
              }}>
              {debate.arbitrator_decision?.decision || 'PENDING'}
            </span>
          ),
          children: (
          <div className="space-y-4">
            {/* Trigger Reason */}
            <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkSubtle }}>
              <AlertTriangle className="w-3.5 h-3.5" style={{ color: colors.warning }} />
              Debate triggered: <span className="font-medium" style={{ color: colors.ink }}>{debate.trigger_reason}</span>
              {debate.debate_duration_ms != null && <span className="font-mono ml-2">{debate.debate_duration_ms}ms</span>}
            </div>

            {/* Three-Agent Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Proposer */}
              <div className="rounded-lg p-4" style={{ background: 'rgba(39,166,68,0.05)', border: '1px solid rgba(39,166,68,0.15)' }}>
                <div className="flex items-center gap-2 mb-3">
                  <User2 className="w-4 h-4" style={{ color: colors.success }} />
                  <span className="text-[12px] font-semibold" style={{ color: colors.success }}>Proposer</span>
                  {debate.proposer_argument?.confidence != null && (
                    <span className="text-[10px] font-mono ml-auto" style={{ color: colors.inkTertiary }}>
                      conf: {debate.proposer_argument.confidence.toFixed?.(2) || debate.proposer_argument.confidence}
                    </span>
                  )}
                </div>
                <p className="text-[12px] mb-2" style={{ color: colors.inkMuted }}>{debate.proposer_argument?.conclusion || 'No conclusion'}</p>
                {debate.proposer_argument?.evidence && (
                  <ul className="space-y-1">
                    {(debate.proposer_argument.evidence || []).slice(0, 3).map((e: string, i: number) => (
                      <li key={i} className="text-[11px] flex items-start gap-1" style={{ color: colors.inkSubtle }}>
                        <CheckCircle2 className="w-3 h-3 mt-0.5 flex-shrink-0" style={{ color: colors.success }} />{e}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Devil's Advocate */}
              <div className="rounded-lg p-4" style={{ background: 'rgba(229,83,75,0.05)', border: '1px solid rgba(229,83,75,0.15)' }}>
                <div className="flex items-center gap-2 mb-3">
                  <User2 className="w-4 h-4" style={{ color: colors.error }} />
                  <span className="text-[12px] font-semibold" style={{ color: colors.error }}>Devil's Advocate</span>
                  {debate.advocate_argument?.ungrounded_claims_found != null && (
                    <span className="text-[10px] font-mono ml-auto" style={{ color: colors.inkTertiary }}>
                      {debate.advocate_argument.ungrounded_claims_found} ungrounded
                    </span>
                  )}
                </div>
                <p className="text-[12px] mb-2" style={{ color: colors.inkMuted }}>{debate.advocate_argument?.conclusion || 'No conclusion'}</p>
                {debate.advocate_argument?.risks && (
                  <ul className="space-y-1">
                    {(debate.advocate_argument.risks || []).slice(0, 3).map((r: string, i: number) => (
                      <li key={i} className="text-[11px] flex items-start gap-1" style={{ color: colors.inkSubtle }}>
                        <XCircle className="w-3 h-3 mt-0.5 flex-shrink-0" style={{ color: colors.error }} />{r}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Arbitrator */}
              <div className="rounded-lg p-4" style={{ background: 'rgba(94,106,210,0.05)', border: '1px solid rgba(94,106,210,0.15)' }}>
                <div className="flex items-center gap-2 mb-3">
                  <Scale className="w-4 h-4" style={{ color: colors.primary }} />
                  <span className="text-[12px] font-semibold" style={{ color: colors.primary }}>Arbitrator</span>
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full ml-auto"
                    style={{
                      background: debate.arbitrator_decision?.decision === 'PROCEED' ? 'rgba(39,166,68,0.12)' : debate.arbitrator_decision?.decision === 'BLOCK' ? 'rgba(229,83,75,0.12)' : 'rgba(245,166,35,0.12)',
                      color: debate.arbitrator_decision?.decision === 'PROCEED' ? colors.success : debate.arbitrator_decision?.decision === 'BLOCK' ? colors.error : colors.warning,
                    }}>
                    {debate.arbitrator_decision?.decision || '-'}
                  </span>
                </div>
                <p className="text-[12px] mb-2" style={{ color: colors.inkMuted }}>{debate.arbitrator_decision?.rationale || 'No rationale'}</p>
                {debate.arbitrator_decision?.final_confidence != null && (
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-[10px]" style={{ color: colors.inkTertiary }}>Final confidence:</span>
                    <div className="flex-1 h-1.5 rounded-full" style={{ background: colors.surface3 }}>
                      <div className="h-full rounded-full transition-all" style={{
                        width: `${(debate.arbitrator_decision.final_confidence || 0) * 100}%`,
                        background: debate.arbitrator_decision.final_confidence >= 0.7 ? colors.success : debate.arbitrator_decision.final_confidence >= 0.5 ? colors.warning : colors.error,
                      }} />
                    </div>
                    <span className="text-[11px] font-mono font-bold" style={{ color: colors.ink }}>
                      {(debate.arbitrator_decision.final_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
          )
        })
      )}

      {/* ── Fairness Assessment ──────────────────────────────────────────── */}
      {fairness.length > 0 && (
        renderSection({ id: "fairness", title: "Fairness Assessment", icon: Scale,
          badge: (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
              style={{
                background: fairness[0]?.passed ? 'rgba(39,166,68,0.1)' : 'rgba(229,83,75,0.1)',
                color: fairness[0]?.passed ? colors.success : colors.error,
              }}>
              {fairness[0]?.passed ? 'PASSED' : 'BLOCKED'}
            </span>
          ),
          children: (
          <div className="space-y-4">
            {/* Overall Score */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Overall Score:</span>
                <span className="text-[18px] font-bold" style={{ color: fairness[0]?.passed ? colors.success : colors.error }}>
                  {((fairness[0]?.fairness_score || 0) * 100).toFixed(0)}%
                </span>
              </div>
              <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
                Threshold: {((fairness[0]?.threshold_used || 0.85) * 100).toFixed(0)}%
              </span>
            </div>

            {/* Attribute Breakdown */}
            {fairness[0]?.attribute_scores && (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {Object.entries(fairness[0].attribute_scores).map(([attr, data]: [string, any]) => {
                  const score = typeof data === 'object' ? data.score : data;
                  const flagged = typeof data === 'object' ? data.flag : false;
                  return (
                    <div key={attr} className="rounded-lg p-3 text-center" style={{
                      background: flagged ? 'rgba(229,83,75,0.06)' : colors.surface2,
                      border: `1px solid ${flagged ? 'rgba(229,83,75,0.2)' : colors.hairline}`,
                    }}>
                      <span className="text-[10px] uppercase font-semibold block mb-1" style={{ color: colors.inkTertiary }}>{attr}</span>
                      <span className="text-[16px] font-bold" style={{ color: flagged ? colors.error : colors.success }}>
                        {(score * 100).toFixed(0)}%
                      </span>
                      {flagged && <Eye className="w-3 h-3 mx-auto mt-1" style={{ color: colors.error }} />}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Rationale */}
            {fairness[0]?.rationale && (
              <p className="text-[12px] p-3 rounded-lg" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                {fairness[0].rationale}
              </p>
            )}
          </div>
          )
        })
      )}

      {/* ── Provenance ───────────────────────────────────────────────────── */}
      {renderSection({ id: "provenance", title: "Provenance Trail", icon: Hash,
        children: (
        <div className="space-y-2">
          <div className="flex items-center gap-3 p-3 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <Hash className="w-4 h-4" style={{ color: colors.primary }} />
            <div className="flex-1 min-w-0">
              <span className="text-[12px] font-medium block" style={{ color: colors.ink }}>Execution Record</span>
              <span className="text-[11px] font-mono block truncate" style={{ color: colors.inkTertiary }}>{execution.id}</span>
            </div>
            <span className="text-[10px]" style={{ color: colors.inkSubtle }}>{new Date(execution.started_at).toISOString()}</span>
          </div>
          <div className="flex items-center gap-3 p-3 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <Shield className="w-4 h-4" style={{ color: colors.success }} />
            <div className="flex-1">
              <span className="text-[12px] font-medium block" style={{ color: colors.ink }}>Route Type</span>
              <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{execution.route_type || 'SKILL_EXEC'}</span>
            </div>
            <span className="text-[10px] font-mono" style={{ color: colors.inkTertiary }}>
              Δ conf: {execution.confidence_delta != null ? (execution.confidence_delta > 0 ? '+' : '') + execution.confidence_delta.toFixed(3) : '-'}
            </span>
          </div>
        </div>
        )
      })}

      {/* ── Human feedback → AI Foundry training signal ──────────────────── */}
      {execution.id && (
        <FeedbackCapture executionId={execution.id} instruction={execution.task_intent} colors={colors} />
      )}
    </div>
  );
}
