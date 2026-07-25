import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import {
 Radar, ShieldAlert, TrendingUp, Target, Loader2, CheckCircle,
 AlertTriangle, Clock, UserCheck, Activity,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

/**
 * KAEOS Foresight — the autonomous, prescriptive reality lane.
 *
 * Shock / What-if / Wargame / Replay are REACTIVE: a human poses a premise and
 * watches the twin respond, which assumes the executive already knows what to
 * ask. Foresight inverts that. It sweeps the whole shock catalogue against the
 * live twin with no prompt and answers the two questions a CXO actually has:
 *   1. Pre-Mortem Radar        — what should I worry about, ranked by exposure?
 *   2. Prescriptive Trajectory — what will KAEOS do on its own, and where does
 *                                it still need me?
 */

const exposureColor = (exposure: number, colors: any) =>
 exposure >= 0.25 ? colors.error : exposure >= 0.1 ? colors.warning : colors.success;

const pct = (v: number | null | undefined) =>
 v === null || v === undefined ? '-' : `${Math.round(v * 100)}%`;

const Foresight = () => {
 const { colors } = useTheme();
 const [lane, setLane] = useState<'radar' | 'trajectory'>('radar');
 const [radar, setRadar] = useState<any>(null);
 const [traj, setTraj] = useState<any>(null);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [commissioning, setCommissioning] = useState<string | null>(null);
 const [commissioned, setCommissioned] = useState<Record<string, string>>({});

 const load = () => {
  setError(null);
  Promise.all([api.getPremortemRadar(90, 8), api.getForesightTrajectory(45)])
   .then(([r, t]) => { setRadar(r); setTraj(t); setLoading(false); })
   .catch((e: any) => { setError(e?.message || 'Failed to load Foresight'); setLoading(false); });
 };

 useEffect(() => { load(); }, []);

 const commission = async (scenario: string) => {
  setCommissioning(scenario);
  try {
   const res = await api.commissionGapCloser(scenario);
   setCommissioned(prev => ({ ...prev, [scenario]: res.mission_id }));
   const r = await api.getPremortemRadar(90, 8);
   setRadar(r);
  } catch (e: any) {
   setError(e?.message || 'Could not commission the mission');
  } finally {
   setCommissioning(null);
  }
 };

 if (loading) return <BrainLoading message="Sweeping the threat space against the live twin…" />;
 if (error && !radar) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

 const card = {
  background: colors.surface1,
  border: `1px solid ${colors.hairline}`,
  borderRadius: 12,
 };

 const totals = radar?.totals || {};
 const scenarios = radar?.scenarios || [];

 return (
  <div className="p-6 space-y-6">
   {/* Header */}
   <div className="flex items-start justify-between flex-wrap gap-4">
    <div>
     <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2" style={{ color: colors.ink }}>
      <Radar className="w-6 h-6" style={{ color: colors.primary }} />
      Foresight
     </h1>
     <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>
      Autonomous and prescriptive: KAEOS proposes what to worry about, you decide what to do
     </p>
    </div>
    <div className="flex gap-2">
     {(['radar', 'trajectory'] as const).map(k => (
      <button
       key={k}
       onClick={() => setLane(k)}
       className="px-4 py-2 text-[12px] font-semibold rounded-lg transition-colors"
       style={{
        background: lane === k ? colors.primary : colors.surface1,
        color: lane === k ? '#fff' : colors.ink,
        border: `1px solid ${lane === k ? colors.primary : colors.hairline}`,
       }}
      >
       {k === 'radar' ? 'Pre-Mortem Radar' : 'Prescriptive Trajectory'}
      </button>
     ))}
    </div>
   </div>

   {error && (
    <div className="px-4 py-3 rounded-lg text-[12px]" style={{ background: `${colors.error}15`, color: colors.error }}>
     {error}
    </div>
   )}

   {lane === 'radar' ? (
    <>
     {/* Exposure summary */}
     <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {[
       { label: 'Scenarios scored', value: totals.scenarios_scored ?? 0, icon: Target, color: colors.primary },
       { label: 'No governed response', value: totals.uncovered ?? 0, icon: ShieldAlert, color: colors.error },
       { label: 'Twin entities', value: totals.twin_nodes ?? 0, icon: Activity, color: colors.info },
       { label: 'Signals considered', value: totals.signals_considered ?? 0, icon: TrendingUp, color: colors.success },
      ].map(k => (
       <div key={k.label} className="p-4" style={card}>
        <div className="flex items-center gap-2 mb-1">
         <k.icon className="w-4 h-4" style={{ color: k.color }} />
         <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{k.label}</span>
        </div>
        <div className="text-[24px] font-bold" style={{ color: colors.ink }}>{k.value}</div>
       </div>
      ))}
     </div>

     {/* Method — the honesty contract, stated in the UI */}
     <div className="px-4 py-3 rounded-lg text-[11px] leading-relaxed" style={{ background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
      {radar?.method}
     </div>

     {/* Ranked scenarios */}
     {scenarios.length === 0 ? (
      <BrainEmpty title="No scenarios scored yet." action="Build the enterprise twin to run a pre-mortem." icon={Radar} />
     ) : (
      <div className="space-y-3">
       {scenarios.map((s: any) => {
        const accent = exposureColor(s.exposure, colors);
        const done = commissioned[s.scenario];
        return (
         <div key={s.scenario} className="p-5" style={{ ...card, borderLeft: `3px solid ${accent}` }}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
           <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
             <h3 className="text-[15px] font-semibold" style={{ color: colors.ink }}>{s.title}</h3>
             {s.is_inevitable_surprise && (
              <span className="px-2 py-0.5 text-[10px] font-semibold rounded" style={{ background: `${colors.error}20`, color: colors.error }}>
               INEVITABLE SURPRISE
              </span>
             )}
            </div>
            <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>
             {s.governed_responses > 0
              ? `${s.governed_responses} governed response(s) on record`
              : 'No governed, tested response exists for this scenario'}
             {s.entities_in_cascade > 0 && ` - cascade reaches ${s.entities_in_cascade} connected entities`}
             {s.epicentre && ` from ${s.epicentre}`}
            </p>
           </div>
           <div className="text-right">
            <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Exposure</div>
            <div className="text-[26px] font-bold leading-none" style={{ color: accent }}>{s.exposure.toFixed(3)}</div>
           </div>
          </div>

          {/* The three factors, shown so the score is never a black box */}
          <div className="grid grid-cols-3 gap-3 mt-4">
           {[
            { label: 'Likelihood', value: pct(s.likelihood), hint: `${s.evidence?.signal_matches ?? 0} signal matches, ${s.evidence?.prior_shocks ?? 0} prior shocks` },
            { label: 'Blast radius', value: pct(s.blast_radius), hint: `${s.entities_in_cascade} entities in cascade` },
            { label: 'Preparedness gap', value: pct(s.preparedness_gap), hint: `${s.governed_responses} governed response(s)` },
           ].map(f => (
            <div key={f.label} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
             <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{f.label}</div>
             <div className="text-[16px] font-semibold" style={{ color: colors.ink }}>{f.value}</div>
             <div className="text-[10px] mt-0.5 truncate" style={{ color: colors.inkSubtle }} title={f.hint}>{f.hint}</div>
            </div>
           ))}
          </div>

          {/* Gap-closer: drafts a mission, a human approves it */}
          <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
           <p className="text-[11px] flex-1 min-w-0" style={{ color: colors.inkSubtle }}>
            {s.recommended_mission?.goal}
           </p>
           {done ? (
            <span className="flex items-center gap-1.5 text-[12px] font-semibold" style={{ color: colors.success }}>
             <CheckCircle className="w-4 h-4" /> Mission drafted for approval
            </span>
           ) : (
            <button
             onClick={() => commission(s.scenario)}
             disabled={commissioning === s.scenario}
             className="px-4 py-2 text-[12px] font-semibold rounded-lg whitespace-nowrap flex items-center gap-2"
             style={{ background: colors.primary, color: '#fff', opacity: commissioning === s.scenario ? 0.6 : 1 }}
            >
             {commissioning === s.scenario
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Drafting…</>
              : <>Commission a mission</>}
            </button>
           )}
          </div>
         </div>
        );
       })}
      </div>
     )}
    </>
   ) : (
    <>
     {/* North star */}
     <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="p-5" style={card}>
       <div className="flex items-center gap-2 mb-1">
        <TrendingUp className="w-4 h-4" style={{ color: colors.success }} />
        <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Safe-autonomy rate</span>
       </div>
       <div className="text-[28px] font-bold" style={{ color: colors.ink }}>
        {pct(traj?.north_star?.current)}
       </div>
       <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
        over the last {traj?.north_star?.window_days ?? 45} days
       </div>
      </div>
      <div className="p-5" style={card}>
       <div className="flex items-center gap-2 mb-1">
        <Activity className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Missions in flight</span>
       </div>
       <div className="text-[28px] font-bold" style={{ color: colors.ink }}>{traj?.totals?.missions_in_flight ?? 0}</div>
      </div>
      <div className="p-5" style={card}>
       <div className="flex items-center gap-2 mb-1">
        <UserCheck className="w-4 h-4" style={{ color: colors.warning }} />
        <span className="text-[11px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Awaiting your decision</span>
       </div>
       <div className="text-[28px] font-bold" style={{ color: colors.ink }}>{traj?.totals?.decisions_awaiting_human ?? 0}</div>
      </div>
     </div>

     {/* Horizons */}
     <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {(['30d', '60d', '90d'] as const).map(h => {
       const bucket = traj?.horizons?.[h];
       return (
        <div key={h} className="p-5" style={card}>
         <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4" style={{ color: colors.primary }} />
          <h3 className="text-[13px] font-semibold" style={{ color: colors.ink }}>Next {bucket?.horizon_days ?? h}</h3>
         </div>
         <div className="text-[22px] font-bold mb-2" style={{ color: colors.ink }}>
          {bucket?.autonomous_actions_projected ?? 0}
         </div>
         <div className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>autonomous actions projected</div>
         <div className="space-y-2">
          {(bucket?.missions || []).slice(0, 4).map((m: any) => (
           <div key={m.id} className="text-[11px] truncate" style={{ color: colors.inkSubtle }} title={m.goal}>
            <span className="font-semibold" style={{ color: colors.ink }}>{m.status}</span> {m.goal}
           </div>
          ))}
          {(bucket?.missions || []).length === 0 && (
           <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Nothing committed in this window.</div>
          )}
         </div>
        </div>
       );
      })}
     </div>

     {/* Decision points */}
     <div className="p-5" style={card}>
      <h3 className="text-[13px] font-semibold flex items-center gap-2 mb-3" style={{ color: colors.ink }}>
       <AlertTriangle className="w-4 h-4" style={{ color: colors.warning }} />
       Where KAEOS will need you
      </h3>
      {(traj?.human_decision_points || []).length === 0 ? (
       <BrainEmpty title="No decisions are waiting on you." action="Gated steps and HITL approvals appear here." icon={UserCheck} />
      ) : (
       <div className="space-y-2">
        {traj.human_decision_points.map((d: any, i: number) => (
         <div key={i} className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg" style={{ border: `1px solid ${colors.hairline}` }}>
          <span className="text-[12px] truncate" style={{ color: colors.ink }}>
           {d.kind === 'mission_step' ? `${d.name} (mission step ${d.seq})` : (d.skill || 'Pending approval')}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded whitespace-nowrap" style={{ background: `${colors.warning}20`, color: colors.warning }}>
           {d.kind === 'mission_step' ? d.department || 'mission' : 'HITL'}
          </span>
         </div>
        ))}
       </div>
      )}
     </div>

     <div className="px-4 py-3 rounded-lg text-[11px] leading-relaxed" style={{ background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
      {traj?.method}
     </div>
    </>
   )}
  </div>
 );
};

export default Foresight;
