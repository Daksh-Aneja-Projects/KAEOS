import React, { useState } from 'react';
import { Rocket, Shield, Gauge, AlertTriangle, X, Zap } from 'lucide-react';

interface Props {
  blueprintId: string;
  blueprintName: string;
  colors: any;
  onDeploy: (config: DeployConfig) => void;
  onCancel: () => void;
}

export interface DeployConfig {
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  confidence_threshold: number;
  hitl_mode: 'ALWAYS' | 'CONDITIONAL' | 'NEVER';
  hitl_threshold: number;
}

const RISK_LEVELS = [
  { id: 'LOW' as const, label: 'Low Risk', desc: 'Conservative execution - extra validation gates', color: '#27a644', icon: '🟢' },
  { id: 'MEDIUM' as const, label: 'Medium Risk', desc: 'Balanced autonomy with standard guardrails', color: '#f5a623', icon: '🟡' },
  { id: 'HIGH' as const, label: 'High Risk', desc: 'Maximum autonomy - minimal human intervention', color: '#e5534b', icon: '🔴' },
];

const HITL_MODES = [
  { id: 'ALWAYS' as const, label: 'Always', desc: 'Human reviews every decision' },
  { id: 'CONDITIONAL' as const, label: 'Conditional', desc: 'Only when confidence drops below threshold' },
  { id: 'NEVER' as const, label: 'Never', desc: 'Fully autonomous - no human review' },
];

export default function DeployConfigModal({ blueprintId, blueprintName, colors, onDeploy, onCancel }: Props) {
  const [config, setConfig] = useState<DeployConfig>({
    risk_level: 'MEDIUM',
    confidence_threshold: 0.85,
    hitl_mode: 'CONDITIONAL',
    hitl_threshold: 0.70,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}>
      <div className="w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #f59e0b, #fbbf24)' }}>
              <Rocket className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-[16px] font-semibold" style={{ color: colors.ink }}>Deploy Agent</h2>
              <p className="text-[11px]" style={{ color: colors.inkTertiary }}>{blueprintName}</p>
            </div>
          </div>
          <button onClick={onCancel} className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{ color: colors.inkTertiary }}
            onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
          {/* Risk Level */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Shield className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[13px] font-medium" style={{ color: colors.ink }}>Risk Level</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {RISK_LEVELS.map(r => (
                <button key={r.id} onClick={() => setConfig(c => ({ ...c, risk_level: r.id }))}
                  className="p-3 rounded-lg text-left transition-all"
                  style={{
                    background: config.risk_level === r.id ? `${r.color}12` : colors.surface2,
                    border: `1px solid ${config.risk_level === r.id ? `${r.color}40` : colors.hairline}`,
                  }}>
                  <span className="text-[12px] font-semibold block mb-0.5" style={{ color: config.risk_level === r.id ? r.color : colors.ink }}>
                    {r.icon} {r.label}
                  </span>
                  <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{r.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Confidence Threshold */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Gauge className="w-4 h-4" style={{ color: colors.primary }} />
                <span className="text-[13px] font-medium" style={{ color: colors.ink }}>Confidence Threshold</span>
              </div>
              <span className="text-[14px] font-bold font-mono" style={{ color: colors.primary }}>
                {(config.confidence_threshold * 100).toFixed(0)}%
              </span>
            </div>
            <input type="range" min="0.50" max="0.99" step="0.01"
              value={config.confidence_threshold}
              onChange={e => setConfig(c => ({ ...c, confidence_threshold: parseFloat(e.target.value) }))}
              className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
              style={{ background: `linear-gradient(90deg, ${colors.primary} ${(config.confidence_threshold - 0.5) / 0.49 * 100}%, ${colors.surface3} ${(config.confidence_threshold - 0.5) / 0.49 * 100}%)` }}
            />
            <div className="flex justify-between mt-1.5 text-[10px]" style={{ color: colors.inkTertiary }}>
              <span>50% (Lenient)</span>
              <span>99% (Strict)</span>
            </div>
          </div>

          {/* HITL Mode */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[13px] font-medium" style={{ color: colors.ink }}>Human-in-the-Loop</span>
            </div>
            <div className="space-y-2">
              {HITL_MODES.map(m => (
                <button key={m.id} onClick={() => setConfig(c => ({ ...c, hitl_mode: m.id }))}
                  className="w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all"
                  style={{
                    background: config.hitl_mode === m.id ? `${colors.primary}08` : colors.surface2,
                    border: `1px solid ${config.hitl_mode === m.id ? `${colors.primary}40` : colors.hairline}`,
                  }}>
                  <div className="w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
                    style={{ border: `2px solid ${config.hitl_mode === m.id ? colors.primary : colors.hairlineStrong}` }}>
                    {config.hitl_mode === m.id && (
                      <div className="w-2 h-2 rounded-full" style={{ background: colors.primary }} />
                    )}
                  </div>
                  <div>
                    <span className="text-[12px] font-medium block" style={{ color: config.hitl_mode === m.id ? colors.ink : colors.inkMuted }}>{m.label}</span>
                    <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{m.desc}</span>
                  </div>
                </button>
              ))}
            </div>

            {/* HITL Threshold (conditional only) */}
            {config.hitl_mode === 'CONDITIONAL' && (
              <div className="mt-3 p-3 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Escalate to human when confidence below:</span>
                  <span className="text-[12px] font-bold font-mono" style={{ color: colors.warning }}>
                    {(config.hitl_threshold * 100).toFixed(0)}%
                  </span>
                </div>
                <input type="range" min="0.30" max="0.95" step="0.05"
                  value={config.hitl_threshold}
                  onChange={e => setConfig(c => ({ ...c, hitl_threshold: parseFloat(e.target.value) }))}
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                  style={{ background: `linear-gradient(90deg, ${colors.warning} ${(config.hitl_threshold - 0.3) / 0.65 * 100}%, ${colors.surface3} ${(config.hitl_threshold - 0.3) / 0.65 * 100}%)` }}
                />
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          <button onClick={onCancel}
            className="px-4 py-2 rounded-lg text-[13px] font-medium transition-colors"
            style={{ color: colors.inkSubtle }}
            onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            Cancel
          </button>
          <button onClick={() => onDeploy(config)}
            className="flex items-center gap-2 px-5 py-2 rounded-lg text-[13px] font-semibold transition-all text-white"
            style={{ background: 'linear-gradient(135deg, #5e6ad2, #828fff)', boxShadow: '0 2px 8px rgba(94,106,210,0.3)' }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}>
            <Zap className="w-4 h-4" /> Deploy Agent
          </button>
        </div>
      </div>
    </div>
  );
}
