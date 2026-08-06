import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import {
 FlaskConical, Satellite, Users, Gauge, Zap, ScrollText,
 AlertTriangle, CheckCircle, TrendingUp,
 GitBranch, Radio, Scale,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { humanize, toPct } from '../lib/format';
import { BrainEmpty, BrainError, BrainLoading } from '../components/BrainStates';

/**
 * KAEOS Pioneer Lab — the consolidated surface for the advanced engines that
 * were fully built and e2e-tested but had no UI: external intelligence (P1),
 * org intelligence (P2), what-if simulation (L6), physics shocks + precog,
 * cross-org benchmark (L14), and the 10X engine ledgers.
 *
 * Every panel calls a real endpoint; nothing here is decorative. LLM-backed
 * actions run on the local model and can take a minute - each button carries
 * its own spinner so the rest of the lab stays usable.
 */

import {
  SIGNAL_TYPES, SEVERITIES, SHOCKS, LANES, riskColor, cleanReason,
  SectionTitle, ErrorBanner, ActionButton, Badge, LedgersLane,
} from './PioneerLab.parts';
import type { Lane } from './PioneerLab.parts';

const PioneerLab = () => {
 const { colors } = useTheme();
 const [lane, setLane] = useState<Lane>('intelligence');

 const card: React.CSSProperties = {
  background: colors.surface1,
  border: `1px solid ${colors.hairline}`,
  borderRadius: 12,
 };
 const inputStyle: React.CSSProperties = {
  background: colors.surface2,
  border: `1px solid ${colors.hairline}`,
  color: colors.ink,
  borderRadius: 8,
 };
 const labelCls = 'text-[11px] uppercase tracking-wide font-semibold';
 // ─── P1: External Intelligence ───────────────────────────────────
 const [signal, setSignal] = useState({
  signal_type: 'REGULATORY', source: '', title: '', content: '', severity: 'MEDIUM',
 });
 const [intelBusy, setIntelBusy] = useState<string | null>(null);
 const [intelError, setIntelError] = useState<string | null>(null);
 const [ingestResult, setIngestResult] = useState<any>(null);
 const [correlation, setCorrelation] = useState<any>(null);
 const [alertResult, setAlertResult] = useState<any>(null);

 const runIntel = async (action: 'ingest' | 'correlate' | 'alert') => {
  setIntelBusy(action); setIntelError(null);
  try {
   if (action === 'ingest') setIngestResult(await api.ingestSignal(signal));
   if (action === 'correlate') setCorrelation(await api.correlateSignal(signal.content));
   if (action === 'alert') setAlertResult(await api.generateProactiveAlert(signal));
  } catch (e: any) {
   setIntelError(e?.message || 'The intelligence engine could not process that signal');
  } finally {
   setIntelBusy(null);
  }
 };

 // ─── P2: Org Intelligence ────────────────────────────────────────
 const [topology, setTopology] = useState<any>(null);
 const [topoState, setTopoState] = useState<'loading' | 'ready' | 'error'>('loading');
 const [readinessForm, setReadinessForm] = useState({ department: '', change: '' });
 const [readiness, setReadiness] = useState<any>(null);
 const [influenceForm, setInfluenceForm] = useState({ outcome: '', department: '' });
 const [influence, setInfluence] = useState<any>(null);
 const [orgBusy, setOrgBusy] = useState<string | null>(null);
 const [orgError, setOrgError] = useState<string | null>(null);

 useEffect(() => {
  if (lane !== 'organization' || topology) return;
  setTopoState('loading');
  api.getSkillsTopology()
   .then(t => { setTopology(t); setTopoState('ready'); })
   .catch(() => setTopoState('error'));
 }, [lane, topology]);

 const runOrg = async (action: 'readiness' | 'influence') => {
  setOrgBusy(action); setOrgError(null);
  try {
   if (action === 'readiness') {
    setReadiness(await api.scoreChangeReadiness(readinessForm.department, readinessForm.change));
   } else {
    setInfluence(await api.mapInfluencePath(influenceForm.outcome, influenceForm.department));
   }
  } catch (e: any) {
   setOrgError(e?.message || 'The org intelligence engine could not complete that analysis');
  } finally {
   setOrgBusy(null);
  }
 };

 // ─── L6: Simulation + physics + precog ───────────────────────────
 const [simForm, setSimForm] = useState({ change: '', domain: 'all', tolerance: 'MEDIUM' });
 const [simResult, setSimResult] = useState<any>(null);
 const [shockType, setShockType] = useState(SHOCKS[0]);
 const [shockResult, setShockResult] = useState<any>(null);
 const [precogResult, setPrecogResult] = useState<any>(null);
 const [simBusy, setSimBusy] = useState<string | null>(null);
 const [simError, setSimError] = useState<string | null>(null);

 const runSim = async (action: 'whatif' | 'shock' | 'precog') => {
  setSimBusy(action); setSimError(null);
  try {
   if (action === 'whatif') setSimResult(await api.runSimulation(simForm.change, simForm.domain, simForm.tolerance));
   if (action === 'shock') setShockResult(await api.simulatePhysicsShock(shockType));
   if (action === 'precog') setPrecogResult(await api.forcePrecogCycle());
  } catch (e: any) {
   setSimError(e?.message || 'The simulation engine could not run that scenario');
  } finally {
   setSimBusy(null);
  }
 };

 // ─── L14: Benchmark ──────────────────────────────────────────────
 const [benchmark, setBenchmark] = useState<any>(null);
 const [benchState, setBenchState] = useState<'loading' | 'ready' | 'error'>('loading');
 const [report, setReport] = useState<any>(null);
 const [reportBusy, setReportBusy] = useState(false);
 const [benchError, setBenchError] = useState<string | null>(null);

 useEffect(() => {
  if (lane !== 'benchmark' || benchmark) return;
  setBenchState('loading');
  api.getBenchmark()
   .then(b => { setBenchmark(b); setBenchState('ready'); })
   .catch(() => setBenchState('error'));
 }, [lane, benchmark]);

 const runReport = async () => {
  setReportBusy(true); setBenchError(null);
  try {
   setReport(await api.getIntelligenceReport());
  } catch (e: any) {
   setBenchError(e?.message || 'The report engine is unavailable right now');
  } finally {
   setReportBusy(false);
  }
 };

 // ─── Engine ledgers ──────────────────────────────────────────────
 const [ledgers, setLedgers] = useState<any>(null);
 const [ledgerState, setLedgerState] = useState<'loading' | 'ready'>('loading');

 useEffect(() => {
  if (lane !== 'ledgers' || ledgers) return;
  setLedgerState('loading');
  Promise.allSettled([
   api.getQuantumEvents(), api.getRegulatoryRules(),
   api.getFederatedExports(), api.getPolymorphicEvents(),
   api.getPipelineConnectors(), api.getPipelineTransforms(),
  ]).then(([q, r, f, p, pc, pt]) => {
   setLedgers({
    quantum: q.status === 'fulfilled' ? q.value : [],
    regulatory: r.status === 'fulfilled' ? r.value : [],
    federated: f.status === 'fulfilled' ? f.value : [],
    polymorphic: p.status === 'fulfilled' ? p.value : [],
    connectors: pc.status === 'fulfilled' ? pc.value.connectors : [],
    transforms: pt.status === 'fulfilled' ? pt.value.nodes : [],
   });
   setLedgerState('ready');
  });
 }, [lane, ledgers]);

 return (
  <div className="h-full flex flex-col">
   <div className="p-6 pb-0">
    <div className="flex items-start justify-between flex-wrap gap-4">
     <div>
      <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2" style={{ color: colors.ink }}>
       <FlaskConical className="w-6 h-6" style={{ color: colors.primary }} />
       Pioneer Lab
      </h1>
      <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>
       Hands-on console for the advanced engines: feed signals, probe the org, simulate change, benchmark the enterprise
      </p>
     </div>
     <div className="flex gap-2 flex-wrap">
      {LANES.map(l => (
       <button
        key={l.key}
        onClick={() => setLane(l.key)}
        className="px-3 py-2 text-[12px] font-semibold rounded-lg transition-colors flex items-center gap-1.5"
        style={{
         background: lane === l.key ? colors.primary : colors.surface1,
         color: lane === l.key ? '#fff' : colors.ink,
         border: `1px solid ${lane === l.key ? colors.primary : colors.hairline}`,
        }}
       >
        <l.icon className="w-3.5 h-3.5" />
        {l.label}
       </button>
      ))}
     </div>
    </div>
   </div>

   <div className="flex-1 overflow-y-auto p-6 space-y-6">
    {lane === 'intelligence' && (
     <>
      <ErrorBanner message={intelError} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
       {/* Signal composer */}
       <div className="p-5 space-y-3" style={card}>
        <SectionTitle icon={Radio}>Feed an external signal</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
         <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Signal type</label>
          <select value={signal.signal_type}
           onChange={e => setSignal(s => ({ ...s, signal_type: e.target.value }))}
           className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle}>
           {SIGNAL_TYPES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
          </select>
         </div>
         <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Severity</label>
          <select value={signal.severity}
           onChange={e => setSignal(s => ({ ...s, severity: e.target.value }))}
           className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle}>
           {SEVERITIES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
          </select>
         </div>
        </div>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Source</label>
         <input value={signal.source} placeholder="e.g. EU Official Journal, vendor advisory, market feed"
          onChange={e => setSignal(s => ({ ...s, source: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
        </div>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Title</label>
         <input value={signal.title} placeholder="One line naming the signal"
          onChange={e => setSignal(s => ({ ...s, title: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
        </div>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>What happened</label>
         <textarea value={signal.content} rows={4}
          placeholder="Paste or describe the signal. The engine correlates it against your Company Brain."
          onChange={e => setSignal(s => ({ ...s, content: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px] resize-none" style={inputStyle} />
        </div>
        <div className="flex gap-2 flex-wrap">
         <ActionButton busy={intelBusy === 'correlate'} disabled={!signal.content.trim()}
          onClick={() => runIntel('correlate')}>Correlate with Brain</ActionButton>
         <ActionButton busy={intelBusy === 'alert'} disabled={!signal.content.trim()}
          onClick={() => runIntel('alert')}>Raise proactive alert</ActionButton>
         <ActionButton busy={intelBusy === 'ingest'}
          disabled={!signal.content.trim() || !signal.title.trim() || !signal.source.trim()}
          onClick={() => runIntel('ingest')}>Ingest into Brain</ActionButton>
        </div>
        {ingestResult && (
         <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.success }}>
          <CheckCircle className="w-4 h-4" />
          Signal recorded in the Brain as a {humanize(ingestResult.signal_type)} signal
         </div>
        )}
       </div>

       {/* Correlation / alert results */}
       <div className="space-y-4">
        {!correlation && !alertResult && (
         <div className="p-5" style={card}>
          <BrainEmpty title="No analysis yet." action="Describe a signal on the left, then correlate it or raise an alert." icon={Satellite} />
         </div>
        )}
        {[
         correlation && { heading: 'Brain correlation', data: correlation },
         alertResult && { heading: 'Proactive alert', data: alertResult.correlation, alert: alertResult },
        ].filter(Boolean).map((r: any) => {
         const c = r.data?.correlation || {};
         return (
          <div key={r.heading} className="p-5 space-y-3" style={card}>
           <div className="flex items-center justify-between gap-3">
            <SectionTitle icon={Satellite}>{r.heading}</SectionTitle>
            {r.alert && (
             <Badge tone={r.alert.alert_generated ? colors.warning : colors.success}>
              {r.alert.alert_generated ? 'Alert raised in the activity feed' : 'No alert needed'}
             </Badge>
            )}
           </div>
           {r.data?.status === 'FAILED' ? (
            <p className="text-[12px]" style={{ color: colors.error }}>
             The correlation engine could not analyze this signal. Try again once the model is responsive.
            </p>
           ) : (
            <>
             <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Risk level</span>
              <Badge tone={riskColor(c.risk_level, colors)}>{humanize(c.risk_level || 'unknown')}</Badge>
              {typeof c.urgency_hours === 'number' && (
               <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
                act within about {c.urgency_hours} hours
               </span>
              )}
             </div>
             {(c.impacted_domains || []).length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
               {(c.impacted_domains || []).map((d: string) => (
                <Badge key={d} tone={colors.primary}>{humanize(d)}</Badge>
               ))}
              </div>
             )}
             {(c.recommended_actions || []).length > 0 && (
              <ul className="space-y-1.5">
               {(c.recommended_actions || []).map((a: string, i: number) => (
                <li key={i} className="text-[12px] flex gap-2" style={{ color: colors.ink }}>
                 <span style={{ color: colors.primary }}>{i + 1}.</span>{a}
                </li>
               ))}
              </ul>
             )}
            </>
           )}
          </div>
         );
        })}
       </div>
      </div>
     </>
    )}

    {lane === 'organization' && (
     <>
      <ErrorBanner message={orgError} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
       {/* Change readiness */}
       <div className="p-5 space-y-3" style={card}>
        <SectionTitle icon={Gauge}>Score change readiness</SectionTitle>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Department</label>
         <input value={readinessForm.department} placeholder="e.g. Finance"
          onChange={e => setReadinessForm(f => ({ ...f, department: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
        </div>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Proposed change</label>
         <textarea value={readinessForm.change} rows={3}
          placeholder="What are you planning to change in this department?"
          onChange={e => setReadinessForm(f => ({ ...f, change: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px] resize-none" style={inputStyle} />
        </div>
        <ActionButton busy={orgBusy === 'readiness'}
         disabled={!readinessForm.department.trim() || !readinessForm.change.trim()}
         onClick={() => runOrg('readiness')}>Assess readiness</ActionButton>
        {readiness && (
         <div className="pt-3 space-y-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-4">
           <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Readiness</div>
            <div className="text-[26px] font-bold leading-none" style={{ color: colors.ink }}>
             {toPct(readiness.readiness_score) !== null ? `${Math.round(toPct(readiness.readiness_score)!)}%` : '-'}
            </div>
           </div>
           <Badge tone={riskColor(readiness.resistance_level, colors)}>
            {humanize(readiness.resistance_level || '')} resistance
           </Badge>
           {typeof readiness.estimated_adoption_weeks === 'number' && (
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
             about {readiness.estimated_adoption_weeks} weeks to adopt
            </span>
           )}
          </div>
          {(readiness.key_risks || []).length > 0 && (
           <div>
            <div className="text-[11px] uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>Key risks</div>
            {(readiness.key_risks || []).map((k: string, i: number) => (
             <div key={i} className="text-[12px] flex gap-2 items-start" style={{ color: colors.ink }}>
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: colors.warning }} />{k}
             </div>
            ))}
           </div>
          )}
          {(readiness.recommended_engagement_sequence || []).length > 0 && (
           <div>
            <div className="text-[11px] uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>How to bring people along</div>
            {(readiness.recommended_engagement_sequence || []).map((s: string, i: number) => (
             <div key={i} className="text-[12px] flex gap-2" style={{ color: colors.ink }}>
              <span style={{ color: colors.primary }}>{i + 1}.</span>{s}
             </div>
            ))}
           </div>
          )}
          {(readiness.champion_roles || []).length > 0 && (
           <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Champions to recruit</span>
            {(readiness.champion_roles || []).map((rle: string) => <Badge key={rle} tone={colors.primary}>{rle}</Badge>)}
           </div>
          )}
         </div>
        )}
       </div>

       {/* Influence path */}
       <div className="p-5 space-y-3" style={card}>
        <SectionTitle icon={GitBranch}>Plan an influence path</SectionTitle>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Target outcome</label>
         <input value={influenceForm.outcome} placeholder="e.g. Adopt automated invoice approval"
          onChange={e => setInfluenceForm(f => ({ ...f, outcome: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
        </div>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Department</label>
         <input value={influenceForm.department} placeholder="e.g. Finance"
          onChange={e => setInfluenceForm(f => ({ ...f, department: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
        </div>
        <ActionButton busy={orgBusy === 'influence'}
         disabled={!influenceForm.outcome.trim() || !influenceForm.department.trim()}
         onClick={() => runOrg('influence')}>Map the path</ActionButton>
        {influence && influence.status === 'MAPPED' && (
         <div className="pt-3 space-y-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          {typeof influence.critical_path_weeks === 'number' && (
           <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
            Critical path: about {influence.critical_path_weeks} weeks
           </div>
          )}
          {(influence.influence_path || []).map((s: any, i: number) => (
           <div key={i} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <div className="text-[12px] font-semibold" style={{ color: colors.ink }}>
             {s.step ?? i + 1}. {s.stakeholder_role}
            </div>
            <div className="text-[12px]" style={{ color: colors.inkSubtle }}>{s.action}</div>
            {s.expected_outcome && (
             <div className="text-[11px] mt-0.5" style={{ color: colors.success }}>Expected: {s.expected_outcome}</div>
            )}
           </div>
          ))}
         </div>
        )}
        {influence && influence.status === 'FAILED' && (
         <p className="text-[12px]" style={{ color: colors.error }}>
          The planner could not map this path. Try again once the model is responsive.
         </p>
        )}
       </div>
      </div>

      {/* Skills topology */}
      <div className="p-5" style={card}>
       <SectionTitle icon={Users}>Skills topology across departments</SectionTitle>
       {topoState === 'loading' && <BrainLoading message="Mapping who can do what, department by department…" />}
       {topoState === 'error' && <BrainError message="Could not load the skills topology" onRetry={() => { setTopology(null); setTopoState('loading'); api.getSkillsTopology().then(t => { setTopology(t); setTopoState('ready'); }).catch(() => setTopoState('error')); }} />}
       {topoState === 'ready' && Object.keys(topology?.topology || {}).length === 0 && (
        <BrainEmpty title="No employee records yet." action="Onboard employee data to see the capability map." icon={Users} />
       )}
       {topoState === 'ready' && Object.keys(topology?.topology || {}).length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
         {Object.entries(topology.topology).map(([dept, info]: [string, any]) => (
          <div key={dept} className="px-4 py-3 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
           <div className="flex items-center justify-between mb-2">
            <span className="text-[13px] font-semibold" style={{ color: colors.ink }}>{humanize(dept)}</span>
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{info.total} {info.total === 1 ? 'person' : 'people'}</span>
           </div>
           <div className="space-y-1">
            {Object.entries(info.roles || {}).map(([role, count]: [string, any]) => (
             <div key={role} className="flex items-center gap-2">
              <span className="text-[11px] w-28 truncate" title={role} style={{ color: colors.inkSubtle }}>{humanize(role)}</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
               <div className="h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, (count / Math.max(1, info.total)) * 100)}%`, background: colors.primary }} />
              </div>
              <span className="text-[11px] w-6 text-right" style={{ color: colors.ink }}>{count}</span>
             </div>
            ))}
           </div>
          </div>
         ))}
        </div>
       )}
      </div>
     </>
    )}

    {lane === 'simulation' && (
     <>
      <ErrorBanner message={simError} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
       {/* What-if */}
       <div className="p-5 space-y-3" style={card}>
        <SectionTitle icon={Zap}>What-if: simulate before you execute</SectionTitle>
        <div>
         <label className={labelCls} style={{ color: colors.inkSubtle }}>Proposed change</label>
         <textarea value={simForm.change} rows={3}
          placeholder="Describe the change you are considering. The blast radius comes from your real rules and skills, not a guess."
          onChange={e => setSimForm(f => ({ ...f, change: e.target.value }))}
          className="w-full mt-1 px-3 py-2 text-[12px] resize-none" style={inputStyle} />
        </div>
        <div className="grid grid-cols-2 gap-3">
         <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Target domain</label>
          <input value={simForm.domain} placeholder="all, or a domain like finance"
           onChange={e => setSimForm(f => ({ ...f, domain: e.target.value }))}
           className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle} />
         </div>
         <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Risk tolerance</label>
          <select value={simForm.tolerance}
           onChange={e => setSimForm(f => ({ ...f, tolerance: e.target.value }))}
           className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle}>
           {SEVERITIES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
          </select>
         </div>
        </div>
        <ActionButton busy={simBusy === 'whatif'} disabled={!simForm.change.trim()}
         onClick={() => runSim('whatif')}>Run the simulation</ActionButton>
        {simResult && (
         <div className="pt-3 space-y-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-3 flex-wrap">
           <Badge tone={simResult.simulation_result === 'SAFE' ? colors.success : simResult.simulation_result === 'BLOCKED' ? colors.error : colors.warning}>
            {humanize(simResult.simulation_result)}
           </Badge>
           <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
            rollback would take about {simResult.estimated_rollback_time_hours} hours
           </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
           {[
            { label: 'Rules in scope', value: simResult.blast_radius?.affected_rules ?? 0 },
            { label: 'Skills in scope', value: simResult.blast_radius?.affected_skills ?? 0 },
            { label: 'Departments', value: (simResult.blast_radius?.affected_departments || []).length },
           ].map(k => (
            <div key={k.label} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
             <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{k.label}</div>
             <div className="text-[18px] font-bold" style={{ color: colors.ink }}>{k.value}</div>
            </div>
           ))}
          </div>
          {(simResult.blast_radius?.affected_departments || []).length > 0 && (
           <div className="flex items-center gap-2 flex-wrap">
            {(simResult.blast_radius.affected_departments || []).map((d: string) => (
             <Badge key={d} tone={colors.primary}>{humanize(d)}</Badge>
            ))}
           </div>
          )}
          {(simResult.risk_factors || []).map((f: any, i: number) => (
           <div key={i} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
             <Badge tone={riskColor(f.severity, colors)}>{humanize(f.severity || '')}</Badge>
             <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>{f.factor}</span>
            </div>
            {f.mitigation && <div className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>Mitigation: {f.mitigation}</div>}
           </div>
          ))}
          {simResult.recommendation && (
           <p className="text-[12px]" style={{ color: colors.ink }}>{simResult.recommendation}</p>
          )}
         </div>
        )}
       </div>

       <div className="space-y-6">
        {/* Physics shock */}
        <div className="p-5 space-y-3" style={card}>
         <SectionTitle icon={Scale}>Stress-test with a macro shock</SectionTitle>
         <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
          Sends a macro-economic shock through the enterprise physics engine and traces the causal ripple across the twin.
         </p>
         <div className="flex gap-2 flex-wrap items-end">
          <div className="flex-1 min-w-[200px]">
           <label className={labelCls} style={{ color: colors.inkSubtle }}>Shock scenario</label>
           <select value={shockType} onChange={e => setShockType(e.target.value)}
            className="w-full mt-1 px-3 py-2 text-[12px]" style={inputStyle}>
            {SHOCKS.map(s => <option key={s} value={s}>{humanize(s)}</option>)}
           </select>
          </div>
          <ActionButton busy={simBusy === 'shock'} onClick={() => runSim('shock')}>Trigger shock</ActionButton>
         </div>
         {shockResult && (
          <div className="pt-3 space-y-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
           <div className="text-[12px]" style={{ color: colors.ink }}>
            <span className="font-semibold">{shockResult.nodes_affected}</span> impact paths traced for {humanize(shockResult.shock_type)}
           </div>
           <p className="text-[11px]" style={{ color: colors.inkSubtle }}>
            Modeled across industry archetypes by the physics engine, not measured from your tenant data.
           </p>
           <div className="max-h-48 overflow-y-auto space-y-1 pr-1">
            {(shockResult.ripple_effect || []).map((n: any, i: number) => (
             <div key={i} className="flex items-center justify-between gap-2 text-[11px] px-2 py-1.5 rounded" style={{ background: colors.surface2 }}>
              <span className="truncate" style={{ color: colors.ink }}>
               {humanize(n.enterprise_type)}: {humanize(n.feature)}
              </span>
              <span className="whitespace-nowrap" style={{ color: colors.inkSubtle }}>
               {typeof n.control_mean === 'number' && typeof n.intervention_mean === 'number'
                ? `${n.control_mean.toFixed(1)} to ${n.intervention_mean.toFixed(1)}`
                : ''}
              </span>
              {n.significant && <Badge tone={colors.warning}>Significant</Badge>}
             </div>
            ))}
           </div>
          </div>
         )}
        </div>

        {/* Precog */}
        <div className="p-5 space-y-3" style={card}>
         <SectionTitle icon={Radio}>Force a precog cycle</SectionTitle>
         <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
          Makes the precog engine scan for macro signals right now instead of waiting for its scheduled sweep.
         </p>
         <ActionButton busy={simBusy === 'precog'} onClick={() => runSim('precog')}>Scan for signals now</ActionButton>
         {precogResult && (
          <div className="flex items-start gap-2 text-[12px]" style={{ color: precogResult.status === 'PROCESSED' ? colors.success : colors.inkSubtle }}>
           <CheckCircle className="w-4 h-4 mt-0.5 shrink-0" />
           {precogResult.status === 'PROCESSED'
            ? `Signal processed: ${precogResult.signal}`
            : 'No new macro signals detected right now.'}
          </div>
         )}
        </div>
       </div>
      </div>
     </>
    )}

    {lane === 'benchmark' && (
     <>
      <ErrorBanner message={benchError} />
      {benchState === 'loading' && <BrainLoading message="Comparing your enterprise against the network…" />}
      {benchState === 'error' && <BrainError message="Could not load the benchmark" onRetry={() => { setBenchmark(null); setBenchState('loading'); api.getBenchmark().then(b => { setBenchmark(b); setBenchState('ready'); }).catch(() => setBenchState('error')); }} />}
      {benchState === 'ready' && benchmark && (
       <>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
         {[
          { key: 'kb_coverage_pct', label: 'Knowledge coverage', suffix: '%' },
          { key: 'agent_autonomy_pct', label: 'Agent autonomy', suffix: '%' },
          { key: 'time_to_onboard_days', label: 'Days to onboard', suffix: '' },
          { key: 'active_skills', label: 'Active skills', suffix: '' },
         ].map(m => (
          <div key={m.key} className="p-4" style={card}>
           <div className="text-[11px] uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>{m.label}</div>
           <div className="text-[24px] font-bold" style={{ color: colors.ink }}>
            {benchmark.local_org?.[m.key] ?? '-'}{m.suffix}
           </div>
           <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
            median {benchmark.industry_median?.[m.key] ?? '-'}{m.suffix}, top quartile {benchmark.top_quartile?.[m.key] ?? '-'}{m.suffix}
           </div>
          </div>
         ))}
        </div>

        {(benchmark.department_benchmarks || []).length > 0 && (
         <div className="p-5" style={card}>
          <SectionTitle icon={TrendingUp}>Department standing</SectionTitle>
          <div className="space-y-2">
           {benchmark.department_benchmarks.map((d: any) => (
            <div key={d.department} className="flex items-center gap-3">
             <span className="text-[12px] w-32 truncate" style={{ color: colors.ink }}>{humanize(d.department)}</span>
             <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
              <div className="h-full rounded-full transition-all duration-500"
               style={{ width: `${Math.min(100, d.local_coverage ?? 0)}%`, background: d.status === 'LEADER' ? colors.success : colors.warning }} />
             </div>
             <span className="text-[11px] w-20 text-right" style={{ color: colors.inkSubtle }}>
              {d.local_coverage}% vs {d.industry_median}%
             </span>
             <Badge tone={d.status === 'LEADER' ? colors.success : colors.warning}>
              {d.status === 'LEADER' ? 'Leading' : 'Lagging'}
             </Badge>
            </div>
           ))}
          </div>
         </div>
        )}

        <div className="p-5 space-y-3" style={card}>
         <div className="flex items-center justify-between gap-3 flex-wrap">
          <SectionTitle icon={ScrollText}>Maturity intelligence report</SectionTitle>
          <ActionButton busy={reportBusy} onClick={runReport}>
           {report ? 'Regenerate report' : 'Generate report'}
          </ActionButton>
         </div>
         {!report && !reportBusy && (
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
           A model-written maturity assessment built from your real rule and skill counts. Takes a minute on the local model.
          </p>
         )}
         {report && (
          <div className="space-y-3">
           <div className="flex items-center gap-3 flex-wrap">
            <div className="text-[26px] font-bold" style={{ color: colors.ink }}>
             {report.report?.maturity_score ?? 0}<span className="text-[13px] font-normal" style={{ color: colors.inkSubtle }}> / 100</span>
            </div>
            <Badge tone={colors.primary}>{humanize(report.report?.maturity_tier || '')}</Badge>
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
             from {report.org_snapshot?.total_rules ?? 0} rules and {report.org_snapshot?.total_skills ?? 0} skills on record
            </span>
           </div>
           {report.report?.executive_summary && (
            <p className="text-[12px] leading-relaxed" style={{ color: colors.ink }}>{report.report.executive_summary}</p>
           )}
           <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
             { title: 'Strengths', items: report.report?.strengths || [], tone: colors.success },
             { title: 'Gaps', items: report.report?.gaps || [], tone: colors.warning },
            ].map(col => col.items.length > 0 && (
             <div key={col.title}>
              <div className="text-[11px] uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>{col.title}</div>
              {col.items.map((s: string, i: number) => (
               <div key={i} className="text-[12px] flex gap-2 items-start" style={{ color: colors.ink }}>
                <span className="mt-1 w-1.5 h-1.5 rounded-full shrink-0" style={{ background: col.tone }} />{s}
               </div>
              ))}
             </div>
            ))}
           </div>
           {(report.report?.recommendations || []).map((r: any, i: number) => (
            <div key={i} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
             <div className="flex items-center gap-2">
              <Badge tone={riskColor(r.priority, colors)}>{humanize(r.priority || '')} priority</Badge>
              <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>{r.action}</span>
             </div>
             {r.impact && <div className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>{r.impact}</div>}
            </div>
           ))}
          </div>
         )}
        </div>
       </>
      )}
     </>
    )}

    {lane === 'ledgers' && <LedgersLane ledgers={ledgers} ledgerState={ledgerState} />}
   </div>
  </div>
 );
};

export default PioneerLab;
