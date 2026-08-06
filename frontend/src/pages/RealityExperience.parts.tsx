/**
 * RealityExperience — extracted parts.
 *
 * Static catalogs (shock types, what-if options, twin legend), the shared
 * ModeActivity shape, the pure mode->activity builders (Wargame / Replay /
 * What-If produce the same Decision-Center payload), and the two self-contained
 * read-out panels (StatsStrip, LearningState). Kept out of the page component so
 * RealityExperience.tsx stays under the size budget; behavior is unchanged.
 */
import { Brain } from 'lucide-react';
import { humanize } from '../lib/format';

export const WHATIF_DOMAINS = ['All Domains', 'HR', 'Finance', 'Legal', 'Sales', 'Support', 'Operations', 'Engineering'];
export const WHATIF_RISK = ['conservative', 'balanced', 'aggressive'];

export interface TwinNode { id: string; name: string; group: number; label: string; [k: string]: any }
export interface TwinLink { source: string; target: string; type?: string }
export interface DecisionTrace {
  impact: any;
  options_evaluated: any[];
  recommendation: any;
}
export interface EventTrace { event: string; id: number; ts?: string }
// A normalized "what happened" for the Decision Center + Why Panel, shared by the
// What-If / Wargame / Replay modes so every mode fills the same two panels.
export interface ModeActivity {
  mode: 'whatif' | 'wargame' | 'replay';
  label: string;
  severity: number;                 // 0-100, drives the accent color
  headline: string;                 // one-line impact summary
  itemsLabel: string;
  items: { label: string; sub?: string; right?: string; tone?: 'good' | 'warn' | 'bad' }[];
  why: [string, string][];          // reasoning chain rows
  final: string;                    // the executed / recommended outcome
}

// Must stay in sync with SHOCK_PROFILES in backend/app/api/routes/reality.py.
// Merger and cyber carry the richest causal models (deepest propagation, highest
// severity multipliers, scenario-specific decision options) - they were missing
// from this list, so the backend's two best scenarios were unreachable from the UI.
export const SHOCK_TYPES = [
  // Security & Reliability
  { value: 'CYBER_INCIDENT', label: 'Cyber Incident', targetLabel: 'Department', group: 'Security & Reliability' },
  { value: 'DATA_BREACH_PII', label: 'PII Data Breach', targetLabel: 'Department', group: 'Security & Reliability' },
  { value: 'RANSOMWARE', label: 'Ransomware Attack', targetLabel: 'Department', group: 'Security & Reliability' },
  { value: 'SEV1_ESCALATION', label: 'SEV-1 Incident', targetLabel: 'Incident', group: 'Security & Reliability' },
  { value: 'SYSTEM_OUTAGE', label: 'System Outage', targetLabel: 'Department', group: 'Security & Reliability' },
  // Legal & Regulatory
  { value: 'REGULATORY_ACTION', label: 'Regulatory Action', targetLabel: 'Department', group: 'Legal & Regulatory' },
  { value: 'CONTRACT_DISPUTE', label: 'Contract Dispute', targetLabel: 'Contract', group: 'Legal & Regulatory' },
  { value: 'PRODUCT_RECALL', label: 'Product Recall', targetLabel: 'Department', group: 'Legal & Regulatory' },
  // Financial
  { value: 'LIQUIDITY_CRUNCH', label: 'Liquidity Crunch', targetLabel: 'Department', group: 'Financial' },
  { value: 'BUDGET_CUT', label: 'Budget Reduction', targetLabel: 'Department', group: 'Financial' },
  // Commercial
  { value: 'KEY_ACCOUNT_AT_RISK', label: 'Key Account At Risk', targetLabel: 'Account', group: 'Commercial' },
  { value: 'VENDOR_FAILURE', label: 'Vendor Failure', targetLabel: 'Vendor', group: 'Commercial' },
  { value: 'SUPPLY_CHAIN_DISRUPTION', label: 'Supply-Chain Disruption', targetLabel: 'Vendor', group: 'Commercial' },
  // People
  { value: 'EXECUTIVE_DEPARTURE', label: 'Executive Departure', targetLabel: 'Employee', group: 'People' },
  { value: 'TALENT_EXODUS', label: 'Talent Exodus', targetLabel: 'Department', group: 'People' },
  { value: 'EMPLOYEE_TERMINATION', label: 'Employee Termination', targetLabel: 'Employee', group: 'People' },
  // Strategic
  { value: 'MERGER_INTEGRATION', label: 'M&A Integration', targetLabel: 'Department', group: 'Strategic' },
  { value: 'CAPABILITY_LOSS', label: 'Capability Loss', targetLabel: 'Capability', group: 'Strategic' },
];
export const SHOCK_GROUPS = Array.from(new Set(SHOCK_TYPES.map(s => s.group)));

