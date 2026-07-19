import React, { useState, useEffect, useCallback } from 'react';
import { useTheme } from '../context/ThemeContext';
import {
  Activity, Zap, Database, Eye, Crosshair, Brain, GitPullRequest, X,
  Users, Building2, Boxes, Bot, Package, FolderOpen,
} from 'lucide-react';
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
      fetchLearning();
      fetchFeed();
    } catch (e: any) {
      console.error(e);
      setShockError(e?.message || 'Shock simulation failed. Please retry.');
    } finally {
      setIsSimulating(false);
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
              Live enterprise twin · shock simulation · decision provenance
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
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Zap className="w-4 h-4" /> Shock Simulator
            </h2>
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
