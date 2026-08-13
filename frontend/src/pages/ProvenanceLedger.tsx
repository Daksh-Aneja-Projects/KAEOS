import React, { useEffect, useState } from 'react';
import type { ProvenanceEntry } from '../api/client';
import { api, downloadFile } from '../api/client';
import { Link2, Hash, Download, ShieldCheck, ShieldAlert, Loader2, XCircle } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

const ProvenanceLedger = () => {
 const { colors } = useTheme();
 const [ledger, setLedger] = useState<ProvenanceEntry[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [exporting, setExporting] = useState(false);
 const [exportError, setExportError] = useState<string | null>(null);
 // Chain-integrity results, keyed by rule id (one verify covers every entry of that rule).
 const [verifying, setVerifying] = useState<string | null>(null);
 const [verdicts, setVerdicts] = useState<Record<string, { valid: boolean | null; status: string }>>({});

 const exportCsv = async () => {
  setExporting(true);
  setExportError(null);
  try {
   await downloadFile(api.provenanceLedgerCsvPath(), 'provenance_ledger.csv');
  } catch (e: any) {
   setExportError(e?.message || 'Export failed.');
  } finally {
   setExporting(false);
  }
 };

 const verifyChain = async (ruleId: string) => {
  setVerifying(ruleId);
  setExportError(null);
  try {
   const r = await api.verifyProvenance(ruleId);
   setVerdicts(prev => ({ ...prev, [ruleId]: { valid: r.chain_valid, status: r.status } }));
  } catch (e: any) {
   setExportError(e?.message || 'Could not verify that chain.');
  } finally {
   setVerifying(null);
  }
 };

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
   <div className={`${PAGE_PAD} space-y-5`}>
    {/* Header */}
    <div className="flex items-start gap-3">
     <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
       style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
      <Link2 className="w-6 h-6 text-white" />
     </div>
     <div className="flex-1">
      <h1 className="text-[24px] font-bold tracking-tight">Provenance Ledger</h1>
      <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Immutable, tamper-evident knowledge lineage</p>
     </div>
     <button onClick={exportCsv} disabled={exporting}
       className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium self-center disabled:opacity-50"
       style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
      {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
      {exporting ? 'Preparing…' : 'Export CSV'}
     </button>
    </div>

    {exportError && (
     <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
       style={{ background: colors.error + '15', color: colors.error }}>
      <XCircle className="w-4 h-4 shrink-0" />
      <span className="flex-1">{exportError}</span>
      <button onClick={() => setExportError(null)} className="text-[11px] opacity-70">dismiss</button>
     </div>
    )}

    {ledger.length === 0 ? (
     <BrainEmpty title="No ledger entries yet" action="Knowledge lineage is recorded here as rules are created and validated." icon={Hash} />
    ) : (
     <div className="overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: '14px' }}>
      <div className="overflow-x-auto">
       <div className="min-w-[1060px]">
        <div className="grid grid-cols-[110px_1fr_100px_70px_1fr_170px_130px] gap-4 px-6 py-3 text-[11px] uppercase tracking-wider font-semibold"
          style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
         <span>Event</span><span>Rule</span><span>Actor</span><span>Conf.</span><span>Reasoning</span><span>Chain Hash</span><span>Integrity</span>
        </div>
        {ledger.map((e, i) => {
         const verdict = e.rule_id ? verdicts[e.rule_id] : undefined;
         return (
         <div key={e.id || i} className="grid grid-cols-[110px_1fr_100px_70px_1fr_170px_130px] gap-4 px-6 py-4 transition-colors items-center"
           style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <span className="px-2 py-0.5 rounded text-[11px] font-medium inline-block w-fit" style={eventStyle(e.event_type)}>{humanize(e.event_type)}</span>
          <span className="text-[13px] truncate" style={{ color: colors.inkMuted }}>{e.rule_statement || '-'}</span>
          <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{humanize(e.actor_role)}</span>
          <span className="text-[13px] font-mono tabular-nums" style={{ color: colors.ink }}>{e.confidence_at?.toFixed(2)}</span>
          <span className="text-[12px] truncate" style={{ color: colors.inkSubtle }}>{e.reasoning}</span>
          <span className="text-[12px] font-mono truncate flex items-center gap-1" style={{ color: colors.inkMuted }}><Hash className="w-3 h-3 shrink-0" />{e.chain_hash?.slice(0, 16)}…</span>
          <span>
           {!e.rule_id ? (
            <span className="text-[11px]" style={{ color: colors.inkTertiary }}>-</span>
           ) : verdict ? (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-semibold w-fit"
              title={verdict.valid === true
                ? 'Every link in this rule’s signed history checks out. Nothing has been altered.'
                : verdict.valid === false
                ? 'The signed chain does not line up. This rule’s history has been altered outside the ledger.'
                : 'These entries predate the signed ledger, so their integrity cannot be proven or disproven. New entries are signed and verifiable.'}
              style={{
                background: (verdict.valid === true ? colors.success : verdict.valid === false ? colors.error : colors.inkSubtle) + '18',
                color: verdict.valid === true ? colors.success : verdict.valid === false ? colors.error : colors.inkMuted,
              }}>
             {verdict.valid === false ? <ShieldAlert className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
             {verdict.valid === true ? 'Intact' : verdict.valid === false ? 'Altered' : 'Predates signing'}
            </span>
           ) : (
            <button onClick={() => verifyChain(e.rule_id as string)} disabled={verifying === e.rule_id}
              className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-medium disabled:opacity-50"
              style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
             {verifying === e.rule_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
             Verify
            </button>
           )}
          </span>
         </div>
         );
        })}
       </div>
      </div>
     </div>
    )}
   </div>
  </div>
 );
};

export default ProvenanceLedger;
