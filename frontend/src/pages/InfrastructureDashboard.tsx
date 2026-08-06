import React, { useCallback, useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainError } from '../components/BrainStates';
import { CountUp } from '../components/CountUp';
import { humanize } from '../lib/format';
import { PAGE_PAD, PAGE_PAD_X } from '../lib/layout';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import {
  Cpu, DollarSign, Radio, BarChart3, AlertTriangle, CheckCircle,
  Loader2, RefreshCw, Zap, Shield, Activity, Server, CircuitBoard, Heart,
  Route, XCircle, RotateCcw
} from 'lucide-react';

type Tab = 'models' | 'cost' | 'agents';

/**
 * Only these four task types are understood by BOTH the router (which maps a
 * task to a model tier) and the estimator (which prices it), so the picker is
 * limited to their intersection - anything else silently falls back to a
 * generic estimate and would make the readout lie.
 */
const SAMPLE_TASKS: { key: string; label: string; hint: string }[] = [
  { key: 'pii_classification', label: 'Spot personal data', hint: 'Short, high-volume screening' },
  { key: 'compliance_check', label: 'Check a rule for compliance', hint: 'Everyday governed reasoning' },
  { key: 'simulation', label: 'Simulate a change', hint: 'Long-context what-if reasoning' },
  { key: 'blueprint_generation', label: 'Draft an agent blueprint', hint: 'The heaviest reasoning we do' },
];

/** The budget governor speaks in enforcement verbs; people do not. */
const BUDGET_COPY: Record<string, { text: string; tone: 'ok' | 'warn' | 'bad' }> = {
  ALLOW: { text: 'Comfortably inside budget - this would run right away.', tone: 'ok' },
  WARN: { text: 'Inside budget but past the soft limit - worth watching.', tone: 'warn' },
  DEGRADE: { text: 'Over the hard limit - this would be downgraded to a cheaper model.', tone: 'bad' },
  QUEUE: { text: 'Over the hard limit - this would be queued until the window resets.', tone: 'bad' },
  BLOCK: { text: 'Over the hard limit - this would be refused.', tone: 'bad' },
};

