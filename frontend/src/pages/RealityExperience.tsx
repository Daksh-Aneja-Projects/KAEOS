import React, { useState, useEffect, useCallback } from 'react';
import { useTheme } from '../context/ThemeContext';
import {
  Activity, Zap, Database, Eye, Crosshair, Brain, GitPullRequest, X,
  Users, Building2, Boxes, Bot, Package, FolderOpen,
  Sparkles, ShieldCheck, AlertTriangle, Ban, RotateCcw, Lightbulb, Loader2,
} from 'lucide-react';

const WHATIF_DOMAINS = ['All Domains', 'HR', 'Finance', 'Legal', 'Sales', 'Support', 'Operations', 'Engineering'];
const WHATIF_RISK = ['conservative', 'balanced', 'aggressive'];
import { request } from '../api/client';

interface TwinNode { id: string; name: string; group: number; label: string; [k: string]: any }
interface TwinLink { source: string; target: string; type?: string }
interface DecisionTrace {
  impact: any;
  options_evaluated: any[];
  recommendation: any;
}
interface EventTrace { event: string; id: number; ts?: string }

// Must stay in sync with SHOCK_PROFILES in backend/app/api/routes/reality.py.
// Merger and cyber carry the richest causal models (deepest propagation, highest
// severity multipliers, scenario-specific decision options) - they were missing
// from this list, so the backend's two best scenarios were unreachable from the UI.
const SHOCK_TYPES = [
  { value: 'MERGER_INTEGRATION', label: 'M&A Integration', targetLabel: 'Department' },
  { value: 'CYBER_INCIDENT', label: 'Cyber Incident', targetLabel: 'Department' },
  { value: 'EMPLOYEE_TERMINATION', label: 'Employee Termination', targetLabel: 'Employee' },
  { value: 'TALENT_EXODUS', label: 'Talent Exodus', targetLabel: 'Department' },
  { value: 'VENDOR_FAILURE', label: 'Vendor Failure', targetLabel: 'Vendor' },
  { value: 'BUDGET_CUT', label: 'Budget Reduction', targetLabel: 'Department' },
  { value: 'SYSTEM_OUTAGE', label: 'System Outage', targetLabel: 'Department' },
  { value: 'CAPABILITY_LOSS', label: 'Capability Loss', targetLabel: 'Capability' },
];

const TwinGraph = React.lazy(() => import('../components/TwinGraph'));

