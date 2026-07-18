import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plug, Rocket, Cpu, ShieldCheck, Users, Factory, CheckCircle2,
  ArrowRight, Sparkles, RefreshCw, PartyPopper,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

// Read a numeric field that different endpoints spell differently, defensively.
function firstNum(obj: any, keys: string[]): number {
  if (!obj || typeof obj !== 'object') return 0;
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === 'number' && !Number.isNaN(v)) return v;
  }
  return 0;
}

interface Step {
  key: string;
  title: string;
  desc: string;
  icon: React.ElementType;
  color: string;
  cta: string;
  path: string;
  done: boolean;
  optional?: boolean;
}

export default function GettingStarted() {
  const { colors } = useTheme();
  const { user, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [steps, setSteps] = useState<Step[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [connectors, departments, llm, users, overview, foundry] = await Promise.all([
      api.getConnectors().catch(() => null),
      api.getWorkforceDepartments().catch(() => null),
      api.getLLMConfig().catch(() => null),
      isAdmin ? api.authUsers().catch(() => null) : Promise.resolve(null),
      api.getWorkforceOverview().catch(() => null),
      api.getFoundryStats().catch(() => null),
    ]);

    const connectedCount = firstNum(connectors?.stats, ['connected']) ||
      (Array.isArray(connectors?.connectors) ? connectors.connectors.filter((c: any) => (c.status || '').toUpperCase() === 'CONNECTED').length : 0);
    const deptCount = Array.isArray(departments) ? departments.length
      : firstNum(overview, ['departments', 'total_departments', 'department_count']);
    const llmConfigured = Array.isArray(llm) && llm.length > 0;
    const userCount = Array.isArray(users) ? users.length : 0;
    const executions = firstNum(overview, ['total_executions', 'executions', 'executions_total', 'tasks_completed', 'decisions']) ||
      firstNum(foundry, ['total_examples']);

    const built: Step[] = [
      {
        key: 'connect', title: 'Connect your first data source', icon: Plug, color: '#06b6d4',
        desc: 'Link a system of record - CRM, HR, finance, Slack - so KAEOS reasons over your real data.',
        cta: 'Connect a system', path: '/integrations', done: connectedCount > 0,
      },
      {
        key: 'deploy', title: 'Deploy your first department', icon: Rocket, color: colors.primary,
        desc: 'Stand up a governed AI department from a domain pack in four guided steps.',
        cta: 'Deploy a department', path: '/deploy', done: deptCount > 0,
      },
      {
        key: 'decision', title: 'Run your first governed decision', icon: ShieldCheck, color: '#27a644',
        desc: 'Trigger an agent action and watch it walk the 7-gate pipeline - the product’s core promise.',
        cta: 'Open a department', path: '/departments', done: executions > 0,
      },
      {
        key: 'ai', title: 'Configure your AI model', icon: Cpu, color: '#8b5cf6', optional: true,
        desc: 'Bring your own model or keep the platform default. A weaker model simply routes more decisions to humans.',
        cta: 'Open AI settings', path: '/platform/settings', done: llmConfigured,
      },
      {
        key: 'team', title: 'Invite your team', icon: Users, color: '#f59e0b', optional: true,
        desc: 'Add teammates as admins, analysts, or viewers so the right people approve the right decisions.',
        cta: 'Manage users', path: '/platform/users', done: isAdmin ? userCount > 1 : true,
      },
      {
        key: 'foundry', title: 'Watch your AI training dataset grow', icon: Factory, color: colors.primary, optional: true,
        desc: 'Every governed decision becomes training data. Your activity is quietly building a bespoke AI asset.',
        cta: 'Open the AI Foundry', path: '/platform/foundry', done: executions > 0,
      },
    ];
    setSteps(built);
    setLoading(false);
  }, [isAdmin, colors.primary]);

  useEffect(() => { load(); }, [load]);

  const core = steps.filter(s => !s.optional);
  const coreDone = core.filter(s => s.done).length;
  const allDone = core.length > 0 && coreDone === core.length;
  const pct = core.length ? Math.round((coreDone / core.length) * 100) : 0;

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`, padding: '20px',
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Hero */}
        <div className="rounded-2xl p-6 relative overflow-hidden"
          style={{ background: `linear-gradient(135deg, ${colors.primary}18, ${colors.surface1})`, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Sparkles className="w-5 h-5" style={{ color: colors.primary }} />
                <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.primary }}>Getting started</span>
              </div>
              <h1 className="text-[24px] font-bold tracking-tight">
                Welcome{user?.display_name ? `, ${user.display_name.split(' ')[0]}` : ''}
              </h1>
              <p className="text-[13px] mt-1 max-w-xl" style={{ color: colors.inkSubtle }}>
                A few steps stand up your governed AI workforce. Each one is quick, and you can leave and come back -
                this checklist reflects your live status.
              </p>
            </div>
            <button onClick={load}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium hover:opacity-80"
              style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
            </button>
          </div>
          {/* Progress */}
          <div className="mt-5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>
                {allDone ? 'All set up' : `${coreDone} of ${core.length} essentials complete`}
              </span>
              <span className="text-[12px] tabular-nums font-semibold" style={{ color: colors.primary }}>{pct}%</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
              <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${colors.primary}, ${colors.primaryHover})` }} />
            </div>
          </div>
        </div>

        {allDone && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl" style={{ background: 'rgba(39,166,68,0.1)', border: '1px solid rgba(39,166,68,0.25)' }}>
            <PartyPopper className="w-5 h-5 shrink-0" style={{ color: colors.success }} />
            <div className="text-[13px]" style={{ color: colors.inkMuted }}>
              <span className="font-semibold" style={{ color: colors.ink }}>You’re live.</span> Your governed AI workforce is running.
              Explore the optional steps below to get more from KAEOS.
            </div>
          </div>
        )}

        {/* Steps */}
        <div className="space-y-3">
          {steps.map((s, i) => (
            <div key={s.key} style={card}
              className="flex items-center gap-4 transition-all hover:border-opacity-100"
              onClick={() => navigate(s.path)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') navigate(s.path); }}
            >
              <div className="shrink-0">
                {s.done
                  ? <CheckCircle2 className="w-7 h-7" style={{ color: colors.success }} />
                  : <div className="w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-bold"
                      style={{ border: `2px solid ${colors.hairlineStrong}`, color: colors.inkSubtle }}>{i + 1}</div>}
              </div>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: s.color + '18' }}>
                <s.icon className="w-4.5 h-4.5" style={{ color: s.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-semibold" style={{ color: colors.ink, textDecoration: s.done ? 'none' : 'none' }}>{s.title}</span>
                  {s.optional && <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full" style={{ background: colors.surface3, color: colors.inkTertiary }}>Optional</span>}
                </div>
                <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{s.desc}</p>
              </div>
              <button
                className="shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all hover:opacity-90"
                style={s.done
                  ? { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }
                  : { background: colors.primary, color: '#fff' }}
                onClick={(e) => { e.stopPropagation(); navigate(s.path); }}>
                {s.done ? 'Review' : s.cta} <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-center pt-2" style={{ color: colors.inkTertiary }}>
          Need a hand? Every screen has a copilot - open it from the chat icon in the top bar.
        </p>
      </div>
    </div>
  );
}