// Legend for the twin constellation - one hue per record type, mirrors
// TYPE_COLORS in TwinGraph.tsx. Only types actually on the graph are shown.
export const TWIN_LEGEND = [
  { label: 'Department', color: '#5e6ad2' },
  { label: 'Employee', color: '#f59e0b' },
  { label: 'Customer', color: '#22d3ee' },
  { label: 'Account', color: '#a78bfa' },
  { label: 'Ticket', color: '#fb923c' },
  { label: 'Contract', color: '#f472b6' },
  { label: 'Incident', color: '#f87171' },
  { label: 'PurchaseOrder', color: '#a3e635' },
  { label: 'Vendor', color: '#ec4899' },
  { label: 'Project', color: '#ef4444' },
  { label: 'Capability', color: '#06b6d4' },
  { label: 'Agent', color: '#8b5cf6' },
  { label: 'Process', color: '#22c55e' },
];

// ─── Pure mode -> impact builders ───
// Each returns the shared ModeActivity plus the departments/severity the page
// should pulse on the twin. Pure functions: no component state, fully testable.
export interface ModeImpact { activity: ModeActivity; depts: string[]; sev: number; epicenter?: string }

export function buildWargameImpact(r: any, twinNodeCount: number): ModeImpact {
  const depts = (r?.steps || []).map((s: any) => s.department).filter(Boolean);
  const sev = Math.max(20, 100 - (Number(r?.resilience_score) || 50));
  return {
    depts, sev, epicenter: r?.weakest_link?.department,
    activity: {
      mode: 'wargame',
      label: `Wargame · ${humanize(r?.playbook || 'adversarial cascade')}`,
      severity: sev,
      headline: `Integrity retained ${r?.resilience_score ?? 0}% (grade ${r?.grade ?? '-'}). Weakest link: ${r?.weakest_link?.department ?? 'n/a'}.`,
      itemsLabel: 'CASCADE: SHOCK BY SHOCK',
      items: (r?.steps || []).map((s: any) => ({
        label: `${humanize(s.shock)} → ${s.department}`,
        sub: `-${s.damage} integrity → ${s.integrity_after}% remaining`,
        right: s.response === 'autonomous' ? 'AUTONOMOUS' : 'HUMAN',
        tone: s.response === 'autonomous' ? 'good' : 'warn',
      })),
      why: [
        ['Adversarial Cascade', `${(r?.steps || []).length} compounding shocks`],
        ['Twin State Capture', `${twinNodeCount} nodes · live snapshot`],
        ['Fragility Model', 'skill confidence + adverse outcome history'],
        ['Autonomous Response', `${Math.round((r?.safe_response_rate ?? 0) * 100)}% handled without a human`],
        ['Weakest Link', `${r?.weakest_link?.department ?? 'n/a'} (−${r?.weakest_link?.damage ?? 0})`],
        ['Resilience Grade', `${r?.grade ?? '-'} · ${r?.resilience_score ?? 0}%`],
      ],
      final: r?.verdict || `Grade ${r?.grade ?? '-'} resilience`,
    },
  };
}

export function buildReplayImpact(evt: any, cf: any): ModeImpact {
  const klass = String(evt?.klass || '');
  const sev = (klass === 'overridden' || klass === 'failed') ? 72
    : klass === 'routed_to_human' ? 46 : 26;
  const deltaPts = cf?.delta != null ? `${cf.delta > 0 ? '+' : ''}${(cf.delta * 100).toFixed(1)} pts` : null;
  return {
    depts: evt?.department ? [evt.department] : [], sev,
    activity: {
      mode: 'replay',
      label: `Replay · ${String(evt?.skill_id || 'decision').slice(0, 48)}`,
      severity: sev,
      headline: cf
        ? `Counterfactual: had this decision ${cf.flip === 'approve' ? 'run clean' : cf.flip === 'fail' ? 'failed' : 'escalated'}, safe-autonomy would move to ${cf.after_rate == null ? '--' : `${(cf.after_rate * 100).toFixed(0)}%`} (${deltaPts ?? 'no change'}).`
        : `Replaying a real ${humanize(klass)} decision in ${evt?.department || 'the org'}. Pick an outcome to run the counterfactual.`,
      itemsLabel: 'DECISION UNDER REPLAY',
      items: [
        { label: evt?.skill_id || 'decision', sub: `Actual outcome: ${humanize(klass)}`, right: humanize(evt?.department), tone: klass === 'failed' || klass === 'overridden' ? 'bad' : klass === 'routed_to_human' ? 'warn' : 'good' },
        ...(cf ? [{
          label: `Counterfactual: ${cf.flip}`,
          sub: `actual ${cf.before_rate == null ? '--' : `${(cf.before_rate * 100).toFixed(0)}%`} → counterfactual ${cf.after_rate == null ? '--' : `${(cf.after_rate * 100).toFixed(0)}%`}`,
          right: deltaPts ?? undefined,
          tone: (cf.delta ?? 0) > 0 ? 'good' as const : (cf.delta ?? 0) < 0 ? 'bad' as const : 'warn' as const,
        }] : []),
      ],
      why: [
        ['Decision Selected', evt?.skill_id || 'n/a'],
        ['Department', evt?.department || 'n/a'],
        ['Actual Classification', humanize(klass) || 'n/a'],
        ['Counterfactual', cf ? `flipped to "${cf.flip}"` : 'not run yet'],
        ['North-Star Recompute', cf ? `${cf.before_rate == null ? '--' : `${(cf.before_rate * 100).toFixed(0)}%`} → ${cf.after_rate == null ? '--' : `${(cf.after_rate * 100).toFixed(0)}%`}` : 'pending'],
        ['Delta', deltaPts ?? 'pending'],
      ],
      final: cf ? `Safe-autonomy delta ${deltaPts ?? '0'}` : 'Awaiting counterfactual',
    },
  };
}

