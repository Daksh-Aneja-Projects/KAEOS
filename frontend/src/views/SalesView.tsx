import React, { useEffect, useState } from 'react';
import {
  TrendingUp, Users, BarChart2, Briefcase, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle, Star,
  ShieldAlert, FileText, Calculator, Wallet, BadgeDollarSign
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { timeAgo } from '../lib/time';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import BulkActionBar from '../components/BulkActionBar';
import { useBulkSelect } from '../hooks/useBulkSelect';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';

type SalesTab = 'opportunities' | 'leads' | 'forecasts' | 'accounts' | 'commission' | 'analytics';

interface CommissionRow {
  id: string; plan_id: string | null; plan_name: string | null; opportunity_id: string | null;
  deal_value: number; calculated_payout: number;
  is_approved: boolean | null; paid_date: string | null;
}

interface Opportunity { id: string; name: string; account: string | null; stage: string; value: number; close_date: string | null; win_probability: number; next_step: string | null; }
interface Lead { id: string; name: string; company: string; email: string; source: string; status: string; score: number; }
interface Forecast { id: string; period: string; rep: string | null; committed: number; best_case: number; pipeline: number; quota: number; }
interface SalesAccount { id: string; name: string; industry: string; arr: number; health: string; owner: string | null; last_activity: string | null; }

const SalesView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<SalesTab>(() => {
    const valid: SalesTab[] = ['opportunities', 'leads', 'forecasts', 'accounts', 'commission', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as SalesTab)) return defaultTab as SalesTab;
    return 'opportunities';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [accounts, setAccounts] = useState<SalesAccount[]>([]);
  const [commissions, setCommissions] = useState<CommissionRow[]>([]);
  // CPQ runs through the same 7-gate pipeline as every other sales agent; the
  // quote gets its own card (discount %, margin summary, counter) instead of
  // the generic gate trace because that is the shape a rep actually wants to read.
  const [quote, setQuote] = useState<{ opportunity: string; discount: number; result: any } | null>(null);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const bulk = useBulkSelect(opportunities, workflows['opportunity'], o => o.stage);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getSalesOpportunities(), api.getSalesLeads(),
      api.getSalesForecasts(), api.getSalesAccounts(),
      api.getDomainWorkflows('sales'), api.getSalesCommissions(),
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setOpportunities(val(0)); setLeads(val(1)); setForecasts(val(2)); setAccounts(val(3));
    if (results[4].status === 'fulfilled') setWorkflows((results[4] as any).value || {});
    setCommissions(val(5));
    setLoading(false);
  };

  /** CPQ is gated like every other agent, but renders as a quote card, not a gate trace. */
  const runCpq = async (opp: Opportunity) => {
    const raw = window.prompt(`What discount is being asked for on "${opp.name}"? Enter a percentage.`, '10');
    if (raw === null) return;
    const discount = Number(raw);
    if (!Number.isFinite(discount) || discount < 0 || discount > 100) {
      setActionMsg('Quote check failed: enter a discount between 0 and 100.');
      return;
    }
    setRunningAgent(`${opp.id}-cpq`);
    setActionMsg('');
    setQuote(null);
    try {
      const res = await api.runSalesCpqAgent(opp.id, discount);
      setQuote({ opportunity: opp.name, discount, result: res });
    } catch (e: any) {
      setActionMsg(`Quote check failed: ${e?.message || e}`);
    } finally {
      setRunningAgent(null);
    }
  };

  const payCommission = async (row: CommissionRow) => {
    if (!window.confirm(
      `Approve a payout of $${(row.calculated_payout || 0).toLocaleString()} on a $${(row.deal_value || 0).toLocaleString()} deal? Payouts of $10,000 or more still need a second human approval.`
    )) return;
    setRunningAgent(row.id);
    setActionMsg('');
    try {
      const res = await api.paySalesCommission(row.id);
      setActionMsg(res.status === 'APPROVED'
        ? `Payout of $${res.calculated_payout.toLocaleString()} approved at a ${(res.rate_applied * 100).toFixed(1)}% rate.`
        : `Held for a second approver: ${res.reason || 'the amount is above the automatic limit.'}`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Payout failed: ${e?.message || e}`);
    } finally {
      setRunningAgent(null);
    }
  };

  const runAgent = async (label: string, id: string, fn: (id: string) => Promise<any>) => {
    setRunningAgent(id); setActionMsg('');
    // Show the gate pipeline where the action was clicked, not as a banner
    // at the top of the page.
    setTrace({ id, label, result: undefined });
    try {
      const res = await fn(id);
      setTrace({ id, label, result: res });
      await loadData();
    } catch (e: any) {
      setActionMsg(`${label} failed: ${e?.message || e}`);
      setTrace(null);
    }
    finally { setRunningAgent(null); }
  };

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['WON', 'ACTIVE', 'QUALIFIED', 'HOT', 'CLOSED_WON', 'HEALTHY'].includes(n)) return '#22c55e';
    if (['PROPOSAL', 'NEGOTIATION', 'IN_PROGRESS', 'WARM', 'DEMO', 'DISCOVERY'].includes(n)) return '#f59e0b';
    if (['LOST', 'CHURNED', 'COLD', 'CLOSED_LOST', 'AT_RISK'].includes(n)) return '#ef4444';
    if (['PROSPECTING', 'NEW', 'PENDING'].includes(n)) return '#3b82f6';
    return colors.inkSubtle;
  };

  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'N/A'}
    </span>
  );

  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-16 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-12 h-12 mx-auto mb-4" style={{ color: colors.inkTertiary }} />
      <p className="text-[15px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  const TABS: { key: SalesTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'opportunities', label: 'Pipeline', icon: TrendingUp, color: '#6366f1' },
    { key: 'leads', label: 'Leads', icon: Users, color: '#f59e0b' },
    { key: 'forecasts', label: 'Forecasts', icon: BarChart2, color: '#22c55e' },
    { key: 'accounts', label: 'Accounts', icon: Briefcase, color: '#3b82f6' },
    { key: 'commission', label: 'Commission', icon: Wallet, color: '#14b8a6' },
    { key: 'analytics', label: 'Analytics', icon: BarChart3, color: '#a855f7' },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  // Left/right arrows move between tabs, as a tablist is expected to.
  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.key);
    document.getElementById(`sales-tab-${next.key}`)?.focus();
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: activeTab.color }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Sales Department</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <PlusIcon className="w-3.5 h-3.5" /> New Deal
            </button>
            <button onClick={loadData} aria-label="Refresh sales data" className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
            title="New Deal" domain="sales" entityPath="opportunities"
            fields={[
              { key: 'name', label: 'Opportunity Name', type: 'text', required: true },
              { key: 'amount', label: 'Amount ($)', type: 'number', defaultValue: 0 },
              { key: 'probability', label: 'Win Probability (%)', type: 'number', defaultValue: 10 },
              { key: 'close_date', label: 'Expected Close', type: 'date' },
            ]}
            onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
        </div>

        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label="Sales sections" style={{ background: colors.surface1 }}>
          {TABS.map((t, i) => (
            <button key={t.key} id={`sales-tab-${t.key}`} role="tab"
              aria-selected={tab === t.key}
              tabIndex={tab === t.key ? 0 : -1}
              onClick={() => setTab(t.key)}
              onKeyDown={e => moveTab(e, i)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap shrink-0"
              style={{ background: tab === t.key ? colors.canvas : 'transparent', color: tab === t.key ? t.color : colors.inkSubtle, boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none' }}>
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          ))}
        </div>

        {actionMsg && (
          <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
            style={{ background: actionMsg.includes('failed') ? '#ef444415' : '#22c55e15', color: actionMsg.includes('failed') ? '#ef4444' : '#22c55e' }}>
            {actionMsg.includes('failed') ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {actionMsg}
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60">dismiss</button>
          </div>
        )}

        {trace && (
          <GateTrace running={runningAgent === trace.id} result={trace.result} skillLabel={trace.label} />
        )}

        {/* Quote verdict (CPQ is gated; its status can be a clean decision,
            pending human review, or a compliance block) */}
        {quote && (() => {
          const status = quote.result?.status;
          const badge = status === 'PENDING_HITL'
            ? { label: 'Awaiting human approval', color: '#f59e0b' }
            : status === 'BLOCKED_COMPLIANCE' || status === 'BLOCKED_FAIRNESS' || status === 'BLOCKED_DEBATE'
            ? { label: 'Blocked', color: '#ef4444' }
            : status && status !== 'SUCCESS_CLEAN'
            ? { label: 'Check failed', color: '#ef4444' }
            : quote.result?.approved
            ? { label: 'Within policy', color: '#22c55e' }
            : { label: 'Needs approval', color: '#f59e0b' };
          const blockedReason = (quote.result?.violations || [])[0]?.reason;
          return (
            <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="flex items-center gap-2 mb-2">
                <Calculator className="w-4 h-4" style={{ color: '#14b8a6' }} />
                <span className="text-[13px] font-semibold">
                  {quote.discount}% discount on {quote.opportunity}
                </span>
                <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: badge.color + '20', color: badge.color }}>
                  {badge.label}
                </span>
                <button onClick={() => setQuote(null)} className="ml-auto text-[11px] opacity-60">dismiss</button>
              </div>
              <div className="text-[12px] space-y-1" style={{ color: colors.inkSubtle }}>
                {status === 'PENDING_HITL' && (
                  <p>{quote.result?.reason || 'This discount needs a second human approver before it takes effect.'}</p>
                )}
                {(status === 'BLOCKED_COMPLIANCE' || status === 'BLOCKED_FAIRNESS' || status === 'BLOCKED_DEBATE') && (
                  <p>{blockedReason || 'A compliance or fairness gate stopped this quote before it reached a decision.'}</p>
                )}
                {quote.result?.maximum_allowable_discount != null && (
                  <p>The most this deal can give away without escalation is{' '}
                    <strong style={{ color: colors.ink }}>{quote.result.maximum_allowable_discount}%</strong>.</p>
                )}
                {quote.result?.margin_impact_summary && <p>{quote.result.margin_impact_summary}</p>}
                {quote.result?.negotiation_counter && (
                  <p><strong style={{ color: colors.ink }}>Suggested counter:</strong> {quote.result.negotiation_counter}</p>
                )}
                {!quote.result?.margin_impact_summary && !quote.result?.negotiation_counter && quote.result?.maximum_allowable_discount == null
                  && status !== 'PENDING_HITL' && !(status === 'BLOCKED_COMPLIANCE' || status === 'BLOCKED_FAIRNESS' || status === 'BLOCKED_DEBATE') && (
                  <p>The quote engine returned no detail for this deal.</p>
                )}
              </div>
            </div>
          );
        })()}

        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
          <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
            placeholder={`Search ${activeTab.label.toLowerCase()}...`}
            className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none"
            style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>
        ) : (
          <>
            {/* OPPORTUNITIES (Pipeline) */}
            {tab === 'opportunities' && (
              <div className="space-y-3">
                <BulkActionBar domain="sales" entityType="opportunity" noun="deal"
                  ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className="px-3 py-3 w-8">
                      <input type="checkbox" aria-label="Select all opportunities"
                        checked={bulk.allSelected} onChange={e => bulk.setAll(e.target.checked)} />
                    </th>
                    {['Opportunity', 'Account', 'Stage', 'Value', 'Close Date', 'Win %', 'Actions'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {opportunities.filter(o => !searchQ || o.name?.toLowerCase().includes(searchQ.toLowerCase()) || o.account?.toLowerCase().includes(searchQ.toLowerCase())).map((o) => (
                      <tr key={o.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-3 py-3">
                          <input type="checkbox" aria-label={`Select ${o.name}`}
                            checked={bulk.isSelected(o.id)} onChange={() => bulk.toggle(o.id)} />
                        </td>
                        <td className="px-4 py-3 font-medium">{o.name}</td>
                        <td className="px-4 py-3">{o.account}</td>
                        <td className="px-4 py-3"><Badge status={o.stage} /></td>
                        <td className="px-4 py-3 font-mono font-semibold">${(o.value || 0).toLocaleString()}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(o.close_date)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 rounded-full" style={{ background: colors.hairline }}>
                              <div className="h-full rounded-full" style={{ width: `${o.win_probability || 0}%`, background: (o.win_probability || 0) > 60 ? '#22c55e' : (o.win_probability || 0) > 30 ? '#f59e0b' : '#ef4444' }} />
                            </div>
                            <span className="font-mono text-[11px]">{o.win_probability || 0}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            <button onClick={() => runAgent('Pipeline coach', o.id, api.runSalesPipelineAgent)}
                              disabled={runningAgent === o.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#6366f115', color: '#6366f1' }}>
                              {runningAgent === o.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                              Coach
                            </button>
                            <button onClick={() => runAgent('Proposal draft', `${o.id}-proposal`, () => api.runSalesProposalAgent(o.id))}
                              disabled={!!runningAgent}
                              title="Draft a proposal for this deal. It always goes to a human for review before it leaves."
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                              {runningAgent === `${o.id}-proposal` ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileText className="w-3 h-3" />}
                              Proposal
                            </button>
                            <button onClick={() => runCpq(o)}
                              disabled={!!runningAgent}
                              title="Check whether a requested discount is allowed, and what it does to margin"
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#14b8a615', color: '#14b8a6' }}>
                              {runningAgent === `${o.id}-cpq` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Calculator className="w-3 h-3" />}
                              Quote
                            </button>
                          </div>
                          <div className="mt-1">
                            <WorkflowActions domain="sales" entityPath="opportunities" entityId={o.id}
                              currentState={o.stage} transitions={workflows['opportunity']?.transitions}
                              onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {opportunities.length === 0 && <EmptyState icon={TrendingUp} title="No opportunities" sub="Pipeline opportunities appear here" />}
              </div>
              </div>
            )}

            {/* LEADS */}
            {tab === 'leads' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Name', 'Company', 'Status', 'Source', 'Score', 'AI Score'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {leads.filter(l => !searchQ || l.name?.toLowerCase().includes(searchQ.toLowerCase()) || l.company?.toLowerCase().includes(searchQ.toLowerCase())).map((l) => (
                      <tr key={l.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{l.name}</td>
                        <td className="px-4 py-3">{l.company}</td>
                        <td className="px-4 py-3"><Badge status={l.status} /></td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{humanize(l.source) || '-'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            {[1,2,3,4,5].map(s => (
                              <Star key={s} className="w-3 h-3" fill={(l.score || 0) >= s ? '#f59e0b' : 'none'} style={{ color: '#f59e0b' }} />
                            ))}
                            <span className="ml-1 font-mono text-[11px]">{l.score || 0}/5</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Lead scoring', l.id, api.runSalesLeadScoringAgent)}
                            disabled={runningAgent === l.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                            style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                            {runningAgent === l.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Score
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {leads.length === 0 && <EmptyState icon={Users} title="No leads" sub="Sales leads appear here" />}
              </div>
            )}

            {/* FORECASTS */}
            {tab === 'forecasts' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Period', 'Rep / Team', 'Committed', 'Best Case', 'Pipeline', 'Quota', 'AI Predict'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {forecasts.filter(f => !searchQ || f.period?.toLowerCase().includes(searchQ.toLowerCase()) || f.rep?.toLowerCase().includes(searchQ.toLowerCase())).map((f) => (
                      <tr key={f.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{f.period}</td>
                        <td className="px-4 py-3">{f.rep || '-'}</td>
                        <td className="px-4 py-3 font-mono">${(f.committed || 0).toLocaleString()}</td>
                        <td className="px-4 py-3 font-mono">${(f.best_case || 0).toLocaleString()}</td>
                        <td className="px-4 py-3 font-mono">${(f.pipeline || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">
                          {(() => {
                            const pct = f.quota ? f.committed / f.quota : 0;
                            return (
                              <div className="space-y-1">
                                <div className="flex justify-between text-[11px]">
                                  <span>${(f.quota || 0).toLocaleString()}</span>
                                  <span style={{ color: pct > 0.8 ? '#22c55e' : '#f59e0b' }}>
                                    {Math.round(pct * 100)}%
                                  </span>
                                </div>
                                <div className="h-1 rounded-full w-24" style={{ background: colors.hairline }}>
                                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.round(pct * 100))}%`, background: '#22c55e' }} />
                                </div>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Forecast predict', f.id, api.runSalesForecastAgent)}
                            disabled={runningAgent === f.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                            style={{ background: '#22c55e15', color: '#22c55e' }}>
                            {runningAgent === f.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Predict
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {forecasts.length === 0 && <EmptyState icon={BarChart2} title="No forecasts" sub="Sales forecasts appear here" />}
              </div>
            )}

            {/* ACCOUNTS */}
            {tab === 'accounts' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Account', 'Industry', 'Health', 'ARR', 'Owner', 'Last Activity', 'AI Health'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {accounts.filter(a => !searchQ || a.name?.toLowerCase().includes(searchQ.toLowerCase())).map((a) => (
                      <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{a.name}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{humanize(a.industry) || '-'}</td>
                        <td className="px-4 py-3"><Badge status={a.health} /></td>
                        <td className="px-4 py-3 font-mono font-semibold">${(a.arr || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">{a.owner || '-'}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{a.last_activity || '-'}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            <button onClick={() => runAgent('Account health', a.id, api.runSalesAccountAgent)}
                              disabled={!!runningAgent}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#3b82f615', color: '#3b82f6' }}>
                              {runningAgent === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                              Health
                            </button>
                            <button onClick={() => runAgent('Churn risk', `${a.id}-churn`, () => api.runSalesChurnRiskAgent(a.id))}
                              disabled={!!runningAgent}
                              title="Estimate how likely this account is to leave, and what would keep it"
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#ef444415', color: '#ef4444' }}>
                              {runningAgent === `${a.id}-churn` ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldAlert className="w-3 h-3" />}
                              Churn Risk
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {accounts.length === 0 && <EmptyState icon={Briefcase} title="No accounts" sub="Sales accounts appear here" />}
              </div>
            )}

            {/* COMMISSION */}
            {tab === 'commission' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Deal Value', 'Payout', 'Approved', 'Paid', 'Plan', 'Action'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {commissions.map(c => (
                      <tr key={c.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-mono font-semibold">${(c.deal_value || 0).toLocaleString()}</td>
                        <td className="px-4 py-3 font-mono" style={{ color: '#14b8a6' }}>${(c.calculated_payout || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <Badge status={c.is_approved ? 'APPROVED' : 'PENDING'} />
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>
                          {c.paid_date ? new Date(c.paid_date.replace(' ', 'T')).toLocaleDateString() : 'Not yet paid'}
                        </td>
                        <td className="px-4 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                          {c.plan_name || 'No plan'}
                        </td>
                        <td className="px-4 py-3">
                          {c.paid_date ? (
                            <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Settled</span>
                          ) : (
                            <button onClick={() => payCommission(c)} disabled={!!runningAgent}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#14b8a615', color: '#14b8a6' }}>
                              {runningAgent === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <BadgeDollarSign className="w-3 h-3" />}
                              Approve payout
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {commissions.length === 0 && <EmptyState icon={Wallet} title="No commission calculations" sub="Payouts appear here once deals close" />}
              </div>
            )}

            {/* ANALYTICS */}
            {tab === 'analytics' && <DomainAnalytics domain="sales" />}
          </>
        )}
      </div>
    </div>
  );
};

export default SalesView;
