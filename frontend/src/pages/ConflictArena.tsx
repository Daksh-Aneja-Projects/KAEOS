import React, { useEffect, useState } from 'react';
import type { ConflictItem } from '../api/client';
import { api } from '../api/client';
import { Swords, AlertTriangle, CheckCircle, Clock } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';

const ConflictArena = () => {
 const { colors } = useTheme();
 const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
 const [openCount, setOpenCount] = useState(0);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);

 const load = () => {
  setError(null);
  api.getConflicts().then(d => { setConflicts(d.conflicts); setOpenCount(d.open_count); setLoading(false); }).catch((e: any) => { setError(e?.message || 'Failed to load conflicts'); setLoading(false); });
 };
 useEffect(load, []);

 const handleResolve = async (id: string, type: string) => {
  await api.resolveConflict(id, type, `Resolved via ${type}`);
  load();
 };

 const sevStyle = (s: string): React.CSSProperties => {
  const c = s === 'CRITICAL' ? colors.error : s === 'MODERATE' ? colors.warning : colors.info;
  return { color: c, background: c + '1a', border: `1px solid ${c}33` };
 };
 const statusIcon = (s: string) => s === 'RESOLVED'
  ? <CheckCircle className="w-4 h-4" style={{ color: colors.success }} />
  : s === 'IN_REVIEW'
   ? <Clock className="w-4 h-4" style={{ color: colors.warning }} />
   : <AlertTriangle className="w-4 h-4" style={{ color: colors.error }} />;

 const card: React.CSSProperties = {
  background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: '14px',
 };

 if (loading) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainLoading message="Loading conflicts…" />
  </div>
 );
 if (error) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainError message={error} onRetry={load} />
  </div>
 );

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    {/* Header */}
    <div className="flex items-start justify-between gap-4 flex-wrap pb-5" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
     <div className="flex items-start gap-3">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
       style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
       <Swords className="w-6 h-6 text-white" />
      </div>
      <div>
       <h1 className="text-[24px] font-bold tracking-tight">Conflict Resolution Arena</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Structured async debate and resolution</p>
      </div>
     </div>
     <div className="px-4 py-2 rounded-xl" style={{ background: colors.error + '14', border: `1px solid ${colors.error}33` }}>
      <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.error }}>Open Conflicts</div>
      <div className="text-2xl font-bold tracking-tight tabular-nums" style={{ color: colors.error }}>{openCount}</div>
     </div>
    </div>

    {conflicts.length === 0 ? (
     <BrainEmpty title="No conflicts to resolve" action="The Brain hasn't detected any contradictory rules yet." icon={Swords} />
    ) : (
     <div className="space-y-4">
      {conflicts.map(c => (
       <div key={c.id} style={{ ...card, ...(c.status === 'RESOLVED' ? { borderColor: colors.success + '55', opacity: 0.75 } : {}) }} className="p-6">
        <div className="flex items-center justify-between mb-4">
         <div className="flex items-center gap-3">
          {statusIcon(c.status)}
          <span className="px-2 py-0.5 rounded text-xs font-medium" style={sevStyle(c.severity)}>{c.severity}</span>
          <span className="text-xs" style={{ color: colors.inkSubtle }}>{c.conflict_type.replace(/_/g, ' ')}</span>
         </div>
         <div className="flex items-center gap-3 text-xs" style={{ color: colors.inkSubtle }}>
          {c.assigned_to && <span>Assigned: <span style={{ color: colors.ink }}>{c.assigned_to}</span></span>}
          {c.deadline && <span>Deadline: {new Date(c.deadline).toLocaleDateString()}</span>}
         </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
         {c.rule_a && (
          <div className="rounded-xl p-4" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
           <div className="text-xs uppercase mb-1" style={{ color: colors.inkSubtle }}>Rule A - {c.rule_a.domain}</div>
           <p className="text-sm mb-2" style={{ color: colors.inkMuted }}>{c.rule_a.statement}</p>
           <div className="flex gap-4 text-xs" style={{ color: colors.inkSubtle }}>
            <span>Confidence: <span style={{ color: colors.ink }}>{c.rule_a.confidence.toFixed(2)}</span></span>
            <span>Sources: {c.rule_a.sources}</span>
           </div>
          </div>
         )}
         {c.rule_b && (
          <div className="rounded-xl p-4" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
           <div className="text-xs uppercase mb-1" style={{ color: colors.inkSubtle }}>Rule B - {c.rule_b.domain}</div>
           <p className="text-sm mb-2" style={{ color: colors.inkMuted }}>{c.rule_b.statement}</p>
           <div className="flex gap-4 text-xs" style={{ color: colors.inkSubtle }}>
            <span>Confidence: <span style={{ color: colors.ink }}>{c.rule_b.confidence.toFixed(2)}</span></span>
            <span>Sources: {c.rule_b.sources}</span>
           </div>
          </div>
         )}
        </div>

        {c.status === 'RESOLVED' ? (
         <div className="rounded-xl p-3 text-sm" style={{ background: colors.success + '14', border: `1px solid ${colors.success}33`, color: colors.success }}>
          Resolved: {c.resolution_type?.replace(/_/g, ' ')} - {c.resolution_note}
         </div>
        ) : (
         <div className="flex gap-2 pt-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          {['CHOOSE_A', 'CHOOSE_B', 'MERGE', 'SUPERSEDE'].map(rt => (
           <button key={rt} onClick={() => handleResolve(c.id, rt)}
            className="px-3 py-1.5 rounded-xl text-xs font-medium transition-colors hover:opacity-80"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}
           >{rt.replace(/_/g, ' ')}</button>
          ))}
         </div>
        )}
       </div>
      ))}
     </div>
    )}
   </div>
  </div>
 );
};

export default ConflictArena;
