import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import {
  Network, Sliders, FileSearch, BarChart3, Workflow, Eye, FileText,
  TrendingDown, TrendingUp, Search, Filter, Download, Loader2,
  GitBranch, AlertTriangle, CheckCircle, Clock, ArrowRight, Layers
} from 'lucide-react';

type Tab = 'graph' | 'scenario' | 'confidence' | 'audit';

export default function AnalystWorkspace({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('graph');
  const [graphData, setGraphData] = useState<any>(null);
  const [ledger, setLedger] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getGraph().catch(() => null),
      api.getGlobalLedger().catch(() => ({ ledger: [] })),
    ]).then(([g, l]) => {
      setGraphData(g);
      setLedger(l?.ledger || []);
      setLoading(false);
    });
  }, []);

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: 'graph', label: 'Knowledge Graph Explorer', icon: Network },
    { id: 'scenario', label: 'Scenario Modeller', icon: Sliders },
    { id: 'confidence', label: 'Confidence Explorer', icon: BarChart3 },
    { id: 'audit', label: 'Audit Log Browser', icon: FileText },
  ];

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px',
  };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Tab Bar */}
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
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
          </div>
        )}

        {/* Knowledge Graph Explorer */}
        {!loading && tab === 'graph' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">Knowledge Graph Explorer</h2>
                <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                  Interactive graph: {graphData?.nodes?.length || 0} nodes, {graphData?.edges?.length || 0} relationships
                </p>
              </div>
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
                  <input placeholder="Search entities..." className="pl-8 pr-3 py-1.5 rounded-lg border text-[12px]"
                    style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink, width: 200 }} />
                </div>
              </div>
            </div>

            {/* Graph Visualization Area */}
            <div className="rounded-xl border relative overflow-hidden" style={{ borderColor: colors.hairline, height: 400, background: colors.surface1 }}>
              {/* Simulated Graph Nodes */}
              <svg width="100%" height="100%" viewBox="0 0 800 400">
                {(graphData?.edges || []).slice(0, 30).map((e: any, i: number) => {
                  const x1 = 100 + (i * 47) % 600;
                  const y1 = 80 + (i * 73) % 250;
                  const x2 = 150 + ((i + 3) * 53) % 600;
                  const y2 = 100 + ((i + 5) * 67) % 250;
                  return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={colors.hairline} strokeWidth="1" opacity="0.5" />;
                })}
                {(graphData?.nodes || []).slice(0, 20).map((n: any, i: number) => {
                  const x = 100 + (i * 47) % 600;
                  const y = 80 + (i * 73) % 250;
                  const groupColor = n.group === 'rule' ? '#8b5cf6' : n.group === 'skill' ? '#3b82f6' :
                    n.group === 'workflow' ? '#22c55e' : n.group === 'employee' ? '#f59e0b' : colors.primary;
                  return (
                    <g key={i}>
                      <circle cx={x} cy={y} r={12 + (n.confidence || 0.5) * 8} fill={groupColor + '30'} stroke={groupColor} strokeWidth="2" />
                      <text x={x} y={y + 24} textAnchor="middle" fill={colors.inkSubtle} fontSize="9" fontFamily="monospace">
                        {(n.label || '').substring(0, 15)}
                      </text>
                    </g>
                  );
                })}
              </svg>
              {/* Legend */}
              <div className="absolute bottom-3 left-3 flex items-center gap-3 px-3 py-1.5 rounded-lg text-[10px]"
                style={{ background: colors.canvas + 'ee', border: `1px solid ${colors.hairline}` }}>
                {[
                  { label: 'Rules', color: '#8b5cf6' },
                  { label: 'Skills', color: '#3b82f6' },
                  { label: 'Workflows', color: '#22c55e' },
                  { label: 'People', color: '#f59e0b' },
                ].map(l => (
                  <span key={l.label} className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ background: l.color }} />
                    {l.label}
                  </span>
                ))}
              </div>
            </div>

            {/* Node Stats */}
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: 'Total Nodes', value: graphData?.nodes?.length || 0, icon: Network, color: colors.primary },
                { label: 'Relationships', value: graphData?.edges?.length || 0, icon: GitBranch, color: '#8b5cf6' },
                { label: 'Clusters', value: new Set((graphData?.nodes || []).map((n: any) => n.group)).size, icon: Layers, color: '#22c55e' },
                { label: 'Avg Confidence', value: '0.72', icon: BarChart3, color: '#f59e0b' },
              ].map(s => (
                <div key={s.label} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  {React.createElement(s.icon, { className: 'w-5 h-5', style: { color: s.color } })}
                  <div>
                    <div className="text-[16px] font-bold">{s.value}</div>
                    <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Scenario Modeller */}
        {!loading && tab === 'scenario' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Scenario Modeller</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>What-if simulation: model proposed changes before execution</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Input Panel */}
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-3">Configure Scenario</h3>
                <div className="space-y-3">
                  <div>
                    <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Change Description</label>
                    <textarea className="w-full p-2.5 rounded-lg border text-[12px] resize-none" rows={3}
                      placeholder="e.g., Restructure Engineering team into 3 sub-departments..."
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
                  </div>
                  <div>
                    <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Target Domain</label>
                    <select className="w-full p-2 rounded-lg border text-[12px]"
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                      <option>Engineering</option><option>HR</option><option>Sales</option><option>Finance</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Risk Tolerance</label>
                    <div className="flex gap-2">
                      {['LOW', 'MEDIUM', 'HIGH'].map(r => (
                        <button key={r} className="flex-1 py-1.5 rounded-lg text-[11px] font-medium border"
                          style={{ borderColor: colors.hairline, background: r === 'MEDIUM' ? colors.primary + '15' : 'transparent',
                            color: r === 'MEDIUM' ? colors.primary : colors.inkSubtle }}>
                          {r}
                        </button>
                      ))}
                    </div>
                  </div>
                  <button className="w-full py-2 rounded-lg text-[12px] font-medium text-white"
                    style={{ background: colors.primary }}>
                    Run Simulation →
                  </button>
                </div>
              </div>

              {/* Results Panel */}
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-3">Simulation Results</h3>
                <div className="space-y-3">
                  <div className="p-3 rounded-lg" style={{ background: '#f59e0b10', border: '1px solid #f59e0b20' }}>
                    <div className="flex items-center gap-2 mb-1">
                      <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} />
                      <span className="text-[12px] font-semibold">Blast Radius Analysis</span>
                    </div>
                    <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
                      12 rules affected • 3 skills require recompilation • 2 agent workflows impacted
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                      <div className="text-[18px] font-bold" style={{ color: '#f59e0b' }}>MEDIUM</div>
                      <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Risk Level</div>
                    </div>
                    <div className="p-2.5 rounded-lg text-center" style={{ background: colors.canvas }}>
                      <div className="text-[18px] font-bold" style={{ color: '#22c55e' }}>72%</div>
                      <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Confidence</div>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    {['Escalation rules need update', 'SLA thresholds affected', 'Skill recompilation required'].map((r, i) => (
                      <div key={i} className="flex items-center gap-2 text-[11px]" style={{ color: colors.inkSubtle }}>
                        <ArrowRight className="w-3 h-3" style={{ color: '#f59e0b' }} /> {r}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Confidence Explorer */}
        {!loading && tab === 'confidence' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">5D Confidence Explorer</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Explore the 5-dimensional confidence vector for any knowledge node
              </p>
            </div>

            {/* Confidence Gate Thresholds */}
            <div style={card}>
              <h3 className="text-[13px] font-semibold mb-3">Agent Execution Gate Thresholds</h3>
              <div className="flex gap-1">
                {[
                  { gate: 'SPECULATIVE', range: '<0.29', color: '#ef4444', desc: 'Log only' },
                  { gate: 'CANDIDATE', range: '0.29-0.59', color: '#f59e0b', desc: 'Human review' },
                  { gate: 'VALIDATED', range: '0.60-0.74', color: '#8b5cf6', desc: 'Execute + 24h rollback' },
                  { gate: 'ENDORSED', range: '0.75-0.94', color: '#3b82f6', desc: 'Auto non-Tier-1' },
                  { gate: 'VERIFIED', range: '≥0.95', color: '#22c55e', desc: 'Full autonomy' },
                ].map((g, i) => (
                  <div key={g.gate} className="flex-1 p-3 rounded-lg text-center" style={{ background: g.color + '10', border: `1px solid ${g.color}20` }}>
                    <div className="text-[9px] font-bold" style={{ color: g.color }}>{g.gate}</div>
                    <div className="text-[14px] font-bold mt-1" style={{ color: g.color }}>{g.range}</div>
                    <div className="text-[9px] mt-1" style={{ color: colors.inkSubtle }}>{g.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* 5D Vector Breakdown */}
            <div style={card}>
              <h3 className="text-[13px] font-semibold mb-3">5-Dimensional Vector</h3>
              <div className="space-y-3">
                {[
                  { dim: 'Source Breadth', value: 0.78, desc: 'No. of independent confirmations', source: 'B2 Signal Accumulator' },
                  { dim: 'Source Authority', value: 0.85, desc: 'Trust tier of connector', source: 'Connector Registry' },
                  { dim: 'Temporal Freshness', value: 0.92, desc: 'Age relative to decay half-life', source: 'B7 Decay Engine' },
                  { dim: 'Human Validation', value: 0.65, desc: 'Expert review and endorsement', source: 'B5 Elicitation + HITL' },
                  { dim: 'Outcome Validation', value: 0.71, desc: 'Track record of past executions', source: 'E2 Governance Audit' },
                ].map(d => {
                  const color = d.value >= 0.8 ? '#22c55e' : d.value >= 0.6 ? '#f59e0b' : '#ef4444';
                  return (
                    <div key={d.dim} className="flex items-center gap-3">
                      <div className="w-36">
                        <div className="text-[11px] font-medium">{d.dim}</div>
                        <div className="text-[9px]" style={{ color: colors.inkSubtle }}>{d.source}</div>
                      </div>
                      <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full transition-all" style={{ width: `${d.value * 100}%`, background: color }} />
                      </div>
                      <span className="text-[12px] font-mono font-bold w-12 text-right" style={{ color }}>{d.value.toFixed(2)}</span>
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 pt-3 border-t flex items-center justify-between" style={{ borderColor: colors.hairline }}>
                <span className="text-[12px] font-semibold">Composite Score (Weighted Harmonic Mean)</span>
                <span className="text-[18px] font-bold" style={{ color: '#3b82f6' }}>0.78</span>
              </div>
            </div>
          </div>
        )}

        {/* Audit Log Browser */}
        {!loading && tab === 'audit' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">Provenance Audit Log</h2>
                <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                  Immutable ledger: {ledger.length} entries with SHA-256 chain hashing
                </p>
              </div>
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-medium"
                style={{ background: colors.primary + '15', color: colors.primary }}>
                <Download className="w-3.5 h-3.5" /> Export PDF
              </button>
            </div>

            <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
              <div className="grid grid-cols-12 gap-0 text-[10px] font-semibold uppercase tracking-wider px-4 py-2.5"
                style={{ background: colors.surface1, color: colors.inkSubtle }}>
                <div className="col-span-2">Timestamp</div>
                <div className="col-span-2">Event Type</div>
                <div className="col-span-1">Actor</div>
                <div className="col-span-1">Confidence</div>
                <div className="col-span-4">Reasoning</div>
                <div className="col-span-2">Chain Hash</div>
              </div>
              {ledger.slice(0, 20).map((e, i) => {
                const typeColor = e.event_type === 'CREATION' ? '#22c55e' : e.event_type === 'VALIDATION' ? '#3b82f6' :
                  e.event_type === 'DECAY' ? '#f59e0b' : colors.primary;
                return (
                  <div key={i} className="grid grid-cols-12 gap-0 items-center px-4 py-2 text-[11px]"
                    style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <div className="col-span-2 font-mono text-[10px]" style={{ color: colors.inkSubtle }}>
                      {e.timestamp ? new Date(e.timestamp).toLocaleString() : '-'}
                    </div>
                    <div className="col-span-2">
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: typeColor + '20', color: typeColor }}>
                        {e.event_type}
                      </span>
                    </div>
                    <div className="col-span-1 text-[10px]" style={{ color: colors.inkSubtle }}>{e.actor_role || '-'}</div>
                    <div className="col-span-1 font-mono">{e.confidence_at?.toFixed(2) || '-'}</div>
                    <div className="col-span-4 truncate" style={{ color: colors.inkSubtle }}>{e.reasoning || '-'}</div>
                    <div className="col-span-2 font-mono text-[9px] truncate" style={{ color: colors.inkSubtle }}>
                      {e.chain_hash?.substring(0, 16) || '-'}…
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
