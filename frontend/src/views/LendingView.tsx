import React, { useEffect, useState } from 'react';
import {
  Landmark, FileText, Gavel, MailWarning, Search, RefreshCw, Loader2,
  Bot, CheckCircle2, XCircle, Scale, ShieldCheck, AlertTriangle,
  Wallet, SlidersHorizontal, PhoneCall, ChevronDown, ChevronUp, Pencil,
  Save, X as XIcon, Mail, Clock, BarChart3,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  DomainAnalyticsPayload, LoanApplicationRow, UnderwriteResult, AdverseActionRow,
  CreditPolicyRow, ServicedLoanRow, CollectionCaseRow, DelinquenciesPayload,
  CollectionContactResult,
} from '../api/endpoints/lending';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import Ring from '../components/shared/Ring';
import { MiniDonut } from '../components/shared/MiniDonut';
import TableCard from '../components/shared/TableCard';
import EmptyState from '../components/shared/EmptyState';
import TabBar from '../components/shared/TabBar';
import { useTabParam } from '../hooks/useTabParam';
import LiveBadge from '../components/LiveBadge';
import GateTrace, { type GateTraceResult } from '../components/GateTrace';
import DomainAnalytics from '../components/DomainAnalytics';
import { humanize, formatCurrency, formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

const ACCENT = DEPARTMENT_COLORS.lending;

type Tab = 'overview' | 'applications' | 'underwriting' | 'adverse' | 'servicing' | 'policy' | 'analytics';
const VALID: Tab[] = ['overview', 'applications', 'underwriting', 'adverse', 'servicing', 'policy'];

const APPROVABLE = ['RECEIVED', 'IN_REVIEW'];
const DECIDED = ['APPROVED', 'DENIED', 'PENDING_HITL'];

type GateLike = { status?: string; execution_id?: string; rationale?: string | null; reason?: string; violations?: any[] } | null | undefined;

/** Map an underwrite/collection-contact terminal status onto GateTrace's
 *  vocabulary, keeping only the fields GateTrace renders. A clean pass
 *  returns "success"; GateTrace speaks "SUCCESS_CLEAN". */
function toTrace(res: GateLike): GateTraceResult | undefined {
  if (!res) return undefined;
  return {
    status: res.status === 'success' ? 'SUCCESS_CLEAN' : res.status,
    execution_id: res.execution_id,
    rationale: res.rationale ?? undefined,
    reason: res.reason,
    violations: res.violations,
  };
}

type PolicyDraft = {
  min_credit_score: number; max_dti_ratio: number; min_annual_income: number;
  max_amount: number; base_apr: number;
};

const CHANNEL_LABEL: Record<string, string> = { phone: 'Phone call', mail: 'Mailed letter', email: 'Email' };

const statusColor = (s: string, colors: ReturnType<typeof useTheme>['colors']) => {
  const n = (s || '').toUpperCase();
  if (n === 'APPROVED') return colors.success;
  if (['RECEIVED', 'IN_REVIEW', 'PENDING_HITL'].includes(n)) return colors.warning;
  if (['DENIED', 'WITHDRAWN'].includes(n)) return colors.error;
  return colors.inkSubtle;
};

// Module scope on purpose: declared inside the render body this was a fresh
// component type every render, so React remounted every badge on each keystroke.
const Badge = ({ status }: { status: string }) => {
  const { colors } = useTheme();
  return (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status, colors) + '18', color: statusColor(status, colors) }}>
      {humanize(status) || 'N/A'}
    </span>
  );
};

