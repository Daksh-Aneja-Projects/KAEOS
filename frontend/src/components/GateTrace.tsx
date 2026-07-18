import React, { useEffect, useState } from 'react';
import {
  CheckCircle2, Loader2, ShieldCheck, Scale, Gauge, Users,
  MessagesSquare, Play, FileLock2, XCircle, AlertTriangle,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useWebSocket } from '../hooks/useWebSocket';

/**
 * The 7-gate pipeline, rendered live.
 *
 * A gated agent action takes 1-3 minutes on a local model. Showing a spinner
 * for that whole time hides the single thing that makes KAEOS different:
 * every AI decision walks a governance pipeline before it executes. This turns
 * the wait into the proof - the gates advance, and the terminal state explains
 * itself in the product's own vocabulary.
 */

export type GateStatus = 'pending' | 'running' | 'passed' | 'blocked' | 'paused';

export interface GateTraceResult {
  status?: string;
  execution_id?: string;
  reasoning_chain?: any[];
  violations?: any[];
  rationale?: string;
  reason?: string;
  debate_decision?: string;
  duration_ms?: number;
  cost?: {
    model_calls_metered: number;
    total_cost_usd: number;
    total_tokens: number;
    note?: string;
  } | null;
}

const GATES = [
  { key: 'compliance', label: 'Compliance', icon: ShieldCheck, blurb: 'SOX · GDPR · HIPAA · PCI' },
  { key: 'fairness', label: 'Fairness', icon: Scale, blurb: 'EU AI Act Art.13 bias check' },
  { key: 'confidence', label: 'Confidence', icon: Gauge, blurb: 'Model ceiling vs threshold' },
  { key: 'hitl', label: 'Human Approval', icon: Users, blurb: 'Pauses below threshold' },
  { key: 'debate', label: 'Debate', icon: MessagesSquare, blurb: 'Adversarial review' },
  { key: 'execute', label: 'Execute', icon: Play, blurb: 'Generative step run' },
  { key: 'audit', label: 'Audit', icon: FileLock2, blurb: 'Provenance ledger entry' },
] as const;

/** Map a terminal result to how far the pipeline actually got. */
function resolveGates(result?: GateTraceResult): Record<string, GateStatus> {
  const s: Record<string, GateStatus> = {};
  GATES.forEach(g => { s[g.key] = 'pending'; });
  if (!result) return s;
  const status = result.status || '';
  const pass = (...keys: string[]) => keys.forEach(k => { s[k] = 'passed'; });

  if (status === 'BLOCKED_COMPLIANCE') { s.compliance = 'blocked'; return s; }
  if (status === 'BLOCKED_FAIRNESS') { pass('compliance'); s.fairness = 'blocked'; return s; }
  if (status === 'PENDING_HITL') { pass('compliance', 'fairness'); s.confidence = 'passed'; s.hitl = 'paused'; return s; }
  if (status === 'HUMAN_OVERRIDDEN') { pass('compliance', 'fairness', 'confidence'); s.hitl = 'blocked'; return s; }
  if (status === 'BLOCKED_DEBATE') { pass('compliance', 'fairness', 'confidence', 'hitl'); s.debate = 'blocked'; return s; }
  if (status === 'ESCALATED_DEBATE') { pass('compliance', 'fairness', 'confidence', 'hitl'); s.debate = 'paused'; return s; }
  if (status === 'SUCCESS_CLEAN') { pass('compliance', 'fairness', 'confidence', 'hitl', 'debate', 'execute', 'audit'); return s; }
  if (status.startsWith('FAILED')) { pass('compliance', 'fairness', 'confidence', 'hitl', 'debate'); s.execute = 'blocked'; return s; }
  return s;
}

const TERMINAL_COPY: Record<string, { tone: 'ok' | 'warn' | 'bad'; title: string; body: string }> = {
  SUCCESS_CLEAN: { tone: 'ok', title: 'Executed autonomously', body: 'All gates cleared. A provenance entry was written.' },
  PENDING_HITL: { tone: 'warn', title: 'Paused for human approval', body: 'Confidence fell below the threshold for this action. Approve it in the HITL queue to resume execution.' },
  ESCALATED_DEBATE: { tone: 'warn', title: 'Escalated by debate', body: 'The adversarial review did not reach consensus, so it routed to a human.' },
  BLOCKED_COMPLIANCE: { tone: 'bad', title: 'Blocked at the compliance gate', body: 'A regulatory control refused this action before any model ran.' },
  BLOCKED_FAIRNESS: { tone: 'bad', title: 'Blocked by the fairness gate', body: 'A protected-attribute risk was flagged.' },
  BLOCKED_DEBATE: { tone: 'bad', title: 'Blocked by debate', body: 'The adversarial review rejected this action.' },
  HUMAN_OVERRIDDEN: { tone: 'bad', title: 'Rejected by a human', body: 'The reviewer declined this action.' },
};

