import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import {
  Network, Sliders, FileSearch, BarChart3, Workflow, Eye, FileText,
  TrendingDown, TrendingUp, Search, Filter, Download, Loader2,
  GitBranch, AlertTriangle, CheckCircle, Clock, ArrowRight, Layers
} from 'lucide-react';

type Tab = 'graph' | 'audit';

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

  // Real deterministic layout: nodes on a circle (stable, no random), edges drawn
  // between their ACTUAL source/target node positions so the lines represent real
  // relationships (the previous version hashed positions by index, so the lines
  // were meaningless). Avg confidence is computed from the real nodes.
  const layout = React.useMemo(() => {
    const nodes = (graphData?.nodes || []).slice(0, 40);
    const N = Math.max(1, nodes.length);
    const cx = 400, cy = 200, R = 155;
    const pos: Record<string, { x: number; y: number }> = {};
    nodes.forEach((n: any, i: number) => {
      const a = (2 * Math.PI * i) / N - Math.PI / 2;
      pos[String(n.id ?? i)] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) };
    });
    const avgConf = nodes.length
      ? nodes.reduce((s: number, n: any) => s + (Number(n.confidence) || 0), 0) / nodes.length
      : 0;
    return { nodes, pos, avgConf };
  }, [graphData]);

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: 'graph', label: 'Knowledge Graph Explorer', icon: Network },
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

            {/* Graph Visualization Area — real layout: edges connect actual nodes */}
            <div className="rounded-xl border relative overflow-hidden" style={{ borderColor: colors.hairline, height: 400, background: colors.surface1 }}>
              <svg width="100%" height="100%" viewBox="0 0 800 400">
                {(graphData?.edges || []).map((e: any, i: number) => {
                  const s = layout.pos[String(e.source ?? e.from ?? e.src)];
                  const t = layout.pos[String(e.target ?? e.to ?? e.dst)];
                  if (!s || !t) return null;
                  return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke={colors.hairline} strokeWidth="1" opacity="0.5" />;
                })}
                {layout.nodes.map((n: any, i: number) => {
                  const p = layout.pos[String(n.id ?? i)];
                  if (!p) return null;
                  const groupColor = n.group === 'rule' ? '#8b5cf6' : n.group === 'skill' ? '#3b82f6' :
                    n.group === 'workflow' ? '#22c55e' : n.group === 'employee' ? '#f59e0b' : colors.primary;
                  return (
                    <g key={n.id ?? i}>
                      <circle cx={p.x} cy={p.y} r={10 + (Number(n.confidence) || 0.5) * 8} fill={groupColor + '30'} stroke={groupColor} strokeWidth="2" />
                      <text x={p.x} y={p.y + 22} textAnchor="middle" fill={colors.inkSubtle} fontSize="9" fontFamily="monospace">
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
                { label: 'Avg Confidence', value: layout.avgConf.toFixed(2), icon: BarChart3, color: '#f59e0b' },
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
