import React, { useEffect, useState } from 'react';
import type { SkillItem, ExecutionItem } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import ExecutionDetailView from '../components/ExecutionDetailView';
import { Bot, CheckCircle, XCircle, Clock, AlertTriangle, Zap, ArrowRight, Activity, ChevronRight } from 'lucide-react';

export default function AgentMonitor({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [allExecs, setAllExecs] = useState<ExecutionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedExec, setSelectedExec] = useState<ExecutionItem | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Derive the skill set from the live registry instead of a hardcoded
        // whitelist, so every skill's executions appear in the feed.
        const reg = await api.getSkills();
        const skillList = (reg as any)?.skills || [];
        setSkills(skillList);
        const ids: string[] = skillList
          .map((s: any) => s.skill_id || s.id || s.name)
          .filter(Boolean)
          .slice(0, 50);
        const execArrays = await Promise.all(
          ids.map((id) => api.getExecutions(id).catch(() => [])),
        );
        const flat = execArrays.flat() as ExecutionItem[];
        flat.sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
        setAllExecs(flat);
      } catch {
        /* leave empty on failure */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // ── If an execution is selected, show the detail view ──────────────────
  if (selectedExec) {
    return <ExecutionDetailView execution={selectedExec} onBack={() => setSelectedExec(null)} colors={colors} />;
  }

  if (loading) return <div className="p-8 animate-pulse" style={{ color: colors.inkTertiary }}>Loading Agent Monitor…</div>;

  const successCount = allExecs.filter((e) => e.status.includes('SUCCESS')).length;
  const overrideCount = allExecs.filter((e) => e.outcome_type === 'HUMAN_OVERRIDDEN').length;
  const failCount = allExecs.filter((e) => e.status.includes('FAILED')).length;
  const hitlCount = allExecs.filter((e) => e.hitl_required).length;

  const statusIcon = (status: string) => {
    if (status.includes('SUCCESS')) return <CheckCircle className="w-4 h-4" style={{ color: colors.success }} />;
    if (status === 'HUMAN_OVERRIDDEN') return <Clock className="w-4 h-4" style={{ color: colors.warning }} />;
    return <XCircle className="w-4 h-4" style={{ color: colors.error }} />;
  };

  const statusStyle = (status: string) => {
    if (status.includes('SUCCESS')) return { bg: 'rgba(39,166,68,0.12)', color: colors.success, border: 'rgba(39,166,68,0.25)' };
    if (status === 'HUMAN_OVERRIDDEN') return { bg: 'rgba(245,166,35,0.12)', color: colors.warning, border: 'rgba(245,166,35,0.25)' };
    return { bg: 'rgba(229,83,75,0.12)', color: colors.error, border: 'rgba(229,83,75,0.25)' };
  };

  const STATES = [
    { name: 'IDLE', desc: 'Awaiting task', color: colors.inkSubtle },
    { name: 'ROUTING', desc: 'Skill Router: exact → fuzzy → RAG', color: colors.info },
    { name: 'PRE_CHECK', desc: 'Guardrails + Compliance gate', color: colors.primary },
    { name: 'EXECUTING', desc: 'Sandbox execution with MCP tools', color: colors.primaryHover },
    { name: 'POST_CHECK', desc: 'Audit verification + provenance write', color: colors.success },
    { name: 'REPORTING', desc: 'Feedback bus → confidence update', color: colors.info },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>
          <Bot className="w-7 h-7 inline-block mr-2" style={{ color: colors.primary }} />
          Agent Monitor
        </h1>
        <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>Real-time agent execution tracking & HITL oversight</p>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Successful', value: successCount, icon: CheckCircle, accent: colors.success },
          { label: 'Overrides', value: overrideCount, icon: Clock, accent: colors.warning },
          { label: 'Failed', value: failCount, icon: XCircle, accent: colors.error },
          { label: 'Active Skills', value: skills.length, icon: Zap, accent: colors.primaryHover },
        ].map((m, i) => (
          <div key={i} className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg" style={{ background: `${m.accent}15` }}>
                <m.icon className="w-5 h-5" style={{ color: m.accent }} />
              </div>
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: colors.inkSubtle }}>{m.label}</span>
            </div>
            <div className="text-[28px] font-bold tracking-tight" style={{ color: colors.ink, fontVariantNumeric: 'tabular-nums' }}>{m.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* Execution Feed - 3 cols */}
        <div className="lg:col-span-3 rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: colors.hairline }}>
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Execution Feed</span>
            </div>
            <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{allExecs.length} total</span>
          </div>
          <div className="max-h-[600px] overflow-y-auto">
            {allExecs.slice(0, 30).map((e) => {
              const ss = statusStyle(e.status);
              return (
                <button key={e.id} onClick={() => setSelectedExec(e)}
                  className="w-full text-left flex items-center gap-3 px-5 py-3.5 border-b transition-colors"
                  style={{ borderColor: colors.hairline }}
                  onMouseEnter={ev => (ev.currentTarget.style.background = colors.surface2)}
                  onMouseLeave={ev => (ev.currentTarget.style.background = 'transparent')}>
                  {statusIcon(e.status)}
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium truncate" style={{ color: colors.ink }}>{e.task_intent}</div>
                    <div className="flex items-center gap-3 text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>
                      <span>{new Date(e.started_at).toLocaleString()}</span>
                      <span className="font-mono">{e.duration_ms}ms</span>
                      {e.hitl_required && (
                        <span className="flex items-center gap-1 font-medium" style={{ color: colors.warning }}>
                          <AlertTriangle className="w-3 h-3" /> HITL
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded"
                    style={{ background: ss.bg, color: ss.color, border: `1px solid ${ss.border}` }}>
                    {e.status.replace(/_/g, ' ')}
                  </span>
                  <ChevronRight className="w-4 h-4 flex-shrink-0" style={{ color: colors.inkTertiary }} />
                </button>
              );
            })}
          </div>
        </div>

        {/* Agent State Machine - 2 cols */}
        <div className="lg:col-span-2 space-y-5">
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <h2 className="text-[14px] font-medium mb-4" style={{ color: colors.ink }}>Agent State Machine</h2>
            <div className="space-y-3">
              {STATES.map((state, i) => (
                <div key={state.name} className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold"
                    style={{ background: `${state.color}15`, color: state.color, border: `1px solid ${state.color}30` }}>
                    {i + 1}
                  </div>
                  <div className="flex-1">
                    <div className="text-[12px] font-semibold" style={{ color: colors.ink }}>{state.name}</div>
                    <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{state.desc}</div>
                  </div>
                  {i < STATES.length - 1 && <ArrowRight className="w-3.5 h-3.5" style={{ color: colors.hairlineStrong }} />}
                </div>
              ))}
            </div>
          </div>

          {/* Latest Reasoning Chain */}
          {allExecs[0]?.reasoning_chain?.length > 0 && (
            <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <h2 className="text-[13px] font-medium mb-3" style={{ color: colors.ink }}>Latest Reasoning Chain</h2>
              <div className="space-y-2">
                {allExecs[0].reasoning_chain.map((step: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 text-[12px]">
                    <span className="font-bold font-mono w-12" style={{ color: colors.primary }}>Step {step.step}</span>
                    <span className="flex-1" style={{ color: colors.inkMuted }}>{step.action}</span>
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                      style={{
                        background: step.status === 'SUCCESS' ? 'rgba(39,166,68,0.1)' : 'rgba(229,83,75,0.1)',
                        color: step.status === 'SUCCESS' ? colors.success : colors.error,
                      }}>{step.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