export default function GateTrace({ running, result, skillLabel }: {
  running: boolean;
  result?: GateTraceResult;
  skillLabel?: string;
}) {
  const { colors } = useTheme();
  const [elapsed, setElapsed] = useState(0);
  const [liveGates, setLiveGates] = useState<Record<string, GateStatus>>({});
  const { lastMessage } = useWebSocket();

  // Elapsed time is the only thing we time. Gate PROGRESS comes from the
  // backend: it now emits a `gate_event` as each gate resolves, so this shows
  // the pipeline that actually ran rather than a plausible-looking animation.
  useEffect(() => {
    if (!running) { setElapsed(0); return; }
    setLiveGates({});
    const t0 = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 250);
    return () => clearInterval(id);
  }, [running]);

  useEffect(() => {
    const m: any = lastMessage;
    if (!m || m.type !== 'gate_event' || !m.gate) return;
    setLiveGates(prev => ({
      ...prev,
      [m.gate]: m.state === 'passed' ? 'passed'
        : m.state === 'blocked' ? 'blocked'
          : m.state === 'paused' ? 'paused'
            : 'running',
    }));
  }, [lastMessage]);

  const resolved = resolveGates(result);
  const terminal = result?.status ? TERMINAL_COPY[result.status] : undefined;

  const statusOf = (i: number, key: string): GateStatus => {
    if (!running) return resolved[key];
    // Live: whatever the backend has told us. The first gate with no verdict
    // yet is the one currently working.
    if (liveGates[key]) return liveGates[key];
    const firstUnknown = GATES.findIndex(g => !liveGates[g.key]);
    return i === firstUnknown ? 'running' : 'pending';
  };

  const colorOf = (st: GateStatus) =>
    st === 'passed' ? '#22c55e'
      : st === 'running' ? colors.primary
        : st === 'paused' ? '#f59e0b'
          : st === 'blocked' ? '#ef4444'
            : colors.inkSubtle;

  if (!running && !result) return null;

  return (
    <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>
          7-Gate Pipeline{skillLabel ? ` · ${skillLabel}` : ''}
        </div>
        {running && (
          <div className="text-[11px] tabular-nums" style={{ color: colors.inkSubtle }}>
            {elapsed.toFixed(0)}s
          </div>
        )}
      </div>

      <div className="flex items-stretch gap-1">
        {GATES.map((g, i) => {
          const st = statusOf(i, g.key);
          const c = colorOf(st);
          return (
            <div key={g.key} className="flex-1 group relative">
              <div className="h-1 rounded-full mb-2 transition-all duration-500" style={{
                background: st === 'pending' ? colors.hairline : c,
                opacity: st === 'running' ? 0.6 : 1,
              }} />
              <div className="flex flex-col items-center gap-1 text-center">
                {st === 'running'
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: c }} />
                  : st === 'passed'
                    ? <CheckCircle2 className="w-3.5 h-3.5" style={{ color: c }} />
                    : st === 'blocked'
                      ? <XCircle className="w-3.5 h-3.5" style={{ color: c }} />
                      : st === 'paused'
                        ? <AlertTriangle className="w-3.5 h-3.5" style={{ color: c }} />
                        : <g.icon className="w-3.5 h-3.5" style={{ color: c, opacity: 0.5 }} />}
                <span className="text-[9px] leading-tight" style={{ color: st === 'pending' ? colors.inkSubtle : c }}>
                  {g.label}
                </span>
              </div>
              {/* blurb on hover: teaches the gate vocabulary without clutter */}
              <div className="absolute left-1/2 -translate-x-1/2 top-full mt-1 px-2 py-1 rounded text-[9px] whitespace-nowrap
                              opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10"
                style={{ background: colors.surface2 || colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                {g.blurb}
              </div>
            </div>
          );
        })}
      </div>

      {terminal && (
        <div className="mt-4 p-3 rounded-lg flex items-start gap-2" style={{
          background: (terminal.tone === 'ok' ? '#22c55e' : terminal.tone === 'warn' ? '#f59e0b' : '#ef4444') + '12',
        }}>
          {terminal.tone === 'ok' ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#22c55e' }} />
            : terminal.tone === 'warn' ? <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#f59e0b' }} />
              : <XCircle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#ef4444' }} />}
          <div>
            <div className="text-[12px] font-semibold" style={{
              color: terminal.tone === 'ok' ? '#22c55e' : terminal.tone === 'warn' ? '#f59e0b' : '#ef4444',
            }}>{terminal.title}</div>
            <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{terminal.body}</div>
            {result?.violations?.length ? (
              <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                {result.violations.map((v: any, i: number) => (
                  <div key={i}>· {v.framework}: {v.reason}</div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* What this decision actually cost. Measured, not modelled: a local
          model really is $0, and that is the number a buyer compares against
          an analyst's hourly rate. */}
      {!running && (result?.duration_ms || result?.cost) && (
        <div className="mt-3 pt-3 flex items-center gap-4 text-[10px]"
          style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
          {result?.duration_ms ? (
            <span><span style={{ color: colors.ink, fontWeight: 600 }}>
              {(result.duration_ms / 1000).toFixed(1)}s
            </span> end-to-end</span>
          ) : null}
          {result?.cost ? (
            <>
              <span><span style={{ color: colors.ink, fontWeight: 600 }}>
                ${result.cost.total_cost_usd.toFixed(4)}
              </span> metered for this skill</span>
              <span>{result.cost.total_tokens.toLocaleString()} tokens · {result.cost.model_calls_metered} model calls</span>
            </>
          ) : null}
        </div>
      )}

      {/* The reasoning the model actually produced - the payoff of provenance */}
      {!running && result?.reasoning_chain?.length ? (
        <div className="mt-3 space-y-1.5">
          {result.reasoning_chain.map((step: any, i: number) => (
            <div key={i} className="flex items-start gap-2 text-[11px]">
              <span className="w-4 h-4 rounded-full flex items-center justify-center text-[8px] shrink-0 mt-0.5"
                style={{ background: colors.hairline, color: colors.inkSubtle }}>{i + 1}</span>
              <span style={{ color: colors.ink }}>
                {typeof step.decision === 'string' ? step.decision : JSON.stringify(step.decision)}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
