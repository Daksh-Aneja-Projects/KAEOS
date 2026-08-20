import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Brain, Database, FileUp, Mic, Search, Send, Sparkles, Waypoints, X,
} from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { api } from '../../api/client';
import { humanize } from '../../lib/format';
import { CountUp } from '../CountUp';
import { BrainLoading, BrainError, BrainEmpty } from '../BrainStates';
import { domainColor } from '../DomainIcon';
import DomainIcon from '../DomainIcon';
import TwinGraph, { TWIN_W, TWIN_H, type ShockPulse } from '../TwinGraph';
import { useLiveRefresh } from '../../hooks/useLiveRefresh';
import BrainParticles from './BrainParticles';
import DossierDrawer, { type DossierTarget } from './DossierDrawer';
import './neural.css';

/**
 * Neural Map: the organization as ONE living, free-flow graph.
 *
 * Free-flow mode is an Obsidian-style force simulation: every department is a
 * self-organizing cluster (its integrations, agents, tasks, capabilities and
 * processes), departments bridge through shared systems and the hub mesh, and
 * the company brain anchors the center. Nothing is laid out by hand - springs
 * and repulsion decide, and you can drag any node and watch the org react.
 *
 * Brain mode is the knowledge core itself: a dense particle sphere with every
 * department on its ring, live stats, search and ingest.
 */

const TYPE_LABEL: Record<string, string> = {
  department: 'Department', agent: 'Agent', task: 'Task', connector: 'Connector',
  capability: 'Capability', process: 'Process', brain: 'Brain', knowledge: 'Knowledge',
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Measuring hook (callback ref: safe across loading early-returns).          */
/* ────────────────────────────────────────────────────────────────────────── */

function useMeasured(): [(el: HTMLDivElement | null) => void, { w: number; h: number }] {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const roRef = useRef<ResizeObserver | null>(null);
  const refCb = useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const r = entries[0].contentRect;
      setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    roRef.current = ro;
    const r = el.getBoundingClientRect();
    setSize({ w: r.width, h: r.height });
  }, []);
  return [refCb, size];
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Ingest bar: dump into the brain (text, or drop/attach a document).         */
/* ────────────────────────────────────────────────────────────────────────── */

