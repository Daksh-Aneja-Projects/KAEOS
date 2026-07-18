import React, { useEffect, useState } from 'react';
import type { Signal, CandidateRule } from '../api/client';
import { api } from '../api/client';
import { FileSearch, Beaker, ShieldCheck, Inbox } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading } from '../components/BrainStates';

const ExtractionHub = () => {
 const { colors } = useTheme();
 const [signals, setSignals] = useState<Signal[]>([]);
 const [candidates, setCandidates] = useState<CandidateRule[]>([]);
 const [loading, setLoading] = useState(true);
 const [tab, setTab] = useState<'signals' | 'candidates'>('signals');

 useEffect(() => {
  Promise.all([api.getSignals(), api.getCandidates()])
   .then(([s, c]) => { setSignals(s.signals); setCandidates(c.candidates); setLoading(false); })
   .catch(() => setLoading(false));
 }, []);

 const card: React.CSSProperties = {
  background: colors.surface1,
  border: `1px solid ${colors.hairline}`,
  borderRadius: '14px',
 };

 if (loading) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainLoading message="Loading extraction data…" />
  </div>
 );

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    <header className="flex items-start gap-3 pb-5 border-b" style={{ borderColor: colors.hairline }}>
     <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
       style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
      <FileSearch className="w-6 h-6 text-white" />
     </div>
     <div>
      <h1 className="text-[24px] font-bold tracking-tight">Candidate Broker</h1>
      <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Knowledge Extraction & Rule Mining</p>
     </div>
    </header>

    <div className="flex gap-2">
     {(['signals', 'candidates'] as const).map(t => {
      const active = tab === t;
      return (
       <button key={t} onClick={() => setTab(t)}
        className="px-4 py-2 rounded-lg text-[13px] font-medium capitalize transition-all hover:opacity-80"
        style={active
          ? { background: colors.primary + '20', color: colors.primary, border: `1px solid ${colors.primary}40` }
          : { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}
       >{t} ({t === 'signals' ? signals.length : candidates.length})</button>
      );
     })}
    </div>

    {tab === 'signals' && (
     <div className="space-y-3">
      {signals.length === 0 ? (
       <div style={card} className="text-center py-16">
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3" style={{ background: colors.surface2 }}>
         <Inbox className="w-7 h-7" style={{ color: colors.inkTertiary }} />
        </div>
        <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>No signals ingested yet</p>
        <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>Connect enterprise apps to start harvesting.</p>
       </div>
      ) : signals.map(s => (
       <div key={s.id} style={card} className="p-4">
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
         <div className="flex items-center gap-2 flex-wrap">
          <span className="px-2 py-0.5 text-[11px] rounded" style={{ background: colors.info + '18', color: colors.info, border: `1px solid ${colors.info}30` }}>{s.source_type}</span>
          <span className="px-2 py-0.5 text-[11px] rounded" style={{ background: colors.surface2, color: colors.inkSubtle }}>{s.domain}</span>
          {s.pii_present && (
            <span className="px-2 py-0.5 text-[11px] rounded flex items-center gap-1" style={{ background: colors.success + '15', color: colors.success, border: `1px solid ${colors.success}30` }}>
              <ShieldCheck className="w-3 h-3" /> PII Scrubbed (L17)
            </span>
          )}
         </div>
         <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Authority: {s.authority_score.toFixed(2)}</span>
        </div>
        <p className="text-[13px]" style={{ color: colors.inkMuted }}>{s.clean_payload}</p>
       </div>
      ))}
     </div>
    )}

    {tab === 'candidates' && (
     <div className="space-y-3">
      {candidates.length === 0 ? (
       <div style={card} className="text-center py-16">
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3" style={{ background: colors.surface2 }}>
         <Beaker className="w-7 h-7" style={{ color: colors.inkTertiary }} />
        </div>
        <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>No candidate rules mined yet</p>
        <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>Minimum 3 signals per domain required.</p>
       </div>
      ) : candidates.map(c => (
       <div key={c.id} style={card} className="p-4">
        <div className="flex items-center gap-2 mb-2">
         <Beaker className="w-4 h-4" style={{ color: colors.primary }} />
         <span className="px-2 py-0.5 text-[11px] rounded" style={{ background: colors.primary + '18', color: colors.primary, border: `1px solid ${colors.primary}30` }}>{c.domain}</span>
        </div>
        <p className="text-[13px] mb-2" style={{ color: colors.inkMuted }}>{c.statement}</p>
        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Basis: {c.confidence_basis}</span>
       </div>
      ))}
     </div>
    )}
   </div>
  </div>
 );
};

export default ExtractionHub;
