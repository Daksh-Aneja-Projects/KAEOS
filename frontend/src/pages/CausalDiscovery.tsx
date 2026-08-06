import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import { GitFork, RefreshCw, Info } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError } from '../components/BrainStates';
import DomainIcon from '../components/DomainIcon';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

/**
 * Causal Discovery — an interactive directed graph of the causal links KAEOS
 * inferred between departments from real adverse-event series (lagged
 * cross-correlation). Nodes are departments (sized by trouble volume); a directed
 * edge A→B means A's trouble tends to precede B's. Hover a node to isolate its
 * links; hover an edge for its strength and lag. No mock: honest about thin data.
 */
const CausalDiscovery = () => {
  const { colors } = useTheme();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const load = () => {
    setError(null);
    api.getCausalLinks(60, 0.35)
      .then(d => { setData(d); setLoading(false); })
      .catch((e: any) => { setError(e?.message || 'Failed to load causal graph'); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const W = 900, H = 460, CX = W / 2, CY = H / 2, R = 165;

  // Circular layout of the nodes (deterministic).
  const layout = useMemo(() => {
    const nodes: any[] = data?.nodes || [];
    const pos: Record<string, { x: number; y: number }> = {};
    const n = Math.max(1, nodes.length);
    nodes.forEach((nd, i) => {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      pos[nd.id] = { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) };
    });
    return pos;
  }, [data]);

  if (loading) return <BrainLoading message="Inferring causal structure…" />;
  if (error) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const nodes: any[] = data?.nodes || [];
  const links: any[] = data?.links || [];
  const maxAdv = Math.max(1, ...nodes.map(n => n.adverse_total));
  const edgeColor = (l: any) => (l.strength >= 0.7 ? '#ef4444' : l.strength >= 0.5 ? '#f59e0b' : '#8b5cf6');

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <style>{`
        @keyframes causalDash { to { stroke-dashoffset: -24; } }
        .causal-edge { stroke-dasharray: 6 6; animation: causalDash 1.2s linear infinite; }
      `}</style>
      <div className={`${PAGE_PAD} space-y-5`}>
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
            <GitFork className="w-6 h-6 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="text-[24px] font-bold tracking-tight">Causal Discovery</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              Likely cause→effect links between departments, inferred from real adverse-event timing. An arrow A→B means A's trouble tends to precede B's.
            </p>
          </div>
          <button onClick={() => { setLoading(true); load(); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium self-center"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
            <RefreshCw className="w-3.5 h-3.5" /> Recompute
          </button>
        </div>

        {data?.insufficient || nodes.length === 0 ? (
          <div className="rounded-xl p-8 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <Info className="w-6 h-6 mx-auto mb-2" style={{ color: colors.inkSubtle }} />
            <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
              {data?.reason ? `Not enough operational history to infer causal structure yet (${data.reason}).`
                : 'No causal links crossed the strength threshold. As departments accumulate adverse events over more days, links will appear.'}
            </p>
          </div>
        ) : (
          <>
            <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }} ref={wrapRef}>
              <div className="overflow-x-auto">
                <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: 640 }}>
                  <defs>
                    {['#ef4444', '#f59e0b', '#8b5cf6'].map(c => (
                      <marker key={c} id={`arrow-${c.slice(1)}`} viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                        <path d="M0,0 L10,5 L0,10 z" fill={c} />
                      </marker>
                    ))}
                  </defs>
                  {/* edges */}
                  {links.map((l, i) => {
                    const a = layout[l.source], b = layout[l.target];
                    if (!a || !b) return null;
                    // shorten to node edge
                    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
                    const ux = dx / len, uy = dy / len;
                    const rA = 16 + 10 * ((nodes.find(n => n.id === l.source)?.adverse_total || 0) / maxAdv);
                    const rB = 16 + 10 * ((nodes.find(n => n.id === l.target)?.adverse_total || 0) / maxAdv);
                    const x1 = a.x + ux * rA, y1 = a.y + uy * rA, x2 = b.x - ux * (rB + 8), y2 = b.y - uy * (rB + 8);
                    const dim = (hoverNode && l.source !== hoverNode && l.target !== hoverNode) || (hoverEdge != null && hoverEdge !== i);
                    const c = edgeColor(l);
                    return (
                      <g key={i} opacity={dim ? 0.12 : 1} onMouseEnter={() => setHoverEdge(i)} onMouseLeave={() => setHoverEdge(null)} style={{ cursor: 'pointer' }}>
                        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={c}
                          strokeWidth={1 + l.strength * 3} className={l.kind === 'leads' ? 'causal-edge' : undefined}
                          markerEnd={l.kind === 'leads' ? `url(#arrow-${c.slice(1)})` : undefined} />
                      </g>
                    );
                  })}
                  {/* nodes */}
                  {nodes.map(nd => {
                    const p = layout[nd.id]; if (!p) return null;
                    const r = 16 + 10 * (nd.adverse_total / maxAdv);
                    const active = !hoverNode || hoverNode === nd.id ||
                      links.some(l => (l.source === hoverNode && l.target === nd.id) || (l.target === hoverNode && l.source === nd.id));
                    return (
                      <g key={nd.id} opacity={active ? 1 : 0.2} onMouseEnter={() => setHoverNode(nd.id)} onMouseLeave={() => setHoverNode(null)} style={{ cursor: 'pointer' }}>
                        <circle cx={p.x} cy={p.y} r={r} fill={colors.surface2} stroke={colors.primary} strokeWidth={hoverNode === nd.id ? 2.5 : 1.5} />
                        <text x={p.x} y={p.y + r + 14} textAnchor="middle" className="text-[11px]" fill={colors.ink} style={{ fontWeight: 600 }}>
                          {nd.label}
                        </text>
                        <text x={p.x} y={p.y + 4} textAnchor="middle" className="text-[11px]" fill={colors.inkSubtle}>
                          {nd.adverse_total}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </div>
              <div className="flex items-center gap-4 mt-1 text-[11px]" style={{ color: colors.inkSubtle }}>
                <span>node size = adverse-event volume</span>
                <span className="flex items-center gap-1"><span className="w-4 h-0.5 inline-block" style={{ background: '#ef4444' }} /> strong (≥0.7)</span>
                <span className="flex items-center gap-1"><span className="w-4 h-0.5 inline-block" style={{ background: '#f59e0b' }} /> moderate</span>
                <span>animated arrow = leads by 1 day</span>
              </div>
            </div>

            {/* Ranked causal links list */}
            <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="px-5 py-3 border-b text-[13px] font-medium" style={{ borderColor: colors.hairline }}>
                Inferred links ({links.length}) · {humanize(data.method)}
              </div>
              {links.length === 0 && <div className="p-5 text-center text-[12px]" style={{ color: colors.inkTertiary }}>No links above threshold.</div>}
              {links.map((l, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-2.5 border-b" style={{ borderColor: colors.hairline, background: hoverEdge === i ? colors.surface2 : 'transparent' }}
                  onMouseEnter={() => setHoverEdge(i)} onMouseLeave={() => setHoverEdge(null)}>
                  <DomainIcon hint={l.source} size={18} />
                  <span className="text-[12px] font-medium" style={{ color: colors.ink }}>{humanize(l.source)}</span>
                  <span className="text-[13px]" style={{ color: edgeColor(l) }}>{l.kind === 'leads' ? '→' : '↔'}</span>
                  <DomainIcon hint={l.target} size={18} />
                  <span className="text-[12px] font-medium" style={{ color: colors.ink }}>{humanize(l.target)}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full ml-2" style={{ background: edgeColor(l) + '22', color: edgeColor(l) }}>
                    {l.kind === 'leads' ? `leads by ${l.lag_days}d` : 'co-occurs'}
                  </span>
                  <span className="ml-auto text-[12px] font-mono" style={{ color: colors.inkSubtle }}>r = {l.strength.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default CausalDiscovery;
