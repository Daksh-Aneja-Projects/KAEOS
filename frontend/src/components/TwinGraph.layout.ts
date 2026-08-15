/**
 * TwinGraph — layout + visual constants.
 *
 * The deterministic seed layout, the per-type colour/radius maps, the
 * per-tier link styles, and the viewBox geometry. Pure data + one pure
 * function, extracted so the TwinGraph component file stays focused on the
 * force simulation and rendering. Behavior unchanged.
 */

export interface GraphNode { id: string; name: string; label: string; [k: string]: any }
export interface GraphLink { source: string; target: string; type?: string }
export interface GraphData { nodes?: GraphNode[]; links?: GraphLink[] }

export const TYPE_COLORS: Record<string, string> = {
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
  Encounter: '#14b8a6',      // healthcare encounters (teal, matches DEPARTMENT_COLORS.healthcare)
  LoanApplication: '#d97706',// lending applications (amber, matches DEPARTMENT_COLORS.lending)
  Requisition: '#facc15',    // procurement requisitions (gold)
  // Neural Map entities.
  Task: '#f59e0b',           // skills an agent runs (amber)
  Connector: '#22d3ee',      // integrations feeding a department (cyan)
  Brain: '#fb923c',          // the company knowledge core (warm coral)
  Knowledge: '#fbbf24',      // ingested notes/documents
};
/** One hue per department: hub node, territory glow, and legend entry all match.
 *  12 distinct hues so 10+ departments never wrap and collide (index i % length). */
export const DEPT_PALETTE = [
  '#6366f1', '#f97316', '#14b8a6', '#e879f9', '#3b82f6', '#facc15',
  '#34d399', '#f472b6', '#a78bfa', '#22d3ee', '#ef4444', '#84cc16',
];
export const TYPE_RADIUS: Record<string, number> = {
  Department: 16, Capability: 7, Agent: 6, Process: 6, Employee: 5, Vendor: 7, Project: 7,
  Customer: 5, Account: 5.5, Ticket: 5, Contract: 6, Incident: 6, PurchaseOrder: 5,
  Encounter: 5, LoanApplication: 6, Requisition: 5,
  Task: 5, Connector: 6.5, Brain: 22, Knowledge: 4,
};

/** Per-tier link styling: the map reads as a system, not a hairball, because
 *  each relationship kind has its own weight, hue and motion. Unknown types
 *  fall back to the neutral hairline. */
export const LINK_STYLE: Record<string, { stroke: string; width: number; opacity: number; dash?: string; animated?: boolean }> = {
  'agent-comms':     { stroke: '#eab308', width: 1.3, opacity: 0.8 },
  'agent-task':      { stroke: '#94a3b8', width: 0.9, opacity: 0.55 },
  'agent-peer':      { stroke: '#8b5cf6', width: 0.8, opacity: 0.35, dash: '1 5' },
  'connector-agent': { stroke: '#22d3ee', width: 0.9, opacity: 0.5 },
  'connector-hub':   { stroke: '#22d3ee', width: 0.8, opacity: 0.32, dash: '2 5' },
  'task-hub':        { stroke: '#64748b', width: 0.8, opacity: 0.5, dash: '3 5', animated: true },
  'hub-brain':       { stroke: '#fb923c', width: 1.0, opacity: 0.55, dash: '3 5', animated: true },
  'hub-hub':         { stroke: '#94a3b8', width: 1.0, opacity: 0.45, dash: '2 6' },
};
export const DEFAULT_LINK = { stroke: '#334155', width: 0.7, opacity: 0.35, dash: undefined as string | undefined, animated: false };

export const W = 960;
export const H = 680;
export const CX = W / 2;
export const CY = H / 2;
/** ViewBox size, exported so callers can compute custom seed positions. */
export const TWIN_W = W;
export const TWIN_H = H;

/**
 * Department name-label sizing. Labels render in a fixed monospace font
 * under each hub; at low department counts there is plenty of room, but a
 * fixed viewBox (TWIN_W) divided across more departments shrinks the gap
 * between neighboring labels. 'Labels always visible' is a locked product
 * decision (no hiding behind a zoom threshold), so instead each label gets
 * the largest font size that still fits half the distance to its nearest
 * neighboring department, down to a floor size, truncating with an ellipsis
 * only past that floor - the full name stays reachable via the node's hover
 * tooltip (TwinGraph's existing setHover panel).
 */
export const DEPT_LABEL_BASE_FONT = 10.5;
export const DEPT_LABEL_MIN_FONT = 7;
export const DEPT_LABEL_LETTER_SPACING = 0.8;
// ponytail: heuristic char width for ui-monospace (~0.6x font-size), not a
// measured glyph metric - upgrade to a real getBBox() measurement if a
// non-monospace fallback font ever gets used for these labels.
export const DEPT_LABEL_CHAR_WIDTH = 0.6;

export function fitDeptLabel(name: string, halfWidthBudget: number): { fontSize: number; maxChars: number } {
  const len = (name || '').length;
  if (!len) return { fontSize: DEPT_LABEL_BASE_FONT, maxChars: Infinity };
  const widthAt = (fs: number) =>
    len * DEPT_LABEL_CHAR_WIDTH * fs + Math.max(0, len - 1) * DEPT_LABEL_LETTER_SPACING;
  if (widthAt(DEPT_LABEL_BASE_FONT) / 2 <= halfWidthBudget) {
    return { fontSize: DEPT_LABEL_BASE_FONT, maxChars: Infinity };
  }
  const fit = (2 * halfWidthBudget - Math.max(0, len - 1) * DEPT_LABEL_LETTER_SPACING)
    / (len * DEPT_LABEL_CHAR_WIDTH);
  if (fit >= DEPT_LABEL_MIN_FONT) {
    return { fontSize: Math.round(fit * 10) / 10, maxChars: Infinity };
  }
  const maxChars = Math.max(3, Math.floor(
    (2 * halfWidthBudget + DEPT_LABEL_LETTER_SPACING)
    / (DEPT_LABEL_CHAR_WIDTH * DEPT_LABEL_MIN_FONT + DEPT_LABEL_LETTER_SPACING),
  ));
  return { fontSize: DEPT_LABEL_MIN_FONT, maxChars };
}

export type SimNode = GraphNode & {
  x: number; y: number; vx: number; vy: number;
  hx: number; hy: number;            // home (cluster seed) position
  r: number;
  fixed: boolean;                     // pinned while dragging
  phase: number;                      // ambient-motion phase offset
};

/** Deterministic seed layout: departments on a ring, children fanned around them. */
export function seedLayout(nodes: GraphNode[], links: GraphLink[]) {
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

