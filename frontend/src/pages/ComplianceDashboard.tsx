import React, { useEffect, useState } from 'react';
import type { ComplianceDashboard as CDType } from '../api/client';
import { api } from '../api/client';
import { Shield, CheckCircle, AlertTriangle, XCircle, Check } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

const ComplianceDashboard = () => {
 const { colors } = useTheme();
 const [data, setData] = useState<CDType | null>(null);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);

 const load = () => {
  setError(null);
  api.getCompliance().then(d => { setData(d); setLoading(false); }).catch((e: any) => { setError(e?.message || 'Failed to load compliance data'); setLoading(false); });
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
       <h1 className="text-[24px] font-bold tracking-tight">Compliance Engine</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Regulatory policy enforcement</p>
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
   </div>
  </div>
 );
};

export default ComplianceDashboard;