export default function RealityExperience() {
  const { colors } = useTheme();

  const [twinNodes, setTwinNodes] = useState<TwinNode[]>([]);
  const [twinLinks, setTwinLinks] = useState<TwinLink[]>([]);
  const [realityFeed, setRealityFeed] = useState<EventTrace[]>([]);
  const [learningStats, setLearningStats] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);

  const [selectedNode, setSelectedNode] = useState<TwinNode | null>(null);
  const [decision, setDecision] = useState<DecisionTrace | null>(null);
  const [shockPulse, setShockPulse] = useState<import('../components/TwinGraph').ShockPulse | undefined>(undefined);

  const [isSimulating, setIsSimulating] = useState(false);
  const [shockType, setShockType] = useState('EMPLOYEE_TERMINATION');
  const [shockTarget, setShockTarget] = useState('');
  // The twin is the backbone of this view; a failed load must be visible and
  // retryable, not silently swallowed into an empty graph.
  const [twinError, setTwinError] = useState<string | null>(null);
  // Surfaced when a shock injection fails so the button doesn't just reset.
  const [shockError, setShockError] = useState<string | null>(null);

  // ── What-If Scenario Simulator (IP-1) — a second mode beside the shock sim.
  // Propose a change in plain language; the real /simulation/what-if engine
  // returns a governed verdict + blast radius + ranked risk factors + rollback.
  const [mode, setMode] = useState<'shock' | 'whatif'>('shock');
  const [whatIfChange, setWhatIfChange] = useState('');
  const [whatIfDomain, setWhatIfDomain] = useState('All Domains');
  const [whatIfRisk, setWhatIfRisk] = useState('balanced');
  const [whatIfRunning, setWhatIfRunning] = useState(false);
  const [whatIfResult, setWhatIfResult] = useState<any>(null);
  const [whatIfError, setWhatIfError] = useState<string | null>(null);

  // Scenario comparison (IP-2): each shock run is captured so several can be
  // ranked side by side by severity/blast — turning single shocks into planning.
  const [scenarios, setScenarios] = useState<any[]>([]);

  const fetchTwin = useCallback(async () => {
    try {
      const data = await request<any>('/reality/twin');
      setTwinNodes(data.nodes || []);
      setTwinLinks(data.links || []);
      setStats(data.stats || null);
      setTwinError(null);
    } catch (e: any) {
      console.error(e);
      setTwinError(e?.message || 'Failed to load the enterprise twin.');
    }
  }, []);

  const fetchFeed = useCallback(async () => {
    try {
      const data = await request<any>('/reality/provenance');
      setRealityFeed(data.feed || []);
    } catch { /* transient */ }
  }, []);

  const fetchLearning = useCallback(async () => {
    try {
      setLearningStats(await request<any>('/reality/learning'));
    } catch { /* transient */ }
  }, []);

  useEffect(() => {
    fetchTwin();
    fetchLearning();
    fetchFeed();
    const interval = setInterval(fetchFeed, 4000);
    return () => clearInterval(interval);
  }, [fetchTwin, fetchLearning, fetchFeed]);

  // Candidate targets for the chosen shock type (fall back to all nodes)
  const targetLabel = SHOCK_TYPES.find(s => s.value === shockType)?.targetLabel;
  const targetOptions = twinNodes.filter(n => !targetLabel || n.label === targetLabel);
  const effectiveTarget = shockTarget && targetOptions.some(n => n.id === shockTarget)
    ? shockTarget
    : targetOptions[0]?.id || '';

  const triggerShock = async () => {
    if (!effectiveTarget) return;
    setIsSimulating(true);
    setShockError(null);
    setDecision(null);
    try {
      const data = await request<any>('/reality/shock', {
        method: 'POST',
        body: JSON.stringify({ shock_type: shockType, target_id: effectiveTarget }),
      });
      setDecision(data);
      // Drive the twin's shockwave: epicenter + blast radius + severity.
      setShockPulse({
        targetId: effectiveTarget,
        impactedIds: data?.impact?.impacted_nodes || [],
        severity: data?.impact?.severity ?? 50,
        ts: Date.now(),
      });
      // Capture this run for side-by-side scenario comparison (real data).
      const rec = data?.recommendation;
      const recText = typeof rec === 'string' ? rec : (rec?.action || rec?.decision || rec?.summary || '');
      const shockLabel = SHOCK_TYPES.find(s => s.value === shockType)?.label || shockType;
      const targetName = targetOptions.find(n => n.id === effectiveTarget)?.name || 'target';
      setScenarios(prev => [{
        id: Date.now(),
        label: `${shockLabel} → ${targetName}`,
        severity: Number(data?.impact?.severity) || 0,
        impacted: (data?.impact?.impacted_nodes || []).length,
        recommendation: recText,
      }, ...prev].slice(0, 8));
      fetchLearning();
      fetchFeed();
    } catch (e: any) {
      console.error(e);
      setShockError(e?.message || 'Shock simulation failed. Please retry.');
    } finally {
      setIsSimulating(false);
    }
  };

  const runWhatIf = async () => {
    if (!whatIfChange.trim() || whatIfRunning) return;
    setWhatIfRunning(true);
    setWhatIfError(null);
    setWhatIfResult(null);
    try {
      const data = await request<any>('/simulation/what-if', {
        method: 'POST',
        body: JSON.stringify({
          change_description: whatIfChange.trim(),
          target_domain: whatIfDomain === 'All Domains' ? 'all' : whatIfDomain.toLowerCase(),
          risk_tolerance: whatIfRisk,
        }),
      });
      setWhatIfResult(data);
    } catch (e: any) {
      setWhatIfError(e?.message || 'Simulation failed. Please retry.');
    } finally {
      setWhatIfRunning(false);
    }
  };

  const card = { background: colors.surface1, borderColor: colors.hairline };
  const statTiles = [
    { label: 'Employees', value: stats?.employees, icon: Users, color: '#f59e0b' },
    { label: 'Departments', value: stats?.departments, icon: Building2, color: '#5e6ad2' },
    { label: 'Capabilities', value: stats?.capabilities, icon: Boxes, color: '#06b6d4' },
    { label: 'Agents', value: stats?.agents, icon: Bot, color: '#8b5cf6' },
    { label: 'Vendors', value: stats?.vendors, icon: Package, color: '#ec4899' },
    { label: 'Projects', value: stats?.projects, icon: FolderOpen, color: '#ef4444' },
  ];

  return (
    <div className="flex flex-col h-full w-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        <div className="flex items-center gap-3">
          <Eye className="w-6 h-6" style={{ color: colors.primary }} />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Reality Experience</h1>
            <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
              Live enterprise twin · shock + what-if simulation · decision provenance
            </p>
          </div>
        </div>
        {twinError ? (
          <div className="flex items-center gap-3 text-sm font-mono" style={{ color: colors.error }}>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ background: colors.error }} /> TWIN OFFLINE
            </span>
            <button onClick={fetchTwin} className="px-2.5 py-1 rounded text-xs font-semibold"
              style={{ background: colors.error + '18', color: colors.error }}>Retry</button>
          </div>
        ) : (
          <div className="flex gap-2 text-sm text-green-500 font-mono items-center">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" /> LIVE TWIN · {twinNodes.length} NODES
          </div>
        )}
      </div>

      {twinError && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm"
          style={{ background: colors.error + '12', border: `1px solid ${colors.error}33`, color: colors.error }}>
          {twinError}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6 p-6">
        {/* Left Column: Shock Simulator & Learning */}
        <div className="col-span-3 flex flex-col gap-6">
          <div className="rounded-xl border shadow-sm p-4" style={card}>
            {/* Mode toggle: Shock (inject a disruption) vs What-If (propose a change) */}
            <div className="flex gap-1 p-1 rounded-lg mb-4" style={{ background: colors.canvas }}>
              <button onClick={() => setMode('shock')}
                className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[12px] font-semibold transition-all"
                style={{ background: mode === 'shock' ? colors.primary : 'transparent', color: mode === 'shock' ? '#fff' : colors.inkSubtle }}>
                <Zap className="w-3.5 h-3.5" /> Shock
              </button>
              <button onClick={() => setMode('whatif')}
                className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[12px] font-semibold transition-all"
                style={{ background: mode === 'whatif' ? colors.primary : 'transparent', color: mode === 'whatif' ? '#fff' : colors.inkSubtle }}>
                <Sparkles className="w-3.5 h-3.5" /> What-If
              </button>
            </div>

            {mode === 'shock' ? (
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold mb-1 block">Shock Event</label>
                  <select
                    className="w-full text-sm p-2 border rounded focus:outline-none"
                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                    value={shockType} onChange={e => { setShockType(e.target.value); setShockTarget(''); }}
                  >
                    {SHOCK_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold mb-1 block">
                    Target {targetLabel || 'Node'} <span style={{ color: colors.inkTertiary }}>({targetOptions.length} live)</span>
                  </label>
                  <select
                    className="w-full text-sm p-2 border rounded focus:outline-none"
                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                    value={effectiveTarget} onChange={e => setShockTarget(e.target.value)}
                  >
                    {targetOptions.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
                  </select>
                </div>
                <button
                  onClick={triggerShock}
                  disabled={isSimulating || !effectiveTarget}
                  className="w-full py-2 rounded text-white font-semibold text-sm transition-opacity"
                  style={{ background: isSimulating ? colors.inkSubtle : colors.primary, opacity: isSimulating || !effectiveTarget ? 0.7 : 1 }}
                >
                  {isSimulating ? 'INJECTING…' : 'INJECT REALITY SHOCK'}
                </button>
                {shockError && (
                  <div className="rounded px-3 py-2 text-xs" style={{ background: colors.error + '12', border: `1px solid ${colors.error}33`, color: colors.error }}>
                    {shockError}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold mb-1 block">Proposed change</label>
                  <textarea
                    value={whatIfChange}
                    onChange={e => setWhatIfChange(e.target.value)}
                    rows={3}
                    placeholder="e.g. Cut the Finance budget 15% next quarter"
                    className="w-full text-sm p-2 border rounded focus:outline-none resize-none"
                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold mb-1 block">Target domain</label>
                  <select
                    className="w-full text-sm p-2 border rounded focus:outline-none"
                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                    value={whatIfDomain} onChange={e => setWhatIfDomain(e.target.value)}
                  >
                    {WHATIF_DOMAINS.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold mb-1 block">Risk tolerance</label>
                  <div className="flex gap-1 p-1 rounded-lg" style={{ background: colors.canvas }}>
                    {WHATIF_RISK.map(r => (
                      <button key={r} onClick={() => setWhatIfRisk(r)}
                        className="flex-1 py-1 rounded-md text-[11px] font-medium capitalize transition-all"
                        style={{ background: whatIfRisk === r ? colors.primary + '22' : 'transparent', color: whatIfRisk === r ? colors.primary : colors.inkSubtle }}>
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
                <button
                  onClick={runWhatIf}
                  disabled={whatIfRunning || !whatIfChange.trim()}
                  className="w-full py-2 rounded text-white font-semibold text-sm flex items-center justify-center gap-2 transition-opacity"
                  style={{ background: whatIfRunning ? colors.inkSubtle : colors.primary, opacity: whatIfRunning || !whatIfChange.trim() ? 0.7 : 1 }}
                >
                  {whatIfRunning ? <><Loader2 className="w-4 h-4 animate-spin" /> SIMULATING…</> : <><Sparkles className="w-4 h-4" /> RUN WHAT-IF</>}
                </button>
                {whatIfError && (
                  <div className="rounded px-3 py-2 text-xs" style={{ background: colors.error + '12', border: `1px solid ${colors.error}33`, color: colors.error }}>
                    {whatIfError}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="rounded-xl border shadow-sm p-4 flex-1" style={card}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Brain className="w-4 h-4" /> Learning State
            </h2>
            {learningStats ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 border rounded" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                    <div className="text-[10px] font-mono mb-1" style={{ color: colors.primary }}>SHOCKS PROCESSED</div>
                    <div className="text-2xl font-bold">{learningStats.shocks_processed ?? 0}</div>
                  </div>
                  <div className="p-3 border rounded" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                    <div className="text-[10px] font-mono mb-1" style={{ color: colors.primary }}>RISK PENALTY</div>
                    <div className="text-2xl font-bold text-red-500">-{learningStats.modifiers?.MITIGATE_FAILURE?.toFixed(1) || 0}</div>
                  </div>
                </div>
                <div className="text-xs">
                  <div className="font-semibold mb-2">Recent Outcomes</div>
                  <div className="max-h-[180px] overflow-y-auto space-y-1">
                    {(learningStats.historical_outcomes || []).slice().reverse().map((o: any, i: number) => (
                      <div key={i} className="p-2 border rounded font-mono text-[10px] space-y-0.5" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                        <div className="flex justify-between">
                          <span className="font-bold">{o.shock_type}</span>
                          <span className={o.severity > 60 ? 'text-red-500' : 'text-amber-500'}>sev {o.severity?.toFixed(0)}</span>
                        </div>
                        <div style={{ color: colors.inkTertiary }} className="truncate">{o.target} → {o.decision}</div>
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
        </div>

        {/* Middle Column: Overview, Twin Graph, Decisions */}
        <div className="col-span-6 flex flex-col gap-6">
          <div className="rounded-xl border shadow-sm p-4" style={card}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Activity className="w-4 h-4" /> Enterprise Overview
            </h2>
            <div className="grid grid-cols-3 gap-3">
              {statTiles.map(t => (
                <div key={t.label} className="p-3 border rounded-lg flex items-center gap-3" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: t.color + '18' }}>
                    <t.icon className="w-4 h-4" style={{ color: t.color }} />
                  </div>
                  <div>
                    <div className="text-xl font-bold leading-none">{t.value?.toLocaleString() ?? '-'}</div>
                    <div className="text-[10px] uppercase font-semibold mt-1" style={{ color: colors.inkTertiary }}>{t.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {mode === 'shock' && scenarios.length > 0 && (
            <div className="rounded-xl border shadow-sm p-5" style={card}>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-bold uppercase flex items-center gap-2" style={{ color: colors.inkSubtle }}>
                  <GitPullRequest className="w-4 h-4" /> Scenario Comparison
                </h2>
                <button onClick={() => setScenarios([])} className="text-[11px] px-2 py-1 rounded hover:bg-red-500/10" style={{ color: colors.inkSubtle }}>Clear</button>
              </div>
              <div className="space-y-2">
                {[...scenarios].sort((a, b) => b.severity - a.severity).map(s => {
                  const sc = s.severity > 66 ? '#ef4444' : s.severity > 33 ? '#f59e0b' : '#22c55e';
                  return (
                    <div key={s.id} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center gap-3">
                        <div className="text-[12px] font-semibold flex-1 truncate">{s.label}</div>
                        <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{s.impacted} nodes</div>
                        <div className="text-[13px] font-mono font-bold w-10 text-right" style={{ color: sc }}>{s.severity.toFixed(0)}</div>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, s.severity)}%`, background: sc }} />
                      </div>
                      {s.recommendation && (
                        <div className="text-[11px] mt-1.5" style={{ color: colors.inkSubtle }}>{s.recommendation}</div>
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="text-[10px] mt-3" style={{ color: colors.inkTertiary }}>
                Ranked by severity. Inject more shocks to compare their blast side by side.
              </p>
            </div>
          )}

          {mode === 'whatif' && (
            <div className="rounded-xl border shadow-sm p-5" style={card}>
              <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
                <Sparkles className="w-4 h-4" /> What-If Scenario Result
              </h2>
              {whatIfRunning ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3" style={{ color: colors.inkSubtle }}>
                  <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
                  <span className="text-[13px]">Simulating the change against the enterprise twin…</span>
                </div>
              ) : !whatIfResult ? (
                <div className="text-center py-12">
                  <Sparkles className="w-8 h-8 mx-auto mb-3" style={{ color: colors.inkSubtle, opacity: 0.5 }} />
                  <div className="text-[13px] font-medium">Describe a change and run the simulation</div>
                  <div className="text-[12px]" style={{ color: colors.inkSubtle }}>
                    The twin returns a governed verdict, blast radius, risk factors, and mitigations.
                  </div>
                </div>
              ) : (() => {
                const verdict = String(whatIfResult.simulation_result || 'RISKY').toUpperCase();
                const v = verdict === 'SAFE' ? { c: '#22c55e', Icon: ShieldCheck, label: 'Safe to proceed' }
                  : verdict === 'BLOCKED' ? { c: '#ef4444', Icon: Ban, label: 'Blocked - do not proceed' }
                    : { c: '#f59e0b', Icon: AlertTriangle, label: 'Proceed with caution' };
                const br = whatIfResult.blast_radius || {};
                const sevRank: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
                const sevColor = (s: string) => s === 'HIGH' ? '#ef4444' : s === 'MEDIUM' ? '#f59e0b' : '#22c55e';
                const risks = [...(whatIfResult.risk_factors || [])].sort(
                  (a: any, b: any) => (sevRank[String(a.severity).toUpperCase()] ?? 3) - (sevRank[String(b.severity).toUpperCase()] ?? 3));
                return (
                  <div className="space-y-5">
                    <div className="flex items-center gap-4 p-4 rounded-xl" style={{ background: v.c + '12', border: `1px solid ${v.c}44` }}>
                      <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: v.c + '22' }}>
                        <v.Icon className="w-6 h-6" style={{ color: v.c }} />
                      </div>
                      <div>
                        <div className="text-[20px] font-bold" style={{ color: v.c }}>{verdict}</div>
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>{v.label}</div>
                      </div>
                      {typeof whatIfResult.estimated_rollback_time_hours === 'number' && (
                        <div className="ml-auto text-right">
                          <div className="flex items-center gap-1.5 justify-end text-[18px] font-bold">
                            <RotateCcw className="w-4 h-4" style={{ color: colors.inkSubtle }} />~{whatIfResult.estimated_rollback_time_hours}h
                          </div>
                          <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Rollback time</div>
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="text-[11px] uppercase tracking-wide font-semibold mb-2" style={{ color: colors.inkSubtle }}>Blast radius</div>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Rules affected', value: br.affected_rules ?? 0 },
                          { label: 'Skills affected', value: br.affected_skills ?? 0 },
                          { label: 'Departments', value: (br.affected_departments || []).length },
                        ].map(s => (
                          <div key={s.label} className="p-3 rounded-lg text-center" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                            <div className="text-[24px] font-bold">{s.value}</div>
                            <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
                          </div>
                        ))}
                      </div>
                      {(br.affected_departments || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {(br.affected_departments || []).map((d: string, i: number) => (
                            <span key={i} className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>{d}</span>
                          ))}
                        </div>
                      )}
                    </div>

                    {risks.length > 0 && (
                      <div>
                        <div className="text-[11px] uppercase tracking-wide font-semibold mb-2" style={{ color: colors.inkSubtle }}>Risk factors</div>
                        <div className="space-y-2">
                          {risks.map((r: any, i: number) => (
                            <div key={i} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                              <div className="flex items-center gap-2 mb-1">
                                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: sevColor(String(r.severity).toUpperCase()) }} />
                                <span className="text-[12px] font-semibold">{r.factor}</span>
                                <span className="ml-auto text-[10px] font-bold uppercase" style={{ color: sevColor(String(r.severity).toUpperCase()) }}>{r.severity}</span>
                              </div>
                              {r.mitigation && (
                                <div className="text-[11px] pl-4" style={{ color: colors.inkSubtle }}>
                                  <span className="font-semibold">Mitigation:</span> {r.mitigation}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {whatIfResult.recommendation && (
                      <div className="p-3 rounded-lg flex gap-2" style={{ background: colors.primary + '0d', border: `1px solid ${colors.primary}33` }}>
                        <Lightbulb className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: colors.primary }} />
                        <div className="text-[12px]"><span className="font-semibold">Recommendation: </span>{whatIfResult.recommendation}</div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

          <div className="rounded-xl border shadow-sm p-4 relative flex flex-col" style={{ ...card, minHeight: 480 }}>
            <h2 className="text-sm font-bold uppercase mb-2 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Database className="w-4 h-4" /> Enterprise Twin - Live
            </h2>
            <div className="flex-1 rounded overflow-hidden relative" style={{ background: colors.canvas }}>
              <React.Suspense fallback={null}>
                <TwinGraph data={{ nodes: twinNodes, links: twinLinks }} onNodeClick={(n: any) => setSelectedNode(n)} shock={shockPulse} />
              </React.Suspense>
            </div>

            {selectedNode && (
              <div className="absolute right-6 top-14 bottom-6 w-64 p-4 border rounded-xl shadow-xl overflow-y-auto z-10" style={{ background: colors.surface1, borderColor: colors.hairline }}>
                <div className="flex justify-between items-center mb-3">
                  <h3 className="font-bold text-sm truncate">{selectedNode.name}</h3>
                  <button onClick={() => setSelectedNode(null)} className="p-1 rounded hover:bg-red-500/20" style={{ color: colors.inkSubtle }}>
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="text-[10px] font-mono px-2 py-0.5 rounded inline-block mb-3" style={{ background: colors.primary + '20', color: colors.primary }}>
                  {selectedNode.label}
                </div>
                <div className="space-y-2 text-xs">
                  {Object.entries(selectedNode)
                    .filter(([k]) => !['id', 'name', 'label', 'group'].includes(k))
                    .map(([k, v]) => (
                      <div key={k} className="border-b pb-1" style={{ borderColor: colors.hairline }}>
                        <div className="font-semibold capitalize" style={{ color: colors.inkSubtle }}>{k.replace(/_/g, ' ')}</div>
                        <div className="font-mono truncate">{String(v)}</div>
                      </div>
                    ))}
                  <button
                    onClick={() => {
                      const st = SHOCK_TYPES.find(s => s.targetLabel === selectedNode.label);
                      if (st) setShockType(st.value);
                      setShockTarget(selectedNode.id);
                      setSelectedNode(null);
                    }}
                    className="w-full mt-2 py-1.5 rounded text-white text-xs font-semibold"
                    style={{ background: colors.primary }}
                  >
                    Set as Shock Target
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-xl border shadow-sm p-4 overflow-y-auto" style={{ ...card, minHeight: 200 }}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Crosshair className="w-4 h-4" /> Decision Center
            </h2>
            {decision ? (
              <div className="space-y-4">
                <div className="p-3 rounded border" style={{ borderColor: 'rgba(239, 68, 68, 0.5)', background: 'rgba(239, 68, 68, 0.05)' }}>
                  <div className="text-xs font-bold text-red-500 mb-1">IMPACT ANALYSIS ({decision.impact?.severity?.toFixed(1) || 0} severity)</div>
                  <div className="text-sm">{decision.impact?.reasoning}</div>
                </div>
                <div>
                  <div className="text-xs font-bold mb-2" style={{ color: colors.inkSubtle }}>GENERATED OPTIONS</div>
                  <div className="space-y-2">
                    {(decision.options_evaluated || []).map((opt: any, i: number) => {
                      const recommended = decision.recommendation?.option?.action === opt.option?.action;
                      return (
                        <div key={i} className="p-3 border rounded text-xs" style={{ borderColor: recommended ? colors.primary : colors.hairline, background: colors.canvas }}>
                          <div className="flex justify-between mb-2">
                            <span className="font-bold font-mono flex items-center gap-2">
                              {opt.option?.action}
                              {recommended && (
                                <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold text-white" style={{ background: colors.primary }}>RECOMMENDED</span>
                              )}
                            </span>
                            <span className="font-bold font-mono" style={{ color: colors.primary }}>{opt.score?.total_score?.toFixed(1)} pts</span>
                          </div>
                          <div className="mb-2" style={{ color: colors.inkTertiary }}>{opt.option?.description}</div>
                          <div className="flex gap-4 font-mono text-[10px]">
                            <span>Cost: {opt.score?.estimated_cost}</span>
                            <span>Time: {opt.score?.estimated_time_days}d</span>
                            <span>Risk: {((opt.score?.risk_penalty || 0) * 100).toFixed(0)}%</span>
                            {opt.modifier_applied > 0 && <span className="text-red-500 font-bold">L-PENALTY: -{opt.modifier_applied.toFixed(1)}</span>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-sm italic flex h-full items-center justify-center opacity-50 py-8" style={{ color: colors.inkSubtle }}>
                Awaiting shock injection…
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Provenance & Live Feed */}
        <div className="col-span-3 flex flex-col gap-6">
          <div className="rounded-xl border shadow-sm p-4 overflow-y-auto" style={{ ...card, minHeight: 280 }}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <GitPullRequest className="w-4 h-4" /> Why Panel
            </h2>
            {decision ? (
              <div className="relative pl-4 border-l space-y-4 text-xs font-mono" style={{ borderColor: colors.primary }}>
                {[
                  ['Source Event', SHOCK_TYPES.find(s => s.value === shockType)?.label || shockType],
                  ['Twin State Capture', `${twinNodes.length} nodes · live snapshot`],
                  ['Impact Engine', `Severity ${decision.impact?.severity?.toFixed(1)} · ${decision.impact?.impacted_nodes?.length ?? 0} nodes hit`],
                  ['Option Engine', `Generated ${(decision.options_evaluated || []).length} candidates`],
                  ['Evaluation Engine', 'Scored & ranked'],
                  ['Learning Engine', `Applied penalty −${(decision.options_evaluated?.[1]?.modifier_applied ?? 0).toFixed(1)}`],
                ].map(([title, sub], i) => (
                  <div key={i} className="relative">
                    <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full" style={{ background: colors.primary }} />
                    <div className="font-bold" style={{ color: colors.ink }}>{title}</div>
                    <div style={{ color: colors.inkTertiary }}>{sub}</div>
                  </div>
                ))}
                <div className="relative">
                  <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: '#22c55e' }} />
                  <div className="font-bold text-green-500">Final Decision Executed</div>
                  <div style={{ color: colors.inkTertiary }} className="truncate">{decision.recommendation?.option?.action}</div>
                </div>
              </div>
            ) : (
              <div className="text-sm italic opacity-50" style={{ color: colors.inkSubtle }}>Trace empty - run a shock to see the reasoning chain.</div>
            )}
          </div>

          <div className="rounded-xl border shadow-sm p-4 flex-1 flex flex-col" style={{ ...card, minHeight: 280 }}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Activity className="w-4 h-4" /> Reality Feed
            </h2>
            <div className="flex-1 overflow-y-auto space-y-2 pr-2 max-h-[420px]">
              {realityFeed.slice().reverse().map((f, i) => (
                <div key={i} className="text-xs p-2 rounded font-mono border" style={{ background: colors.canvas, borderColor: colors.hairline }}>
                  <span className="mr-2" style={{ color: colors.primary }}>[{String(f.id).padStart(4, '0')}]</span>
                  {f.event}
                </div>
              ))}
              {realityFeed.length === 0 && (
                <div className="text-sm italic opacity-50" style={{ color: colors.inkSubtle }}>Listening to enterprise events…</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
