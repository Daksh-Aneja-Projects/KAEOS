import React, { useEffect, useState } from 'react';
import {
  Landmark, FileText, Gavel, MailWarning, Search, RefreshCw, Loader2,
  Bot, CheckCircle2, XCircle, Scale, ShieldCheck, AlertTriangle,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  DomainAnalyticsPayload, LoanApplicationRow, UnderwriteResult, AdverseActionRow,
} from '../api/endpoints/lending';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import Ring from '../components/shared/Ring';
import { MiniDonut } from '../components/shared/MiniDonut';
import TableCard from '../components/shared/TableCard';
import LiveBadge from '../components/LiveBadge';
import GateTrace, { type GateTraceResult } from '../components/GateTrace';
import { humanize, formatCurrency, formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

const ACCENT = '#d97706';

type Tab = 'overview' | 'applications' | 'underwriting' | 'adverse';
const VALID: Tab[] = ['overview', 'applications', 'underwriting', 'adverse'];

const APPROVABLE = ['RECEIVED', 'IN_REVIEW'];
const DECIDED = ['APPROVED', 'DENIED', 'PENDING_HITL'];

/** Map the underwriter agent's terminal status onto GateTrace's vocabulary,
 *  keeping only the fields GateTrace renders. A clean pass returns "success";
 *  GateTrace speaks "SUCCESS_CLEAN". */
function toTrace(res: UnderwriteResult | null): GateTraceResult | undefined {
  if (!res) return undefined;
  return {
    status: res.status === 'success' ? 'SUCCESS_CLEAN' : res.status,
    execution_id: res.execution_id,
    rationale: res.rationale ?? undefined,
    reason: res.reason,
    violations: res.violations,
  };
}

const LendingView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>(
    defaultTab && VALID.includes(defaultTab as Tab) ? (defaultTab as Tab) : 'overview',
  );
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const [dash, setDash] = useState<DomainAnalyticsPayload | null>(null);
  const [apps, setApps] = useState<LoanApplicationRow[]>([]);
  const [notices, setNotices] = useState<AdverseActionRow[]>([]);

  // Shared decision panel + governance trace for the last action taken.
  const [trace, setTrace] = useState<{ id: string; label: string; result?: GateTraceResult } | null>(null);
  const [decision, setDecision] = useState<UnderwriteResult | null>(null);

  useEffect(() => { loadData(); }, []);
  useLiveRefresh(loadData, { intervalMs: 20000 });

  async function loadData() {
    setLoading(true);
    const r = await Promise.allSettled([
      api.getLendingDashboard(),
      api.getLendingApplications(),
      api.getAdverseActions(),
    ]);
    const val = (i: number, d: any) => (r[i].status === 'fulfilled' ? (r[i] as any).value ?? d : d);
    setDash(val(0, null));
    setApps(val(1, []));
    setNotices(val(2, []));
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

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (n === 'APPROVED') return colors.success;
    if (['RECEIVED', 'IN_REVIEW', 'PENDING_HITL'].includes(n)) return colors.warning;
    if (['DENIED', 'WITHDRAWN'].includes(n)) return colors.error;
    return colors.inkSubtle;
  };
  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'N/A'}
    </span>
  );
  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-14 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-11 h-11 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
      <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'overview', label: 'Overview', icon: Landmark },
    { key: 'applications', label: 'Applications', icon: FileText },
    { key: 'underwriting', label: 'Underwriting', icon: Gavel },
    { key: 'adverse', label: 'Adverse Action', icon: MailWarning },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;
  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.key);
    document.getElementById(`lnd-tab-${next.key}`)?.focus();
  };

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
        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label="Lending sections" style={{ background: colors.surface1 }}>
          {TABS.map((t, i) => (
            <button key={t.key} id={`lnd-tab-${t.key}`} role="tab" aria-selected={tab === t.key}
              tabIndex={tab === t.key ? 0 : -1} onClick={() => setTab(t.key)} onKeyDown={e => moveTab(e, i)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
              style={{
                background: tab === t.key ? colors.canvas : 'transparent',
                color: tab === t.key ? ACCENT : colors.inkSubtle,
                boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              }}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>

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

        {/* Search (non-overview tabs) */}
        {tab !== 'overview' && (
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

                {/* KPI row */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {(dash?.kpis || []).map(k => (
                    <div key={k.key} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <p className="text-[11px] font-medium uppercase tracking-wide truncate" style={{ color: colors.inkSubtle }} title={k.label}>{k.label}</p>
                      <p className="text-[22px] font-bold mt-1 tracking-tight tabular-nums" style={{ color: colors.ink }}>{fmtKpi(k.key)}</p>
                      {k.value == null && k.note && <p className="text-[10.5px] mt-1 leading-snug" style={{ color: colors.inkTertiary }}>{k.note}</p>}
                    </div>
                  ))}
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
                ? <EmptyState icon={FileText} title="No applications" sub="Loan applications appear here once received." />
                : (
                  <TableCard minWidth={960}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Application', 'Applicant', 'Product', 'Amount', 'Credit score', 'DTI', 'Status', 'Decision'].map(h => (
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
                    ? <EmptyState icon={Gavel} title="No decisions yet" sub="Underwrite an application to see its decision here." />
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
                    ? <EmptyState icon={MailWarning} title="No adverse-action notices" sub="Reg B notices for denied applications appear here." />
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
