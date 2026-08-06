import React, { useEffect, useState, useCallback } from 'react';
import {
  Factory, Database, CheckCircle2, UserCheck, Download, RefreshCw,
  Hammer, GitBranch, FlaskConical, Boxes, Route, Repeat, Sparkles,
  TrendingUp, ArrowRight, ShieldCheck,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { api, type FoundryStats } from '../api/client';
import DomainIcon from '../components/DomainIcon';
import { BrainLoading, BrainError, LiveIndicator } from '../components/BrainStates';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

// The v2 roadmap. Honest status: Phase 1 shipped, Phase 2 is live, 3-5 planned.
const ROADMAP = [
  { phase: 'Phase 1', label: 'Company Brain', icon: Boxes, status: 'done', blurb: 'Understand, reason, act on enterprise knowledge.' },
  { phase: 'Phase 2', label: 'Learning Intelligence', icon: Sparkles, status: 'live', blurb: 'Curate governed activity into training data.' },
  { phase: 'Phase 3', label: 'Model Evolution', icon: FlaskConical, status: 'live', blurb: 'Evaluate a candidate against the baseline; promotion stays human-gated.' },
  { phase: 'Phase 4', label: 'Specialized Models', icon: Route, status: 'planned', blurb: 'A dedicated expert model per department.' },
  { phase: 'Phase 5', label: 'Autonomous Foundry', icon: Repeat, status: 'planned', blurb: 'The loop runs itself under governance.' },
];

// Evaluation labels, ordered by training-signal strength, with what they mean.
const LABEL_META: Record<string, { color: string; title: string; blurb: string }> = {
  CORRECTED: { color: '#8b5cf6', title: 'Corrected', blurb: 'A human edited the answer - the strongest supervised signal.' },
  APPROVED: { color: '#27a644', title: 'Approved', blurb: 'A human approved the agent’s answer unchanged at a gate.' },
  GOLD: { color: '#f59e0b', title: 'Gold', blurb: 'High-confidence clean success - trusted without a human.' },
  NEGATIVE: { color: '#e5534b', title: 'Negative', blurb: 'Blocked or rejected - a contrastive example of what not to do.' },
};

const SOURCE_LABEL: Record<string, string> = {
  mined: 'Mined from executions',
  human_correction: 'Human corrections',
  human_rating: 'Human ratings',
};

export default function AIFoundry() {
  const { colors } = useTheme();
  const [stats, setStats] = useState<FoundryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [positiveOnly, setPositiveOnly] = useState(true);

  // Phase 3 — model evolution + fine-tune bridge. The endpoints and the gated
  // promotion logic already existed and were tested; nothing in the UI could
  // reach them, so a candidate model could never be evaluated or promoted.
  const [runs, setRuns] = useState<any[]>([]);
  const [ftJobs, setFtJobs] = useState<any[]>([]);
  const [tier, setTier] = useState('reasoning');
  const [candidate, setCandidate] = useState('');
  const [evaluating, setEvaluating] = useState(false);
  const [actingOn, setActingOn] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [s, r, j] = await Promise.all([
        api.getFoundryStats(),
        api.listEvolutionRuns(10).catch(() => ({ runs: [] })),
        api.listFinetuneJobs(10).catch(() => ({ jobs: [] })),
      ]);
      setStats(s);
      setRuns(r?.runs || []);
      setFtJobs(j?.jobs || []);
    } catch (e: any) {
      setError(e.message || 'Failed to load the training dataset');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const flashMsg = (m: string) => { setFlash(m); setTimeout(() => setFlash(null), 4000); };

  const build = async () => {
    setBuilding(true);
    try {
      const r = await api.buildFoundryDataset({});
      await load();
      flashMsg(r.created > 0
        ? `Curated ${r.created} new example${r.created === 1 ? '' : 's'} from governed executions.`
        : `Dataset already up to date - ${r.skipped} execution${r.skipped === 1 ? '' : 's'} already curated.`);
    } catch (e: any) {
      flashMsg(`Build failed: ${e.message}`);
    } finally {
      setBuilding(false);
    }
  };

  const exportJsonl = async () => {
    setExporting(true);
    try {
      const r = await api.exportFoundryDataset({ positive_only: positiveOnly });
      if (!r.count) { flashMsg('No examples match the export filter yet.'); return; }
      const jsonl = r.examples.map(e => JSON.stringify(e)).join('\n');
      const blob = new Blob([jsonl], { type: 'application/x-ndjson' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `kaeos-training-${r.tenant_id}-${r.count}.jsonl`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      flashMsg(`Exported ${r.count} instruction-tuned examples.`);
    } catch (e: any) {
      flashMsg(`Export failed: ${e.message}`);
    } finally {
      setExporting(false);
    }
  };

  const runEvaluation = async () => {
    if (!candidate.trim()) return;
    setEvaluating(true);
    try {
      const r = await api.evaluateCandidateModel({ tier, candidate_model: candidate.trim() });
      await load();
      flashMsg(r.simulated
        ? 'Evaluation ran with no live provider - scores are simulated and cannot justify promotion.'
        : `Evaluated: baseline ${r.baseline_score ?? '-'} vs candidate ${r.candidate_score ?? '-'}.`);
    } catch (e: any) {
      flashMsg(`Evaluation failed: ${e.message}`);
    } finally {
      setEvaluating(false);
    }
  };

  const decideRun = async (runId: string, decision: 'promote' | 'reject') => {
    setActingOn(runId);
    try {
      if (decision === 'promote') await api.promoteEvolutionRun(runId);
      else await api.rejectEvolutionRun(runId);
      await load();
      flashMsg(decision === 'promote'
        ? 'Candidate promoted - it is now this tenant’s model for that tier.'
        : 'Candidate rejected.');
    } catch (e: any) {
      flashMsg(`${decision === 'promote' ? 'Promotion' : 'Rejection'} failed: ${e.message}`);
    } finally {
      setActingOn(null);
    }
  };

  const submitFinetune = async () => {
    setActingOn('finetune');
    try {
      const j = await api.submitFinetune({ tier });
      await load();
      flashMsg(j.status === 'FAILED'
        ? `Fine-tune could not start: ${j.error || 'no provider configured'}`
        : `Fine-tune job ${j.status?.toLowerCase() || 'submitted'} for the ${tier} tier.`);
    } catch (e: any) {
      flashMsg(`Fine-tune submit failed: ${e.message}`);
    } finally {
      setActingOn(null);
    }
  };

  if (loading) return <BrainLoading message="Loading the AI Foundry…" />;
  if (error) return <BrainError message={error} onRetry={load} />;

  const s = stats!;
  const domains = Object.entries(s.by_domain || {}).sort((a, b) => b[1] - a[1]);
  const labels = Object.entries(s.by_label || {}).sort((a, b) => b[1] - a[1]);
  const sources = Object.entries(s.by_source || {}).sort((a, b) => b[1] - a[1]);
  const maxLabel = Math.max(1, ...labels.map(([, v]) => v));
  const maxDomain = Math.max(1, ...domains.map(([, v]) => v));
  const trainablePct = s.total_examples ? Math.round((s.trainable_examples / s.total_examples) * 100) : 0;

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px',
    border: `1px solid ${colors.hairline}`, padding: '20px',
  };

  const KPIS = [
    { label: 'Training Examples', value: s.total_examples, icon: Database, color: colors.primary },
    { label: 'Trainable', value: s.trainable_examples, icon: CheckCircle2, color: '#27a644', sub: `${trainablePct}% of set` },
    { label: 'Human-Verified', value: s.human_verified_examples, icon: UserCheck, color: '#8b5cf6' },
    { label: 'Domains Covered', value: domains.length, icon: Boxes, color: '#06b6d4' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <Factory className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-[24px] font-bold tracking-tight">Enterprise AI Foundry</h1>
                <LiveIndicator isLive />
              </div>
              <p className="text-[13px] mt-1 max-w-2xl" style={{ color: colors.inkSubtle }}>
                Every governed decision your agents make is curated into training data - the first step
                from a Company Brain that <em>remembers</em> to an enterprise that <em>manufactures</em> its own AI.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={load}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium transition-all hover:opacity-80"
              style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            <button onClick={build} disabled={building}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
              {building ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Hammer className="w-4 h-4" />}
              {building ? 'Curating…' : 'Build Dataset'}
            </button>
          </div>
        </div>

        {flash && (
          <div className="px-4 py-2.5 rounded-lg text-[13px] flex items-center gap-2"
            style={{ background: colors.primary + '15', color: colors.primary, border: `1px solid ${colors.primary}30` }}>
            <Sparkles className="w-4 h-4 shrink-0" /> {flash}
          </div>
        )}

        {/* Roadmap stepper */}
        <div style={card}>
          <div className="flex items-center gap-2 mb-4">
            <GitBranch className="w-4 h-4" style={{ color: colors.inkSubtle }} />
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
              The road to an AI Foundry
            </span>
          </div>
          <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
            {ROADMAP.map((p, i) => {
              const isLive = p.status === 'live';
              const isDone = p.status === 'done';
              const accent = isLive ? colors.primary : isDone ? '#27a644' : colors.inkTertiary;
              return (
                <React.Fragment key={p.phase}>
                  <div className="flex-1 min-w-[150px] rounded-xl p-3"
                    style={{
                      background: isLive ? colors.primary + '12' : colors.surface2,
                      border: `1px solid ${isLive ? colors.primary + '40' : colors.hairline}`,
                    }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <p.icon className="w-4 h-4" style={{ color: accent }} />
                      <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: accent }}>
                        {p.phase}
                      </span>
                      {isLive && <span className="ml-auto text-[11px] font-bold px-1.5 py-0.5 rounded-full text-white" style={{ background: colors.primary }}>LIVE</span>}
                      {isDone && <CheckCircle2 className="ml-auto w-3.5 h-3.5" style={{ color: '#27a644' }} />}
                    </div>
                    <div className="text-[12px] font-semibold" style={{ color: colors.ink }}>{p.label}</div>
                    <div className="text-[11px] mt-0.5 leading-snug" style={{ color: colors.inkSubtle }}>{p.blurb}</div>
                  </div>
                  {i < ROADMAP.length - 1 && (
                    <div className="flex items-center shrink-0">
                      <ArrowRight className="w-3.5 h-3.5" style={{ color: colors.inkTertiary }} />
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {KPIS.map(k => (
            <div key={k.label} className="p-4 rounded-xl flex items-center gap-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: k.color + '18' }}>
                <k.icon className="w-4.5 h-4.5" style={{ color: k.color }} />
              </div>
              <div className="min-w-0">
                <div className="text-[22px] font-bold leading-none tabular-nums">{k.value.toLocaleString()}</div>
                <div className="text-[11px] uppercase tracking-wider mt-1 truncate" style={{ color: colors.inkSubtle }}>{k.label}</div>
                {k.sub && <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>{k.sub}</div>}
              </div>
            </div>
          ))}
        </div>

        {s.total_examples === 0 ? (
          <div style={card} className="text-center py-14">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3" style={{ background: colors.primary + '15' }}>
              <Database className="w-7 h-7" style={{ color: colors.primary }} />
            </div>
            <div className="text-[15px] font-semibold">No training data yet</div>
            <p className="text-[13px] mt-1 max-w-md mx-auto" style={{ color: colors.inkSubtle }}>
              As your agents run governed decisions, they become training examples. Click <strong>Build Dataset</strong> to
              curate what already exists, or capture a human correction on any decision to add the strongest signal.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* By label */}
            <div style={card} className="lg:col-span-2">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4" style={{ color: colors.inkSubtle }} />
                  <span className="text-[13px] font-semibold">Signal quality mix</span>
                </div>
                <span className="text-[11px]" style={{ color: colors.inkSubtle }}>by evaluation label</span>
              </div>
              <div className="space-y-3">
                {labels.map(([label, count]) => {
                  const meta = LABEL_META[label] || { color: colors.inkSubtle, title: humanize(label), blurb: '' };
                  return (
                    <div key={label}>
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full" style={{ background: meta.color }} />
                          <span className="text-[12px] font-medium" style={{ color: colors.ink }}>{meta.title}</span>
                        </div>
                        <span className="text-[12px] tabular-nums font-semibold" style={{ color: colors.inkMuted }}>{count.toLocaleString()}</span>
                      </div>
                      <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
                        <div className="h-full rounded-full transition-all" style={{ width: `${(count / maxLabel) * 100}%`, background: meta.color }} />
                      </div>
                      {meta.blurb && <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>{meta.blurb}</div>}
                    </div>
                  );
                })}
              </div>

              {/* By source */}
              <div className="mt-5 pt-4 border-t" style={{ borderColor: colors.hairline }}>
                <div className="text-[11px] font-bold uppercase tracking-wider mb-2.5" style={{ color: colors.inkSubtle }}>Where it comes from</div>
                <div className="flex flex-wrap gap-2">
                  {sources.map(([src, count]) => (
                    <div key={src} className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                      {src === 'mined' ? <Database className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} /> : <UserCheck className="w-3.5 h-3.5" style={{ color: '#8b5cf6' }} />}
                      <span className="text-[12px]" style={{ color: colors.inkMuted }}>{SOURCE_LABEL[src] || humanize(src)}</span>
                      <span className="text-[12px] font-semibold tabular-nums" style={{ color: colors.ink }}>{count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* By domain + export */}
            <div className="space-y-4">
              <div style={card}>
                <div className="flex items-center gap-2 mb-3">
                  <Boxes className="w-4 h-4" style={{ color: colors.inkSubtle }} />
                  <span className="text-[13px] font-semibold">By domain</span>
                </div>
                <div className="space-y-2.5">
                  {domains.map(([domain, count]) => (
                    <div key={domain} className="flex items-center gap-2.5">
                      <DomainIcon hint={domain} size={26} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{humanize(domain)}</span>
                          <span className="text-[11px] tabular-nums" style={{ color: colors.inkSubtle }}>{count.toLocaleString()}</span>
                        </div>
                        <div className="h-1.5 rounded-full mt-1 overflow-hidden" style={{ background: colors.surface3 }}>
                          <div className="h-full rounded-full" style={{ width: `${(count / maxDomain) * 100}%`, background: colors.primary }} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={card}>
                <div className="flex items-center gap-2 mb-3">
                  <Download className="w-4 h-4" style={{ color: colors.inkSubtle }} />
                  <span className="text-[13px] font-semibold">Export for fine-tuning</span>
                </div>
                <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
                  Instruction-tuned JSONL, ready for the Phase 3 fine-tuning pipeline.
                </p>
                <label className="flex items-center gap-2 mb-3 cursor-pointer select-none">
                  <input type="checkbox" checked={positiveOnly} onChange={e => setPositiveOnly(e.target.checked)}
                    style={{ accentColor: colors.primary }} />
                  <span className="text-[12px]" style={{ color: colors.inkMuted }}>Positive examples only (recommended)</span>
                </label>
                <button onClick={exportJsonl} disabled={exporting}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-90 disabled:opacity-50"
                  style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairlineStrong}` }}>
                  {exporting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                  {exporting ? 'Exporting…' : 'Export JSONL'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* How the loop works */}
        <div style={card}>
          <div className="flex items-center gap-2 mb-4">
            <ShieldCheck className="w-4 h-4" style={{ color: '#27a644' }} />
            <span className="text-[13px] font-semibold">A governed learning loop</span>
          </div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {[
              { icon: ShieldCheck, label: 'Governed decision', sub: 'Every agent action walks the 7 gates' },
              { icon: Database, label: 'Curate', sub: 'Mined into training tuples' },
              { icon: UserCheck, label: 'Human feedback', sub: 'Corrections = the strongest signal' },
              { icon: FlaskConical, label: 'Evaluate & fine-tune', sub: 'Phase 3 - only if it beats production' },
              { icon: Route, label: 'Specialized model', sub: 'Phase 4 - routed per department' },
            ].map((step, i, arr) => (
              <React.Fragment key={step.label}>
                <div className="flex-1 min-w-[140px]">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-1.5" style={{ background: colors.primary + '15' }}>
                    <step.icon className="w-4 h-4" style={{ color: colors.primary }} />
                  </div>
                  <div className="text-[12px] font-semibold" style={{ color: colors.ink }}>{step.label}</div>
                  <div className="text-[11px] mt-0.5 leading-snug" style={{ color: colors.inkSubtle }}>{step.sub}</div>
                </div>
                {i < arr.length - 1 && <ArrowRight className="w-4 h-4 shrink-0" style={{ color: colors.inkTertiary }} />}
              </React.Fragment>
            ))}
          </div>
          <p className="text-[11px] mt-4 pt-3 border-t" style={{ color: colors.inkTertiary, borderColor: colors.hairline }}>
            Because every example is derived from a governed execution, nothing blocked at the compliance gate - or
            rejected by a human - ever becomes training data. The dataset inherits the platform’s governance.
          </p>
        </div>

        {/* Phase 3 — Model Evolution. Evaluate a candidate against the tenant's
            baseline on held-out governed examples; promotion is human-gated and a
            simulated run can never win. */}
        <div className="p-6" style={card}>
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <h2 className="text-[15px] font-semibold flex items-center gap-2" style={{ color: colors.ink }}>
                <FlaskConical className="w-4 h-4" style={{ color: colors.primary }} />
                Model Evolution
              </h2>
              <p className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                Score a candidate model against the baseline on held-out governed examples. A win is recorded,
                never auto-applied: promotion is a separate human decision, and a run with no live provider is
                flagged simulated and cannot be promoted.
              </p>
            </div>
          </div>

          <div className="flex items-end gap-2 flex-wrap mb-4">
            <div>
              <label className="text-[11px] uppercase tracking-wide block mb-1" style={{ color: colors.inkSubtle }}>Tier</label>
              <select value={tier} onChange={e => setTier(e.target.value)}
                className="text-[12px] rounded-lg px-2.5 py-2 outline-none"
                style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                {['reasoning', 'classification', 'fast'].map(t => <option key={t} value={t}>{humanize(t)}</option>)}
              </select>
            </div>
            <div className="flex-1 min-w-[220px]">
              <label className="text-[11px] uppercase tracking-wide block mb-1" style={{ color: colors.inkSubtle }}>Candidate model</label>
              <input value={candidate} onChange={e => setCandidate(e.target.value)}
                placeholder="e.g. ollama/qwen2.5-coder:14b"
                className="text-[12px] rounded-lg px-2.5 py-2 outline-none w-full"
                style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            </div>
            <button onClick={runEvaluation} disabled={evaluating || !candidate.trim()}
              className="text-[12px] font-semibold px-4 py-2 rounded-lg text-white"
              style={{ background: colors.primary, opacity: evaluating || !candidate.trim() ? 0.5 : 1 }}>
              {evaluating ? 'Evaluating…' : 'Evaluate'}
            </button>
            <button onClick={submitFinetune} disabled={actingOn === 'finetune'}
              title="Submit curated examples to the configured external fine-tuner"
              className="text-[12px] font-semibold px-4 py-2 rounded-lg"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, opacity: actingOn === 'finetune' ? 0.5 : 1 }}>
              {actingOn === 'finetune' ? 'Submitting…' : 'Fine-tune this tier'}
            </button>
          </div>

          {runs.length === 0 ? (
            <p className="text-[11px] py-3" style={{ color: colors.inkTertiary }}>
              No evaluation runs yet. Evaluate a candidate to compare it against the baseline.
            </p>
          ) : (
            <div className="space-y-2">
              {runs.map((r: any) => {
                const decided = !!r.decision;
                const promotable = r.win && !r.simulated && !decided;
                return (
                  <div key={r.id} className="flex items-center gap-3 p-3 rounded-lg flex-wrap"
                    style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                    <span className="text-[11px] font-bold px-1.5 py-0.5 rounded shrink-0"
                      style={{ background: (r.win ? '#27a644' : '#6b7280') + '22', color: r.win ? '#27a644' : '#6b7280' }}>
                      {r.win ? 'Win' : humanize(r.status) || 'Run'}
                    </span>
                    <div className="flex-1 min-w-[180px]">
                      <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>
                        {r.candidate_model} <span style={{ color: colors.inkTertiary }}>vs</span> {r.baseline_model}
                      </div>
                      <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
                        {humanize(r.tier)} · baseline {r.baseline_score ?? '-'} · candidate {r.candidate_score ?? '-'}
                        {r.score_delta != null && ` · delta ${r.score_delta}`}
                        {r.eval_size ? ` · n=${r.eval_size}` : ''}
                      </div>
                    </div>
                    {r.simulated && (
                      <span className="text-[11px] font-bold px-1.5 py-0.5 rounded shrink-0"
                        style={{ background: '#f59e0b22', color: '#f59e0b' }} title="No live provider ran; cannot be promoted">
                        Simulated
                      </span>
                    )}
                    {decided ? (
                      <span className="text-[11px] font-semibold shrink-0" style={{ color: colors.inkSubtle }}>{humanize(r.decision)}</span>
                    ) : (
                      <div className="flex gap-1.5 shrink-0">
                        <button onClick={() => decideRun(r.id, 'promote')} disabled={!promotable || actingOn === r.id}
                          title={promotable ? 'Promote this candidate for its tier' : 'Only a non-simulated winning run can be promoted'}
                          className="text-[11px] font-semibold px-2.5 py-1 rounded-lg text-white"
                          style={{ background: '#27a644', opacity: promotable && actingOn !== r.id ? 1 : 0.4 }}>
                          Promote
                        </button>
                        <button onClick={() => decideRun(r.id, 'reject')} disabled={actingOn === r.id}
                          className="text-[11px] font-semibold px-2.5 py-1 rounded-lg"
                          style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {ftJobs.length > 0 && (
            <div className="mt-4 pt-3 border-t" style={{ borderColor: colors.hairline }}>
              <h3 className="text-[12px] font-semibold mb-2" style={{ color: colors.ink }}>Fine-tune jobs</h3>
              <div className="space-y-1.5">
                {ftJobs.map((j: any) => (
                  <div key={j.id} className="flex items-center gap-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                    <span className="font-semibold" style={{ color: colors.ink }}>{humanize(j.status)}</span>
                    <span>{humanize(j.tier)}</span>
                    {j.result_model && <span className="truncate">{j.result_model}</span>}
                    {j.error && <span style={{ color: '#e5534b' }} className="truncate">{j.error}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
