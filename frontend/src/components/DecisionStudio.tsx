import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Shield, Target, AlertTriangle, CheckCircle, Zap, Scale, History, BrainCircuit } from 'lucide-react';

export default function DecisionStudio() {
  const { colors } = useTheme();
  
  const [activeDecision, setActiveDecision] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Call the pending HITL API
    import('../api/client').then(({ api }) => {
       
      api.getPendingHITL().then((data: any) => {
        setActiveDecision(data?.[0] || null);
        setLoading(false);
      }).catch((err: any) => {
        console.error(err);
        setLoading(false);
      });
    });
  }, []);

  if (loading || !activeDecision) return <div className="p-8 text-gray-400 animate-pulse">Loading AI Decision Models...</div>;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  return (
    <div className="space-y-6">
      
      {/* Inbox Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-[20px] font-bold flex items-center gap-2">
          <Scale className="w-6 h-6 text-indigo-500" />
          Enterprise Decision Studio
        </h2>
        <div className="text-[12px] font-bold px-3 py-1 rounded bg-red-500/10 text-red-500 border border-red-500/20 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> 1 Critical Decision Required
        </div>
      </div>

      {/* Decision Context */}
      <div style={card} className="border-l-4 border-l-red-500">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[12px] font-bold uppercase tracking-wider text-red-500 mb-1">CRISIS DETECTED</div>
            <h3 className="text-[24px] font-bold">Critical Vendor Bankruptcy: vendor_critical_5</h3>
            <p className="text-[14px] mt-2" style={{ color: colors.inkSubtle }}>
              KAEOS has detected a high-probability failure event. The Option Engine has generated and evaluated alternatives across 10 dimensions.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
             <div className="text-[12px] font-semibold text-green-500 flex items-center gap-1">
               <Shield className="w-4 h-4" /> Enterprise Trust: 92%
             </div>
             <div className="text-[12px] font-semibold text-blue-500 flex items-center gap-1">
               <BrainCircuit className="w-4 h-4" /> Confidence: High
             </div>
          </div>
        </div>
      </div>

      {/* Tradeoff Analysis */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {(activeDecision.options || []).map((opt: any, idx: number) => (
          <div key={idx} style={{
            ...card,
            borderColor: opt.status === 'RECOMMENDED' ? '#22c55e' : opt.status === 'REJECTED' ? '#ef444450' : colors.hairline,
            opacity: opt.status === 'REJECTED' ? 0.6 : 1
          }} className="flex flex-col relative">
            
            {opt.status === 'RECOMMENDED' && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-green-500 text-white text-[10px] font-bold uppercase px-3 py-1 rounded-full shadow flex items-center gap-1">
                <CheckCircle className="w-3 h-3" /> Recommended
              </div>
            )}

            <div className="mb-4 mt-2">
              <h4 className="text-[16px] font-bold">{opt.action}</h4>
              <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>{opt.description}</p>
            </div>

            <div className="space-y-3 flex-1 mt-4 border-t pt-4" style={{ borderColor: colors.hairline }}>
              <div className="flex justify-between items-center text-[12px]">
                <span style={{ color: colors.inkSubtle }}>Decision Quality</span>
                <span className="font-mono font-bold">{opt.quality.toFixed(3)}</span>
              </div>
              <div className="flex justify-between items-center text-[12px]">
                <span style={{ color: colors.inkSubtle }}>Expected Value</span>
                <span className="font-mono font-bold text-green-500">+{opt.ev.toFixed(3)}</span>
              </div>
              <div className="flex justify-between items-center text-[12px]">
                <span style={{ color: colors.inkSubtle }}>Risk Exposure</span>
                <span className="font-mono font-bold text-orange-500">{opt.risk_score.toFixed(3)}</span>
              </div>
            </div>

            {opt.constraints.length > 0 && (
              <div className="mt-4 p-2 bg-red-500/10 border border-red-500/20 rounded text-[11px] text-red-500 font-medium">
                {opt.constraints[0]}
              </div>
            )}

            <button 
              disabled={opt.status === 'REJECTED'}
              className="mt-6 w-full py-2 rounded-lg text-[13px] font-semibold transition-colors"
              style={{
                background: opt.status === 'RECOMMENDED' ? '#22c55e' : colors.surface2,
                color: opt.status === 'RECOMMENDED' ? '#fff' : colors.ink,
                opacity: opt.status === 'REJECTED' ? 0.5 : 1,
                cursor: opt.status === 'REJECTED' ? 'not-allowed' : 'pointer'
              }}
            >
              {opt.status === 'RECOMMENDED' ? 'Execute Decision' : 'Select Alternative'}
            </button>
          </div>
        ))}
      </div>

      {/* Debate Transcripts & Fairness Logs */}
      {activeDecision.debate_transcript && (
        <div style={card} className="mt-6">
          <h3 className="text-[16px] font-bold mb-4 flex items-center gap-2">
            <History className="w-5 h-5 text-indigo-500" />
            Live AI Debate & Fairness Logs
          </h3>
          <div className="space-y-3">
            {activeDecision.debate_transcript.map((log: any, i: number) => (
              <div key={i} className="text-[13px] bg-gray-50 border border-[#E5E5EA] rounded p-3 flex flex-col">
                <span className="font-bold text-gray-800">{log.engine}</span>
                <span className="text-gray-600 mt-1">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Decision Ledger */}
      <div style={card} className="mt-8">
         <h2 className="text-[16px] font-bold mb-4 flex items-center gap-2">
          <History className="w-5 h-5 text-gray-500" /> Decision Ledger & Regret Analysis
        </h2>
        <div className="text-[13px]" style={{ color: colors.inkSubtle }}>
           No historical decisions recorded for this session yet. Execute a decision to generate an end-to-end DecisionTrace.
        </div>
      </div>
    </div>
  );
}