export default function InfrastructureDashboard({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('models');
  const [models, setModels] = useState<any[]>([]);
  const [costData, setCostData] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Circuit-breaker reset (operator action) + shared action feedback.
  const [resetting, setResetting] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ ok: boolean; text: string } | null>(null);

  // Model router probe
  const [task, setTask] = useState(SAMPLE_TASKS[1].key);
  const [routeBusy, setRouteBusy] = useState(false);
  const [route, setRoute] = useState<any>(null);
  const [estimate, setEstimate] = useState<any>(null);
  const [budget, setBudget] = useState<any>(null);

  // `silent === true` keeps the current view while the interval refresh pulls
  // new telemetry; the first load and error-retry still show the spinner.
  const load = useCallback((silent?: boolean) => {
    if (silent !== true) setLoading(true);
    setError(null);
    // Per-call defaults keep partial data visible; a total outage (every call
    // rejected) surfaces an error+retry instead of an empty dashboard.
    Promise.allSettled([
      api.getModelRegistry(),
      api.getCostTelemetry(24),
      api.getAgentRegistry(),
    ]).then(([m, c, a]) => {
      if (m.status === 'rejected' && c.status === 'rejected' && a.status === 'rejected') {
        setError((m.reason as any)?.message || 'Infrastructure services are unreachable');
        setLoading(false);
        return;
      }
      setModels(m.status === 'fulfilled' ? (m.value || []) : []);
      setCostData(c.status === 'fulfilled' ? c.value : null);
      setAgents(a.status === 'fulfilled' ? (a.value || []) : []);
      setLoading(false);
    });
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(() => load(true), { intervalMs: 20000 });

  const resetCircuit = async (agentName: string) => {
    setResetting(agentName);
    setBanner(null);
    try {
      await api.resetAgentCircuit(agentName);
      setBanner({ ok: true, text: `${agentName} is accepting work again. Its failure count was cleared.` });
      load();
    } catch (e: any) {
      setBanner({ ok: false, text: `Could not reset ${agentName}: ${e?.message || 'unknown error'}` });
    } finally {
      setResetting(null);
    }
  };

  /** Pick the model for a sample task, price it, and check it against the budget. */
  const probeRouter = async () => {
    setRouteBusy(true);
    setBanner(null);
    setRoute(null); setEstimate(null); setBudget(null);
    try {
      const [r, est] = await Promise.all([api.routeModel(task), api.estimateTokens(task)]);
      setRoute(r);
      setEstimate(est);
      const tokens = (est?.estimated_input_tokens || 0) + (est?.estimated_output_tokens || 0);
      setBudget(await api.checkBudget(tokens));
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'The router did not answer.' });
    } finally {
      setRouteBusy(false);
    }
  };

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: 'models', label: 'Model Registry', icon: Cpu },
    { id: 'cost', label: 'Cost Governor', icon: DollarSign },
    { id: 'agents', label: 'Agent Protocol', icon: Radio },
  ];

  const tierColor = (t: string) => {
    if (t === 'FAST') return '#22c55e';
    if (t === 'STANDARD') return '#3b82f6';
    if (t === 'DEEP') return '#8b5cf6';
    return '#f59e0b';
  };

  const circuitColor = (s: string) => s === 'CLOSED' ? '#22c55e' : s === 'HALF_OPEN' ? '#f59e0b' : '#ef4444';
  const healthColor = (s: string) => s === 'HEALTHY' ? '#22c55e' : s === 'DEGRADED' ? '#f59e0b' : '#ef4444';

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };

  // ArrowLeft / ArrowRight move between tabs, then focus follows selection.
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = tabs[(tabs.findIndex(t => t.id === tab) + step + tabs.length) % tabs.length];
    setTab(next.id);
    document.getElementById(`infra-tab-${next.id}`)?.focus();
  };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`flex items-center gap-1 ${PAGE_PAD_X} py-2 border-b`}
        role="tablist" aria-label="Infrastructure sections" onKeyDown={onTabKeyDown}
        style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        {tabs.map(t => (
          <button key={t.id} id={`infra-tab-${t.id}`} onClick={() => setTab(t.id)}
            role="tab" aria-selected={tab === t.id} tabIndex={tab === t.id ? 0 : -1}
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

      <div className={`flex-1 overflow-y-auto ${PAGE_PAD}`}>
        {loading && (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.inkSubtle }} />
          </div>
        )}

        {!loading && error && <BrainError message={error} onRetry={load} />}

        {banner && (
          <div className="flex items-start gap-2 px-4 py-2.5 mb-4 rounded-lg text-[12px] font-medium"
            style={{
              background: (banner.ok ? '#22c55e' : '#ef4444') + '15',
              color: banner.ok ? '#22c55e' : '#ef4444',
            }}>
            {banner.ok ? <CheckCircle className="w-4 h-4 shrink-0 mt-px" /> : <XCircle className="w-4 h-4 shrink-0 mt-px" />}
            <span className="flex-1">{banner.text}</span>
            <button onClick={() => setBanner(null)} className="text-[11px] opacity-70">dismiss</button>
          </div>
        )}

        {/* N1: Model Registry */}
        {!loading && !error && tab === 'models' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Model Registry & 4-Tier Routing</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Every request routed to optimal tier: Fast (Haiku) → Standard (Sonnet) → Deep (Opus) → Vertical
              </p>
            </div>

            {/* Tier Overview */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {['FAST', 'STANDARD', 'DEEP', 'VERTICAL'].map(tier => {
                const count = models.filter(m => m.tier === tier).length;
                const labels: Record<string, string> = { FAST: '<$0.004/task', STANDARD: '<$0.02/task', DEEP: '<$0.04/task', VERTICAL: '<$0.01/task' };
                return (
                  <div key={tier} className="p-3 rounded-xl text-center" style={{ background: tierColor(tier) + '10', border: `1px solid ${tierColor(tier)}20` }}>
                    <div className="text-[11px] font-bold" style={{ color: tierColor(tier) }}>Tier: {humanize(tier)}</div>
                    <div className="text-[20px] font-bold mt-1"><CountUp value={count} /></div>
                    <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{labels[tier]}</div>
                  </div>
                );
              })}
            </div>

            {/* Model Router — which model would run a given task, and what it costs */}
            <div style={card}>
              <div className="flex items-center gap-2 mb-1">
                <Route className="w-4 h-4" style={{ color: colors.primary }} />
                <h3 className="text-[13px] font-semibold">Model Router</h3>
              </div>
              <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
                Pick a kind of work and see which model would handle it, what it would cost, and whether the budget allows it.
              </p>
              <div className="flex items-end gap-2 flex-wrap">
                <div className="min-w-[240px]">
                  <label className="text-[11px] uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Kind of work</label>
                  <select value={task} onChange={e => setTask(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-[12px] outline-none"
                    style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                    {SAMPLE_TASKS.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                </div>
                <button onClick={probeRouter} disabled={routeBusy}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50"
                  style={{ background: colors.primary }}>
                  {routeBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Route className="w-3.5 h-3.5" />}
                  Pick a model
                </button>
                <span className="text-[11px] pb-2.5" style={{ color: colors.inkTertiary }}>
                  {SAMPLE_TASKS.find(t => t.key === task)?.hint}
                </span>
              </div>

              {route && (
                <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-3 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                    <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>Model chosen</div>
                    <div className="text-[13px] font-semibold font-mono truncate" title={route.model_name}>{route.model_name}</div>
                    <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                      {route.provider} · <span style={{ color: tierColor(route.tier) }}>{humanize(route.tier)} tier</span>
                      {route.is_canary && <span style={{ color: '#f59e0b' }}> · canary</span>}
                    </div>
                    <div className="text-[11px] mt-1.5" style={{ color: colors.inkTertiary }}>
                      {route.source === 'default_fallback'
                        ? 'No model is registered for this tier yet, so the platform default would be used.'
                        : 'Selected from your registry by success rate.'}
                    </div>
                  </div>
                  {estimate && (
                    <div className="p-3 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                      <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>Expected size</div>
                      <div className="text-[20px] font-bold">
                        ${Number(estimate.estimated_cost_usd ?? 0).toFixed(4)}
                      </div>
                      <div className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                        about {((estimate.estimated_input_tokens || 0) + (estimate.estimated_output_tokens || 0)).toLocaleString()} tokens per run
                      </div>
                      <div className="text-[11px] mt-1.5" style={{ color: colors.inkTertiary }}>
                        {(estimate.estimated_input_tokens || 0).toLocaleString()} in · {(estimate.estimated_output_tokens || 0).toLocaleString()} out
                      </div>
                    </div>
                  )}
                  {budget && (() => {
                    const copy = BUDGET_COPY[budget.action] || { text: `Budget check returned ${budget.action}.`, tone: 'warn' as const };
                    const tone = copy.tone === 'ok' ? '#22c55e' : copy.tone === 'warn' ? '#f59e0b' : '#ef4444';
                    return (
                      <div className="p-3 rounded-xl" style={{ background: tone + '10', border: `1px solid ${tone}30` }}>
                        <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.inkSubtle }}>Budget verdict</div>
                        <div className="text-[13px] font-semibold" style={{ color: tone }}>{copy.text}</div>
                        {budget.reason === 'no_budget_configured' ? (
                          <div className="text-[11px] mt-1.5" style={{ color: colors.inkTertiary }}>
                            No spending limit is set for this workspace, so nothing is being enforced.
                          </div>
                        ) : (
                          <div className="text-[11px] mt-1.5" style={{ color: colors.inkSubtle }}>
                            {budget.usage_pct}% of the window used ·{' '}
                            {(budget.tokens_remaining ?? 0).toLocaleString()} tokens and ${Number(budget.cost_remaining_usd ?? 0).toFixed(2)} left
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>

            {/* Model Table */}
            <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
              <div className="grid grid-cols-9 text-[11px] font-semibold uppercase tracking-wider px-4 py-2.5"
                style={{ background: colors.surface1, color: colors.inkSubtle }}>
                <div className="col-span-2">Model</div>
                <div>Provider</div>
                <div>Tier</div>
                <div className="text-center">Latency</div>
                <div className="text-center">Success</div>
                <div className="text-center">Cost/1k</div>
                <div className="text-center">Context</div>
                <div className="text-center">Status</div>
              </div>
              {models.length === 0 ? (
                <div className="px-4 py-10 text-center text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                  No models registered yet
                </div>
              ) : models.map((m, i) => (
                <div key={m.id} className="grid grid-cols-9 items-center px-4 py-2.5 text-[12px]"
                  style={{ borderTop: `1px solid ${colors.hairline}` }}>
                  <div className="col-span-2 font-mono text-[11px] truncate pr-2" title={m.model_name}>{m.model_name}</div>
                  <div className="capitalize truncate pr-2" title={m.provider}>{m.provider}</div>
                  <div><span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: tierColor(m.tier) + '20', color: tierColor(m.tier) }}>{humanize(m.tier)}</span></div>
                  <div className="text-center font-mono text-[11px]">{m.avg_latency_ms ?? '-'}ms</div>
                  <div className="text-center font-mono text-[11px]" style={{ color: (m.success_rate ?? 0) >= 0.95 ? '#22c55e' : '#f59e0b' }}>{m.success_rate != null ? (m.success_rate * 100).toFixed(1) + '%' : '-'}</div>
                  <div className="text-center font-mono text-[11px]">{m.cost_per_1k_input != null ? `$${m.cost_per_1k_input}` : '-'}</div>
                  <div className="text-center font-mono text-[11px]">{m.max_context_window != null ? `${(m.max_context_window / 1024).toFixed(0)}k` : '-'}</div>
                  <div className="text-center">
                    {m.is_canary ? (
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: '#f59e0b20', color: '#f59e0b' }}>Canary</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>Active</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* N2: Cost Governor */}
        {!loading && !error && tab === 'cost' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Inference Cost Governor</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                Token budgets, real-time telemetry, and cost attribution per model/agent/workflow
              </p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              {[
                { label: 'Total Tokens (24h)', value: costData?.total_tokens != null ? costData.total_tokens.toLocaleString() : '-', color: colors.primary },
                { label: 'LLM Calls (24h)', value: costData?.total_events != null ? costData.total_events.toLocaleString() : '-', color: '#3b82f6' },
                { label: 'Total Cost (24h)', value: costData?.total_cost_usd != null ? `$${costData.total_cost_usd.toFixed(2)}` : '-', color: '#22c55e' },
                { label: 'Avg Cost/Task', value: costData?.avg_cost_per_task != null ? `$${costData.avg_cost_per_task.toFixed(3)}` : '-', color: '#f59e0b' },
                { label: 'Budget Used', value: costData?.budget?.usage_pct != null ? `${costData.budget.usage_pct}%` : '-', color: '#8b5cf6' },
              ].map(s => (
                <div key={s.label} className="p-4 rounded-xl min-w-0" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[11px] uppercase tracking-wider mb-1 truncate" title={s.label} style={{ color: colors.inkSubtle }}>{s.label}</div>
                  <div className="text-[22px] font-bold" style={{ color: s.value === '-' ? colors.inkSubtle : s.color }}>{s.value}</div>
                </div>
              ))}
            </div>
            <div style={card}>
              <h3 className="text-[13px] font-semibold mb-3">Cost by Request Tier</h3>
              <div className="space-y-2">
                {(() => {
                  const tiers = Object.entries((costData?.by_tier || {}) as Record<string, any>)
                    .sort((a, b) => (b[1]?.tokens ?? 0) - (a[1]?.tokens ?? 0));
                  if (tiers.length === 0) {
                    return <div className="text-[11px]" style={{ color: colors.inkSubtle }}>No tier telemetry in the last 24h</div>;
                  }
                  const reqTierColor: Record<string, string> = {
                    fast: '#22c55e', classification: '#f59e0b', reasoning: '#8b5cf6', embedding: '#3b82f6',
                  };
                  const totalTokens = Math.max(costData?.total_tokens || 1, 1);
                  return tiers.map(([tier, tierData]) => {
                    const pct = ((tierData?.tokens ?? 0) / totalTokens) * 100;
                    const c = reqTierColor[tier.toLowerCase()] || colors.primary;
                    return (
                      <div key={tier} className="flex items-center gap-3">
                        <span className="text-[11px] font-mono w-24 truncate" title={humanize(tier)} style={{ color: c }}>{humanize(tier)}</span>
                        <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: c }} />
                        </div>
                        <span className="text-[11px] font-mono w-24 text-right">{(tierData?.tokens ?? 0).toLocaleString()} tok</span>
                        <span className="text-[11px] font-mono w-16 text-right" style={{ color: colors.inkSubtle }}>{tierData?.calls ?? 0} calls</span>
                        <span className="text-[11px] font-mono w-16 text-right" style={{ color: colors.inkSubtle }}>
                          {tierData?.avg_latency_ms != null ? `${(tierData.avg_latency_ms / 1000).toFixed(1)}s` : '-'}
                        </span>
                        <span className="text-[11px] font-mono w-14 text-right" style={{ color: '#22c55e' }}>${(tierData?.cost || 0).toFixed(2)}</span>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
            {/* Budget detail - from cost telemetry budget block */}
            {costData?.budget && (
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-3">Budget Window</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Tokens</span>
                      <span className="text-[11px] font-mono">
                        {(costData.budget.token_used ?? 0).toLocaleString()} / {(costData.budget.token_limit ?? 0).toLocaleString()}
                      </span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full transition-all duration-500" style={{
                        width: `${Math.min(100, ((costData.budget.token_used ?? 0) / Math.max(costData.budget.token_limit ?? 1, 1)) * 100)}%`,
                        background: (costData.budget.usage_pct ?? 0) >= 80 ? '#ef4444' : (costData.budget.usage_pct ?? 0) >= 50 ? '#f59e0b' : '#22c55e',
                      }} />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Spend</span>
                      <span className="text-[11px] font-mono">
                        ${(costData.budget.cost_used_usd ?? 0).toFixed(2)} / ${(costData.budget.cost_limit_usd ?? 0).toFixed(2)}
                      </span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                      <div className="h-full rounded-full transition-all duration-500" style={{
                        width: `${Math.min(100, ((costData.budget.cost_used_usd ?? 0) / Math.max(costData.budget.cost_limit_usd ?? 1, 0.01)) * 100)}%`,
                        background: '#22c55e',
                      }} />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* N3: Agent Protocol */}
        {!loading && !error && tab === 'agents' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Agent Protocol & Circuit Breakers</h2>
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                {agents.length} registered agents. Circuit breakers prevent cascade failures.
              </p>
            </div>
            {agents.length === 0 ? (
              <div className="py-10 text-center text-[12px]" style={{ color: colors.inkSubtle }}>
                No agents registered yet
              </div>
            ) : (
            <div className="grid grid-cols-1 gap-3">
              {agents.map(a => (
                <div key={a.id} className="flex items-center gap-4 p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: healthColor(a.health_status) + '15' }}>
                    <Heart className="w-5 h-5" style={{ color: healthColor(a.health_status) }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold truncate" title={a.agent_name}>{a.agent_name}</span>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold flex-shrink-0" style={{ background: colors.primary + '15', color: colors.primary }}>{humanize(a.agent_type)}</span>
                      {a.model_tier_preference && (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-bold flex-shrink-0" style={{ background: tierColor(a.model_tier_preference) + '15', color: tierColor(a.model_tier_preference) }}>
                          {humanize(a.model_tier_preference)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <span className="truncate" title={(a.capabilities || []).join(', ')}>Capabilities: {(a.capabilities || []).join(', ')}</span>
                      {a.last_heartbeat && (
                        <span className="flex-shrink-0 whitespace-nowrap">Heartbeat: {new Date(a.last_heartbeat).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-[11px] flex-shrink-0">
                    <div className="text-center">
                      <div className="font-mono font-bold">{a.current_load}/{a.max_concurrent}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Load</div>
                    </div>
                    <div className="text-center">
                      <div className="font-mono font-bold" style={{ color: (a.failure_count ?? 0) > 0 ? '#f59e0b' : colors.ink }}>{a.failure_count ?? 0}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Failures</div>
                    </div>
                    <div className="text-center">
                      <div className="font-bold" style={{ color: circuitColor(a.circuit_state) }}>{humanize(a.circuit_state)}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Circuit</div>
                    </div>
                    {a.circuit_state !== 'CLOSED' && (
                      <button onClick={() => resetCircuit(a.agent_name)} disabled={resetting === a.agent_name}
                        title="Let this agent take work again and clear its failure count"
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold disabled:opacity-50"
                        style={{ background: '#f59e0b18', color: '#f59e0b', border: '1px solid #f59e0b40' }}>
                        {resetting === a.agent_name ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                        {resetting === a.agent_name ? 'Resetting…' : 'Reset'}
                      </button>
                    )}
                    <div className="text-center">
                      <div className="font-bold" style={{ color: healthColor(a.health_status) }}>{humanize(a.health_status)}</div>
                      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Health</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
