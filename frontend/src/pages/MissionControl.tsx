import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import {
  Rocket, Target, Play, Ban, Check, X, Loader2, GitBranch, CircleDot,
  CheckCircle2, XCircle, PauseCircle, DollarSign, ChevronRight, Sparkles,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import DomainIcon from '../components/DomainIcon';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';

/**
 * Mission Control — goal-level autonomous orchestration. A plain-language goal is
 * decomposed into a governed DAG of real skills across departments; each step runs
 * through the 7 gates, with a budget gate, HITL checkpoints, and a mission ledger.
 * Lives as a tab in the Agents view (goal-level orchestration of the same agents).
 */

const STATUS_COLOR: Record<string, string> = {
  PLANNING: '#8b5cf6', RUNNING: '#3b82f6', AWAITING_HITL: '#f59e0b',
  BUDGET_BLOCKED: '#f59e0b', COMPLETED: '#22c55e', COMPLETED_WITH_EXCEPTIONS: '#f59e0b',
  FAILED: '#ef4444', ABORTED: '#94a3b8',
};

const STEP_ICON: Record<string, any> = {
  PENDING: CircleDot, READY: CircleDot, RUNNING: Loader2, AWAITING_HITL: PauseCircle,
  DONE: CheckCircle2, FAILED: XCircle, SKIPPED: X,
};

export default function MissionControl({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [missions, setMissions] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [goal, setGoal] = useState('');
  const [budget, setBudget] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    try {
      const d = await api.listMissions(30);
      setMissions(d.missions || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadList(); }, [loadList]);

  const openMission = async (id: string) => {
    try { setSelected(await api.getMission(id)); } catch (e) { console.error(e); }
  };

  const launch = async () => {
    if (!goal.trim()) return;
    setBusy('launch');
    try {
      const b = budget.trim() ? parseFloat(budget) : null;
      const m = await api.createMission(goal.trim(), Number.isFinite(b as any) ? b : null);
      setGoal(''); setBudget('');
      await loadList();
      setSelected(m);
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  // The engine advances one governed step per call (a real gated step can take a
  // while on a live model). Loop until it stops progressing so the UI streams
  // each step as it lands, then refresh the list.
  const advance = async (id?: string) => {
    const mid = id || selected?.id;
    if (!mid) return;
    setBusy('advance');
    try {
      let res = await api.advanceMission(mid);
      setSelected(res);
      let guard = 0;
      while (res?.status === 'RUNNING' && guard++ < 25) {
        res = await api.advanceMission(mid);
        setSelected(res);
      }
      await loadList();
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const abort = async () => {
    if (!selected) return;
    setBusy('abort');
    try { setSelected(await api.abortMission(selected.id)); await loadList(); }
    catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  const resolveHitl = async (seq: number, approved: boolean) => {
    if (!selected) return;
    const mid = selected.id;
    setBusy(`hitl-${seq}`);
    try {
      const res = await api.resolveMissionHitl(mid, seq, approved);
      setSelected(res);
      // Resume auto-advance so remaining steps run after the checkpoint clears.
      if (res?.status === 'RUNNING') { await advance(mid); }
      else { await loadList(); }
    } catch (e) { console.error(e); }
    finally { setBusy(null); }
  };

  if (loading) return <BrainLoading message="Loading Mission Control…" />;

  const budgetPct = selected?.budget_usd
    ? Math.min(100, ((selected.spent_usd || 0) / selected.budget_usd) * 100) : 0;
  const canAdvance = selected && ['RUNNING', 'PLANNING'].includes(selected.status);
  const canAbort = selected && !['COMPLETED', 'FAILED', 'ABORTED'].includes(selected.status);

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-start gap-3 mb-5">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
            <Rocket className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-[24px] font-bold tracking-tight">Mission Control</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              Give KAEOS a goal. It decomposes into a governed plan across departments, runs each step through the gates, and pauses for you at the checkpoints that matter.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-5">
          {/* Left: launcher + mission list */}
          <div className="space-y-4">
            <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-4 h-4" style={{ color: colors.primary }} />
                <span className="text-[13px] font-semibold">Launch a mission</span>
              </div>
              <textarea value={goal} onChange={e => setGoal(e.target.value)}
                placeholder="e.g. Close the quarter: review the vendor contract, approve the budget, and brief support"
                rows={3}
                className="w-full rounded-lg px-3 py-2 text-[13px] resize-none outline-none"
                style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              <div className="flex items-center gap-2 mt-2">
                <div className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 flex-1"
                  style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                  <DollarSign className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
                  <input value={budget} onChange={e => setBudget(e.target.value)}
                    placeholder="Budget (optional)" inputMode="decimal"
                    className="bg-transparent outline-none text-[12px] w-full" style={{ color: colors.ink }} />
                </div>
                <button onClick={launch} disabled={!goal.trim() || busy === 'launch'}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white shrink-0"
                  style={{ background: colors.primary, opacity: !goal.trim() || busy === 'launch' ? 0.5 : 1 }}>
                  {busy === 'launch' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                  Plan
                </button>
              </div>
            </div>

            <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="px-4 py-2.5 border-b text-[11px] uppercase tracking-wider font-semibold"
                style={{ borderColor: colors.hairline, color: colors.inkSubtle }}>Missions</div>
              {missions.length === 0 ? (
                <div className="p-6 text-center text-[12px]" style={{ color: colors.inkTertiary }}>No missions yet. Launch one above.</div>
              ) : missions.map(m => (
                <button key={m.id} onClick={() => openMission(m.id)}
                  className="w-full text-left px-4 py-3 border-b transition-colors flex items-center gap-2"
                  style={{ borderColor: colors.hairline, background: selected?.id === m.id ? colors.surface2 : 'transparent' }}>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{m.goal}</div>
                    <div className="text-[10px] mt-0.5" style={{ color: colors.inkSubtle }}>
                      {(m.departments || []).join(' · ') || 'no departments'}
                    </div>
                  </div>
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0"
                    style={{ background: (STATUS_COLOR[m.status] || colors.inkSubtle) + '22', color: STATUS_COLOR[m.status] || colors.inkSubtle }}>
                    {m.status}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Right: selected mission */}
          <div>
            {!selected ? (
              <BrainEmpty title="Select or launch a mission" action="A mission turns a goal into a governed, cross-department plan you can watch and steer." icon={GitBranch} />
            ) : (
              <div className="space-y-4">
                {/* Mission header */}
                <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[15px] font-semibold">{selected.goal}</span>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: (STATUS_COLOR[selected.status] || colors.inkSubtle) + '22', color: STATUS_COLOR[selected.status] || colors.inkSubtle }}>
                          {selected.status}
                        </span>
                      </div>
                      {selected.narrative && (
                        <p className="text-[12px] mt-2 leading-relaxed" style={{ color: colors.inkSubtle }}>{selected.narrative}</p>
                      )}
                    </div>
                    <div className="flex gap-2 shrink-0">
                      {canAdvance && (
                        <button onClick={() => advance()} disabled={busy === 'advance'}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white"
                          style={{ background: colors.primary, opacity: busy === 'advance' ? 0.5 : 1 }}>
                          {busy === 'advance' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                          Advance
                        </button>
                      )}
                      {canAbort && (
                        <button onClick={abort} disabled={busy === 'abort'}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold"
                          style={{ background: colors.error + '18', color: colors.error, opacity: busy === 'abort' ? 0.5 : 1 }}>
                          <Ban className="w-3.5 h-3.5" /> Abort
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Budget meter */}
                  {selected.budget_usd != null && (
                    <div className="mt-4">
                      <div className="flex items-center justify-between text-[11px] mb-1" style={{ color: colors.inkSubtle }}>
                        <span>Budget</span>
                        <span>${(selected.spent_usd || 0).toFixed(4)} / ${selected.budget_usd.toFixed(2)}</span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: colors.surface2 }}>
                        <div className="h-full rounded-full" style={{ width: `${budgetPct}%`, background: budgetPct >= 100 ? colors.error : colors.primary }} />
                      </div>
                    </div>
                  )}
                </div>

                {/* Step DAG */}
                <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center gap-2 mb-4">
                    <GitBranch className="w-4 h-4" style={{ color: colors.primary }} />
                    <span className="text-[13px] font-semibold">Plan ({selected.steps?.length || 0} steps)</span>
                  </div>
                  <div className="space-y-0">
                    {(selected.steps || []).map((s: any, i: number) => {
                      const Icon = STEP_ICON[s.status] || CircleDot;
                      const sc = s.status === 'DONE' ? '#22c55e' : s.status === 'FAILED' ? '#ef4444'
                        : s.status === 'AWAITING_HITL' ? '#f59e0b' : s.status === 'RUNNING' ? '#3b82f6'
                        : s.status === 'SKIPPED' ? '#94a3b8' : colors.inkSubtle;
                      const last = i === selected.steps.length - 1;
                      return (
                        <div key={s.seq} className="flex gap-3">
                          {/* rail */}
                          <div className="flex flex-col items-center">
                            <Icon className={`w-5 h-5 ${s.status === 'RUNNING' ? 'animate-spin' : ''}`} style={{ color: sc }} />
                            {!last && <div className="w-px flex-1 my-1" style={{ background: colors.hairline, minHeight: 28 }} />}
                          </div>
                          {/* body */}
                          <div className="flex-1 pb-4">
                            <div className="flex items-center gap-2 flex-wrap">
                              <DomainIcon hint={s.department} size={18} />
                              <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{s.name}</span>
                              {s.hitl_required && (
                                <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                                  style={{ background: '#f59e0b22', color: '#f59e0b' }}>HITL</span>
                              )}
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                                style={{ background: sc + '18', color: sc }}>{s.status}</span>
                            </div>
                            <div className="text-[11px] mt-1 flex items-center gap-2 flex-wrap" style={{ color: colors.inkSubtle }}>
                              <span>confidence {(s.confidence ?? 0).toFixed(2)}</span>
                              {s.depends_on?.length > 0 && (
                                <span className="flex items-center gap-0.5"><ChevronRight className="w-3 h-3" /> after step {s.depends_on.join(', ')}</span>
                              )}
                              {s.cost_usd > 0 && <span>· ${s.cost_usd.toFixed(4)}</span>}
                              {s.result_summary && <span>· {s.result_summary}</span>}
                            </div>
                            {s.status === 'AWAITING_HITL' && (
                              <div className="flex gap-2 mt-2">
                                <button onClick={() => resolveHitl(s.seq, true)} disabled={busy === `hitl-${s.seq}`}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold"
                                  style={{ background: '#22c55e18', color: '#22c55e' }}>
                                  <Check className="w-3.5 h-3.5" /> Approve
                                </button>
                                <button onClick={() => resolveHitl(s.seq, false)} disabled={busy === `hitl-${s.seq}`}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold"
                                  style={{ background: '#ef444418', color: '#ef4444' }}>
                                  <X className="w-3.5 h-3.5" /> Reject
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Mission ledger */}
                {selected.ledger?.length > 0 && (
                  <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <div className="text-[13px] font-semibold mb-3">Mission ledger</div>
                    <div className="space-y-2">
                      {selected.ledger.map((e: any, i: number) => (
                        <div key={i} className="flex items-start gap-2 text-[12px]">
                          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0 mt-0.5"
                            style={{ background: colors.surface2, color: colors.inkSubtle }}>{e.kind}</span>
                          <span style={{ color: colors.inkSubtle }}>{e.message}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
