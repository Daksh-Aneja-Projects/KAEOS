/* eslint-disable react-hooks/preserve-manual-memoization --
   The force-layout `step` is a manual requestAnimationFrame physics loop that
   mutates refs in place; the React Compiler cannot preserve its useCallback
   memoization and skips the component, which is the intended behavior here. */
import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { Network, MousePointer2, Maximize2, Flame, X, GitBranch } from 'lucide-react';
import type { GraphData } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';

/**
 * Epistemic Topology - a live, physics-simulated knowledge graph of the
 * company's workflows and the rules that govern them. Force-directed layout
 * (repulsion + edge springs + centering), theme-aware, and fully interactive:
 * drag to reposition, hover to isolate a node's neighborhood, click to inspect,
 * scroll to zoom, drag the canvas to pan.
 */

type Sim = {
  id: string; label: string; group: string; department?: string;
  confidence?: number; domain?: string;
  x: number; y: number; vx: number; vy: number; deg: number;
};

const W = 1000, H = 640;

export default function TopologyVisualizer() {
  const { colors } = useTheme();
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const [view, setView] = useState({ zoom: 1, panX: 0, panY: 0 });

  const nodesRef = useRef<Sim[]>([]);
  const rafRef = useRef<number | null>(null);
  const alphaRef = useRef(1);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ id: string | null; panning: boolean; lastX: number; lastY: number }>({ id: null, panning: false, lastX: 0, lastY: 0 });

  // Node colours by type, from the active theme.
  const nodeColor = useCallback((group: string) => {
    if (group === 'workflow') return colors.primary;
    if (group === 'rule') return colors.success;
    return colors.info;
  }, [colors]);

  useEffect(() => {
    let cancelled = false;
    api.getGraph()
      .then(d => { if (!cancelled) { setGraph(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e.message || 'Could not load the knowledge graph'); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  // Build the simulation nodes once the graph arrives.
  useEffect(() => {
    if (!graph) return;
    const deg: Record<string, number> = {};
    graph.edges.forEach(e => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
    const n = graph.nodes.length;
    nodesRef.current = graph.nodes.map((node, i) => {
      // Seed positions on a spread ring so the sim opens up cleanly (no RNG - deterministic).
      const ang = (i / Math.max(1, n)) * Math.PI * 2;
      const rad = 180 + (i % 5) * 40;
      return {
        ...node, deg: deg[node.id] || 0,
        x: W / 2 + Math.cos(ang) * rad, y: H / 2 + Math.sin(ang) * rad,
        vx: 0, vy: 0,
      };
    });
    alphaRef.current = 1;
    startLoop();
    return stopLoop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const adjacency = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    (graph?.edges || []).forEach(e => {
      (m[e.source] = m[e.source] || new Set()).add(e.target);
      (m[e.target] = m[e.target] || new Set()).add(e.source);
    });
    return m;
  }, [graph]);

  const stopLoop = useCallback(() => { if (rafRef.current) cancelAnimationFrame(rafRef.current); rafRef.current = null; }, []);

  const step = useCallback(() => {
    const nodes = nodesRef.current;
    const edges = graph?.edges || [];
    const alpha = alphaRef.current;
    const REPULSION = 260000, SPRING = 0.02, REST = 150, CENTER = 0.012, DAMP = 0.85;

    // Repulsion (all pairs).
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy; if (d2 < 1) d2 = 1;
        const f = (REPULSION / d2) * alpha;
        const d = Math.sqrt(d2); const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    // Edge springs.
    const byId: Record<string, Sim> = {};
    nodes.forEach(n => byId[n.id] = n);
    edges.forEach(e => {
      const s = byId[e.source], t = byId[e.target]; if (!s || !t) return;
      const dx = t.x - s.x, dy = t.y - s.y; const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - REST) * SPRING * alpha; const fx = (dx / d) * f, fy = (dy / d) * f;
      s.vx += fx; s.vy += fy; t.vx -= fx; t.vy -= fy;
    });
    // Centering + integrate.
    const dragId = dragRef.current.id;
    nodes.forEach(n => {
      n.vx += (W / 2 - n.x) * CENTER * alpha;
      n.vy += (H / 2 - n.y) * CENTER * alpha;
      if (n.id === dragId) { n.vx = 0; n.vy = 0; return; }
      n.vx *= DAMP; n.vy *= DAMP;
      n.x += n.vx * 0.1; n.y += n.vy * 0.1;
    });
    alphaRef.current = Math.max(0.02, alpha * 0.985);
  }, [graph]);

  const startLoop = useCallback(() => {
    stopLoop();
    const loop = () => {
      step();
      setTick(t => (t + 1) % 1_000_000);
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
  }, [step, stopLoop]);

  // Reheat on demand.
  const reheat = () => { alphaRef.current = 1; if (!rafRef.current) startLoop(); };

  // Screen -> sim coordinate mapping (accounts for viewBox + zoom/pan).
  const toSim = (clientX: number, clientY: number) => {
    const svg = svgRef.current; if (!svg) return { x: 0, y: 0 };
    const r = svg.getBoundingClientRect();
    const sx = ((clientX - r.left) / r.width) * W;
    const sy = ((clientY - r.top) / r.height) * H;
    return { x: (sx - view.panX) / view.zoom, y: (sy - view.panY) / view.zoom };
  };

  const onPointerDownNode = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    dragRef.current.id = id;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    reheat();
  };
  const onPointerDownBg = (e: React.PointerEvent) => {
    dragRef.current.panning = true; dragRef.current.lastX = e.clientX; dragRef.current.lastY = e.clientY;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragRef.current.id) {
      const p = toSim(e.clientX, e.clientY);
      const n = nodesRef.current.find(x => x.id === dragRef.current.id);
      if (n) { n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0; }
    } else if (dragRef.current.panning) {
      const dx = e.clientX - dragRef.current.lastX, dy = e.clientY - dragRef.current.lastY;
      const svg = svgRef.current; const r = svg?.getBoundingClientRect();
      const scaleX = r ? W / r.width : 1, scaleY = r ? H / r.height : 1;
      setView(v => ({ ...v, panX: v.panX + dx * scaleX, panY: v.panY + dy * scaleY }));
      dragRef.current.lastX = e.clientX; dragRef.current.lastY = e.clientY;
    }
  };
  const onPointerUp = () => { dragRef.current.id = null; dragRef.current.panning = false; };
  const onWheel = (e: React.WheelEvent) => {
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    setView(v => ({ ...v, zoom: Math.min(3, Math.max(0.4, v.zoom * factor)) }));
  };
  const resetView = () => setView({ zoom: 1, panX: 0, panY: 0 });

  useEffect(() => stopLoop, [stopLoop]);

  const focus = hovered || selected;
  const isDimmed = (id: string) => !!focus && id !== focus && !(adjacency[focus]?.has(id));
  const edgeActive = (s: string, t: string) => !!focus && (s === focus || t === focus);

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}` };
  const sel = selected ? nodesRef.current.find(n => n.id === selected) : null;
  const nodeR = (deg: number) => 7 + Math.min(10, deg * 1.6);

  const counts = useMemo(() => {
    const wf = (graph?.nodes || []).filter(n => n.group === 'workflow').length;
    const rl = (graph?.nodes || []).filter(n => n.group === 'rule').length;
    return { wf, rl };
  }, [graph]);

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5 h-full flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap shrink-0">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <GitBranch className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Knowledge Graph</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                A living knowledge graph - how every workflow connects to the rules that govern it.
                {graph && <> {graph.nodes.length} nodes · {graph.edges.length} edges · live from the DB.</>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={reheat} title="Re-run the layout"
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium hover:opacity-80"
              style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
              <Flame className="w-3.5 h-3.5" /> Re-layout
            </button>
            <button onClick={resetView} title="Reset zoom & pan"
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium hover:opacity-80"
              style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
              <Maximize2 className="w-3.5 h-3.5" /> Fit
            </button>
          </div>
        </div>

        {/* Canvas */}
        <div className="flex-1 rounded-2xl overflow-hidden relative min-h-[500px]" style={card}>
          {/* dotted backdrop */}
          <div className="absolute inset-0" style={{
            backgroundImage: `radial-gradient(${colors.hairline} 1px, transparent 1px)`,
            backgroundSize: '26px 26px', opacity: 0.5,
          }} />

          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
                <span className="text-[13px]" style={{ color: colors.inkSubtle }}>Simulating the knowledge graph…</span>
              </div>
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px]" style={{ color: colors.error }}>{error}</div>
          )}
          {!loading && !error && graph && graph.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px]" style={{ color: colors.inkSubtle }}>No graph data yet.</div>
          )}

          {/* Legend */}
          {!loading && graph && graph.nodes.length > 0 && (
            <div className="absolute top-4 left-4 z-10 p-3 rounded-xl backdrop-blur-sm flex flex-col gap-2"
              style={{ background: colors.surface1 + 'cc', border: `1px solid ${colors.hairline}` }}>
              <div className="text-[9px] font-bold uppercase tracking-widest flex items-center gap-1.5" style={{ color: colors.inkSubtle }}>
                <Network className="w-3 h-3" /> Node types
              </div>
              <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkMuted }}>
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: colors.primary }} /> Workflow <span style={{ color: colors.inkTertiary }}>({counts.wf})</span>
              </div>
              <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkMuted }}>
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: colors.success }} /> Rule <span style={{ color: colors.inkTertiary }}>({counts.rl})</span>
              </div>
            </div>
          )}

          {/* Detail panel */}
          {sel && (
            <div className="absolute top-4 right-4 z-10 w-72 p-4 rounded-2xl backdrop-blur-md"
              style={{ background: colors.surface1 + 'f0', border: `1px solid ${colors.hairline}`, boxShadow: '0 8px 30px rgba(0,0,0,0.25)' }}>
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: nodeColor(sel.group) }} />
                  <h3 className="text-[14px] font-semibold truncate" style={{ color: colors.ink }}>{sel.label}</h3>
                </div>
                <button onClick={() => setSelected(null)} style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
              </div>
              <div className="space-y-2.5 text-[12px]">
                <Row label="Type" value={sel.group} colors={colors} cap />
                {sel.department && <Row label="Department" value={sel.department} colors={colors} cap />}
                {sel.domain && <Row label="Domain" value={sel.domain} colors={colors} />}
                {sel.confidence !== undefined && (
                  <div>
                    <div className="text-[11px] mb-1" style={{ color: colors.inkSubtle }}>Confidence</div>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
                        <div className="h-full rounded-full" style={{ width: `${(sel.confidence || 0) * 100}%`, background: colors.success }} />
                      </div>
                      <span className="tabular-nums" style={{ color: colors.ink }}>{sel.confidence?.toFixed(2)}</span>
                    </div>
                  </div>
                )}
                <Row label="Connections" value={String(sel.deg)} colors={colors} />
              </div>
            </div>
          )}

          {/* Graph */}
          {!loading && graph && graph.nodes.length > 0 && (
            <svg ref={svgRef} className="absolute inset-0 w-full h-full touch-none"
              viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
              onPointerDown={onPointerDownBg} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}
              onWheel={onWheel}
              style={{ cursor: dragRef.current.panning ? 'grabbing' : 'grab' }}>
              <g transform={`translate(${view.panX} ${view.panY}) scale(${view.zoom})`}>
                {/* Edges */}
                {graph.edges.map((e, i) => {
                  const s = nodesRef.current.find(n => n.id === e.source);
                  const t = nodesRef.current.find(n => n.id === e.target);
                  if (!s || !t) return null;
                  const active = edgeActive(e.source, e.target);
                  const dim = !!focus && !active;
                  return (
                    <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                      stroke={active ? colors.primary : colors.hairlineStrong}
                      strokeWidth={active ? 2 : 1}
                      opacity={dim ? 0.08 : active ? 0.9 : 0.35} />
                  );
                })}
                {/* Nodes */}
                {nodesRef.current.map(n => {
                  const c = nodeColor(n.group);
                  const dim = isDimmed(n.id);
                  const isSel = selected === n.id;
                  const r = nodeR(n.deg);
                  return (
                    <g key={n.id} transform={`translate(${n.x} ${n.y})`}
                      onPointerDown={(e) => onPointerDownNode(e, n.id)}
                      onClick={(e) => { e.stopPropagation(); setSelected(selected === n.id ? null : n.id); }}
                      onPointerEnter={() => setHovered(n.id)} onPointerLeave={() => setHovered(null)}
                      style={{ cursor: 'pointer' }} opacity={dim ? 0.2 : 1}>
                      {(isSel || hovered === n.id) && (
                        <circle r={r + 6} fill={c} opacity={0.18} />
                      )}
                      <circle r={r} fill={colors.surface1} stroke={c} strokeWidth={isSel ? 3 : 2} />
                      <circle r={r - 3} fill={c} opacity={0.85} />
                      <text y={r + 12} textAnchor="middle" fontSize={11}
                        fill={dim ? colors.inkTertiary : colors.inkMuted}
                        style={{ pointerEvents: 'none', userSelect: 'none', fontWeight: isSel ? 700 : 500 }}>
                        {n.label.length > 22 ? n.label.slice(0, 22) + '…' : n.label}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          )}

          {/* Footer hint */}
          {!loading && graph && graph.nodes.length > 0 && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 px-4 py-2 rounded-full backdrop-blur-sm flex items-center gap-2 text-[12px]"
              style={{ background: colors.surface1 + 'cc', border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
              <MousePointer2 className="w-3.5 h-3.5" /> Drag nodes · hover to isolate · click to inspect · scroll to zoom
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, colors, cap }: { label: string; value: string; colors: Record<string, string>; cap?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span style={{ color: colors.inkSubtle }}>{label}</span>
      <span className={cap ? 'capitalize' : ''} style={{ color: colors.ink }}>{value}</span>
    </div>
  );
}
