import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import {
  Cpu, DollarSign, Radio, BarChart3, AlertTriangle, CheckCircle,
  Loader2, RefreshCw, Zap, Shield, Activity, Server, CircuitBoard, Heart
} from 'lucide-react';

type Tab = 'models' | 'cost' | 'agents';

export default function InfrastructureDashboard({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('models');
  const [models, setModels] = useState<any[]>([]);
  const [costData, setCostData] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getModelRegistry().catch(() => []),
      api.getCostTelemetry(24).catch(() => null),
      api.getAgentRegistry().catch(() => []),
    ]).then(([m, c, a]) => {
      setModels(m || []);
      setCostData(c);
      setAgents(a || []);
      setLoading(false);
    });
  }, []);

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: 'models', label: 'Model Registry', icon: Cpu },
    { id: 'cost', label: 'Cost Governor', icon: DollarSign },
    { id: 'agents', label: 'Agent Protocol', icon: Radio },
  ];

  const tierColor = (t: string) => {
    if (t === 'FAST') return '#22c55e';
    if (t === 'STANDARD') return '#3b82f6';
    if (t === 'DEEP') return '#8b5cf6';
    return '#f59e0b';
  };

  const circuitColor = (s: string) => s === 'CLOSED' ? '#22c55e' : s === 'HALF_OPEN' ? '#f59e0b' : '#ef4444';
  const healthColor = (s: string) => s === 'HEALTHY' ? '#22c55e' : s === 'DEGRADED' ? '#f59e0b' : '#ef4444';

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="flex items-center gap-1 px-6 py-2 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-medium transition-all"
            style={{
              background: tab === t.id ? colors.primary + '18' : 'transparent',
              color: tab === t.id ? colors.primary : colors.inkSubtle,
            }}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.inkSubtle }} />
          </div>
        )}

        {/* N1: Model Registry */}
        {!loading && tab === 'models' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Model Registry & 4-Tier Routing</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Every request routed to optimal tier: Fast (Haiku) → Standard (Sonnet) → Deep (Opus) → Vertical
              </p>
            </div>

            {/* Tier Overview */}
            <div className="grid grid-cols-4 gap-3">
              {['FAST', 'STANDARD', 'DEEP', 'VERTICAL'].map(tier => {
                const count = models.filter(m => m.tier === tier).length;
                const labels: Record<string, string> = { FAST: '<$0.004/task', STANDARD: '<$0.02/task', DEEP: '<$0.04/task', VERTICAL: '<$0.01/task' };
                return (
                  <div key={tier} className="p-3 rounded-xl text-center" style={{ background: tierColor(tier) + '10', border: `1px solid ${tierColor(tier)}20` }}>
                    <div className="text-[10px] font-bold" style={{ color: tierColor(tier) }}>TIER: {tier}</div>
                    <div className="text-[20px] font-bold mt-1">{count}</div>
                    <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{labels[tier]}</div>
                  </div>
                );
              })}
            </div>

            {/* Model Table */}
            <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
              <div className="grid grid-cols-8 text-[10px] font-semibold uppercase tracking-wider px-4 py-2.5"
                style={{ background: colors.surface1, color: colors.inkSubtle }}>
                <div className="col-span-2">Model</div>
                <div>Provider</div>
                <div>Tier</div>
                <div className="text-center">Latency</div>
                <div className="text-center">Success</div>
                <div className="text-center">Cost/1k</div>
                <div className="text-center">Status</div>
              </div>
              {models.length === 0 ? (
                <div className="px-4 py-10 text-center text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                  No models registered yet
                </div>
              ) : models.map((m, i) => (
                <div key={m.id} className="grid grid-cols-8 items-center px-4 py-2.5 text-[12px]"
                  style={{ borderTop: `1px solid ${colors.hairline}` }}>
                  <div className="col-span-2 font-mono text-[11px]">{m.model_name}</div>
                  <div className="capitalize">{m.provider}</div>
                  <div><span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: tierColor(m.tier) + '20', color: tierColor(m.tier) }}>{m.tier}</span></div>
                  <div className="text-center font-mono text-[11px]">{m.avg_latency_ms ?? '-'}ms</div>
                  <div className="text-center font-mono text-[11px]" style={{ color: (m.success_rate ?? 0) >= 0.95 ? '#22c55e' : '#f59e0b' }}>{m.success_rate != null ? (m.success_rate * 100).toFixed(1) + '%' : '-'}</div>
                  <div className="text-center font-mono text-[11px]">{m.cost_per_1k_input != null ? `$${m.cost_per_1k_input}` : '-'}</div>
                  <div className="text-center">
                    {m.is_canary ? (
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#f59e0b20', color: '#f59e0b' }}>CANARY</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>ACTIVE</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* N2: Cost Governor */}
        {!loading && tab === 'cost' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Inference Cost Governor</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Token budgets, real-time telemetry, and cost attribution per model/agent/workflow
              </p>
            </div>
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: 'Total Tokens (24h)', value: costData?.total_tokens != null ? costData.total_tokens.toLocaleString() : '-', color: colors.primary },
                { label: 'Total Cost (24h)', value: costData?.total_cost_usd != null ? `$${costData.total_cost_usd.toFixed(2)}` : '-', color: '#22c55e' },
                { label: 'Avg Cost/Task', value: costData?.avg_cost_per_task != null ? `$${costData.avg_cost_per_task.toFixed(3)}` : '-', color: '#f59e0b' },
                { label: 'Budget Used', value: costData?.budget?.usage_pct != null ? `${costData.budget.usage_pct}%` : '-', color: '#8b5cf6' },
              ].map(s => (
                <div key={s.label} className="p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>{s.label}</div>
                  <div className="text-[22px] font-bold" style={{ color: s.value === '-' ? colors.inkSubtle : s.color }}>{s.value}</div>
                </div>
              ))}
            </div>
            <div style={card}>
              <h3 className="text-[13px] font-semibold mb-3">Cost by Model Tier</h3>
              <div className="space-y-2">
                {['FAST', 'STANDARD', 'DEEP'].map(tier => {
                  const tierData = costData?.by_tier?.[tier];
                  if (!tierData) {
                    return (
                      <div key={tier} className="flex items-center gap-3">
                        <span className="text-[11px] font-mono w-20" style={{ color: tierColor(tier) }}>{tier}</span>
                        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>No data for this tier</span>
                      </div>
                    );
                  }
                  const totalTokens = costData?.total_tokens || 1;
                  const pct = (tierData.tokens / Math.max(totalTokens, 1)) * 100;
                  return (
                    <div key={tier} className="flex items-center gap-3">
                      <span className="text-[11px] font-mono w-20" style={{ color: tierColor(tier) }}>{tier}</span>
                      <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tierColor(tier) }} />
                      </div>
                      <span className="text-[11px] font-mono w-24 text-right">{tierData.tokens?.toLocaleString()} tok</span>
                      <span className="text-[11px] font-mono w-16 text-right" style={{ color: '#22c55e' }}>${(tierData.cost || 0).toFixed(2)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* N3: Agent Protocol */}
        {!loading && tab === 'agents' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Agent Protocol & Circuit Breakers</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                {agents.length} registered agents. Circuit breakers prevent cascade failures.
              </p>
            </div>
            {agents.length === 0 ? (
              <div className="py-10 text-center text-[12px]" style={{ color: colors.inkSubtle }}>
                No agents registered yet
              </div>
            ) : (
            <div className="grid grid-cols-1 gap-3">
              {agents.map(a => (
                <div key={a.id} className="flex items-center gap-4 p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: healthColor(a.health_status) + '15' }}>
                    <Heart className="w-5 h-5" style={{ color: healthColor(a.health_status) }} />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold">{a.agent_name}</span>
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: colors.primary + '15', color: colors.primary }}>{a.agent_type}</span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[10px]" style={{ color: colors.inkSubtle }}>
                      <span>Capabilities: {(a.capabilities || []).join(', ')}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-[11px]">
                    <div className="text-center">
                      <div className="font-mono font-bold">{a.current_load}/{a.max_concurrent}</div>
                      <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Load</div>
                    </div>
                    <div className="text-center">
                      <div className="font-bold" style={{ color: circuitColor(a.circuit_state) }}>{a.circuit_state}</div>
                      <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Circuit</div>
                    </div>
                    <div className="text-center">
                      <div className="font-bold" style={{ color: healthColor(a.health_status) }}>{a.health_status}</div>
                      <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Health</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
