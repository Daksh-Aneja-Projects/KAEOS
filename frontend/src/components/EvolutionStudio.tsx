import React, { useEffect, useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Activity, Target, Zap, ArrowRight, ArrowUpRight, ArrowDownRight, Layers, Box, Cpu, AlertTriangle, ShieldCheck, Loader2 } from 'lucide-react';
import { request } from '../api/client';

export default function EvolutionStudio() {
  const { colors } = useTheme();
  const [evolutionState, setEvolutionState] = useState<any>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    request<any>('/evolution/state')
      .then(setEvolutionState)
      .catch((e) => setError(e?.message || 'Failed to load evolution state'));
  }, []);

  if (error) {
    return <div className="p-8 text-[13px] text-red-500">Evolution state unavailable: {error}</div>;
  }
  if (!evolutionState) {
    return (
      <div className="p-12 flex items-center gap-2 text-[13px] opacity-70">
        <Loader2 className="w-4 h-4 animate-spin" /> Computing live enterprise fitness…
      </div>
    );
  }

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const scoreColor = (score: number) => score >= 0.8 ? '#22c55e' : score >= 0.6 ? '#f59e0b' : '#ef4444';

  return (
    <div className="space-y-6 pb-12">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-[20px] font-bold flex items-center gap-2">
            <Cpu className="w-6 h-6 text-purple-500" />
            Enterprise Evolution Studio
          </h2>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
            Continuous Structural Optimization & Fitness Simulation (Genome v{evolutionState.genome_version})
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-[14px] font-bold bg-green-500/10 text-green-500 px-4 py-2 rounded-lg border border-green-500/20">
            <ArrowUpRight className="w-4 h-4" /> Expected Delta: +{((evolutionState.future_fitness - evolutionState.current_fitness) * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Fitness Comparison */}
      <div className="grid grid-cols-2 gap-6">
        <div style={card} className="flex flex-col items-center justify-center py-8 relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-orange-500 to-red-500" />
          <div className="text-[12px] font-bold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>Current Enterprise Fitness</div>
          <div className="text-[64px] font-black font-mono leading-none" style={{ color: scoreColor(evolutionState.current_fitness ?? 0) }}>
            {evolutionState.current_fitness != null ? (evolutionState.current_fitness * 100).toFixed(1) : '-'}%
          </div>
          <div className="text-[13px] mt-4 flex items-center gap-2" style={{ color: colors.inkSubtle }}>
            <AlertTriangle className="w-4 h-4 text-orange-500" /> {evolutionState.breaches ?? 0} Critical Threshold Breach{(evolutionState.breaches ?? 0) === 1 ? '' : 'es'} Detected
          </div>
        </div>

        <div style={card} className="flex flex-col items-center justify-center py-8 relative overflow-hidden bg-gradient-to-br from-green-500/5 to-emerald-500/10">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-green-400 to-emerald-600" />
          <div className="text-[12px] font-bold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>Simulated Optimized Fitness</div>
          <div className="text-[64px] font-black font-mono leading-none text-green-500">
            {evolutionState.future_fitness != null ? (evolutionState.future_fitness * 100).toFixed(1) : '-'}%
          </div>
          <div className="text-[13px] mt-4 flex items-center gap-2 text-green-600 font-semibold">
            <ShieldCheck className="w-4 h-4" /> Projected after applying {evolutionState.optimizations?.length ?? 0} optimization{(evolutionState.optimizations?.length ?? 0) === 1 ? '' : 's'}
          </div>
        </div>
      </div>

      {/* Domain Fitness Breakdown */}
      <div style={card}>
        <h3 className="text-[14px] font-bold mb-4 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>8-Dimensional Fitness Matrix</h3>
        <div className="grid grid-cols-4 gap-4">
          {Object.entries(evolutionState.subscores || {}).map(([key, val]: [string, any]) => (
            <div key={key} className="p-3 rounded-lg border flex items-center justify-between" style={{ borderColor: colors.hairline, background: colors.surface2 }}>
              <div className="text-[12px] font-semibold">{key.replace('_fitness', '').replace('_', ' ')}</div>
              <div className="text-[14px] font-bold font-mono" style={{ color: val != null ? scoreColor(val) : colors.inkSubtle }}>
                {val != null ? `${(val * 100).toFixed(0)}%` : '-'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Top Optimization Opportunities */}
      <div>
        <h3 className="text-[16px] font-bold mb-4 flex items-center gap-2">
          <Zap className="w-5 h-5 text-yellow-500" /> Recommended Structural Evolutions
        </h3>
        <div className="space-y-4">
          {evolutionState.optimizations.map((opt: any, idx: number) => (
            <div key={idx} className="flex flex-col gap-4 border-l-4" style={{ ...card, borderLeftColor: colors.primary }}>
              <div className="flex justify-between items-start">
                <div>
                  <div className="text-[11px] font-bold text-purple-500 uppercase tracking-wider mb-1">{opt.type.replace('_', ' ')}</div>
                  <h4 className="text-[15px] font-semibold">{opt.description}</h4>
                </div>
                <div className="text-right">
                  <div className="text-[12px] font-bold uppercase" style={{ color: colors.inkSubtle }}>Enterprise Fitness Gain</div>
                  <div className="text-[24px] font-black font-mono text-green-500">+{Math.round(opt.expected_gain * 100)}%</div>
                </div>
              </div>
              
              <div className="flex items-center gap-6 mt-2 pt-4 border-t" style={{ borderColor: colors.hairline }}>
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase font-bold" style={{ color: colors.inkSubtle }}>Expected Cost</span>
                  <span className="font-mono text-[13px]">${opt.expected_cost.toLocaleString()}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase font-bold" style={{ color: colors.inkSubtle }}>Expected Risk</span>
                  <span className="font-mono text-[13px]" style={{ color: scoreColor(1 - opt.risk) }}>{(opt.risk * 100).toFixed(0)}%</span>
                </div>
                <div className="ml-auto">
                   <button className="px-4 py-2 rounded-lg text-[13px] font-bold bg-white text-black shadow hover:bg-gray-100 transition-colors">
                     Apply Genome Evolution
                   </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
