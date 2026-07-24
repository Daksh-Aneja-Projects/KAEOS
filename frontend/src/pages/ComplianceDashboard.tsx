import React, { useEffect, useState } from 'react';
import type { ComplianceDashboard as CDType } from '../api/client';
import { api } from '../api/client';
import { Shield, CheckCircle, AlertTriangle, XCircle, Check, ShieldAlert, FileCheck, Gauge, Loader2 } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

const TIER_COLOR: Record<string, string> = { HIGH: '#ef4444', LIMITED: '#f59e0b', MINIMAL: '#22c55e' };

const ComplianceDashboard = () => {
 const { colors } = useTheme();
 const [data, setData] = useState<CDType | null>(null);
 const [reg, setReg] = useState<any>(null);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [evidence, setEvidence] = useState<any>(null);
 const [evLoading, setEvLoading] = useState<string | null>(null);

 const load = () => {
  setError(null);
  Promise.all([api.getCompliance(), api.getRegulatoryOverview(30)])
   .then(([c, r]) => { setData(c); setReg(r); setLoading(false); })
   .catch((e: any) => { setError(e?.message || 'Failed to load compliance data'); setLoading(false); });
 };

 const genEvidence = async (framework: string) => {
  setEvLoading(framework);
  try { setEvidence(await api.getRegulatoryEvidence(framework, 90)); }
  catch (e) { console.error(e); }
  finally { setEvLoading(null); }
 };

 useEffect(() => {
  load();
 }, []);

 if (loading) return <BrainLoading message="Loading the Compliance Engine…" />;
 if (error) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;
 if (!data) return <BrainError message="Failed to load compliance data." onRetry={() => { setLoading(true); load(); }} />;

 const statusIcon = (s: string) => s === 'COMPLIANT'
   ? <CheckCircle className="w-5 h-5" style={{ color: colors.success }} />
   : s === 'REVIEW'
     ? <AlertTriangle className="w-5 h-5" style={{ color: colors.warning }} />
     : <XCircle className="w-5 h-5" style={{ color: colors.inkSubtle }} />;

 const statusAccent = (s: string) => s === 'COMPLIANT' ? colors.success : s === 'REVIEW' ? colors.warning : colors.hairline;

 const statusBadgeStyle = (s: string): React.CSSProperties => s === 'COMPLIANT'
   ? { background: colors.success + '1f', color: colors.success }
   : s === 'REVIEW'
     ? { background: colors.warning + '1f', color: colors.warning }
     : { background: colors.surface2, color: colors.inkSubtle };

 const card: React.CSSProperties = {
  background: colors.surface1, borderRadius: '14px',
 };

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    {/* Header */}
    <div className="flex items-start justify-between gap-4 flex-wrap">
     <div className="flex items-start gap-3">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
       <Shield className="w-6 h-6 text-white" />
      </div>
      <div>
       <h1 className="text-[24px] font-bold tracking-tight">Compliance &amp; Regulatory Autopilot</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Framework coverage, per-agent risk register, live monitor, and one-click evidence</p>
      </div>
     </div>
     <div className="flex gap-3">
      <div className="px-4 py-2 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
       <div className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>Tagged Rules</div>
       <div className="text-[20px] font-bold tabular-nums" style={{ color: colors.ink }}>{data.total_tagged_rules}</div>
      </div>
      <div className="px-4 py-2 rounded-xl" style={{ background: colors.warning + '14', border: `1px solid ${colors.warning}33` }}>
       <div className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: colors.warning }}>Untagged</div>
       <div className="text-[20px] font-bold tabular-nums" style={{ color: colors.warning }}>{data.untagged_rules}</div>
      </div>
     </div>
    </div>

    {data.frameworks.length === 0 ? (
     <BrainEmpty title="No compliance frameworks tracked yet" action="Tag rules with a framework to see coverage here." icon={Shield} />
    ) : (
     <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.frameworks.map(fw => (
       <div key={fw.framework} className="p-6" style={{ ...card, border: `1px solid ${statusAccent(fw.status)}${fw.status === 'COMPLIANT' || fw.status === 'REVIEW' ? '55' : ''}` }}>
        <div className="flex items-center justify-between mb-4 gap-2">
         <div className="flex items-center gap-3 min-w-0">
          {statusIcon(fw.status)}
          <h3 className="text-[16px] font-semibold truncate" style={{ color: colors.ink }}>{fw.framework}</h3>
         </div>
         <span className="px-2 py-0.5 rounded text-[11px] font-medium shrink-0" style={statusBadgeStyle(fw.status)}>{fw.status.replace('_', ' ')}</span>
        </div>
        <div className="space-y-3">
         <div>
          <div className="flex justify-between text-[13px] mb-1">
           <span style={{ color: colors.inkSubtle }}>Coverage</span>
           <span className="tabular-nums font-semibold" style={{ color: colors.ink }}>{Math.round(fw.coverage_pct * 100)}%</span>
          </div>
          <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
           <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, Math.round(fw.coverage_pct * 100))}%`, background: fw.coverage_pct >= 0.8 ? colors.success : colors.warning }}></div>
          </div>
         </div>
         <div className="flex justify-between text-[13px]">
          <span style={{ color: colors.inkSubtle }}>Violations</span>
          <span className="flex items-center gap-1 font-medium" style={{ color: fw.violations > 0 ? colors.error : colors.success }}>
           {fw.violations} {fw.violations === 0 ? <Check className="w-3.5 h-3.5" /> : 'blockers'}
          </span>
         </div>
         <div className="flex justify-between text-[13px]">
          <span style={{ color: colors.inkSubtle }}>Last Audit</span>
          <span style={{ color: colors.inkMuted }}>{fw.last_audit || 'N/A'}</span>
         </div>
        </div>
       </div>
      ))}
     </div>
    )}

    {/* ── Regulatory Autopilot ── */}
    {reg && (
     <>
      {/* Risk summary + live monitor */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
       {([['HIGH', reg.risk_summary?.HIGH ?? 0], ['LIMITED', reg.risk_summary?.LIMITED ?? 0], ['MINIMAL', reg.risk_summary?.MINIMAL ?? 0]] as const).map(([tier, n]) => (
        <div key={tier} className="p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
         <div className="text-[22px] font-bold" style={{ color: TIER_COLOR[tier] }}>{n}</div>
         <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{tier} risk</div>
        </div>
       ))}
       {([['compliance_blocks', 'Blocks'], ['audit_failures', 'Audit fails'], ['human_overrides', 'Overrides']] as const).map(([k, label]) => (
        <div key={k} className="p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
         <div className="text-[22px] font-bold" style={{ color: (reg.monitor?.[k] ?? 0) > 0 ? colors.warning : colors.ink }}>{reg.monitor?.[k] ?? 0}</div>
         <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{label} (30d)</div>
        </div>
       ))}
      </div>

      {/* Per-agent risk register (EU AI Act style) */}
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
       <div className="px-5 py-3 border-b flex items-center gap-2" style={{ borderColor: colors.hairline }}>
        <ShieldAlert className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[14px] font-medium">Agent Risk Register</span>
        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>EU-AI-Act-style classification of every deployed skill</span>
       </div>
       <div className="overflow-x-auto">
        <div className="min-w-[720px]">
         <div className="grid grid-cols-[1.4fr_0.8fr_1.2fr_0.7fr_0.8fr] gap-3 px-5 py-2 text-[11px] uppercase tracking-wider font-semibold"
           style={{ background: colors.surface2, color: colors.inkSubtle }}>
          <span>Skill</span><span>Department</span><span>Frameworks</span><span>Autonomy</span><span>Risk tier</span>
         </div>
         {(reg.risk_register || []).slice(0, 20).map((r: any) => (
          <div key={r.skill_id} className="grid grid-cols-[1.4fr_0.8fr_1.2fr_0.7fr_0.8fr] gap-3 px-5 py-2.5 items-center border-b" style={{ borderColor: colors.hairline }}>
           <span className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>
            {r.high_consequence && <span title="high-consequence" style={{ color: colors.warning }}>▲ </span>}{r.skill_id}
           </span>
           <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{r.department}</span>
           <span className="text-[11px] truncate" style={{ color: colors.inkSubtle }}>{(r.frameworks || []).join(', ') || '—'}</span>
           <span className="text-[12px] font-mono" style={{ color: colors.ink }}>{(r.autonomy * 100).toFixed(0)}%</span>
           <span className="text-[10px] font-bold px-2 py-0.5 rounded-full w-fit" style={{ background: TIER_COLOR[r.risk_tier] + '22', color: TIER_COLOR[r.risk_tier] }}>{r.risk_tier}</span>
          </div>
         ))}
        </div>
       </div>
      </div>

      {/* Evidence packs */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
       <div className="flex items-center gap-2 mb-3">
        <FileCheck className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[14px] font-medium">Audit Evidence Packs</span>
        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>assembled live from the provenance + actions ledgers</span>
       </div>
       <div className="flex gap-2 flex-wrap">
        {(reg.frameworks || []).map((fw: any) => (
         <button key={fw.framework} onClick={() => genEvidence(fw.framework)} disabled={evLoading === fw.framework}
           className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium"
           style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
          {evLoading === fw.framework ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Gauge className="w-3.5 h-3.5" style={{ color: colors.primary }} />}
          {fw.framework} <span style={{ color: colors.inkSubtle }}>({fw.controls})</span>
         </button>
        ))}
        {(reg.frameworks || []).length === 0 && <span className="text-[12px]" style={{ color: colors.inkTertiary }}>No framework-tagged controls yet.</span>}
       </div>
       {evidence && (
        <div className="mt-4 p-4 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
         <div className="flex items-center justify-between mb-2">
          <span className="text-[13px] font-semibold">{evidence.framework} evidence pack</span>
          <span className="text-[10px]" style={{ color: colors.inkSubtle }}>{evidence.scope} · {evidence.window_days}d window</span>
         </div>
         <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {([['control_count', 'Controls'], ['control_executions', 'Control runs'], ['provenance_entries', 'Ledger entries'], ['actions_recorded', 'Actions']] as const).map(([k, label]) => (
           <div key={k} className="text-center p-2 rounded-lg" style={{ background: colors.surface1 }}>
            <div className="text-[18px] font-bold" style={{ color: colors.ink }}>{evidence[k] ?? 0}</div>
            <div className="text-[9px]" style={{ color: colors.inkSubtle }}>{label}</div>
           </div>
          ))}
         </div>
         <div className="text-[10px] mt-2" style={{ color: evidence.complete ? colors.success : colors.warning }}>
          {evidence.complete ? '✓ Evidence assembled from real ledger rows' : 'No controls carry this framework tag yet'} · generated {evidence.generated_at ? new Date(evidence.generated_at).toLocaleString() : ''}
         </div>
        </div>
       )}
      </div>
     </>
    )}
   </div>
  </div>
 );
};

export default ComplianceDashboard;
