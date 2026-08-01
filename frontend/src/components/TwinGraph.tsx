import React, { useCallback, useEffect, useMemo, useRef } from 'react';

/**
 * Enterprise Twin - living force-directed graph.
 *
 * The twin is the headline "living organization" visual, so it must feel alive:
 *  - a real force simulation (springs + repulsion + cluster anchoring) that
 *    never fully freezes - the org breathes;
 *  - drag any node and watch its neighborhood react; wheel to zoom, drag the
 *    background to pan;
 *  - energy particles travelling along links (signal flow);
 *  - and the payoff: when a shock is injected, a shockwave ring expands from
 *    the target and the blast radius lights up in propagation order - each
 *    impacted node is hit at a delay proportional to its graph distance and
 *    receives a physical impulse away from the epicenter.
 *
 * Rendering is imperative (refs + requestAnimationFrame mutating SVG attrs);
 * React renders the scene skeleton only when the data identity changes, so the
 * simulation runs at full frame rate with zero per-frame reconciliation.
 * No external physics library - the whole simulation is ~120 lines below.
 */

interface GraphNode { id: string; name: string; label: string; [k: string]: any }
interface GraphLink { source: string; target: string; type?: string }
interface GraphData { nodes?: GraphNode[]; links?: GraphLink[] }

/** A shock event to visualize. Change `ts` to re-trigger. */
export interface ShockPulse {
  targetId: string;
  impactedIds: string[];
  severity?: number;   // 0-100
  ts: number;
}

const TYPE_COLORS: Record<string, string> = {
  Department: '#5e6ad2',
  Capability: '#06b6d4',
  Agent: '#8b5cf6',
  Process: '#22c55e',
  Employee: '#f59e0b',
  Vendor: '#ec4899',
  Project: '#ef4444',
  // Cross-domain headline entities — one hue per record type.
  Customer: '#22d3ee',       // finance customers (cyan)
  Account: '#a78bfa',        // sales accounts (violet)
  Ticket: '#fb923c',         // support tickets (orange)
  Contract: '#f472b6',       // legal contracts (pink)
  Incident: '#f87171',       // engineering incidents (red)
  PurchaseOrder: '#a3e635',  // operations POs (lime)
  // Neural Map entities.
  Task: '#f59e0b',           // skills an agent runs (amber)
  Connector: '#22d3ee',      // integrations feeding a department (cyan)
  Brain: '#fb923c',          // the company knowledge core (warm coral)
  Knowledge: '#fbbf24',      // ingested notes/documents
};
/** One hue per department: hub node, territory glow, and legend entry all match. */
const DEPT_PALETTE = [
  '#6366f1', '#f97316', '#14b8a6', '#e879f9', '#3b82f6', '#facc15', '#34d399', '#f472b6',
];
const TYPE_RADIUS: Record<string, number> = {
  Department: 16, Capability: 7, Agent: 6, Process: 6, Employee: 5, Vendor: 7, Project: 7,
  Customer: 5, Account: 5.5, Ticket: 5, Contract: 6, Incident: 6, PurchaseOrder: 5,
  Task: 5, Connector: 6.5, Brain: 22, Knowledge: 4,
};

/** Per-tier link styling: the map reads as a system, not a hairball, because
 *  each relationship kind has its own weight, hue and motion. Unknown types
 *  fall back to the neutral hairline. */
const LINK_STYLE: Record<string, { stroke: string; width: number; opacity: number; dash?: string; animated?: boolean }> = {
  'agent-comms':     { stroke: '#eab308', width: 1.3, opacity: 0.8 },
  'agent-task':      { stroke: '#94a3b8', width: 0.9, opacity: 0.55 },
  'agent-peer':      { stroke: '#8b5cf6', width: 0.8, opacity: 0.35, dash: '1 5' },
  'connector-agent': { stroke: '#22d3ee', width: 0.9, opacity: 0.5 },
  'connector-hub':   { stroke: '#22d3ee', width: 0.8, opacity: 0.32, dash: '2 5' },
  'task-hub':        { stroke: '#64748b', width: 0.8, opacity: 0.5, dash: '3 5', animated: true },
  'hub-brain':       { stroke: '#fb923c', width: 1.0, opacity: 0.55, dash: '3 5', animated: true },
  'hub-hub':         { stroke: '#94a3b8', width: 1.0, opacity: 0.45, dash: '2 6' },
};
const DEFAULT_LINK = { stroke: '#334155', width: 0.7, opacity: 0.35, dash: undefined as string | undefined, animated: false };

const W = 960;
const H = 680;
const CX = W / 2;
const CY = H / 2;
/** ViewBox size, exported so callers can compute custom seed positions. */
export const TWIN_W = W;
export const TWIN_H = H;