export function buildWhatIfImpact(data: any, change: string, domain: string, twinNodeCount: number): ModeImpact {
  const verdict = String(data?.simulation_result || '').toUpperCase();
  const sev = verdict === 'BLOCKED' ? 92 : verdict === 'SAFE' ? 28 : 62;
  const depts = data?.blast_radius?.affected_departments || [];
  const risks = data?.risk_factors || [];
  return {
    depts: depts.length ? depts : [domain], sev,
    activity: {
      mode: 'whatif',
      label: `What-If · ${change.slice(0, 54)}`,
      severity: sev,
      headline: `Governed verdict: ${verdict}. ${data?.recommendation || (verdict === 'SAFE' ? 'Safe to proceed.' : 'Proceed with caution.')}`,
      itemsLabel: 'RANKED RISK FACTORS',
      items: risks.map((r: any) => ({
        label: r.factor,
        sub: r.mitigation ? `Mitigation: ${r.mitigation}` : undefined,
        right: String(r.severity || '').toUpperCase(),
        tone: String(r.severity).toUpperCase() === 'HIGH' ? 'bad' : String(r.severity).toUpperCase() === 'MEDIUM' ? 'warn' : 'good',
      })),
      why: [
        ['Proposed Change', change.slice(0, 80)],
        ['Twin State Capture', `${twinNodeCount} nodes · live snapshot`],
        ['Blast Radius', `${(depts || []).length} dept(s) · ${data?.blast_radius?.affected_rules ?? 0} rules · ${data?.blast_radius?.affected_skills ?? 0} skills`],
        ['Risk Engine', `${risks.length} factor(s) ranked by severity`],
        ['Governed Verdict', verdict],
        ['Rollback Plan', data?.estimated_rollback_time_hours != null ? `~${data.estimated_rollback_time_hours}h to reverse` : 'n/a'],
      ],
      final: data?.recommendation || verdict,
    },
  };
}

// ─── Read-out panels ───
export function StatsStrip({ tiles, colors, card }: { tiles: any[]; colors: any; card: any }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {tiles.map(t => (
        <div key={t.label} className="rounded-xl border shadow-sm px-4 py-3 flex items-center gap-3" style={card}>
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: t.color + '18' }}>
            <t.icon className="w-4 h-4" style={{ color: t.color }} />
          </div>
          <div className="min-w-0">
            <div className="text-xl font-bold leading-none">{t.value?.toLocaleString() ?? '-'}</div>
            <div className="text-[11px] uppercase font-semibold mt-1 tracking-wide whitespace-nowrap" style={{ color: colors.inkTertiary }}>{t.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function LearningState({ learningStats, colors, card }: { learningStats: any; colors: any; card: any }) {
  return (
    <div className="rounded-xl border shadow-sm p-4 flex-shrink-0 flex flex-col" style={card}>
      <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
        <Brain className="w-4 h-4" /> Learning State
      </h2>
      {learningStats ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 border rounded" style={{ borderColor: colors.hairline, background: colors.canvas }}>
              <div className="text-[11px] font-mono mb-1" style={{ color: colors.primary }}>SHOCKS PROCESSED</div>
              <div className="text-2xl font-bold">{learningStats.shocks_processed ?? 0}</div>
            </div>
            <div className="p-3 border rounded" style={{ borderColor: colors.hairline, background: colors.canvas }}>
              <div className="text-[11px] font-mono mb-1" style={{ color: colors.primary }}>RISK PENALTY</div>
              <div className="text-2xl font-bold text-red-500">-{learningStats.modifiers?.MITIGATE_FAILURE?.toFixed(1) || 0}</div>
            </div>
          </div>
          <div className="text-xs">
            <div className="font-semibold mb-2">Recent Outcomes</div>
            <div className="overflow-y-auto space-y-1 pr-1" style={{ maxHeight: 200 }}>
              {(learningStats.historical_outcomes || []).slice().reverse().map((o: any, i: number) => (
                <div key={i} className="p-2 border rounded font-mono text-[11px] space-y-0.5" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex justify-between">
                    <span className="font-bold">{humanize(o.shock_type)}</span>
                    <span className={o.severity > 60 ? 'text-red-500' : 'text-amber-500'}>sev {o.severity?.toFixed(0)}</span>
                  </div>
                  <div style={{ color: colors.inkTertiary }} className="truncate">{o.target} → {humanize(o.decision)}</div>
                </div>
              ))}
              {!(learningStats.historical_outcomes || []).length && (
                <div className="italic" style={{ color: colors.inkSubtle }}>No shocks run yet - inject one to build history.</div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm italic" style={{ color: colors.inkSubtle }}>Loading learning state…</div>
      )}
    </div>
  );
}