export function BrainIngestBar({ onLearned, compact }: { onLearned?: () => void; compact?: boolean }) {
  const { colors } = useTheme();
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; message: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [listening, setListening] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const recRef = useRef<any>(null);

  useEffect(() => {
    if (!note) return;
    const t = setTimeout(() => setNote(null), 6000);
    return () => clearTimeout(t);
  }, [note]);

  // Voice ingest: native Web Speech API - speak a note straight into the brain.
  const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  useEffect(() => () => recRef.current?.stop?.(), []);
  const toggleVoice = () => {
    if (listening) { recRef.current?.stop(); return; }
    try {
      const rec = new SpeechRec();
      rec.continuous = true;
      rec.interimResults = false;
      rec.lang = navigator.language || 'en-US';
      rec.onresult = (e: any) => {
        const spoken = Array.from(e.results as any).slice(e.resultIndex)
          .map((r: any) => r[0]?.transcript || '').join(' ').trim();
        if (spoken) setText(prev => (prev ? prev + ' ' : '') + spoken);
      };
      rec.onend = () => setListening(false);
      rec.onerror = () => setListening(false);
      recRef.current = rec;
      rec.start();
      setListening(true);
    } catch {
      setNote({ ok: false, message: 'Voice input is not available in this browser' });
    }
  };

  const submit = async () => {
    if (busy || (!text.trim() && !file)) return;
    setBusy(true);
    try {
      const res = await api.neuralBrainIngest({ text: text.trim() || undefined, file: file || undefined });
      setNote({ ok: true, message: res.message });
      setText('');
      setFile(null);
      onLearned?.();
    } catch (e: any) {
      setNote({ ok: false, message: e?.message || 'The brain could not take that in' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-1">
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        className="rounded-xl p-2 flex items-center gap-2 transition-all"
        style={{
          background: `${colors.surface1}f0`,
          border: `1px dashed ${dragging ? colors.primary : colors.hairlineStrong || colors.hairline}`,
          boxShadow: dragging ? `0 0 0 3px ${colors.primary}22` : '0 4px 24px rgba(0,0,0,0.25)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <Sparkles className="w-4 h-4 shrink-0" style={{ color: colors.primary }} />
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit(); }}
          placeholder={compact ? 'Dump into the brain...' : 'Dump into the brain: a note, a policy, a decision. Or drop a document.'}
          className="flex-1 bg-transparent outline-none text-[13px] min-w-0"
          style={{ color: colors.ink }}
          aria-label="Add knowledge to the company brain"
        />
        {file && (
          <span className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold shrink-0 max-w-[160px]"
            style={{ background: `${colors.primary}18`, color: colors.primary }}>
            <span className="truncate">{file.name}</span>
            <button onClick={() => setFile(null)} aria-label="Remove attached file"><X className="w-3 h-3" /></button>
          </span>
        )}
        <input ref={fileRef} type="file" className="hidden"
          accept=".txt,.md,.csv,.json,.yaml,.yml,.log,text/*"
          onChange={e => setFile(e.target.files?.[0] || null)} />
        <button onClick={() => fileRef.current?.click()} aria-label="Attach a document"
          className="p-1.5 rounded-lg transition-colors hover:opacity-75" style={{ color: colors.inkSubtle }}>
          <FileUp className="w-4 h-4" />
        </button>
        {SpeechRec && (
          <button onClick={toggleVoice}
            aria-label={listening ? 'Stop voice input' : 'Speak a note into the brain'}
            className={`p-1.5 rounded-lg transition-colors hover:opacity-75 ${listening ? 'animate-pulse' : ''}`}
            style={{
              color: listening ? '#fff' : colors.inkSubtle,
              background: listening ? colors.error : 'transparent',
            }}>
            <Mic className="w-4 h-4" />
          </button>
        )}
        <button onClick={submit} disabled={busy || (!text.trim() && !file)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white transition-all disabled:opacity-40"
          style={{ background: colors.primary }}>
          {busy
            ? <span className="w-3.5 h-3.5 border-2 rounded-full animate-spin inline-block"
                style={{ borderColor: '#fff', borderTopColor: 'transparent' }} />
            : <Send className="w-3.5 h-3.5" />}
          Learn it
        </button>
      </div>
      {note && (
        <div className="text-[11px] font-medium px-2 py-1 rounded-md inline-block"
          style={{
            background: `${colors.surface1}f0`,
            color: note.ok ? colors.success : colors.error,
            border: `1px solid ${colors.hairline}`,
          }}>
          {note.message}
        </div>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Brain panel: numbers, domain clusters, and query - Obsidian-style.         */
/* ────────────────────────────────────────────────────────────────────────── */

function BrainPanel({ stats, onClose }: { stats: any; onClose: () => void }) {
  const { colors } = useTheme();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  const search = async () => {
    if (!q.trim()) { setResults(null); return; }
    setSearching(true);
    try {
      const r = await api.neuralBrainSearch(q.trim());
      setResults(r.results || []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const kindColor: Record<string, string> = {
    memory: colors.primary, rule: colors.success, skill: colors.warning,
  };
  const mono: React.CSSProperties = { fontFamily: 'var(--font-mono, monospace)' };

  return (
    <div className="absolute left-3 top-3 bottom-3 w-[310px] max-w-[85%] rounded-xl flex flex-col z-20 overflow-hidden"
      style={{ background: `${colors.surface1}f2`, border: `1px solid ${colors.hairline}`, backdropFilter: 'blur(10px)' }}>
      <div className="flex items-center justify-between p-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-widest" style={{ ...mono, color: colors.ink }}>
          <Brain className="w-4 h-4" style={{ color: '#fb923c' }} /> The Brain in Numbers
        </div>
        <button onClick={onClose} aria-label="Close brain panel" className="p-1 rounded hover:opacity-70"
          style={{ color: colors.inkSubtle }}>
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'Notes and rules', value: stats?.notes ?? 0, color: colors.primary },
            { label: 'Graph links', value: stats?.links ?? 0, color: colors.info },
            { label: 'Skills learned', value: stats?.skills ?? 0, color: colors.warning },
            { label: 'Agent runs', value: stats?.executions ?? 0, color: colors.success },
          ].map(s => (
            <div key={s.label} className="p-2.5 rounded-lg"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
              <div className="text-[19px] font-bold" style={{ ...mono, color: s.color }}><CountUp value={s.value} /></div>
              <div className="text-[10px] font-semibold" style={{ color: colors.inkSubtle }}>{s.label}</div>
            </div>
          ))}
        </div>

        {stats?.clusters?.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest" style={{ ...mono, color: colors.inkSubtle }}>
              Knowledge domains
            </div>
            {stats.clusters.slice(0, 8).map((c: any) => (
              <div key={c.domain} className="flex items-center gap-2">
                <span className="text-[11px] w-20 truncate shrink-0" style={{ color: colors.ink }}>{c.label}</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: colors.surface2 }}>
                  <div className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${Math.max(4, c.weight * 100)}%`, background: domainColor(c.domain) }} />
                </div>
                <span className="text-[10px] w-7 text-right shrink-0" style={{ ...mono, color: colors.inkSubtle }}>{c.count}</span>
              </div>
            ))}
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center gap-2 rounded-lg px-2.5 py-2"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <Search className="w-3.5 h-3.5 shrink-0" style={{ color: colors.inkSubtle }} />
            <input value={q} onChange={e => setQ(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') search(); }}
              placeholder="Query the whole brain"
              className="flex-1 bg-transparent outline-none text-[12px] min-w-0"
              style={{ color: colors.ink }} aria-label="Query the company brain" />
            {searching && <span className="w-3 h-3 border-2 rounded-full animate-spin shrink-0"
              style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />}
          </div>
          {results !== null && (
            results.length === 0 ? (
              <div className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Nothing in the brain matches that yet.
              </div>
            ) : (
              <div className="space-y-1.5">
                {results.map((r: any, i: number) => (
                  <div key={`${r.kind}-${r.id}-${i}`} className="p-2 rounded-lg text-[12px] leading-snug"
                    style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-[10px] font-bold px-1.5 py-px rounded-full"
                        style={{ background: `${kindColor[r.kind] || colors.info}22`, color: kindColor[r.kind] || colors.info }}>
                        {humanize(r.kind)}
                      </span>
                      {r.domain && <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{humanize(r.domain)}</span>}
                      {typeof r.score === 'number' && (
                        <span className="text-[10px] ml-auto" style={{ ...mono, color: colors.inkTertiary }}>
                          {Math.round(r.score * 100)}%
                        </span>
                      )}
                    </div>
                    {r.content}
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Free-flow graph: TwinGraph physics over the neural world.                  */
/* ────────────────────────────────────────────────────────────────────────── */

function toTwinData(nodes: any[], edges: any[]) {
  return {
    nodes: (nodes || []).map((n: any) => ({
      ...n,
      name: n.label,
      label: TYPE_LABEL[n.type] || 'Process',
    })),
    links: (edges || []).map((e: any) => ({ source: e.source, target: e.target, type: e.tier })),
  };
}

function FreeFlowGraph({
  nodes,
  edges,
  departments,
  onOpenBrain,
}: {
  nodes: any[];
  edges: any[];
  departments: any[];
  onOpenBrain?: () => void;
}) {
  const { colors } = useTheme();
  const [target, setTarget] = useState<DossierTarget | null>(null);
  const [shock, setShock] = useState<ShockPulse | undefined>(undefined);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ x: number; y: number; zoom: number; ts: number } | null>(null);

  const data = useMemo(() => toTwinData(nodes, edges), [nodes, edges]);

  // ‹ › camera navigation between department clusters, like walking the wall.
  const focusDept = useCallback((i: number | null) => {
    setFocusIdx(i);
    const n = Math.max(1, departments.length);
    const margin = 60;
    const slot = (TWIN_W - margin * 2) / n;
    if (i === null) {
      setFocus({ x: TWIN_W / 2, y: TWIN_H / 2, zoom: 1, ts: Date.now() });
    } else {
      setFocus({ x: margin + slot * (i + 0.5), y: TWIN_H * 0.44, zoom: 1.4, ts: Date.now() });
    }
  }, [departments.length]);

  // The video's structure, kept alive by physics: department brains in a
  // horizontal sequence at the bottom, each department's agents floating
  // ABOVE it, tasks above the agents, shared systems at the top, and the
  // company brain underneath the line. These are spring anchors - the sim
  // still breathes and everything stays draggable.
  const seedPositions = useMemo(() => {
    const pos: Record<string, { x: number; y: number }> = {};
    const n = Math.max(1, departments.length);
    const margin = 60;
    const slot = (TWIN_W - margin * 2) / n;
    const bySlug = new Map(departments.map((d: any, i: number) => [d.slug, i]));
    const counters: Record<string, Record<string, number>> = {};
    const totals: Record<string, Record<string, number>> = {};
    for (const node of nodes || []) {
      const t = node.type;
      if (!node.dept || !bySlug.has(node.dept)) continue;
      (totals[node.dept] ||= {})[t] = ((totals[node.dept] ||= {})[t] || 0) + 1;
    }
    const place = (node: any, y: number, spreadFactor: number, rowJitter = 0) => {
      const i = bySlug.get(node.dept)!;
      const cx = margin + slot * (i + 0.5);
      const c = ((counters[node.dept] ||= {})[node.type] =
        ((counters[node.dept] ||= {})[node.type] || 0) + 1) - 1;
      const total = totals[node.dept]?.[node.type] || 1;
      const width = slot * spreadFactor;
      const x = total === 1 ? cx : cx - width / 2 + (width * c) / (total - 1);
      pos[node.id] = { x, y: y + (rowJitter ? (c % 2 === 0 ? -rowJitter : rowJitter) : 0) };
    };
    for (const node of nodes || []) {
      if (node.type === 'brain') { pos[node.id] = { x: TWIN_W / 2, y: TWIN_H * 0.95 }; continue; }
      if (!node.dept || !bySlug.has(node.dept)) continue;
      if (node.type === 'department') {
        pos[node.id] = { x: margin + slot * (bySlug.get(node.dept)! + 0.5), y: TWIN_H * 0.74 };
      } else if (node.type === 'agent') place(node, TWIN_H * 0.44, 0.78, 20);
      else if (node.type === 'task') place(node, TWIN_H * 0.24, 0.86, 16);
      else if (node.type === 'connector') place(node, TWIN_H * 0.08, 0.7, 8);
      else if (node.type === 'capability') place(node, TWIN_H * 0.87, 0.6, 6);
      else if (node.type === 'process') place(node, TWIN_H * 0.93, 0.8, 5);
    }
    return pos;
  }, [nodes, departments]);

  // Adjacency for cluster pulses (click a department chip → its cluster lights up).
  const adjacency = useMemo(() => {
    const adj: Record<string, string[]> = {};
    for (const e of edges || []) {
      (adj[e.source] ||= []).push(e.target);
      (adj[e.target] ||= []).push(e.source);
    }
    return adj;
  }, [edges]);

  const pulseDept = (deptId: string) => {
    const impacted = new Set<string>();
    let frontier = [deptId];
    for (let depth = 0; depth < 2; depth++) {
      const next: string[] = [];
      for (const id of frontier) {
        for (const nb of adjacency[id] || []) {
          if (nb !== 'brain' && !impacted.has(nb)) { impacted.add(nb); next.push(nb); }
        }
      }
      frontier = next;
    }
    setShock({ targetId: deptId, impactedIds: [...impacted], severity: 30, ts: Date.now() });
  };

  const handleClick = (node: any) => {
    if (node.label === 'Agent') setTarget({ kind: 'agent', id: node.id, label: node.name });
    else if (node.label === 'Task') setTarget({ kind: 'task', id: node.skill_id, label: node.name });
    else if (node.label === 'Department') {
      pulseDept(node.id);
      const i = departments.findIndex((d: any) => d.slug === node.dept);
      if (i >= 0) focusDept(i);
    }
    else if (node.label === 'Brain') onOpenBrain?.();
  };

  const focused = focusIdx !== null ? departments[focusIdx] : null;

  return (
    <div className="relative h-full w-full overflow-hidden">
      <TwinGraph data={data} onNodeClick={handleClick} shock={shock} seedPositions={seedPositions}
        territories={false} labelsAlways focus={focus} />

      {/* ‹ › walk the departments; the center resets to the whole map. */}
      {departments.length > 1 && (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-0.5 px-1.5 py-1 rounded-full z-10"
          style={{ background: `${colors.surface1}ee`, border: `1px solid ${colors.hairline}`, backdropFilter: 'blur(8px)' }}>
          <button
            onClick={() => focusDept(focusIdx === null ? departments.length - 1 : (focusIdx + departments.length - 1) % departments.length)}
            aria-label="Previous department"
            className="px-2 py-0.5 rounded-full text-[15px] leading-none transition-colors hover:opacity-70"
            style={{ color: colors.inkSubtle }}>
            &lsaquo;
          </button>
          <button onClick={() => focusDept(null)}
            title="Show the whole map"
            className="text-[11px] font-bold uppercase tracking-wider px-2 min-w-[128px] text-center transition-colors hover:opacity-80"
            style={{ fontFamily: 'var(--font-mono, monospace)', color: focused ? domainColor(focused.slug) : colors.inkSubtle }}>
            {focused ? focused.name : 'All departments'}
          </button>
          <button
            onClick={() => focusDept(focusIdx === null ? 0 : (focusIdx + 1) % departments.length)}
            aria-label="Next department"
            className="px-2 py-0.5 rounded-full text-[15px] leading-none transition-colors hover:opacity-70"
            style={{ color: colors.inkSubtle }}>
            &rsaquo;
          </button>
        </div>
      )}

      {target && <DossierDrawer target={target} onClose={() => setTarget(null)} />}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Brain mode: the knowledge core sphere with departments on its ring.        */
/* ────────────────────────────────────────────────────────────────────────── */

function BrainCanvas({
  departments,
  stats,
  onOpenDept,
  onOpenBrain,
}: {
  departments: any[];
  stats: any;
  onOpenDept: (slug: string) => void;
  onOpenBrain?: () => void;
}) {
  const { colors } = useTheme();
  const [containerRef, { w, h }] = useMeasured();

  const layout = useMemo(() => {
    if (!w || !h) return null;
    const cx = w / 2, cy = h / 2;
    const rx = Math.max(180, Math.min(w * 0.34, w / 2 - 140));
    const ry = Math.max(130, Math.min(h * 0.38, h / 2 - 70));
    const items = departments.map((d, i) => {
      const a = -Math.PI / 2 + (i / Math.max(1, departments.length)) * Math.PI * 2;
      return { ...d, x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry };
    });
    return { cx, cy, rx, ry, items };
  }, [departments, w, h]);

  const brainSize = layout ? Math.max(200, Math.min(340, layout.ry * 1.5)) : 240;
  const clusterLabels = (stats?.clusters || []).slice(0, 6);
  const mono: React.CSSProperties = { fontFamily: 'var(--font-mono, monospace)' };

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden select-none"
      style={{ background: `radial-gradient(ellipse at center, ${colors.primary}10 0%, transparent 60%), ${colors.canvas}` }}>
      {/* Grid backdrop */}
      <div className="absolute inset-0 pointer-events-none" aria-hidden="true"
        style={{
          backgroundImage: `linear-gradient(${colors.hairline}55 1px, transparent 1px), linear-gradient(90deg, ${colors.hairline}55 1px, transparent 1px)`,
          backgroundSize: '44px 44px',
          maskImage: 'radial-gradient(ellipse at center, black 55%, transparent 100%)',
        }} />

      {layout && (
        <>
          <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
            {/* Sphere containment ring */}
            <circle cx={layout.cx} cy={layout.cy} r={brainSize / 2 + 10}
              fill="none" stroke={colors.hairlineStrong || colors.hairline} strokeWidth={1} />
            {/* Orbit ellipse, slowly rotating */}
            <g className="neural-ring-spin" style={{ transformOrigin: `${layout.cx}px ${layout.cy}px` }}>
              <ellipse cx={layout.cx} cy={layout.cy} rx={layout.rx} ry={layout.ry}
                fill="none" stroke={colors.hairlineStrong || colors.hairline} strokeDasharray="3 7" strokeWidth={1} />
            </g>
            {/* Dashed spokes from the sphere to each department */}
            {layout.items.map(d => {
              const dx = d.x - layout.cx, dy = d.y - layout.cy;
              const dist = Math.hypot(dx, dy) || 1;
              const sx = layout.cx + (dx / dist) * (brainSize / 2 + 10);
              const sy = layout.cy + (dy / dist) * (brainSize / 2 + 10);
              return (
                <line key={d.id} x1={sx} y1={sy} x2={d.x} y2={d.y}
                  className="neural-edge-slow" stroke={domainColor(d.slug)} strokeOpacity={0.55} strokeWidth={1.2} />
              );
            })}
          </svg>

          {/* The knowledge core */}
          <button onClick={onOpenBrain} aria-label="Open the brain stats panel"
            className="absolute cursor-pointer"
            style={{ left: layout.cx, top: layout.cy, transform: 'translate(-50%, -50%)' }}>
            <BrainParticles size={brainSize} color="#fb923c" accent="#ef4444" density={Math.round(brainSize * 0.62)} />
          </button>

          {/* Cluster labels floating at the sphere edge */}
          {clusterLabels.map((c: any, i: number) => {
            const a = (i / Math.max(1, clusterLabels.length)) * Math.PI * 2 + 0.5;
            const r = brainSize / 2 * 0.72;
            return (
              <span key={c.domain} className="absolute text-[9px] uppercase tracking-wider pointer-events-none px-1 rounded"
                style={{
                  ...mono,
                  left: layout.cx + Math.cos(a) * r, top: layout.cy + Math.sin(a) * r,
                  transform: 'translate(-50%, -50%)',
                  color: colors.ink, background: `${colors.canvas}aa`,
                }}>
                {c.label}
              </span>
            );
          })}

          {/* Departments on the ring */}
          {layout.items.map(d => {
            const c = domainColor(d.slug);
            return (
              <button key={d.id} onClick={() => onOpenDept(d.slug)}
                className="absolute flex flex-col items-center gap-1 cursor-pointer group"
                style={{ left: d.x, top: d.y, transform: 'translate(-50%, -50%)' }}
                aria-label={`Open the ${d.name} cluster`}>
                <div className="w-12 h-12 rounded-full flex items-center justify-center transition-transform group-hover:scale-110"
                  style={{ border: `2px solid ${c}`, background: `${c}14`, boxShadow: `0 0 18px ${c}44` }}>
                  <DomainIcon hint={d.slug} fallbackHint={d.name} size={30} />
                </div>
                <span className="text-[11px] font-bold uppercase tracking-wide max-w-[150px] truncate"
                  style={{ ...mono, color: c }}>
                  {d.name}
                </span>
                <span className="text-[9px] font-semibold" style={{ color: colors.inkSubtle }}>
                  {d.agent_count || 0} agents
                </span>
              </button>
            );
          })}
        </>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Single-department free-flow graph (Network tab on a department page).      */
/* ────────────────────────────────────────────────────────────────────────── */

export function DeptNetworkGraph({
  deptRef,
  onNavigateDept,
}: {
  deptRef: string;
  onNavigateDept?: (slug: string) => void;
}) {
  const { colors } = useTheme();
  const [graph, setGraph] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<DossierTarget | null>(null);

  const load = useCallback((silent?: boolean) => {
    if (silent !== true) setLoading(true);
    setError(null);
    return api.getNeuralDeptGraph(deptRef)
      .then(setGraph)
      .catch(e => setError(e?.message || 'Could not load the department network'))
      .finally(() => setLoading(false));
  }, [deptRef]);

  useEffect(() => { setTarget(null); load(); }, [load]);
  useLiveRefresh(() => load(true), { intervalMs: 30000 });

  if (loading) return <BrainLoading message="Waking the department network..." />;
  if (error) return <BrainError message={error} onRetry={load} />;
  if (!graph) return <BrainEmpty title="No network yet" />;

  const data = toTwinData(graph.nodes, graph.edges);
  return (
    <div className="relative h-full w-full overflow-hidden">
      <TwinGraph data={data} onNodeClick={(node: any) => {
        if (node.label === 'Agent') setTarget({ kind: 'agent', id: node.id, label: node.name });
        else if (node.label === 'Task') setTarget({ kind: 'task', id: node.skill_id, label: node.name });
      }} />
      {(graph.prev || graph.next) && onNavigateDept && (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-1 rounded-full z-10"
          style={{ background: `${colors.surface1}ee`, border: `1px solid ${colors.hairline}` }}>
          <button onClick={() => graph.prev && onNavigateDept(graph.prev)} aria-label="Previous department"
            className="px-2 py-1 rounded-full text-[13px] transition-colors hover:opacity-70" style={{ color: colors.inkSubtle }}>
            &lsaquo;
          </button>
          <span className="text-[12px] font-bold px-2 min-w-[90px] text-center" style={{ color: colors.ink }}>
            {graph.department?.name}
          </span>
          <button onClick={() => graph.next && onNavigateDept(graph.next)} aria-label="Next department"
            className="px-2 py-1 rounded-full text-[13px] transition-colors hover:opacity-70" style={{ color: colors.inkSubtle }}>
            &rsaquo;
          </button>
        </div>
      )}
      {target && <DossierDrawer target={target} onClose={() => setTarget(null)} />}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* The full Neural Map experience.                                            */
/* ────────────────────────────────────────────────────────────────────────── */

export default function NeuralMapView({ onOpenDept }: { onOpenDept?: (slug: string) => void }) {
  const { colors } = useTheme();
  const [mode, setMode] = useState<'flow' | 'brain'>('flow');
  const [world, setWorld] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [brainOpen, setBrainOpen] = useState(false);

  const load = useCallback((silent?: boolean) => {
    if (silent !== true) setLoading(true);
    setError(null);
    return api.getNeuralWorld()
      .then(setWorld)
      .catch(e => setError(e?.message || 'Could not load the neural map'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(() => load(true), { intervalMs: 30000 });

  const mono: React.CSSProperties = { fontFamily: 'var(--font-mono, monospace)' };
  const stats = world?.brain;

  return (
    <div className="h-full w-full relative min-h-0 overflow-hidden" style={{ background: colors.canvas }}
      role="region"
      aria-label="Neural map: a live graph of your company's departments, agents and knowledge core. A text list of departments follows.">
      {/* Keyboardable text alternative to the canvas graph, for screen readers
          and keyboard users who can't interact with the visual force graph. */}
      {!loading && !error && world?.departments?.length ? (
        <ul className="sr-only">
          {stats && (
            <li>{`Knowledge core: ${stats.notes} notes, ${stats.links} links, ${stats.executions} runs.`}</li>
          )}
          {world.departments.map((d: any) => (
            <li key={d.slug}>{`${d.name} department, ${d.agent_count || 0} agents.`}</li>
          ))}
        </ul>
      ) : null}
      {loading ? (
        <BrainLoading message="Waking the neural map..." />
      ) : error ? (
        <BrainError message={error} onRetry={load} />
      ) : !world?.departments?.length ? (
        <BrainEmpty title="No departments yet"
          action="Deploy a department from the marketplace and it will appear here, in orbit around your company brain." />
      ) : (
        <>
          {mode === 'flow' ? (
            <FreeFlowGraph
              nodes={world.nodes}
              edges={world.edges}
              departments={world.departments}
              onOpenBrain={() => setBrainOpen(true)}
            />
          ) : (
            <BrainCanvas departments={world.departments} stats={stats}
              onOpenBrain={() => setBrainOpen(true)}
              onOpenDept={(slug) => { setMode('flow'); onOpenDept?.(slug); }} />
          )}

          {/* HUD: headline + mode toggle (top-left) */}
          <div className="absolute top-3 left-3 z-20 space-y-2 pointer-events-none">
            <div>
              <div className="text-[9px] uppercase tracking-[0.2em]" style={{ ...mono, color: colors.inkSubtle }}>
                // Knowledge core
              </div>
              <div className="text-[18px] font-bold uppercase tracking-[0.14em] leading-tight" style={{ ...mono, color: colors.ink }}>
                Neural Map<span className="neural-node-pulse" style={{ color: colors.primary }}>_</span>
              </div>
            </div>
            <div className="flex items-center p-0.5 rounded-lg w-fit pointer-events-auto"
              style={{ background: `${colors.surface1}ee`, border: `1px solid ${colors.hairline}` }}
              role="tablist" aria-label="Map mode">
              {([['flow', 'Free flow', Waypoints], ['brain', 'Brain', Brain]] as const).map(([id, label, Icon]) => (
                <button key={id} onClick={() => setMode(id)} role="tab" aria-selected={mode === id}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider transition-all"
                  style={{ ...mono, ...(mode === id ? { background: colors.primary, color: '#fff' } : { color: colors.inkSubtle }) }}>
                  <Icon className="w-3 h-3" /> {label}
                </button>
              ))}
            </div>
            {!brainOpen && (
              <button onClick={() => setBrainOpen(true)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider pointer-events-auto transition-colors hover:opacity-80"
                style={{ ...mono, background: `${colors.surface1}ee`, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                <Database className="w-3 h-3" style={{ color: '#fb923c' }} /> Brain stats
              </button>
            )}
          </div>

          {/* Ingest bar (top-right) */}
          {/* 46% of a phone viewport is too narrow for the ingest controls, so
              take the full width between the gutters until there is room. */}
          <div className="absolute top-3 right-3 z-20 w-[calc(100%-1.5rem)] sm:w-[min(480px,46%)]">
            <BrainIngestBar compact onLearned={() => load(true)} />
          </div>

          {/* Live status (bottom-right) */}
          {stats && (
            <div className="absolute bottom-3 right-3 z-10 hidden md:flex items-center gap-3 px-3 py-1.5 rounded-lg text-[10px] uppercase tracking-wider pointer-events-none"
              style={{ ...mono, background: `${colors.surface1}ee`, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full neural-node-pulse inline-block" style={{ background: colors.success }} />
                Live
              </span>
              <span>{stats.notes} notes</span>
              <span>{stats.links} links</span>
              <span>{stats.executions} runs</span>
            </div>
          )}

          {/* Brain panel (left) */}
          {brainOpen && <BrainPanel stats={stats} onClose={() => setBrainOpen(false)} />}
        </>
      )}
    </div>
  );
}