type SimNode = GraphNode & {
  x: number; y: number; vx: number; vy: number;
  hx: number; hy: number;            // home (cluster seed) position
  r: number;
  fixed: boolean;                     // pinned while dragging
  phase: number;                      // ambient-motion phase offset
};

/** Deterministic seed layout: departments on a ring, children fanned around them. */
function seedLayout(nodes: GraphNode[], links: GraphLink[]) {
  const adjacency: Record<string, Set<string>> = {};
  for (const l of links) {
    (adjacency[l.source] ||= new Set()).add(l.target);
    (adjacency[l.target] ||= new Set()).add(l.source);
  }
  const positions: Record<string, { x: number; y: number }> = {};
  const departments = nodes.filter(n => n.label === 'Department');
  const deptIds = new Set(departments.map(d => d.id));
  const children: Record<string, GraphNode[]> = {};
  const assigned = new Set<string>(deptIds);
  for (const n of nodes) {
    if (deptIds.has(n.id)) continue;
    const parent = adjacency[n.id] ? [...adjacency[n.id]].find(id => deptIds.has(id)) : undefined;
    if (parent) { (children[parent] ||= []).push(n); assigned.add(n.id); }
  }
  const R_DEPT = Math.min(CX, CY) * 0.52;
  departments.forEach((d, i) => {
    const a = (i / Math.max(departments.length, 1)) * 2 * Math.PI - Math.PI / 2;
    positions[d.id] = { x: CX + Math.cos(a) * R_DEPT, y: CY + Math.sin(a) * R_DEPT };
  });
  // The company brain (if present) anchors the center of the world.
  for (const n of nodes) {
    if (n.label === 'Brain') { positions[n.id] = { x: CX, y: CY }; assigned.add(n.id); }
  }
  const typeOrder = ['Capability', 'Agent', 'Process', 'Employee', 'Vendor', 'Project'];
  departments.forEach(d => {
    const pos = positions[d.id];
    const kids = (children[d.id] || []).sort((a, b) => typeOrder.indexOf(a.label) - typeOrder.indexOf(b.label));
    const outward = Math.atan2(pos.y - CY, pos.x - CX);
    kids.forEach((k, i) => {
      const ring = Math.floor(i / 9);
      const inRing = i % 9;
      const count = Math.min(kids.length - ring * 9, 9);
      const t = count === 1 ? 0.5 : inRing / (count - 1);
      const a = outward - (Math.PI * 0.92) / 2 + t * Math.PI * 0.92;
      const radius = 62 + ring * 34;
      positions[k.id] = { x: pos.x + Math.cos(a) * radius, y: pos.y + Math.sin(a) * radius };
    });
  });
  const orphans = nodes.filter(n => !assigned.has(n.id));
  const R_OUT = Math.min(CX, CY) * 0.94;
  orphans.forEach((n, i) => {
    const a = (i / Math.max(orphans.length, 1)) * 2 * Math.PI;
    positions[n.id] = { x: CX + Math.cos(a) * R_OUT, y: CY + Math.sin(a) * R_OUT };
  });
  const clusterOf: Record<string, string> = {};
  for (const d of departments) {
    clusterOf[d.id] = d.id;
    for (const k of children[d.id] || []) clusterOf[k.id] = d.id;
  }
  return { positions, adjacency, clusterOf };
}

