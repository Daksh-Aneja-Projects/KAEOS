import React, { useEffect, useState } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Database, TrendingUp, Award, Loader2 } from 'lucide-react';
import { request } from '../api/client';

export default function GenomeStudio() {
  const { colors } = useTheme();
  const [genomeState, setGenomeState] = useState<any>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    request<any>('/genome/state')
      .then(setGenomeState)
      .catch((e) => setError(e?.message || 'Failed to load genome state'));
  }, []);

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const scoreColor = (score: number) => score >= 0.8 ? '#22c55e' : score >= 0.5 ? '#f59e0b' : '#ef4444';
  const traitColor = (score: number, inverted = false) => {
    const s = inverted ? 100 - score : score;
    return s >= 70 ? '#22c55e' : s >= 45 ? '#f59e0b' : '#ef4444';
  };

  if (error) {
    return <div className="p-8 text-[13px] text-red-500">Genome state unavailable: {error}</div>;
  }
  if (!genomeState) {
    return (
      <div className="p-12 flex items-center gap-2 text-[13px] opacity-70">
        <Loader2 className="w-4 h-4 animate-spin" /> Compiling live enterprise genome…
      </div>
    );
  }

  const traits = Object.entries(genomeState.traits || {});
  const timeline = genomeState.timeline || [];

  return (
    <div className="space-y-6 pb-12">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-[20px] font-bold flex items-center gap-2">
            <Database className="w-6 h-6 text-indigo-500" />
            Enterprise Genome Intelligence
          </h2>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
            Live genome traits compiled from enterprise physics features
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-end text-[13px] font-bold">
            <span style={{ color: colors.inkSubtle }}>Adaptability Score</span>
            <span className="font-mono text-[20px] text-indigo-500">
              {genomeState.adaptability != null ? genomeState.adaptability.toFixed(1) : '-'}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Genome Traits (live GenomeCompiler output) */}
        <div style={card}>
          <h3 className="text-[14px] font-bold mb-4 flex items-center gap-2 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
            <Award className="w-4 h-4 text-indigo-500" /> Genome Trait Scores
          </h3>
          <div className="space-y-3">
            {traits.map(([name, score]: [string, any]) => {
              const inverted = name === 'Operational_Fragility';
              return (
                <div key={name} className="p-3 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.surface2 }}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-[13px] font-bold">{name.replace(/_/g, ' ')}</div>
                    <div className="text-[14px] font-bold font-mono" style={{ color: traitColor(score, inverted) }}>
                      {Number(score).toFixed(1)}{inverted ? ' (lower is better)' : ''}
                    </div>
                  </div>
                  <div className="h-1.5 rounded-full" style={{ background: colors.hairline }}>
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, score)}%`, background: traitColor(score, inverted) }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 text-[11px]" style={{ color: colors.inkSubtle }}>
            Features: workforce stability {genomeState.features?.workforce_stability}% · agent redundancy {genomeState.features?.capability_redundancy}% ·
            delivery {genomeState.features?.project_delivery}% · vendor concentration {genomeState.features?.vendor_concentration}% ·
            budget utilization {genomeState.features?.budget_utilization}%
          </div>
        </div>

        {/* Fitness timeline from real execution history */}
        <div style={card}>
          <h3 className="text-[14px] font-bold mb-4 flex items-center gap-2 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
            <TrendingUp className="w-4 h-4 text-emerald-500" /> Fitness Timeline ({genomeState.total_genomes_tracked} weekly snapshots)
          </h3>
          {timeline.length === 0 && (
            <p className="text-[12px]" style={{ color: colors.inkSubtle }}>No execution history yet - run skills to build the timeline.</p>
          )}
          <div className="relative pt-4 pl-4 border-l-2 space-y-6" style={{ borderColor: colors.hairline }}>
            {timeline.map((point: any, idx: number) => (
              <div key={idx} className="relative">
                <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-emerald-500 ring-4" />
                <div>
                  <div className="text-[12px] font-bold text-emerald-500">{point.version} &bull; {point.time} &bull; {point.executions} executions</div>
                  <div className="mt-2 flex items-center gap-6">
                    <div>
                      <div className="text-[10px] font-bold uppercase" style={{ color: colors.inkSubtle }}>Execution Fitness</div>
                      <div className="text-[16px] font-mono font-bold" style={{ color: scoreColor(point.fitness) }}>
                        {(point.fitness * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] font-bold uppercase" style={{ color: colors.inkSubtle }}>Failure Risk</div>
                      <div className="text-[16px] font-mono font-bold" style={{ color: point.risk > 0.3 ? '#ef4444' : '#22c55e' }}>
                        {(point.risk * 100).toFixed(1)}%
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
