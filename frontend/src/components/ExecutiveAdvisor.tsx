import React from 'react';
import { useTheme } from '../context/ThemeContext';
import { Shield, Zap, Target, AlertTriangle, CheckCircle, Crosshair, Cpu, Briefcase, Database } from 'lucide-react';

export default function ExecutiveAdvisor() {
  const { colors } = useTheme();

  // Mocking the Context-Aware Recommendation output for UI
  const recommendationData = {
    recommended_transformation: "VENDOR_DIVERSIFICATION",
    expected_fitness_gain: 0.068,
    expected_risk_reduction: -0.052,
    recommendation_trust_score: 0.88,
    rationale: "Matched 17 similar enterprise genomes (Average Similarity: 89.0%). Shared Characteristics: Vendor Concentration > 70%, Elevated Risk Profile. Observed Outcome: 82.4% success rate with an average fitness gain of +6.8%.",
    similarity_drivers: [
      { dimension: "Vendor Concentration", similarity: 0.94 },
      { dimension: "Risk Profile", similarity: 0.91 },
      { dimension: "Portfolio Structure", similarity: 0.88 }
    ],
    historical_evidence: {
      historical_sample_size: 17,
      observed_success_rate: 0.824,
      historical_cases: [
        { memory_id: "mem-01", similarity: 0.92, transformation_applied: "VENDOR_DIVERSIFICATION", observed_result: { fitness_delta: 0.071, risk_delta: -0.06 } },
        { memory_id: "mem-02", similarity: 0.89, transformation_applied: "VENDOR_DIVERSIFICATION", observed_result: { fitness_delta: 0.065, risk_delta: -0.04 } }
      ]
    },
    counterfactuals: [
      {
        transformation_type: "CAPABILITY_INVESTMENT",
        average_fitness_gain: 0.041,
        average_risk_reduction: -0.01,
        reason: "Historical peer enterprises achieved smaller gains than Vendor Diversification due to lack of existing capability gaps."
      }
    ]
  };

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '24px'
  };

  const scoreColor = (score: number) => score >= 0.8 ? '#22c55e' : score >= 0.5 ? '#f59e0b' : '#ef4444';

  return (
    <div className="space-y-6 pb-12">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-[20px] font-bold flex items-center gap-2">
            <Target className="w-6 h-6 text-emerald-500" />
            Executive Advisor
          </h2>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
            Context-Aware Transformation Recommendations
          </p>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Main Recommendation Panel */}
        <div className="col-span-8 space-y-6">
          <div style={{ ...card, border: `2px solid #10b981`, position: 'relative', overflow: 'hidden' }}>
            <div className="absolute top-0 right-0 p-4">
              <div className="text-right">
                <div className="text-[11px] font-bold uppercase" style={{ color: colors.inkSubtle }}>Recommendation Trust Score</div>
                <div className="text-[24px] font-mono font-bold" style={{ color: scoreColor(recommendationData.recommendation_trust_score) }}>
                  {(recommendationData.recommendation_trust_score * 100).toFixed(1)}%
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 mb-6">
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
                <Briefcase className="w-6 h-6 text-emerald-500" />
              </div>
              <div>
                <h3 className="text-[14px] font-bold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Recommended Transformation</h3>
                <div className="text-[22px] font-bold text-emerald-500">{recommendationData.recommended_transformation.replace('_', ' ')}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6 mb-6">
              <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <div className="text-[11px] font-bold uppercase text-emerald-600 mb-1">Expected Fitness Gain</div>
                <div className="text-[20px] font-mono font-bold text-emerald-500">+{ (recommendationData.expected_fitness_gain * 100).toFixed(1) }%</div>
              </div>
              <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <div className="text-[11px] font-bold uppercase text-emerald-600 mb-1">Expected Risk Reduction</div>
                <div className="text-[20px] font-mono font-bold text-emerald-500">{ (recommendationData.expected_risk_reduction * 100).toFixed(1) }%</div>
              </div>
            </div>

            <div className="p-4 rounded-lg bg-gray-500/5 border" style={{ borderColor: colors.hairline }}>
              <div className="text-[13px] font-bold mb-2 flex items-center gap-2">
                <Database className="w-4 h-4 text-indigo-500" /> Recommendation Rationale
              </div>
              <p className="text-[13px] leading-relaxed" style={{ color: colors.ink }}>
                {recommendationData.rationale}
              </p>
            </div>
          </div>

          {/* Counterfactuals */}
          <div style={card}>
            <h3 className="text-[14px] font-bold mb-4 flex items-center gap-2 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
              <Crosshair className="w-4 h-4 text-amber-500" /> Counterfactual Analysis
            </h3>
            <div className="space-y-4">
              {recommendationData.counterfactuals.map((cf, idx) => (
                <div key={idx} className="p-4 rounded-lg border bg-amber-500/5" style={{ borderColor: colors.hairline }}>
                  <div className="flex justify-between items-center mb-2">
                    <div className="text-[14px] font-bold">{cf.transformation_type.replace('_', ' ')}</div>
                    <div className="text-[13px] font-mono text-emerald-500">Gain: +{(cf.average_fitness_gain * 100).toFixed(1)}%</div>
                  </div>
                  <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                    <span className="font-bold text-amber-600">Ranked Lower Because: </span>
                    {cf.reason}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Sidebar: Evidence & Similarity */}
        <div className="col-span-4 space-y-6">
          <div style={card}>
            <h3 className="text-[14px] font-bold mb-4 flex items-center gap-2 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
              <Cpu className="w-4 h-4 text-indigo-500" /> Similarity Drivers
            </h3>
            <div className="space-y-3">
              {recommendationData.similarity_drivers.map((driver, idx) => (
                <div key={idx} className="flex justify-between items-center text-[13px]">
                  <span style={{ color: colors.ink }}>{driver.dimension}</span>
                  <span className="font-mono font-bold" style={{ color: scoreColor(driver.similarity) }}>
                    {(driver.similarity * 100).toFixed(1)}% Match
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div style={card}>
            <h3 className="text-[14px] font-bold mb-4 flex items-center gap-2 uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
              <CheckCircle className="w-4 h-4 text-emerald-500" /> Top Historical Matches
            </h3>
            <div className="space-y-4">
              {recommendationData.historical_evidence.historical_cases.map((case_, idx) => (
                <div key={idx} className="pb-4 border-b last:border-0" style={{ borderColor: colors.hairline }}>
                  <div className="flex justify-between items-center mb-1">
                    <div className="text-[12px] font-bold text-indigo-500">Peer Match #{idx + 1}</div>
                    <div className="text-[12px] font-mono font-bold">Sim: {(case_.similarity * 100).toFixed(1)}%</div>
                  </div>
                  <div className="text-[11px] font-bold mb-1" style={{ color: colors.inkSubtle }}>Transformation: {case_.transformation_applied.replace('_', ' ')}</div>
                  <div className="text-[11px] font-mono text-emerald-500">Outcome: +{(case_.observed_result.fitness_delta * 100).toFixed(1)}% Fitness</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
