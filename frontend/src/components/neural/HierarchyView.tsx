import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Bot, MessageSquare, ShieldCheck, User } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { api } from '../../api/client';
import { humanize } from '../../lib/format';
import { CountUp } from '../CountUp';
import { BrainLoading, BrainError } from '../BrainStates';
import DomainIcon, { domainColor } from '../DomainIcon';
import { useLiveRefresh } from '../../hooks/useLiveRefresh';
import './neural.css';

/**
 * The chain of command, alive: you → the KAEOS Copilot → every department it
 * orchestrates. Flow lines animate top-down, health rings and task counters
 * run live, and "Chat with Copilot" opens the one copilot surface (App listens
 * for kaeos-open-copilot) - one assistant, one name.
 */

function HealthRing({ value, color, size = 30 }: { value: number; color: string; size?: number }) {
  const r = (size - 5) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} className="shrink-0 -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeOpacity={0.18} strokeWidth={3} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={3}
        strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={c * (1 - pct)}
        style={{ transition: 'stroke-dashoffset 0.9s ease' }} />
    </svg>
  );
}

export default function HierarchyView() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paths, setPaths] = useState<string[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const copilotRef = useRef<HTMLDivElement | null>(null);
  const operatorRef = useRef<HTMLDivElement | null>(null);
  const deptRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const load = useCallback((silent?: boolean) => {
    if (silent !== true) setLoading(true);
    setError(null);
    return api.getNeuralHierarchy()
      .then(setData)
      .catch(e => setError(e?.message || 'Could not load the hierarchy'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(() => load(true), { intervalMs: 20000 });

  // Draw the flow lines between the tiers, and keep them attached on resize.
  useLayoutEffect(() => {
    const draw = () => {
      const root = containerRef.current;
      const cop = copilotRef.current;
      const op = operatorRef.current;
      if (!root || !cop || !op) return;
      const rb = root.getBoundingClientRect();
      const rel = (el: HTMLElement) => {
        const b = el.getBoundingClientRect();
        return { cx: b.left + b.width / 2 - rb.left, top: b.top - rb.top, bottom: b.bottom - rb.top };
      };
      const o = rel(op);
      const c = rel(cop);
      const next: string[] = [`M ${o.cx} ${o.bottom} L ${c.cx} ${c.top}`];
      for (const el of deptRefs.current.values()) {
        const d = rel(el);
        const midY = c.bottom + (d.top - c.bottom) * 0.5;
        next.push(`M ${c.cx} ${c.bottom} C ${c.cx} ${midY}, ${d.cx} ${midY}, ${d.cx} ${d.top}`);
      }
      setPaths(next);
    };
    draw();
    const ro = new ResizeObserver(draw);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [data]);

  if (loading) return <BrainLoading message="Drawing the chain of command..." />;
  if (error) return <BrainError message={error} onRetry={load} />;
  if (!data) return null;

  const mono: React.CSSProperties = { fontFamily: 'var(--font-mono, monospace)' };
  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: 14, border: `1px solid ${colors.hairline}`,
  };
  const totalTasks = (data.departments || []).reduce(
    (sum: number, d: any) => sum + (d.tasks_completed_total
      || (d.agents || []).reduce((s: number, a: any) => s + (a.tasks_handled || 0), 0)), 0);
  const totalAgents = (data.departments || []).reduce((s: number, d: any) => s + (d.agents || []).length, 0);

  return (
    <div className="h-full overflow-y-auto">
      <div ref={containerRef} className="relative max-w-6xl mx-auto pb-8">
        {/* Animated flow lines underneath the cards */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
          {paths.map((d, i) => (
            <path key={i} d={d} fill="none" className="neural-edge-flow"
              stroke={colors.primary} strokeOpacity={0.5} strokeWidth={1.2} />
          ))}
        </svg>

        {/* Live totals strip */}
        <div className="flex items-center justify-center gap-4 pb-4 text-[10px] uppercase tracking-widest"
          style={{ ...mono, color: colors.inkSubtle }}>
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full neural-node-pulse inline-block" style={{ background: colors.success }} />
            Live
          </span>
          <span><CountUp value={totalAgents} /> agents on duty</span>
          <span><CountUp value={totalTasks} /> tasks handled</span>
        </div>

        {/* Operator */}
        <div ref={operatorRef} style={card} className="relative w-fit mx-auto px-5 py-3 flex items-center gap-3 neural-rise">
          <div className="w-9 h-9 rounded-full flex items-center justify-center"
            style={{ background: `${colors.success}1c`, color: colors.success }}>
            <User className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[14px] font-bold" style={{ color: colors.ink }}>{data.operator?.name}</div>
            <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
              {data.operator?.title}{data.operator?.email ? ` · ${data.operator.email}` : ''}
            </div>
          </div>
        </div>

        {/* Copilot */}
        <div ref={copilotRef}
          style={{ ...card, boxShadow: `0 0 28px ${colors.primary}20` }}
          className="relative w-full max-w-md mx-auto p-4 space-y-3 mt-9 neural-rise"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center neural-node-pulse"
              style={{ background: `${colors.primary}1c`, border: `1.5px solid ${colors.primary}`, color: colors.primary }}>
              <Bot className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-bold" style={{ color: colors.ink }}>{data.conductor?.name}</span>
                <span className="text-[10px] font-bold px-1.5 py-px rounded-full uppercase tracking-wider"
                  style={{ ...mono, background: `${colors.primary}22`, color: colors.primary }}>Super agent</span>
              </div>
              <div className="text-[12px] leading-snug" style={{ color: colors.inkSubtle }}>
                {data.conductor?.description}
              </div>
            </div>
          </div>
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('kaeos-open-copilot'))}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] transition-all hover:opacity-90"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
            <MessageSquare className="w-4 h-4" style={{ color: colors.primary }} />
            Chat with Copilot...
            <span className="ml-auto neural-node-pulse" style={{ color: colors.primary }}>_</span>
          </button>
          {typeof data.conductor?.pending_approvals === 'number' && data.conductor.pending_approvals > 0 && (
            <button onClick={() => navigate('/my-work')}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[12px] font-semibold transition-colors hover:opacity-90"
              style={{ background: `${colors.warning}14`, border: `1px solid ${colors.warning}44`, color: colors.warning }}>
              <ShieldCheck className="w-4 h-4" />
              <CountUp value={data.conductor.pending_approvals} /> decision{data.conductor.pending_approvals === 1 ? '' : 's'} waiting for a human
            </button>
          )}
        </div>

        {/* Departments */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mt-10">
          {(data.departments || []).map((d: any, i: number) => {
            const c = domainColor(d.slug);
            const deptTasks = d.tasks_completed_total
              || (d.agents || []).reduce((s: number, a: any) => s + (a.tasks_handled || 0), 0);
            return (
              <div key={d.id}
                ref={el => { if (el) deptRefs.current.set(d.id, el); else deptRefs.current.delete(d.id); }}
                style={{ ...card, borderTop: `2px solid ${c}`, animationDelay: `${0.08 * i}s` }}
                className="relative p-4 flex flex-col gap-3 neural-rise">
                <button onClick={() => navigate(`/departments/${d.slug}`)}
                  className="flex items-center gap-3 text-left transition-opacity hover:opacity-80">
                  <DomainIcon hint={d.slug} fallbackHint={d.name} size={38} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-bold truncate" style={{ color: colors.ink }}>{d.name}</div>
                    <div className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <span className="w-1.5 h-1.5 rounded-full inline-block neural-node-pulse"
                        style={{ background: d.status === 'ACTIVE' ? colors.success : colors.warning }} />
                      {humanize(d.status || 'Active')}
                      {deptTasks > 0 && (
                        <span style={{ color: colors.inkTertiary }}>
                          · <CountUp value={deptTasks} /> tasks
                        </span>
                      )}
                    </div>
                  </div>
                  {typeof d.health_score === 'number' && (
                    <div className="relative shrink-0">
                      <HealthRing value={d.health_score || 0} color={c} />
                      <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold"
                        style={{ ...mono, color: c }}>
                        {Math.round((d.health_score || 0) * 100)}
                      </span>
                    </div>
                  )}
                </button>
                <div className="space-y-1">
                  {(d.agents || []).length === 0 ? (
                    <div className="text-[12px] py-2" style={{ color: colors.inkTertiary }}>No agents deployed yet</div>
                  ) : d.agents.map((a: any) => (
                    <div key={a.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg"
                      style={{ background: colors.surface2 }}>
                      <Bot className="w-3.5 h-3.5 shrink-0" style={{ color: c }} />
                      <span className="text-[12px] font-semibold truncate flex-1" style={{ color: colors.ink }}>
                        {a.name}
                      </span>
                      {typeof a.tasks_handled === 'number' && a.tasks_handled > 0 && (
                        <span className="text-[10px] shrink-0" style={{ ...mono, color: colors.inkTertiary }}>
                          <CountUp value={a.tasks_handled} />
                        </span>
                      )}
                      <span className="w-1.5 h-1.5 rounded-full shrink-0 neural-node-pulse"
                        style={{ background: a.status === 'ACTIVE' ? colors.success : colors.warning }} />
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