export default function TwinGraph({
  data, onNodeClick, shock, seedPositions, territories = true, labelsAlways = false, focus,
}: {
  data: GraphData;
  onNodeClick?: (node: GraphNode) => void;
  shock?: ShockPulse;
  /** Optional per-node seed/home positions (viewBox space, see TWIN_W/TWIN_H).
   *  The simulation still runs - these are anchors, not a frozen layout. */
  seedPositions?: Record<string, { x: number; y: number }>;
  /** Soft per-department hue fields behind each cluster (default on). */
  territories?: boolean;
  /** Always show department name labels (default: only past ~1.5x zoom). */
  labelsAlways?: boolean;
  /** Animate the camera to center (x, y) at `zoom` (1 = fit). Retrigger via ts. */
  focus?: { x: number; y: number; zoom: number; ts: number } | null;
}) {
  // ── Static derivations (per data identity) ────────────────────────────────
  const { simNodes, simLinks, adjacency, index, deptColor, clusters } = useMemo(() => {
    const nodes = data?.nodes || [];
    const links = data?.links || [];
    const { positions, adjacency, clusterOf } = seedLayout(nodes, links);
    if (seedPositions) {
      for (const [id, p] of Object.entries(seedPositions)) positions[id] = p;
    }
    const simNodes: SimNode[] = nodes.map((n, i) => {
      const p = positions[n.id] || { x: CX + (i % 13) * 8 - 48, y: CY + (i % 7) * 8 - 24 };
      return {
        ...n, x: p.x, y: p.y, vx: 0, vy: 0, hx: p.x, hy: p.y,
        r: TYPE_RADIUS[n.label] || 6,
        // Band layouts pin the structural nodes (hubs + brain): the clusters
        // stay alive around them and they remain draggable.
        fixed: !!(seedPositions && (n.label === 'Department' || n.label === 'Brain')),
        phase: (i * 0.618) % (Math.PI * 2),
      };
    });
    const index = new Map(simNodes.map((n, i) => [n.id, i]));
    const simLinks = links
      .filter(l => index.has(l.source) && index.has(l.target))
      .map(l => {
        const s = index.get(l.source)!, t = index.get(l.target)!;
        // With a custom seed layout, springs adopt the seeded geometry as
        // their rest length - the sim stays alive without fighting the bands.
        const rest = seedPositions
          ? Math.min(420, Math.max(48, Math.hypot(
              simNodes[s].hx - simNodes[t].hx, simNodes[s].hy - simNodes[t].hy)))
          : undefined;
        return { s, t, rest, type: l.type };
      });
    const departments = simNodes.filter(n => n.label === 'Department');
    const deptColor = new Map<string, string>(
      departments.map((d, i) => [d.id, DEPT_PALETTE[i % DEPT_PALETTE.length]]),
    );
    // per-department cluster: hub index + member indices, for the territory glow
    const clusters = departments.map(d => ({
      deptId: d.id,
      name: d.name,
      color: deptColor.get(d.id)!,
      hubIdx: index.get(d.id)!,
      memberIdxs: simNodes
        .map((n, i) => (clusterOf[n.id] === d.id ? i : -1))
        .filter(i => i >= 0),
    }));
    return { simNodes, simLinks, adjacency, index, deptColor, clusters };
  }, [data, seedPositions]);
  const nodes = data?.nodes || [];
  const links = data?.links || [];

  // ── Mutable render/simulation state ───────────────────────────────────────
  const svgRef = useRef<SVGSVGElement | null>(null);
  const nodeEls = useRef<Map<string, SVGGElement>>(new Map());
  const linkEls = useRef<(SVGPathElement | null)[]>([]);
  const particleEls = useRef<(SVGCircleElement | null)[]>([]);
  const waveEls = useRef<(SVGCircleElement | null)[]>([]);
  const glowEls = useRef<(SVGCircleElement | null)[]>([]);
  const deptLabelEls = useRef<Map<string, SVGTextElement>>(new Map());
  const agentLabelEls = useRef<Map<string, SVGTextElement>>(new Map());
  const microLabelEls = useRef<Map<string, SVGTextElement>>(new Map());
  const tooltipEl = useRef<HTMLDivElement | null>(null);
  const alphaRef = useRef(1);
  const hoverRef = useRef<string | null>(null);
  const dragRef = useRef<{ id: string; moved: boolean } | null>(null);
  const viewRef = useRef({ x: 0, y: 0, w: W, h: H });
  const shockRef = useRef<{
    start: number; targetId: string; severity: number;
    hits: { id: string; delay: number; fired: boolean }[];
  } | null>(null);

  // A stable subset of links carries "energy particles".
  const particleLinks = useMemo(
    () => simLinks.filter((_, i) => i % Math.max(1, Math.floor(simLinks.length / 14)) === 0).slice(0, 14),
    [simLinks],
  );

  // ── Shock ingestion: BFS depths → staggered hit schedule ─────────────────
  useEffect(() => {
    if (!shock || !index.has(shock.targetId)) return;
    const impacted = new Set(shock.impactedIds.filter(id => index.has(id)));
    impacted.add(shock.targetId);
    const depth = new Map<string, number>([[shock.targetId, 0]]);
    const queue = [shock.targetId];
    while (queue.length) {
      const cur = queue.shift()!;
      for (const nb of adjacency[cur] || []) {
        if (impacted.has(nb) && !depth.has(nb)) {
          depth.set(nb, depth.get(cur)! + 1);
          queue.push(nb);
        }
      }
    }
    const maxSeen = Math.max(1, ...depth.values());
    shockRef.current = {
      start: performance.now(),
      targetId: shock.targetId,
      severity: shock.severity ?? 50,
      hits: [...impacted].map(id => ({
        id,
        // unreached-by-BFS impacted nodes hit last
        delay: (depth.get(id) ?? maxSeen + 1) * 240,
        fired: false,
      })),
    };
    alphaRef.current = Math.max(alphaRef.current, 0.9);
  }, [shock, adjacency, index]);

  // ── The simulation + render loop ──────────────────────────────────────────
  useEffect(() => {
    let raf = 0;
    const N = simNodes.length;
    if (!N) return;

    // Honor reduced motion: compute one static frame, never loop.
    const reduced = typeof window !== 'undefined'
      && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    const step = (now: number) => {
      const alpha = alphaRef.current;
      // Cool toward a floor > 0 so the graph keeps breathing.
      alphaRef.current = alpha + (0.035 - alpha) * 0.02;

      // Ambient drift - tiny periodic force, unique phase per node.
      const t = now / 1000;
      for (const n of simNodes) {
        if (n.fixed) continue;
        n.vx += Math.cos(t * 0.7 + n.phase) * 0.012;
        n.vy += Math.sin(t * 0.9 + n.phase) * 0.012;
      }

      // Springs along links.
      for (const l of simLinks) {
        const a = simNodes[l.s], b = simNodes[l.t];
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.max(Math.hypot(dx, dy), 1);
        const rest = l.rest ?? (
          a.label === 'Department' && b.label === 'Department' ? 300
            : (a.label === 'Brain' || b.label === 'Brain') ? 230 : 64);
        const f = ((d - rest) / d) * 0.02 * alpha * 8;
        if (!a.fixed) { a.vx += dx * f; a.vy += dy * f; }
        if (!b.fixed) { b.vx -= dx * f; b.vy -= dy * f; }
      }

      // Pairwise repulsion (short-range).
      for (let i = 0; i < N; i++) {
        const a = simNodes[i];
        for (let j = i + 1; j < N; j++) {
          const b = simNodes[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > 140 * 140 || d2 === 0) continue;
          const d = Math.sqrt(d2);
          const f = Math.min((520 * alpha) / d2, 1.6);
          const fx = (dx / d) * f, fy = (dy / d) * f;
          if (!a.fixed) { a.vx -= fx; a.vy -= fy; }
          if (!b.fixed) { b.vx += fx; b.vy += fy; }
        }
      }

      // Cluster anchoring: departments hold their ring seats firmly, children
      // gently - keeps the layout readable while staying elastic. Custom seed
      // layouts (the Neural Map's horizontal bands) anchor children harder so
      // the intended structure survives the springs.
      for (const n of simNodes) {
        if (n.fixed) continue;
        const k = n.label === 'Department' || n.label === 'Brain'
          ? (seedPositions ? 0.35 : 0.055)
          : seedPositions ? 0.02 : 0.006;
        n.vx += (n.hx - n.x) * k * (alpha * 6 + 0.4);
        n.vy += (n.hy - n.y) * k * (alpha * 6 + 0.4);
      }

      // Shockwave: expanding rings + staggered impulses.
      const sh = shockRef.current;
      if (sh) {
        const elapsed = now - sh.start;
        const epi = simNodes[index.get(sh.targetId)!];
        const mag = 2.2 + (sh.severity / 100) * 5.5;
        for (const hit of sh.hits) {
          if (!hit.fired && elapsed >= hit.delay) {
            hit.fired = true;
            const n = simNodes[index.get(hit.id)!];
            const dx = n.x - epi.x, dy = n.y - epi.y;
            const d = Math.max(Math.hypot(dx, dy), 8);
            n.vx += (dx / d) * mag;
            n.vy += (dy / d) * mag;
            const halo = nodeEls.current.get(hit.id)?.querySelector<SVGCircleElement>('[data-hit]');
            if (halo) {
              // restart the CSS hit animation: clear → force reflow → replay
              halo.style.animation = 'none';
              void halo.getBoundingClientRect();
              halo.style.animation = 'twin-hit 1.6s ease-out forwards';
            }
          }
        }
        // expanding rings drawn from the epicenter
        waveEls.current.forEach((w, i) => {
          if (!w) return;
          const waveT = (elapsed - i * 420) / 2400;
          if (waveT < 0 || waveT > 1) { w.setAttribute('opacity', '0'); return; }
          w.setAttribute('cx', String(epi.x));
          w.setAttribute('cy', String(epi.y));
          w.setAttribute('r', String(24 + waveT * (140 + sh.severity * 2.4)));
          w.setAttribute('opacity', String(0.85 * (1 - waveT)));
          w.setAttribute('stroke-width', String(3.4 - 2.2 * waveT));
        });
        if (elapsed > sh.hits.reduce((m, h) => Math.max(m, h.delay), 0) + 3600) {
          shockRef.current = null;
          waveEls.current.forEach(w => w?.setAttribute('opacity', '0'));
        }
      }

      // Integrate + bounds.
      for (const n of simNodes) {
        if (n.fixed) { n.vx = 0; n.vy = 0; continue; }
        n.vx *= 0.86; n.vy *= 0.86;
        n.x = Math.max(24, Math.min(W - 24, n.x + n.vx));
        n.y = Math.max(24, Math.min(H - 36, n.y + n.vy));
      }

      // Write to DOM.
      for (const n of simNodes) {
        nodeEls.current.get(n.id)?.setAttribute('transform', `translate(${n.x},${n.y})`);
      }
      // Territory glows track their cluster's live extent (breathing softly).
      clusters.forEach((c, ci) => {
        const el = glowEls.current[ci];
        if (!el) return;
        const hub = simNodes[c.hubIdx];
        let r = 46;
        for (const mi of c.memberIdxs) {
          const m = simNodes[mi];
          const d = Math.hypot(m.x - hub.x, m.y - hub.y) + m.r;
          if (d > r) r = d;
        }
        el.setAttribute('cx', String(hub.x));
        el.setAttribute('cy', String(hub.y));
        el.setAttribute('r', String(r + 16 + Math.sin(t * 0.6 + hub.phase) * 4));
      });
      for (let i = 0; i < simLinks.length; i++) {
        const el = linkEls.current[i];
        if (!el) continue;
        const a = simNodes[simLinks[i].s], b = simNodes[simLinks[i].t];
        const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.08;
        const my = (a.y + b.y) / 2 - (b.x - a.x) * 0.08;
        el.setAttribute('d', `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`);
      }
      // Energy particles ride their links (quadratic-bezier interpolation).
      particleLinks.forEach((l, i) => {
        const el = particleEls.current[i];
        if (!el) return;
        const a = simNodes[l.s], b = simNodes[l.t];
        const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.08;
        const my = (a.y + b.y) / 2 - (b.x - a.x) * 0.08;
        const p = ((now / 1000) * 0.22 + i * 0.31) % 1;
        const u = 1 - p;
        el.setAttribute('cx', String(u * u * a.x + 2 * u * p * mx + p * p * b.x));
        el.setAttribute('cy', String(u * u * a.y + 2 * u * p * my + p * p * b.y));
      });

      if (!reduced) raf = requestAnimationFrame(step);
    };
    if (reduced) { step(performance.now()); return; }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [simNodes, simLinks, particleLinks, index, clusters]);

  // ── Pointer interactions ──────────────────────────────────────────────────
  const toGraph = useCallback((e: { clientX: number; clientY: number }) => {
    const svg = svgRef.current!;
    const rect = svg.getBoundingClientRect();
    const v = viewRef.current;
    return {
      x: v.x + ((e.clientX - rect.left) / rect.width) * v.w,
      y: v.y + ((e.clientY - rect.top) / rect.height) * v.h,
    };
  }, []);

  const applyView = useCallback(() => {
    const v = viewRef.current;
    svgRef.current?.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`);
    // Level-of-detail: department names appear once zoomed past ~1.5x -
    // zoomed out the hue territories identify clusters, zoomed in there is
    // room for text without overlapping satellites.
    const k = W / v.w;
    const opacity = labelsAlways ? 1 : k >= 1.5 ? Math.min(1, 0.3 + (k - 1.5) * 1.6) : 0;
    deptLabelEls.current.forEach(el => el.setAttribute('opacity', String(opacity)));
    // Smaller entities reveal their names as the camera moves in (a wide shot
    // full of 8px labels is noise; a focused department deserves names).
    const agentOp = k >= (labelsAlways ? 1.15 : 1.4) ? 0.9 : 0;
    agentLabelEls.current.forEach(el => el.setAttribute('opacity', String(agentOp)));
    const microOp = k >= 1.25 ? 0.85 : 0;
    microLabelEls.current.forEach(el => el.setAttribute('opacity', String(microOp)));
  }, [labelsAlways]);

  const setHover = useCallback((id: string | null) => {
    hoverRef.current = id;
    const neighbors = id ? adjacency[id] : undefined;
    for (const n of simNodes) {
      const el = nodeEls.current.get(n.id);
      if (!el) continue;
      const dim = id !== null && n.id !== id && !neighbors?.has(n.id);
      el.setAttribute('opacity', dim ? '0.16' : '1');
      el.querySelector('[data-core]')?.setAttribute('stroke', n.id === id ? '#ffffff' : 'rgba(255,255,255,0.25)');
    }
    simLinks.forEach((l, i) => {
      const el = linkEls.current[i];
      if (!el) return;
      const st = LINK_STYLE[(l as any).type || ''] || DEFAULT_LINK;
      const active = id !== null && (simNodes[l.s].id === id || simNodes[l.t].id === id);
      el.setAttribute('stroke', active ? '#c7d2fe' : st.stroke);
      el.setAttribute('stroke-width', String(active ? Math.max(1.6, st.width) : st.width));
      el.setAttribute('opacity', id ? (active ? '0.95' : '0.05') : String(st.opacity));
    });
    const tip = tooltipEl.current;
    if (tip) {
      if (id) {
        const n = simNodes[index.get(id)!];
        const tipColor = n.label === 'Department'
          ? (deptColor.get(n.id) || TYPE_COLORS.Department)
          : (TYPE_COLORS[n.label] || '#94a3b8');
        tip.style.display = 'block';
        const esc = (s: string) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        const sub = n.role || n.hint || n.category || '';
        tip.innerHTML =
          `<div style="font-weight:600;color:#f7f8f8;font-size:12px">${esc((n.name || '').slice(0, 30))}</div>` +
          `<div style="font-weight:700;color:${tipColor};font-size:9px;text-transform:uppercase">` +
          `${esc(n.label)}${n.status ? ' · ' + esc(String(n.status).replace(/^[A-Za-z]+Status\./, '')) : ''}</div>` +
          (sub ? `<div style="color:#aab2ba;font-size:9.5px;margin-top:3px;max-width:210px;line-height:1.35">${esc(String(sub).slice(0, 90))}</div>` : '') +
          `<div style="color:#8a8f98;font-size:9px;margin-top:3px">drag to move · click for details</div>`;
      } else {
        tip.style.display = 'none';
      }
    }
  }, [adjacency, simNodes, simLinks, index, deptColor]);

  const onNodePointerDown = useCallback((id: string, e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragRef.current = { id, moved: false };
    const n = simNodes[index.get(id)!];
    n.fixed = true;
  }, [simNodes, index]);

  useEffect(() => {
    const move = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d || !svgRef.current) return;
      d.moved = true;
      const p = toGraph(e);
      const n = simNodes[index.get(d.id)!];
      n.x = p.x; n.y = p.y;
      alphaRef.current = Math.max(alphaRef.current, 0.5);
      const tip = tooltipEl.current;
      if (tip) tip.style.display = 'none';
    };
    const up = () => {
      const d = dragRef.current;
      if (!d) return;
      const n = simNodes[index.get(d.id)!];
      n.fixed = false;
      if (!d.moved) onNodeClick?.(n);
      dragRef.current = null;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  }, [simNodes, index, toGraph, onNodeClick]);

  // Camera focus: ease the viewBox to center a point at a zoom level.
  useEffect(() => {
    if (!focus) return;
    const start = { ...viewRef.current };
    const nw = Math.min(Math.max(W / focus.zoom, W * 0.3), W * 1.6);
    const nh = nw * (H / W);
    const target = { x: focus.x - nw / 2, y: focus.y - nh / 2, w: nw, h: nh };
    const t0 = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / 650);
      const e = ease(t);
      viewRef.current = {
        x: start.x + (target.x - start.x) * e,
        y: start.y + (target.y - start.y) * e,
        w: start.w + (target.w - start.w) * e,
        h: start.h + (target.h - start.h) * e,
      };
      applyView();
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [focus, applyView]);

  // Wheel zoom around the cursor + background pan.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const v = viewRef.current;
      const p = toGraph(e);
      const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
      const nw = Math.min(Math.max(v.w * k, W * 0.3), W * 1.6);
      const nh = nw * (H / W);
      viewRef.current = {
        x: p.x - ((p.x - v.x) / v.w) * nw,
        y: p.y - ((p.y - v.y) / v.h) * nh,
        w: nw, h: nh,
      };
      applyView();
    };
    let pan: { sx: number; sy: number; vx: number; vy: number } | null = null;
    const down = (e: PointerEvent) => {
      if ((e.target as Element).closest('[data-node]')) return;
      pan = { sx: e.clientX, sy: e.clientY, vx: viewRef.current.x, vy: viewRef.current.y };
    };
    const move = (e: PointerEvent) => {
      if (!pan) return;
      const rect = svg.getBoundingClientRect();
      viewRef.current.x = pan.vx - ((e.clientX - pan.sx) / rect.width) * viewRef.current.w;
      viewRef.current.y = pan.vy - ((e.clientY - pan.sy) / rect.height) * viewRef.current.h;
      applyView();
    };
    const up = () => { pan = null; };
    svg.addEventListener('wheel', wheel, { passive: false });
    svg.addEventListener('pointerdown', down);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      svg.removeEventListener('wheel', wheel);
      svg.removeEventListener('pointerdown', down);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    // simNodes in deps: on a clean load the twin data arrives async, so the
    // svg does not exist on first run - the listeners must attach once it does.
  }, [toGraph, applyView, simNodes]);

  if (!nodes.length) {
    return (
      <div className="w-full h-full flex items-center justify-center text-[13px] text-gray-500">
        Twin graph is empty - deploy a department to populate it.
      </div>
    );
  }

  const presentTypes = [...new Set(nodes.map(n => n.label))]
    .filter(t => t !== 'Department' && TYPE_COLORS[t]);

  return (
    <div className="w-full h-full relative overflow-hidden" style={{ touchAction: 'none' }}>
      <style>{`
        @keyframes twin-dept-pulse {
          0%, 100% { transform: scale(1); opacity: 0.14; }
          50%      { transform: scale(1.35); opacity: 0.05; }
        }
        @keyframes twin-hit {
          0%   { opacity: 0.95; transform: scale(0.4); }
          45%  { opacity: 0.55; transform: scale(1.9); }
          100% { opacity: 0;    transform: scale(2.6); }
        }
        @keyframes twin-dash {
          to { stroke-dashoffset: -16; }
        }
        .twin-dash { animation: twin-dash 1.25s linear infinite; }
        @media (prefers-reduced-motion: reduce) {
          .twin-dash { animation: none; }
        }
      `}</style>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
        <defs>
          {clusters.map((c, i) => (
            <radialGradient key={c.deptId} id={`twin-territory-${i}`}>
              <stop offset="0%" stopColor={c.color} stopOpacity={0.16} />
              <stop offset="62%" stopColor={c.color} stopOpacity={0.07} />
              <stop offset="100%" stopColor={c.color} stopOpacity={0} />
            </radialGradient>
          ))}
        </defs>

        {/* Department territories: soft hue fields that follow each cluster */}
        {territories && (
          <g style={{ pointerEvents: 'none' }}>
            {clusters.map((c, i) => (
              <circle
                key={c.deptId}
                ref={el => { glowEls.current[i] = el; }}
                r={0} fill={`url(#twin-territory-${i})`}
              />
            ))}
          </g>
        )}

        <g>
          {links.map((l, i) => {
            const st = LINK_STYLE[l.type || ''] || DEFAULT_LINK;
            return (
              <path
                key={i}
                ref={el => { linkEls.current[i] = el; }}
                className={st.animated ? 'twin-dash' : undefined}
                fill="none" stroke={st.stroke} strokeWidth={st.width}
                strokeDasharray={st.dash} opacity={st.opacity}
              />
            );
          })}
        </g>

        {/* Shockwave rings (3 staggered) */}
        <g style={{ pointerEvents: 'none' }}>
          {[0, 1, 2].map(i => (
            <circle
              key={i}
              ref={el => { waveEls.current[i] = el; }}
              r={0} fill="none" stroke="#ef4444" strokeWidth={2.2 - i * 0.5} opacity={0}
            />
          ))}
        </g>

        {/* Energy particles */}
        <g style={{ pointerEvents: 'none' }}>
          {particleLinks.map((_, i) => (
            <circle
              key={i}
              ref={el => { particleEls.current[i] = el; }}
              r={1.6} fill="#7dd3fc" opacity={0.75}
            />
          ))}
        </g>

        <g>
          {simNodes.map(n => {
            const color = n.label === 'Department'
              ? (deptColor.get(n.id) || TYPE_COLORS.Department)
              : (TYPE_COLORS[n.label] || '#64748b');
            return (
              <g
                key={n.id}
                data-node
                ref={el => { if (el) nodeEls.current.set(n.id, el); }}
                transform={`translate(${n.x},${n.y})`}
                onPointerDown={e => onNodePointerDown(n.id, e)}
                onMouseEnter={() => !dragRef.current && setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: 'grab' }}
              >
                {n.label === 'Department' && (
                  <circle
                    r={n.r + 7} fill={color}
                    style={{ animation: `twin-dept-pulse ${3.4 + (n.phase % 1.2)}s ease-in-out infinite`, transformOrigin: 'center', transformBox: 'fill-box' }}
                  />
                )}
                {/* Type identities: each entity kind has its own silhouette. */}
                {n.label === 'Agent' && (
                  <circle r={n.r + 3} fill="none" stroke={color} strokeWidth={1.2} opacity={0.85} />
                )}
                {n.label === 'Connector' && (
                  <circle r={n.r + 2.5} fill="none" stroke={color} strokeWidth={1} opacity={0.7} />
                )}
                {n.label === 'Task' && (
                  <rect
                    x={-(n.r + 2)} y={-(n.r + 2)} width={(n.r + 2) * 2} height={(n.r + 2) * 2} rx={2}
                    fill="none" stroke={color} strokeWidth={1} opacity={0.65} transform="rotate(45)"
                  />
                )}
                {n.label === 'Brain' && (
                  <circle r={n.r + 8} fill="none" stroke={color} strokeWidth={1}
                    strokeDasharray="4 7" className="twin-dash" opacity={0.75} />
                )}
                {/* shock-hit flash halo (driven by CSS animation, retriggered on impact) */}
                <circle
                  data-hit
                  r={n.r + 5} fill="none" stroke="#ef4444" strokeWidth={2.6} opacity={0}
                  style={{ transformOrigin: 'center', transformBox: 'fill-box', animation: 'none' }}
                />
                <circle
                  data-core r={n.r}
                  fill={n.label === 'Connector' ? 'rgba(0,0,0,0.25)' : color}
                  stroke="rgba(255,255,255,0.25)" strokeWidth={0.8}
                />
                {n.label === 'Connector' && <circle r={2} fill={color} />}
                {n.label === 'Department' ? (
                  <text
                    ref={el => { if (el) deptLabelEls.current.set(n.id, el); }}
                    y={n.r + 14} fill={color} fontSize={10.5} fontWeight={700}
                    fontFamily="ui-monospace, SFMono-Regular, monospace" letterSpacing="0.8"
                    textAnchor="middle" opacity={labelsAlways ? 1 : 0}
                    style={{ userSelect: 'none', pointerEvents: 'none' }}
                  >
                    {labelsAlways ? (n.name || '').toUpperCase() : n.name}
                  </text>
                ) : n.label === 'Agent' ? (
                  <text
                    ref={el => { if (el) agentLabelEls.current.set(n.id, el); }}
                    y={n.r + 12} fill="#cbd5e1" fontSize={7.5} fontWeight={600}
                    textAnchor="middle" opacity={0}
                    style={{ userSelect: 'none', pointerEvents: 'none' }}
                  >
                    {(n.name || '').slice(0, 18)}
                  </text>
                ) : (n.label === 'Task' || n.label === 'Connector') ? (
                  <text
                    ref={el => { if (el) microLabelEls.current.set(n.id, el); }}
                    y={n.r + 11} fill="#8a9098" fontSize={6.5} fontWeight={500}
                    textAnchor="middle" opacity={0}
                    style={{ userSelect: 'none', pointerEvents: 'none' }}
                  >
                    {(n.name || '').slice(0, 20)}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Imperative tooltip (no re-render on hover) */}
      <div
        ref={tooltipEl}
        className="absolute top-3 right-3 px-3 py-2 rounded-lg"
        style={{ display: 'none', background: 'rgba(11,12,14,0.92)', border: '1px solid #2a2d33', pointerEvents: 'none', minWidth: 150 }}
      />

      {/* Legend: a slim dot strip that expands into the full key on hover */}
      <div className="absolute bottom-3 left-3 group" style={{ zIndex: 5 }}>
        <div className="absolute bottom-full left-0 mb-2 px-3 py-2 rounded-lg hidden group-hover:block"
          style={{ background: 'rgba(11,12,14,0.94)', border: '1px solid #2a2d33', minWidth: 200 }}>
          <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: '#565b64' }}>Departments</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {clusters.map(c => (
              <div key={c.deptId} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c.color, boxShadow: `0 0 5px ${c.color}66` }} />
                <span className="text-[11px] whitespace-nowrap" style={{ color: '#c9cdd4' }}>{c.name}</span>
              </div>
            ))}
          </div>
          <div className="text-[11px] font-semibold uppercase tracking-wider mt-2 mb-1" style={{ color: '#565b64' }}>Node types</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {presentTypes.map(t => (
              <div key={t} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: TYPE_COLORS[t] }} />
                <span className="text-[11px]" style={{ color: '#8a8f98' }}>{t}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full cursor-default"
          style={{ background: 'rgba(11,12,14,0.85)', border: '1px solid #2a2d33' }}>
          {clusters.map(c => (
            <span key={c.deptId} className="w-2 h-2 rounded-full" style={{ background: c.color }} />
          ))}
          <span className="w-px h-3 mx-0.5" style={{ background: '#2a2d33' }} />
          {presentTypes.map(t => (
            <span key={t} className="w-1.5 h-1.5 rounded-full" style={{ background: TYPE_COLORS[t] }} />
          ))}
          <span className="text-[11px] ml-1" style={{ color: '#565b64' }}>legend</span>
        </div>
      </div>

      <div className="absolute bottom-3 right-3 text-[11px] px-2 py-1 rounded-md"
        style={{ color: '#565b64', background: 'rgba(11,12,14,0.6)' }}>
        hover for names · drag · scroll to zoom
      </div>
    </div>
  );
}