const LendingView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useTabParam<Tab>(VALID, 'overview', defaultTab);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const [dash, setDash] = useState<DomainAnalyticsPayload | null>(null);
  const [apps, setApps] = useState<LoanApplicationRow[]>([]);
  const [notices, setNotices] = useState<AdverseActionRow[]>([]);
  const [policies, setPolicies] = useState<CreditPolicyRow[]>([]);
  const [loans, setLoans] = useState<ServicedLoanRow[]>([]);
  const [delinq, setDelinq] = useState<DelinquenciesPayload | null>(null);

  // Shared decision panel + governance trace for the last action taken.
  const [trace, setTrace] = useState<{ id: string; label: string; result?: GateTraceResult } | null>(null);
  const [decision, setDecision] = useState<UnderwriteResult | null>(null);

  // Servicing tab: which loan's payment schedule is expanded.
  const [expandedLoanId, setExpandedLoanId] = useState<string | null>(null);
  // Per-case draft for the "attempt contact" mini-form.
  const [contactDrafts, setContactDrafts] = useState<Record<string, { hour_local: number; channel: string; harassment: boolean; notes: string }>>({});

  // Policy tab: which product is being edited, and its draft values.
  const [editingPolicy, setEditingPolicy] = useState<string | null>(null);
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft | null>(null);
  const [policySaving, setPolicySaving] = useState<string | null>(null);

  useEffect(() => { loadData(); }, []);
  useLiveRefresh(loadData, { intervalMs: 20000 });

  async function loadData() {
    setLoading(true);
    const r = await Promise.allSettled([
      api.getLendingDashboard(),
      api.getLendingApplications(),
      api.getAdverseActions(),
      api.getCreditPolicies(),
      api.getServicedLoans(),
      api.getDelinquencies(),
    ]);
    const val = (i: number, d: any) => (r[i].status === 'fulfilled' ? (r[i] as any).value ?? d : d);
    setDash(val(0, null));
    setApps(val(1, []));
    setNotices(val(2, []));
    setPolicies(val(3, []));
    setLoans(val(4, []));
    setDelinq(val(5, null));
    setLastSync(Date.now());
    setLoading(false);
  }

  async function underwrite(a: LoanApplicationRow) {
    setRunning(a.id); setActionMsg(''); setDecision(null);
    const label = `Underwriting decision · application ${a.application_number}`;
    setTrace({ id: a.id, label, result: undefined });
    try {
      const res = await api.underwriteApplication(a.id);
      setTrace({ id: a.id, label, result: toTrace(res) });
      setDecision(res);
      setActionMsg(
        res.status === 'PENDING_HITL' ? 'Decision routed to a human reviewer for approval.'
          : res.decision === 'APPROVE' ? 'Application approved through the fair-lending gates.'
            : res.decision === 'DENY' ? 'Application denied. Specific principal reasons captured for the adverse-action notice.'
              : 'Underwriting completed.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`Underwriting failed: ${e?.message || e}`);
      setTrace(null);
    } finally { setRunning(null); }
  }

  async function issueNotice(a: LoanApplicationRow) {
    setRunning(a.id); setActionMsg('');
    try {
      const res = await api.issueAdverseAction(a.id);
      setActionMsg(`Adverse-action notice issued with ${res.specific_reasons.length} specific reason(s), within the 30-day ECOA window.`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Could not issue notice: ${e?.message || e}`);
    } finally { setRunning(null); }
  }

  function contactDraft(caseId: string) {
    return contactDrafts[caseId] || { hour_local: 10, channel: 'phone', harassment: false, notes: '' };
  }
  function setContactField(caseId: string, patch: Partial<{ hour_local: number; channel: string; harassment: boolean; notes: string }>) {
    setContactDrafts(prev => ({ ...prev, [caseId]: { ...contactDraft(caseId), ...patch } }));
  }

  async function attemptContact(c: CollectionCaseRow) {
    const draft = contactDraft(c.id);
    setRunning(c.id); setActionMsg(''); setDecision(null);
    const label = `Collection contact · ${c.loan_number || c.id.slice(0, 8)}`;
    setTrace({ id: c.id, label, result: undefined });
    try {
      const res: CollectionContactResult = await api.attemptCollectionContact(c.id, {
        hour_local: draft.hour_local, channel: draft.channel,
        harassment: draft.harassment, notes: draft.notes || undefined,
      });
      setTrace({ id: c.id, label, result: toTrace(res) });
      setActionMsg(
        res.status === 'success'
          ? 'Contact logged. It cleared the FDCPA gate: inside the 8am-9pm window, validation notice on file, no harassment flag.'
          : res.status === 'PENDING_HITL'
            ? 'Contact routed to a human reviewer for approval.'
            : 'Contact blocked by the FDCPA gate - nothing was added to the log.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`Contact attempt failed: ${e?.message || e}`);
      setTrace(null);
    } finally { setRunning(null); }
  }

  function startEditPolicy(p: CreditPolicyRow) {
    setEditingPolicy(p.product);
    setPolicyDraft({
      min_credit_score: p.min_credit_score, max_dti_ratio: p.max_dti_ratio,
      min_annual_income: p.min_annual_income, max_amount: p.max_amount, base_apr: p.base_apr,
    });
  }
  function cancelEditPolicy() { setEditingPolicy(null); setPolicyDraft(null); }

  async function saveEditPolicy(p: CreditPolicyRow) {
    if (!policyDraft) return;
    setPolicySaving(p.product); setActionMsg('');
    try {
      const saved = await api.putCreditPolicy(p.product, { ...policyDraft, is_active: p.is_active });
      setPolicies(prev => prev.map(x => (x.product === p.product ? saved : x)));
      setActionMsg(`${humanize(p.product)} policy updated - it now drives every automated decision on this product.`);
      cancelEditPolicy();
    } catch (e: any) {
      setActionMsg(`Could not update policy: ${e?.message || e}`);
    } finally { setPolicySaving(null); }
  }

  function scheduleWindow(loan: ServicedLoanRow) {
    const sched = loan.payment_schedule || [];
    let lastPaidIdx = -1;
    sched.forEach((r, i) => { if (r.status === 'paid') lastPaidIdx = i; });
    const start = Math.max(0, lastPaidIdx - 1);
    return sched.slice(start, start + 6);
  }

  const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'overview', label: 'Overview', icon: Landmark },
    { key: 'applications', label: 'Applications', icon: FileText },
    { key: 'underwriting', label: 'Underwriting', icon: Gavel },
    { key: 'adverse', label: 'Adverse Action', icon: MailWarning },
    { key: 'servicing', label: 'Servicing', icon: Wallet },
    { key: 'policy', label: 'Policy', icon: SlidersHorizontal },
    { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  // KPI + chart helpers from the analytics-shaped dashboard.
  const kpi = (k: string) => dash?.kpis.find(x => x.key === k);
  const approvalKpi = kpi('approval_rate');
  const approvalPct = approvalKpi?.value != null ? Math.round(approvalKpi.value * 100) : null;
  const statusMix = (dash?.charts || []).find(c => c.key === 'status_mix');
  const statusDonut = (statusMix?.items || []).map(it => ({ label: humanize(it.label), value: it.value }));
  const fairLending = (dash?.charts || []).find(c => c.key === 'fair_lending');

  const fmtKpi = (key: string): string => {
    const k = kpi(key);
    if (!k || k.value == null) return k?.note ? 'n/a' : '0';
    if (k.format === 'currency') return formatCurrency(k.value);
    if (k.format === 'ratio') return `${Math.round(k.value * 100)}%`;
    if (k.format === 'percent') return `${k.value}%`;
    return k.value.toLocaleString();
  };

  /** CountUp props for a KPI tile, format-aware; null when there is nothing
   *  real to animate (the honesty contract - never count up to a guess). */
  const kpiCountUp = (key: string): { value: number; decimals: number; prefix?: string; suffix?: string } | null => {
    const k = kpi(key);
    if (!k || k.value == null) return null;
    if (k.format === 'currency') return { value: k.value, decimals: 0, prefix: '$' };
    if (k.format === 'ratio') return { value: k.value * 100, decimals: 0, suffix: '%' };
    if (k.format === 'percent') return { value: k.value, decimals: 0, suffix: '%' };
    return { value: k.value, decimals: 0 };
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: ACCENT }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Lending &amp; Credit · underwriting governed by ECOA, fair-lending and TILA gates
            </p>
          </div>
          <div className="flex items-center gap-3">
            <LiveBadge lastSync={lastSync} />
            <button onClick={loadData} aria-label="Refresh lending data" className="p-2 rounded-lg transition-colors" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <TabBar tabs={TABS} value={tab} onChange={setTab}
          idPrefix="lnd" ariaLabel="Lending sections" accent={ACCENT} />

        {/* Action feedback */}
        {actionMsg && (
          <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
            style={{ background: /failed|Could not/.test(actionMsg) ? colors.error + '15' : colors.success + '15',
                     color: /failed|Could not/.test(actionMsg) ? colors.error : colors.success }}>
            {/failed|Could not/.test(actionMsg) ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {actionMsg}
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60 hover:opacity-100">dismiss</button>
          </div>
        )}

        {/* Shared governance trace + decision (from the last underwrite) */}
        {trace && <GateTrace running={running === trace.id} result={trace.result} skillLabel={trace.label} />}
        {decision && <DecisionPanel res={decision} colors={colors} />}

        {/* Search (non-overview tabs; policy has nothing to filter) */}
        {tab !== 'overview' && tab !== 'policy' && (
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder={`Search ${activeTab.label.toLowerCase()}...`}
              className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
              style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
          </div>
        )}

        {loading && !dash ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: ACCENT }} /></div>
        ) : (
          <>
            {/* ═══ OVERVIEW ═══ */}
            {tab === 'overview' && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {/* Approval-rate ring */}
                  <div className="rounded-xl p-5 flex items-center gap-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    {approvalPct != null
                      ? <Ring value={approvalPct} max={100} size={104} color={ACCENT} label="approved" />
                      : <div className="w-[104px] h-[104px] rounded-full flex items-center justify-center text-center text-[11px] px-3 shrink-0"
                          style={{ border: `2px dashed ${colors.hairline}`, color: colors.inkTertiary }}>No decisions yet</div>}
                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Approval rate</p>
                      <p className="text-[13px] mt-1" style={{ color: colors.ink }}>
                        {approvalPct != null
                          ? <>Of every decided application, <span className="font-bold">{approvalPct}%</span> were approved.</>
                          : (approvalKpi?.note || 'No underwriting decisions yet.')}
                      </p>
                      <p className="text-[12px] mt-1.5" style={{ color: colors.inkSubtle }}>
                        <span className="font-semibold">{fmtKpi('pending_hitl')}</span> applications await human review.
                      </p>
                    </div>
                  </div>
                  {/* Status mix */}
                  <div className="rounded-xl p-5 flex flex-col" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <p className="text-[12px] font-semibold uppercase tracking-wide mb-3" style={{ color: colors.inkSubtle }}>Application status</p>
                    {statusDonut.length > 0
                      ? <MiniDonut items={statusDonut} size={92} centerLabel="apps" />
                      : <p className="text-[12px] my-auto" style={{ color: colors.inkTertiary }}>No applications recorded yet.</p>}
                  </div>
                  {/* Book value + governance narrative */}
                  <div className="rounded-xl p-5" style={{ background: ACCENT + '10', border: `1px solid ${ACCENT}33` }}>
                    <div className="flex items-center gap-2 mb-2">
                      <Scale className="w-4 h-4" style={{ color: ACCENT }} />
                      <p className="text-[12px] font-semibold" style={{ color: ACCENT }}>Fair-lending posture</p>
                    </div>
                    <p className="text-[20px] font-bold tracking-tight" style={{ color: colors.ink }}>{fmtKpi('approved_book_value')}</p>
                    <p className="text-[11px] mb-2" style={{ color: colors.inkSubtle }}>approved book value</p>
                    <p className="text-[12px] leading-relaxed" style={{ color: colors.ink }}>
                      Every credit decision is made from permissible inputs only; protected-class data feeds four-fifths monitoring, never the decision.
                    </p>
                  </div>
                </div>

                {/* KPI row - a live count-up, never a static number */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {(dash?.kpis || []).map(k => {
                    const cu = kpiCountUp(k.key);
                    return (
                      <div key={k.key} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                        <p className="text-[11px] font-medium uppercase tracking-wide truncate" style={{ color: colors.inkSubtle }} title={k.label}>{k.label}</p>
                        <p className="text-[22px] font-bold mt-1 tracking-tight tabular-nums" style={{ color: colors.ink }}>
                          {cu ? <CountUp value={cu.value} decimals={cu.decimals} prefix={cu.prefix} suffix={cu.suffix} /> : 'n/a'}
                        </p>
                        {k.value == null && k.note && <p className="text-[10.5px] mt-1 leading-snug" style={{ color: colors.inkTertiary }}>{k.note}</p>}
                      </div>
                    );
                  })}
                </div>

                {/* Fair-lending ratios */}
                {fairLending && fairLending.items.length > 0 && (
                  <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <p className="text-[12px] font-semibold mb-3" style={{ color: colors.ink }}>Fair-lending approval ratio (four-fifths)</p>
                    <div className="space-y-2">
                      {fairLending.items.map((it, i) => {
                        const ratio = it.value || 0;
                        const flag = ratio < 0.8;
                        return (
                          <div key={i} className="flex items-center gap-2">
                            <span className="text-[11px] w-40 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{humanize(it.label)}</span>
                            <div className="flex-1 h-3 rounded relative" style={{ background: colors.canvas }}>
                              <div className="h-3 rounded transition-all duration-700" style={{ width: `${Math.min(100, ratio * 100)}%`, background: flag ? colors.error : colors.success }} />
                            </div>
                            <span className="text-[11px] font-mono w-12 shrink-0" style={{ color: flag ? colors.error : colors.ink }}>{(ratio * 100).toFixed(0)}%</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Insights */}
                {(dash?.insights || []).length > 0 && (
                  <div className="space-y-2">
                    {dash!.insights.map((ins, i) => {
                      const c = ins.severity === 'critical' ? colors.error : ins.severity === 'warning' ? colors.warning : ACCENT;
                      return (
                        <div key={i} className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg text-[12px]" style={{ background: c + '12' }}>
                          <AlertTriangle className="w-4 h-4 shrink-0" style={{ color: c }} />
                          <span style={{ color: colors.ink }}>{ins.message}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* ═══ APPLICATIONS ═══ */}
            {tab === 'applications' && (() => {
              const rows = apps.filter(a => !searchQ
                || a.application_number.toLowerCase().includes(searchQ.toLowerCase())
                || a.applicant_name.toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState compact icon={FileText} title="No applications" sub="Loan applications appear here once received." />
                : (
                  <TableCard minWidth={1060}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Application', 'Applicant', 'Product', 'Amount', 'Credit score', 'DTI', 'Intake score', 'Status', 'Decision'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(a => (
                          <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium font-mono">{a.application_number}</td>
                            <td className="px-4 py-3">{a.applicant_name}</td>
                            <td className="px-4 py-3">{humanize(a.product)}</td>
                            <td className="px-4 py-3 font-mono">{formatCurrency(a.amount)}</td>
                            <td className="px-4 py-3 font-mono">{a.credit_score ?? <span style={{ color: colors.inkTertiary }}>-</span>}</td>
                            <td className="px-4 py-3 font-mono">{a.dti_ratio != null ? `${Math.round(a.dti_ratio * 100)}%` : '-'}</td>
                            <td className="px-4 py-3">
                              {a.intake_score != null ? (
                                <div className="flex items-center gap-2">
                                  <div className="w-14 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                                    <div className="h-full rounded-full" style={{ width: `${Math.round(a.intake_score * 100)}%`, background: ACCENT }} />
                                  </div>
                                  <span className="text-[11px] font-mono">{Math.round(a.intake_score * 100)}%</span>
                                </div>
                              ) : <span style={{ color: colors.inkTertiary }}>-</span>}
                            </td>
                            <td className="px-4 py-3"><Badge status={a.status} /></td>
                            <td className="px-4 py-3">
                              {APPROVABLE.includes(a.status) ? (
                                <button onClick={() => underwrite(a)} disabled={running === a.id}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                                  style={{ background: ACCENT + '18', color: ACCENT }}>
                                  {running === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                                  Underwrite
                                </button>
                              ) : <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Decided</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ UNDERWRITING ═══ */}
            {tab === 'underwriting' && (() => {
              const decided = apps.filter(a => DECIDED.includes(a.status)
                && (!searchQ || a.application_number.toLowerCase().includes(searchQ.toLowerCase())
                  || a.applicant_name.toLowerCase().includes(searchQ.toLowerCase())));
              return (
                <div className="space-y-4">
                  <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <ShieldCheck className="w-4 h-4" style={{ color: ACCENT }} />
                      <p className="text-[13px] font-semibold">How a decision is reached</p>
                    </div>
                    <p className="text-[12px] leading-relaxed" style={{ color: colors.inkSubtle }}>
                      A deterministic credit policy scores each application on permissible inputs (credit score, income, debt-to-income and
                      amount). The decision then passes the fair-lending gate and, on a denial, the ECOA adverse-action check. A decision below
                      the confidence floor pauses for human approval. Protected-class attributes never enter the decision.
                    </p>
                  </div>
                  {decided.length === 0
                    ? <EmptyState compact icon={Gavel} title="No decisions yet" sub="Underwrite an application to see its decision here." />
                    : (
                      <TableCard minWidth={780}>
                        <table className="w-full text-[12px]">
                          <thead>
                            <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                              {['Application', 'Applicant', 'Amount', 'Outcome', 'Intake readiness', 'Next step'].map(h => (
                                <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {decided.map(a => (
                              <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                <td className="px-4 py-3 font-medium font-mono">{a.application_number}</td>
                                <td className="px-4 py-3">{a.applicant_name}</td>
                                <td className="px-4 py-3 font-mono">{formatCurrency(a.amount)}</td>
                                <td className="px-4 py-3"><Badge status={a.status} /></td>
                                <td className="px-4 py-3">
                                  {a.intake_score != null ? (
                                    <div className="flex items-center gap-2">
                                      <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                                        <div className="h-full rounded-full" style={{ width: `${Math.round(a.intake_score * 100)}%`, background: ACCENT }} />
                                      </div>
                                      <span className="text-[11px]">{Math.round(a.intake_score * 100)}%</span>
                                    </div>
                                  ) : <span style={{ color: colors.inkTertiary }}>-</span>}
                                </td>
                                <td className="px-4 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                                  {a.status === 'DENIED' ? 'Adverse-action notice required'
                                    : a.status === 'PENDING_HITL' ? 'Awaiting human approval'
                                      : 'Proceed to funding'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableCard>
                    )}
                </div>
              );
            })()}

            {/* ═══ ADVERSE ACTION ═══ */}
            {tab === 'adverse' && (() => {
              const noticed = new Set(notices.map(n => n.application_id));
              const deniedNoNotice = apps.filter(a => a.status === 'DENIED' && !noticed.has(a.id));
              const rows = notices.filter(n => !searchQ
                || n.specific_reasons.some(r => r.toLowerCase().includes(searchQ.toLowerCase())));
              return (
                <div className="space-y-4">
                  {deniedNoNotice.length > 0 && (
                    <div className="rounded-xl p-4" style={{ background: colors.warning + '10', border: `1px solid ${colors.warning}33` }}>
                      <p className="text-[12px] font-semibold mb-2" style={{ color: colors.warning }}>
                        {deniedNoNotice.length} denied application{deniedNoNotice.length === 1 ? '' : 's'} still owe an ECOA notice
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {deniedNoNotice.map(a => (
                          <button key={a.id} onClick={() => issueNotice(a)} disabled={running === a.id}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold"
                            style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                            {running === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <MailWarning className="w-3 h-3" style={{ color: colors.warning }} />}
                            Issue notice · {a.application_number}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {rows.length === 0
                    ? <EmptyState compact icon={MailWarning} title="No adverse-action notices" sub="Reg B notices for denied applications appear here." />
                    : rows.map(n => {
                      const app = apps.find(a => a.id === n.application_id);
                      return (
                        <div key={n.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                          <div className="flex items-start justify-between gap-3 flex-wrap">
                            <div>
                              <p className="text-[13.5px] font-semibold">Adverse-action notice{app ? ` · ${app.application_number}` : ''}</p>
                              <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                                {app ? `${app.applicant_name} · ` : ''}Decision {formatDate(n.decision_date) || 'recorded'}
                                {n.sent_at ? ` · sent ${formatDate(n.sent_at)}` : ''}
                              </p>
                            </div>
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0"
                              style={{ background: (n.within_30_days ? colors.success : colors.error) + '18', color: n.within_30_days ? colors.success : colors.error }}>
                              <ShieldCheck className="w-3 h-3" /> {n.within_30_days ? 'Within 30-day ECOA window' : 'Outside 30-day window'}
                            </span>
                          </div>
                          <div className="mt-3">
                            <p className="text-[11px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: colors.inkSubtle }}>Specific principal reasons</p>
                            <ul className="space-y-1">
                              {n.specific_reasons.map((r, i) => (
                                <li key={i} className="flex items-start gap-2 text-[12px]" style={{ color: colors.ink }}>
                                  <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: ACCENT }} />
                                  {r}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      );
                    })}
                </div>
              );
            })()}

            {/* ═══ SERVICING ═══ */}
            {tab === 'servicing' && (() => {
              const loanRows = loans.filter(l => !searchQ
                || l.loan_number.toLowerCase().includes(searchQ.toLowerCase())
                || l.borrower_name.toLowerCase().includes(searchQ.toLowerCase()));
              const buckets = delinq?.buckets || [];
              const maxBucket = Math.max(1, ...buckets.map(b => b.value));
              return (
                <div className="space-y-4">
                  {/* Delinquency buckets */}
                  {buckets.length > 0 && (
                    <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <p className="text-[12px] font-semibold mb-3" style={{ color: colors.ink }}>Delinquency buckets</p>
                      <div className="space-y-2">
                        {buckets.map(b => (
                          <div key={b.label} className="flex items-center gap-2">
                            <span className="text-[11px] w-20 shrink-0" style={{ color: colors.inkSubtle }}>
                              {b.label === 'current' ? 'Current' : `${b.label} days`}
                            </span>
                            <div className="flex-1 h-3 rounded relative" style={{ background: colors.canvas }}>
                              <div className="h-3 rounded transition-all duration-700"
                                style={{
                                  width: `${(b.value / maxBucket) * 100}%`,
                                  background: b.label === '90+' ? colors.error
                                    : (b.label === '30-59' || b.label === '60-89') ? colors.warning : ACCENT,
                                }} />
                            </div>
                            <span className="text-[11px] font-mono w-6 shrink-0 text-right">{b.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Serviced loans + payment schedule */}
                  {loanRows.length === 0 ? (
                    <EmptyState compact icon={Wallet} title="No serviced loans" sub="A funded, approved loan appears here once servicing begins." />
                  ) : (
                    <TableCard minWidth={920}>
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            {['Loan', 'Borrower', 'Product', 'Outstanding', 'APR', 'Next due', 'Payments', 'Status', ''].map(h => (
                              <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {loanRows.map(loan => {
                            const open = expandedLoanId === loan.id;
                            return (
                              <React.Fragment key={loan.id}>
                                <tr style={{ borderBottom: open ? 'none' : `1px solid ${colors.hairline}` }}>
                                  <td className="px-4 py-3 font-medium font-mono">{loan.loan_number}</td>
                                  <td className="px-4 py-3">{loan.borrower_name}</td>
                                  <td className="px-4 py-3">{humanize(loan.product)}</td>
                                  <td className="px-4 py-3 font-mono">{formatCurrency(loan.outstanding_principal)}</td>
                                  <td className="px-4 py-3 font-mono">{loan.apr.toFixed(2)}%</td>
                                  <td className="px-4 py-3">{loan.next_due_date ? formatDate(loan.next_due_date) : '-'}</td>
                                  <td className="px-4 py-3 font-mono">{loan.payments_made}/{loan.term_months}</td>
                                  <td className="px-4 py-3"><Badge status={loan.status} /></td>
                                  <td className="px-4 py-3">
                                    <button onClick={() => setExpandedLoanId(open ? null : loan.id)}
                                      aria-expanded={open}
                                      aria-label={`${open ? 'Hide' : 'Show'} payment schedule for ${loan.loan_number}`}
                                      className="p-1 rounded" style={{ color: colors.inkSubtle }}>
                                      {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                    </button>
                                  </td>
                                </tr>
                                {open && (
                                  <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                    <td colSpan={9} className="px-4 pb-4">
                                      <div className="rounded-lg p-3" style={{ background: colors.canvas }}>
                                        <p className="text-[11px] font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5" style={{ color: colors.inkSubtle }}>
                                          <Clock className="w-3.5 h-3.5" /> Payment schedule, around today
                                        </p>
                                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                          {scheduleWindow(loan).map((row, i) => (
                                            <div key={i} className="rounded-md px-2.5 py-2 text-[11px]"
                                              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                                              <div className="flex items-center justify-between gap-2">
                                                <span style={{ color: colors.ink }}>{formatDate(row.due_date)}</span>
                                                <span className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded-full shrink-0"
                                                  style={{
                                                    background: (row.status === 'paid' ? colors.success : row.status === 'missed' ? colors.error : colors.inkSubtle) + '18',
                                                    color: row.status === 'paid' ? colors.success : row.status === 'missed' ? colors.error : colors.inkSubtle,
                                                  }}>{row.status}</span>
                                              </div>
                                              <p className="font-mono mt-1" style={{ color: colors.inkSubtle }}>{formatCurrency(row.amount)}</p>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    </td>
                                  </tr>
                                )}
                              </React.Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </TableCard>
                  )}

                  {/* Collections, FDCPA-governed */}
                  <div>
                    <p className="text-[13px] font-semibold mb-2 flex items-center gap-2" style={{ color: colors.ink }}>
                      <PhoneCall className="w-4 h-4" style={{ color: ACCENT }} /> Collections, governed by FDCPA
                    </p>
                    {(delinq?.cases || []).length === 0 ? (
                      <EmptyState compact icon={PhoneCall} title="No open collections cases" sub="A loan more than 30 days past due opens a case here." />
                    ) : (
                      <div className="space-y-3">
                        {(delinq?.cases || []).map(c => {
                          const draft = contactDraft(c.id);
                          return (
                            <div key={c.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                              <div className="flex items-start justify-between gap-3 flex-wrap">
                                <div>
                                  <p className="text-[13.5px] font-semibold">{c.loan_number || 'Loan'} · {c.borrower_name || 'Borrower'}</p>
                                  <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                                    {c.days_past_due != null ? `${c.days_past_due} days past due` : ''}
                                    {c.outstanding_principal != null ? ` · ${formatCurrency(c.outstanding_principal)} outstanding` : ''}
                                  </p>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide"
                                    style={{
                                      background: (c.delinquency_bucket === '90+' ? colors.error : colors.warning) + '18',
                                      color: c.delinquency_bucket === '90+' ? colors.error : colors.warning,
                                    }}>
                                    {c.delinquency_bucket} bucket
                                  </span>
                                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1"
                                    style={{
                                      background: (c.validation_notice_sent ? colors.success : colors.error) + '18',
                                      color: c.validation_notice_sent ? colors.success : colors.error,
                                    }}>
                                    <ShieldCheck className="w-3 h-3" /> {c.validation_notice_sent ? 'Validation notice sent' : 'Validation notice due'}
                                  </span>
                                </div>
                              </div>

                              {c.contact_log.length > 0 && (
                                <div className="mt-3 space-y-1.5">
                                  {c.contact_log.map((entry, i) => (
                                    <div key={i} className="flex items-start gap-2 text-[11.5px]" style={{ color: colors.ink }}>
                                      {entry.channel === 'mail'
                                        ? <Mail className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: colors.inkTertiary }} />
                                        : <PhoneCall className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: colors.inkTertiary }} />}
                                      <span style={{ color: colors.inkSubtle }} className="shrink-0">
                                        {formatDate(entry.at)} · {String(entry.hour_local).padStart(2, '0')}:00 · {CHANNEL_LABEL[entry.channel] || humanize(entry.channel)}
                                      </span>
                                      <span>{entry.notes}</span>
                                      <span className="ml-auto flex items-center gap-1 text-[10px] font-semibold shrink-0 px-1.5 py-0.5 rounded-full"
                                        style={{ background: colors.success + '18', color: colors.success }}>
                                        <CheckCircle2 className="w-3 h-3" /> FDCPA-compliant
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}

                              <div className="mt-3 pt-3 flex items-end gap-2 flex-wrap" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                                <div>
                                  <label className="block text-[10.5px] font-semibold uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>Local hour</label>
                                  <input type="number" min={0} max={23} value={draft.hour_local}
                                    onChange={e => setContactField(c.id, { hour_local: Math.max(0, Math.min(23, Number(e.target.value) || 0)) })}
                                    className="w-16 px-2 py-1.5 rounded-lg border text-[12px] font-mono"
                                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
                                </div>
                                <div>
                                  <label className="block text-[10.5px] font-semibold uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>Channel</label>
                                  <select value={draft.channel} onChange={e => setContactField(c.id, { channel: e.target.value })}
                                    className="px-2 py-1.5 rounded-lg border text-[12px]"
                                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                                    <option value="phone">Phone call</option>
                                    <option value="mail">Mailed letter</option>
                                    <option value="email">Email</option>
                                  </select>
                                </div>
                                <div className="flex-1 min-w-[180px]">
                                  <label className="block text-[10.5px] font-semibold uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>Notes</label>
                                  <input type="text" value={draft.notes} onChange={e => setContactField(c.id, { notes: e.target.value })}
                                    placeholder="What was discussed"
                                    className="w-full px-2 py-1.5 rounded-lg border text-[12px]"
                                    style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
                                </div>
                                <button onClick={() => attemptContact(c)} disabled={running === c.id}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold shrink-0"
                                  style={{ background: ACCENT + '18', color: ACCENT }}>
                                  {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PhoneCall className="w-3.5 h-3.5" />}
                                  Attempt contact
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* ═══ POLICY ═══ */}
            {tab === 'policy' && (
              <div className="space-y-4">
                <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <SlidersHorizontal className="w-4 h-4" style={{ color: ACCENT }} />
                    <p className="text-[13px] font-semibold">Credit policy drives every automated decision</p>
                  </div>
                  <p className="text-[12px] leading-relaxed" style={{ color: colors.inkSubtle }}>
                    These five thresholds are the only input to the deterministic underwriting decision, no model, no
                    judgment call. Editing a value here changes every future decision on that product immediately.
                  </p>
                </div>
                {policies.length === 0 ? (
                  <EmptyState compact icon={SlidersHorizontal} title="No credit policies" sub="A credit policy appears here once configured for a product." />
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {policies.map(p => {
                      const editing = editingPolicy === p.product;
                      const d: PolicyDraft = editing && policyDraft ? policyDraft : {
                        min_credit_score: p.min_credit_score, max_dti_ratio: p.max_dti_ratio,
                        min_annual_income: p.min_annual_income, max_amount: p.max_amount, base_apr: p.base_apr,
                      };
                      const field = (label: string, key: keyof PolicyDraft, step = 1) => (
                        <div>
                          <p className="text-[10.5px] font-semibold uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>{label}</p>
                          {editing ? (
                            <input type="number" step={step} value={d[key]}
                              onChange={e => setPolicyDraft({ ...d, [key]: Number(e.target.value) })}
                              className="w-full px-2 py-1.5 rounded-lg border text-[13px] font-mono"
                              style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
                          ) : (
                            <p className="text-[15px] font-bold font-mono" style={{ color: colors.ink }}>
                              {key === 'max_dti_ratio' ? `${Math.round(d[key] * 100)}%`
                                : (key === 'min_annual_income' || key === 'max_amount') ? formatCurrency(d[key])
                                  : key === 'base_apr' ? `${d[key]}%` : d[key]}
                            </p>
                          )}
                        </div>
                      );
                      return (
                        <div key={p.product} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                          <div className="flex items-center justify-between mb-3">
                            <p className="text-[13px] font-semibold">{humanize(p.product)}</p>
                            {editing ? (
                              <div className="flex items-center gap-1.5">
                                <button onClick={() => saveEditPolicy(p)} disabled={policySaving === p.product}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                                  style={{ background: colors.success + '18', color: colors.success }}>
                                  {policySaving === p.product ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Save
                                </button>
                                <button onClick={cancelEditPolicy}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                                  style={{ background: colors.hairline, color: colors.inkSubtle }}>
                                  <XIcon className="w-3 h-3" /> Cancel
                                </button>
                              </div>
                            ) : (
                              <button onClick={() => startEditPolicy(p)}
                                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                                style={{ background: ACCENT + '18', color: ACCENT }}>
                                <Pencil className="w-3 h-3" /> Edit
                              </button>
                            )}
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                            {field('Min credit score', 'min_credit_score')}
                            {field('Max DTI', 'max_dti_ratio', 0.01)}
                            {field('Min annual income', 'min_annual_income', 1000)}
                            {field('Max amount', 'max_amount', 1000)}
                            {field('Base APR', 'base_apr', 0.1)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {tab === 'analytics' && <DomainAnalytics domain="lending" />}
          </>
        )}
      </div>
    </div>
  );
};

/** Plain-English underwriting outcome for the last decision. */
function DecisionPanel({ res, colors }: { res: UnderwriteResult; colors: Record<string, string> }) {
  if (res.status === 'PENDING_HITL') {
    return (
      <div className="rounded-xl p-4 flex items-start gap-2" style={{ background: colors.warning + '12', border: `1px solid ${colors.warning}33` }}>
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: colors.warning }} />
        <div>
          <p className="text-[12px] font-semibold" style={{ color: colors.warning }}>Paused for human approval</p>
          <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{res.reason || 'This decision fell below the confidence floor and routed to the review queue.'}</p>
        </div>
      </div>
    );
  }
  if (!res.decision) return null;
  const approved = res.decision === 'APPROVE';
  const c = approved ? colors.success : colors.error;
  return (
    <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-2">
        {approved ? <CheckCircle2 className="w-4 h-4" style={{ color: c }} /> : <XCircle className="w-4 h-4" style={{ color: c }} />}
        <span className="text-[13px] font-semibold" style={{ color: c }}>{approved ? 'Approved' : 'Denied'}</span>
        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>· cleared the ECOA and fair-lending gates</span>
      </div>
      {res.rationale && <p className="text-[12px] mt-2 leading-relaxed" style={{ color: colors.ink }}>{res.rationale}</p>}
      {(res.reasons || []).length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: colors.inkSubtle }}>
            {approved ? 'Conditions met' : 'Specific principal reasons'}
          </p>
          <ul className="space-y-1">
            {res.reasons!.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-[12px]" style={{ color: colors.ink }}>
                <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: c }} />{r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default LendingView;
