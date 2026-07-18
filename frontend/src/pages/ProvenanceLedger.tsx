import React, { useEffect, useState } from 'react';
import type { ProvenanceEntry } from '../api/client';
import { api } from '../api/client';
import { Link2, Hash } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

const ProvenanceLedger = () => {
 const { colors } = useTheme();
 const [ledger, setLedger] = useState<ProvenanceEntry[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);

 const load = () => {
  setError(null);
  api.getGlobalLedger().then(d => { setLedger(d.ledger); setLoading(false); }).catch((e: any) => { setError(e?.message || 'Failed to load the provenance ledger'); setLoading(false); });
 };

 useEffect(() => {
  load();
 }, []);

 const eventStyle = (t: string): React.CSSProperties => {
  if (t === 'CREATED') return { background: colors.info + '1f', color: colors.info, border: `1px solid ${colors.info}40` };
  if (t === 'VALIDATED') return { background: colors.success + '1f', color: colors.success, border: `1px solid ${colors.success}40` };
  if (t === 'DECAYED') return { background: colors.warning + '1f', color: colors.warning, border: `1px solid ${colors.warning}40` };
  return { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` };
 };

 if (loading) return <BrainLoading message="Loading the Provenance Ledger…" />;
 if (error) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    {/* Header */}
    <div className="flex items-start gap-3">
     <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
       style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
      <Link2 className="w-6 h-6 text-white" />
     </div>
     <div>
      <h1 className="text-[24px] font-bold tracking-tight">Provenance Ledger</h1>
      <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Immutable, tamper-evident knowledge lineage</p>
     </div>
    </div>

    {ledger.length === 0 ? (
     <BrainEmpty title="No ledger entries yet" action="Knowledge lineage is recorded here as rules are created and validated." icon={Hash} />
    ) : (
     <div className="overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: '14px' }}>
      <div className="overflow-x-auto">
       <div className="min-w-[900px]">
        <div className="grid grid-cols-[120px_1fr_120px_80px_1fr_200px] gap-4 px-6 py-3 text-[11px] uppercase tracking-wider font-semibold"
          style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
         <span>Event</span><span>Rule</span><span>Actor</span><span>Conf.</span><span>Reasoning</span><span>Chain Hash</span>
        </div>
        {ledger.map((e, i) => (
         <div key={e.id || i} className="grid grid-cols-[120px_1fr_120px_80px_1fr_200px] gap-4 px-6 py-4 transition-colors items-center"
           style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <span className="px-2 py-0.5 rounded text-[11px] font-medium inline-block w-fit" style={eventStyle(e.event_type)}>{e.event_type}</span>
          <span className="text-[13px] truncate" style={{ color: colors.inkMuted }}>{e.rule_statement || '-'}</span>
          <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{e.actor_role}</span>
          <span className="text-[13px] font-mono tabular-nums" style={{ color: colors.ink }}>{e.confidence_at?.toFixed(2)}</span>
          <span className="text-[12px] truncate" style={{ color: colors.inkSubtle }}>{e.reasoning}</span>
          <span className="text-[12px] font-mono truncate flex items-center gap-1" style={{ color: colors.inkMuted }}><Hash className="w-3 h-3 shrink-0" />{e.chain_hash?.slice(0, 16)}…</span>
         </div>
        ))}
       </div>
      </div>
     </div>
    )}
   </div>
  </div>
 );
};

export default ProvenanceLedger;
