import React, { useState, useEffect, useCallback } from 'react';
import { useTheme } from '../context/ThemeContext';
import {
  Activity, Zap, Database, Eye, Crosshair, Brain, GitPullRequest, X,
  Users, Building2, Boxes, Bot, Package, FolderOpen,
  Sparkles, ShieldCheck, AlertTriangle, Ban, RotateCcw, Lightbulb, Loader2, History, Swords,
} from 'lucide-react';
import TimeMachinePanel from '../components/TimeMachinePanel';
import WargamePanel from '../components/WargamePanel';
import { humanize } from '../lib/format';
import { PAGE_PAD_X } from '../lib/layout';
import { useVisiblePoll } from '../hooks/useLiveRefresh';

import { request } from '../api/client';
import {
  WHATIF_DOMAINS, WHATIF_RISK, SHOCK_TYPES, SHOCK_GROUPS, TWIN_LEGEND,
  StatsStrip, LearningState,
  buildWargameImpact, buildReplayImpact, buildWhatIfImpact,
} from './RealityExperience.parts';
import type { TwinNode, TwinLink, DecisionTrace, EventTrace, ModeActivity } from './RealityExperience.parts';

const TwinGraph = React.lazy(() => import('../components/TwinGraph'));

export default function RealityExperience() {
  const { colors } = useTheme();

  const [twinNodes, setTwinNodes] = useState<TwinNode[]>([]);
  const [twinLinks, setTwinLinks] = useState<TwinLink[]>([]);
  const [realityFeed, setRealityFeed] = useState<EventTrace[]>([]);
  const [learningStats, setLearningStats] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [twinMeta, setTwinMeta] = useState<{ shown: number; total: number } | null>(null);

  const [selectedNode, setSelectedNode] = useState<TwinNode | null>(null);
  const [decision, setDecision] = useState<DecisionTrace | null>(null);
  // Unified Decision Center + Why Panel content for the NON-shock modes, so all
  // four modes drive the same two panels (shock keeps its richer native trace).
  const [activity, setActivity] = useState<ModeActivity | null>(null);
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
  const [mode, setMode] = useState<'shock' | 'whatif' | 'replay' | 'wargame'>('shock');
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
      setTwinMeta(data.sampled ? { shown: (data.nodes || []).length, total: data.total_nodes } : null);
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
  }, [fetchTwin, fetchLearning, fetchFeed]);
  useVisiblePoll(fetchFeed, 4000);

  // Each mode owns the Decision Center + Why Panel - reset them on a mode switch.
  useEffect(() => { setDecision(null); setActivity(null); }, [mode]);

  // Candidate targets for the chosen shock type (fall back to all nodes)
  const targetLabel = SHOCK_TYPES.find(s => s.value === shockType)?.targetLabel;
  const targetOptions = twinNodes.filter(n => !targetLabel || n.label === targetLabel);
  const effectiveTarget = shockTarget && targetOptions.some(n => n.id === shockTarget)
    ? shockTarget
    : targetOptions[0]?.id || '';

  // ── Live twin reaction for EVERY mode ────────────────────────────────────
  // Shock already pulses the graph; What-If / Wargame / Replay now drive the
  // same shockwave so their impact is visible on the constellation too. Map a
  // department name/slug to its twin node, then light up that department + its
  // records (the blast region) at a severity the mode computes.
  const deptNodeId = useCallback((nameOrSlug: string): string | undefined => {
    const t = String(nameOrSlug || '').toLowerCase().trim();
    if (!t) return undefined;
    const d = twinNodes.find(n => n.label === 'Department' && (
      String(n.slug || '').toLowerCase() === t ||
      String(n.name || '').toLowerCase() === t ||
      String(n.name || '').toLowerCase().includes(t) ||
      t.includes(String(n.slug || '').toLowerCase())
    ));
    return d?.id;
  }, [twinNodes]);

  const pulseDepartments = useCallback((deptRefs: string[], severity: number, epicenter?: string) => {
    const ids = Array.from(new Set(deptRefs.map(deptNodeId).filter(Boolean))) as string[];
    if (!ids.length) return;
    const targetId = (epicenter ? deptNodeId(epicenter) : undefined) || ids[0];
    // Extend the blast to each hit department's records so a whole region lights up.
    const impacted = new Set<string>(ids);
    for (const l of twinLinks) {
      const s = typeof l.source === 'string' ? l.source : (l.source as any)?.id;
      const tg = typeof l.target === 'string' ? l.target : (l.target as any)?.id;
      if (ids.includes(s) && tg) impacted.add(tg);
      if (ids.includes(tg) && s) impacted.add(s);
    }
    setShockPulse({ targetId, impactedIds: Array.from(impacted), severity: Math.max(8, Math.min(100, severity)), ts: Date.now() });
  }, [deptNodeId, twinLinks]);

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
      // Light up the affected departments on the twin + populate the shared
      // Decision Center + Why Panel (severity from the governed verdict).
      const { activity, depts, sev } = buildWhatIfImpact(data, whatIfChange.trim(), whatIfDomain, twinNodes.length);
      pulseDepartments(depts, sev);
      setActivity(activity);
    } catch (e: any) {
      setWhatIfError(e?.message || 'Simulation failed. Please retry.');
    } finally {
      setWhatIfRunning(false);
    }
  };

  const card = { background: colors.surface1, borderColor: colors.hairline };
  const toneColor = (t?: string) => t === 'good' ? '#22c55e' : t === 'bad' ? '#ef4444' : t === 'warn' ? '#f59e0b' : colors.inkSubtle;
  const sevAccent = (sev: number) => sev > 66 ? '#ef4444' : sev > 33 ? '#f59e0b' : '#22c55e';
  const statTiles = [
    { label: 'Employees', value: stats?.employees, icon: Users, color: '#f59e0b' },
    { label: 'Departments', value: stats?.departments, icon: Building2, color: '#5e6ad2' },
    { label: 'Capabilities', value: stats?.capabilities, icon: Boxes, color: '#06b6d4' },
    { label: 'Agents', value: stats?.agents, icon: Bot, color: '#8b5cf6' },
    { label: 'Vendors', value: stats?.vendors, icon: Package, color: '#ec4899' },
    { label: 'Projects', value: stats?.projects, icon: FolderOpen, color: '#ef4444' },
  ];

  const presentLabels = new Set(twinNodes.map(n => n.label));
  const legend = TWIN_LEGEND.filter(l => presentLabels.has(l.label));

  const modeButtons = [
    { key: 'shock', label: 'Shock', Icon: Zap },
    { key: 'whatif', label: 'What-If', Icon: Sparkles },
    { key: 'replay', label: 'Replay', Icon: History },
    { key: 'wargame', label: 'Wargame', Icon: Swords },
  ] as const;

  const simControls = (
    <div className="rounded-xl border shadow-sm p-4" style={card}>
      {/* Mode toggle: Shock / What-If / Replay / Wargame - 2x2 so labels never wrap */}
      <div className="grid grid-cols-2 gap-1 p-1 rounded-lg mb-4" style={{ background: colors.canvas }}>
        {modeButtons.map(({ key, label, Icon }) => (
          <button key={key} onClick={() => setMode(key)}
            className="flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[12px] font-semibold transition-all whitespace-nowrap"
            style={{ background: mode === key ? colors.primary : 'transparent', color: mode === key ? '#fff' : colors.inkSubtle }}>
            <Icon className="w-3.5 h-3.5" /> {label}
          </button>
        ))}
      </div>

      {mode === 'wargame' ? (
        <WargamePanel colors={colors} onImpact={(r) => {
          const { activity, depts, sev, epicenter } = buildWargameImpact(r, twinNodes.length);
          pulseDepartments(depts, sev, epicenter);
          setActivity(activity);
        }} />
      ) : mode === 'replay' ? (
        <TimeMachinePanel colors={colors} onImpact={(evt, cf) => {
          const { activity, depts, sev } = buildReplayImpact(evt, cf);
          if (depts.length) pulseDepartments(depts, sev);
          setActivity(activity);
        }} />
      ) : mode === 'shock' ? (
        <div className="space-y-3">
          <div>
            <label className="text-[11px] font-semibold mb-1 block">Shock Event</label>
            <select
              className="w-full text-[12px] p-1.5 border rounded focus:outline-none"
              style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
              value={shockType} onChange={e => { setShockType(e.target.value); setShockTarget(''); }}
            >
              {SHOCK_GROUPS.map(g => (
                <optgroup key={g} label={g}>
                  {SHOCK_TYPES.filter(s => s.group === g).map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-semibold mb-1 block">
              Target {targetLabel || 'Node'} <span style={{ color: colors.inkTertiary }}>({targetOptions.length} live)</span>
            </label>
            <select
              className="w-full text-[12px] p-1.5 border rounded focus:outline-none"
              style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
              value={effectiveTarget} onChange={e => setShockTarget(e.target.value)}
            >
              {targetOptions.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </div>
          <button
            onClick={triggerShock}
            disabled={isSimulating || !effectiveTarget}
            className="w-full py-1.5 rounded text-white font-semibold text-[12px] transition-opacity"
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
            <label className="text-[11px] font-semibold mb-1 block">Proposed change</label>
            <textarea
              value={whatIfChange}
              onChange={e => setWhatIfChange(e.target.value)}
              rows={3}
              placeholder="e.g. Cut the Finance budget 15% next quarter"
              className="w-full text-[12px] p-1.5 border rounded focus:outline-none resize-none"
              style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold mb-1 block">Target domain</label>
            <select
              className="w-full text-[12px] p-1.5 border rounded focus:outline-none"
              style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
              value={whatIfDomain} onChange={e => setWhatIfDomain(e.target.value)}
            >
              {WHATIF_DOMAINS.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-semibold mb-1 block">Risk tolerance</label>
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
            className="w-full py-1.5 rounded text-white font-semibold text-[12px] flex items-center justify-center gap-2 transition-opacity"
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
  );

  return (
    <div className="flex flex-col h-full w-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header */}
      <div className={`flex items-center justify-between ${PAGE_PAD_X} py-4 border-b`} style={{ borderColor: colors.hairline, background: colors.surface1 }}>
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
        <div className={`${PAGE_PAD_X} mt-4`}>
          <div className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm"
            style={{ background: colors.error + '12', border: `1px solid ${colors.error}33`, color: colors.error }}>
            {twinError}
          </div>
        </div>
      )}

      {/* Enterprise stat strip - full width so no label wraps */}
      <div className={`${PAGE_PAD_X} pt-6`}>
        <StatsStrip tiles={statTiles} colors={colors} card={card} />
      </div>

      {/* ── HERO: the living enterprise twin. Full-bleed and tall - this is the IP.
          Simulation controls sit to its left so a shock visibly pulses the graph. */}
      <div className={`grid grid-cols-1 lg:grid-cols-12 gap-6 ${PAGE_PAD_X} pt-6`}>
        <div className="lg:col-span-3 flex flex-col gap-6 overflow-y-auto pr-1 lg:h-[640px]">
          {simControls}
          <LearningState learningStats={learningStats} colors={colors} card={card} />
        </div>

        <div className="lg:col-span-9 rounded-xl border shadow-sm p-4 relative flex flex-col min-h-0" style={{ ...card, height: 640 }}>
          <div className="flex items-start justify-between mb-2 gap-4">
            <div>
              <h2 className="text-sm font-bold uppercase flex items-center gap-2" style={{ color: colors.inkSubtle }}>
                <Database className="w-4 h-4" /> Enterprise Twin - Live Constellation
              </h2>
              <p className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>
                Every department and its live records - customers, accounts, tickets, contracts, incidents, orders. Click a node to inspect or shock it.
              </p>
            </div>
            {twinMeta && (
              <div className="text-[11px] font-mono px-2 py-1 rounded whitespace-nowrap" style={{ background: colors.primary + '15', color: colors.primary }}>
                {twinMeta.shown} of {twinMeta.total.toLocaleString()} nodes
              </div>
            )}
          </div>

          {/* Node-type legend - makes the rich constellation readable at a glance */}
          {legend.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 mb-2">
              {legend.map(l => (
                <span key={l.label} className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}>
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: l.color }} />
                  {l.label}
                </span>
              ))}
            </div>
          )}

          <div className="flex-1 rounded overflow-hidden relative" style={{ background: colors.canvas }}>
            <React.Suspense fallback={null}>
              <TwinGraph data={{ nodes: twinNodes, links: twinLinks }} onNodeClick={(n: any) => setSelectedNode(n)} shock={shockPulse} />
            </React.Suspense>
          </div>

          {selectedNode && (
            <div className="absolute right-6 top-14 bottom-6 w-64 max-w-[calc(100%-2rem)] p-4 border rounded-xl shadow-xl overflow-y-auto z-10" style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-bold text-sm truncate">{selectedNode.name}</h3>
                <button onClick={() => setSelectedNode(null)} aria-label="Close node details"
                  className="p-1 rounded hover:bg-red-500/20" style={{ color: colors.inkSubtle }}>
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="text-[11px] font-mono px-2 py-0.5 rounded inline-block mb-3" style={{ background: colors.primary + '20', color: colors.primary }}>
                {selectedNode.label}
              </div>
              <div className="space-y-2 text-xs">
                {Object.entries(selectedNode)
                  .filter(([k]) => !['id', 'name', 'label', 'group', 'x', 'y', 'vx', 'vy', 'hx', 'hy', 'r', 'fixed', 'phase'].includes(k))
                  .map(([k, v]) => (
                    <div key={k} className="border-b pb-1" style={{ borderColor: colors.hairline }}>
                      <div className="font-semibold" style={{ color: colors.inkSubtle }}>{humanize(k)}</div>
                      <div className="font-mono truncate">{String(v)}</div>
                    </div>
                  ))}
                {SHOCK_TYPES.some(s => s.targetLabel === selectedNode.label) && (
                  <button
                    onClick={() => {
                      const st = SHOCK_TYPES.find(s => s.targetLabel === selectedNode.label);
                      if (st) { setShockType(st.value); setMode('shock'); }
                      setShockTarget(selectedNode.id);
                      setSelectedNode(null);
                    }}
                    className="w-full mt-2 py-1.5 rounded text-white text-xs font-semibold"
                    style={{ background: colors.primary }}
                  >
                    Set as Shock Target
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={`grid grid-cols-1 lg:grid-cols-12 gap-6 ${PAGE_PAD_X} py-6`}>
        {/* Left: Scenario/What-If results + Decisions */}
        <div className="lg:col-span-8 flex flex-col gap-6">
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
              <p className="text-[11px] mt-3" style={{ color: colors.inkTertiary }}>
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
                          <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Rollback time</div>
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="text-[11px] uppercase tracking-wide font-semibold mb-2" style={{ color: colors.inkSubtle }}>Blast radius</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {[
                          { label: 'Rules affected', value: br.affected_rules ?? 0 },
                          { label: 'Skills affected', value: br.affected_skills ?? 0 },
                          { label: 'Departments', value: (br.affected_departments || []).length },
                        ].map(s => (
                          <div key={s.label} className="p-3 rounded-lg text-center" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                            <div className="text-[24px] font-bold">{s.value}</div>
                            <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
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
                                <span className="ml-auto text-[11px] font-bold uppercase" style={{ color: sevColor(String(r.severity).toUpperCase()) }}>{r.severity}</span>
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
                                <span className="px-1.5 py-0.5 rounded-full text-[11px] font-bold text-white" style={{ background: colors.primary }}>RECOMMENDED</span>
                              )}
                            </span>
                            <span className="font-bold font-mono" style={{ color: colors.primary }}>{opt.score?.total_score?.toFixed(1)} pts</span>
                          </div>
                          <div className="mb-2" style={{ color: colors.inkTertiary }}>{opt.option?.description}</div>
                          <div className="flex gap-4 font-mono text-[11px]">
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
            ) : activity ? (
              <div className="space-y-4">
                <div className="p-3 rounded border" style={{ borderColor: sevAccent(activity.severity) + '80', background: sevAccent(activity.severity) + '12' }}>
                  <div className="text-xs font-bold mb-1" style={{ color: sevAccent(activity.severity) }}>{activity.mode.toUpperCase()} IMPACT ({activity.severity} severity)</div>
                  <div className="text-sm">{activity.headline}</div>
                </div>
                {activity.items.length > 0 && (
                  <div>
                    <div className="text-xs font-bold mb-2" style={{ color: colors.inkSubtle }}>{activity.itemsLabel}</div>
                    <div className="space-y-2">
                      {activity.items.map((it, i) => (
                        <div key={i} className="p-3 border rounded text-xs" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                          <div className="flex justify-between gap-2 mb-1">
                            <span className="font-bold font-mono">{it.label}</span>
                            {it.right && <span className="font-bold font-mono flex-shrink-0" style={{ color: toneColor(it.tone) }}>{it.right}</span>}
                          </div>
                          {it.sub && <div style={{ color: colors.inkTertiary }}>{it.sub}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-sm italic flex h-full items-center justify-center opacity-50 py-8 text-center" style={{ color: colors.inkSubtle }}>
                {mode === 'shock' ? 'Awaiting shock injection…'
                  : mode === 'whatif' ? 'Run a what-if to see the governed verdict, blast radius, and ranked risks here.'
                  : mode === 'wargame' ? 'Run the wargame to see the resilience debrief and shock cascade here.'
                  : 'Pick a decision to replay, then run a counterfactual to see the impact here.'}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Provenance & Live Feed */}
        <div className="lg:col-span-4 flex flex-col gap-6">
          <div className="rounded-xl border shadow-sm p-4 overflow-y-auto" style={{ ...card, minHeight: 280 }}>
            <h2 className="text-sm font-bold uppercase mb-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <GitPullRequest className="w-4 h-4" /> Why Panel
            </h2>
            {decision ? (
              <div className="relative pl-4 border-l space-y-4 text-xs font-mono" style={{ borderColor: colors.primary }}>
                {[
                  ['Source Event', SHOCK_TYPES.find(s => s.value === shockType)?.label || humanize(shockType)],
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
            ) : activity ? (
              <div className="relative pl-4 border-l space-y-4 text-xs font-mono" style={{ borderColor: sevAccent(activity.severity) }}>
                {activity.why.map(([title, sub], i) => (
                  <div key={i} className="relative">
                    <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full" style={{ background: sevAccent(activity.severity) }} />
                    <div className="font-bold" style={{ color: colors.ink }}>{title}</div>
                    <div style={{ color: colors.inkTertiary }} className="break-words">{sub}</div>
                  </div>
                ))}
                <div className="relative">
                  <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: '#22c55e' }} />
                  <div className="font-bold text-green-500">{activity.mode === 'replay' ? 'Counterfactual Resolved' : 'Governed Outcome'}</div>
                  <div style={{ color: colors.inkTertiary }} className="break-words">{activity.final}</div>
                </div>
              </div>
            ) : (
              <div className="text-sm italic opacity-50" style={{ color: colors.inkSubtle }}>
                {mode === 'shock' ? 'Trace empty - run a shock to see the reasoning chain.'
                  : mode === 'whatif' ? 'Trace empty - run a what-if to see the reasoning chain.'
                  : mode === 'wargame' ? 'Trace empty - run the wargame to see the reasoning chain.'
                  : 'Trace empty - replay a decision to see the reasoning chain.'}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Reality Feed: a full-width event stream so it reads as a live ticker
          across the whole dashboard, not a cramped side rail. */}
      <div className={`${PAGE_PAD_X} pb-6`}>
        <div className="rounded-xl border shadow-sm p-4" style={card}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold uppercase flex items-center gap-2" style={{ color: colors.inkSubtle }}>
              <Activity className="w-4 h-4" /> Reality Feed
            </h2>
            <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{realityFeed.length} events</span>
          </div>
          {realityFeed.length === 0 ? (
            <div className="text-sm italic opacity-50 py-6 text-center" style={{ color: colors.inkSubtle }}>Listening to enterprise events…</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2 max-h-72 overflow-y-auto pr-1">
              {realityFeed.slice().reverse().map((f, i) => (
                <div key={i} className="text-xs p-3 rounded-lg border flex items-start gap-2.5" style={{ background: colors.canvas, borderColor: colors.hairline }}>
                  <span className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ background: colors.primary }} />
                  <div className="min-w-0 flex-1">
                    <div className="leading-snug break-words" style={{ color: colors.ink }}>{f.event}</div>
                    <div className="text-[11px] font-mono mt-1 truncate" style={{ color: colors.inkTertiary }}>{String(f.id).slice(0, 8)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
