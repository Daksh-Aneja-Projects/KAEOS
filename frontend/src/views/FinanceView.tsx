import React, { useEffect, useState } from 'react';
import {
  Receipt, Landmark, BarChart3, Wallet, Scale, ShieldAlert,
  Search, Filter, RefreshCw, Loader2, Bot, ArrowUpRight,
  CheckCircle2, XCircle, AlertCircle, Clock, DollarSign,
  FileText, TrendingUp, ShieldCheck, PiggyBank, ChevronDown,
  ChevronRight, FileBarChart2, FileCheck2, Gavel, ArrowDownCircle, ArrowUpCircle,
  Building2,
} from 'lucide-react';
import { useNavigate } from 'react-router';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import TableCard from '../components/shared/TableCard';
import StatCard from '../components/shared/StatCard';
import EmptyState from '../components/shared/EmptyState';
import { humanize } from '../lib/format';
import { toPct } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { MiniDonut, DONUT_PALETTE, type DonutItem } from '../components/shared/MiniDonut';
import { timeAgo } from '../lib/time';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import GateTrace from '../components/GateTrace';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import BulkActionBar from '../components/BulkActionBar';
import { useBulkSelect } from '../hooks/useBulkSelect';
import { Plus as PlusIcon } from 'lucide-react';

type FinanceTab = 'ap' | 'ar' | 'budgets' | 'expenses' | 'tax' | 'treasury' | 'audit' | 'accounts' | 'analytics';

/** Accounting types in the order a ledger is normally read. */
const ACCOUNT_TYPE_ORDER = ['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'];

const FinanceView: React.FC<{ domain?: string; defaultTab?: string }> = ({ domain, defaultTab }) => {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [tab, setTab] = useState<FinanceTab>(() => {
    const valid: FinanceTab[] = ['ap', 'ar', 'budgets', 'expenses', 'tax', 'treasury', 'audit', 'accounts', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as FinanceTab)) return defaultTab as FinanceTab;
    return 'ap';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  // Data
  const [vendors, setVendors] = useState<any[]>([]);
  const [invoices, setInvoices] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [receivables, setReceivables] = useState<any[]>([]);
  const [budgets, setBudgets] = useState<any[]>([]);
  const [forecasts, setForecasts] = useState<any[]>([]);
  const [expenseReports, setExpenseReports] = useState<any[]>([]);
  const [taxFilings, setTaxFilings] = useState<any[]>([]);
  const [taxRules, setTaxRules] = useState<any[]>([]);
  const [auditFindings, setAuditFindings] = useState<any[]>([]);
  const [soxControls, setSoxControls] = useState<any[]>([]);
  const [chartOfAccounts, setChartOfAccounts] = useState<any[]>([]);
  const [bankAccounts, setBankAccounts] = useState<any[]>([]);
  const [cashFlows, setCashFlows] = useState<any[]>([]);
  const [financialReports, setFinancialReports] = useState<any[]>([]);
  const [complianceRules, setComplianceRules] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const bulk = useBulkSelect(invoices, workflows['invoice'], (i: any) => i.status);

  // Drill-down: budget lines / expense items are fetched lazily on expand and
  // cached by parent id so re-expanding never re-fetches.
  const [expandedBudget, setExpandedBudget] = useState<string | null>(null);
  const [budgetLines, setBudgetLines] = useState<Record<string, any[]>>({});
  const [budgetLinesLoading, setBudgetLinesLoading] = useState<string | null>(null);
  const [expandedReport, setExpandedReport] = useState<string | null>(null);
  const [expenseItems, setExpenseItems] = useState<Record<string, any[]>>({});
  const [expenseItemsLoading, setExpenseItemsLoading] = useState<string | null>(null);

  const toggleBudget = async (budgetId: string) => {
    if (expandedBudget === budgetId) { setExpandedBudget(null); return; }
    setExpandedBudget(budgetId);
    if (!budgetLines[budgetId]) {
      setBudgetLinesLoading(budgetId);
      try {
        const lines = await api.getFinanceBudgetLines(budgetId);
        setBudgetLines((prev) => ({ ...prev, [budgetId]: lines || [] }));
      } catch { setBudgetLines((prev) => ({ ...prev, [budgetId]: [] })); }
      finally { setBudgetLinesLoading(null); }
    }
  };

  const toggleReport = async (reportId: string) => {
    if (expandedReport === reportId) { setExpandedReport(null); return; }
    setExpandedReport(reportId);
    if (!expenseItems[reportId]) {
      setExpenseItemsLoading(reportId);
      try {
        const items = await api.getFinanceExpenseItems(reportId);
        setExpenseItems((prev) => ({ ...prev, [reportId]: items || [] }));
      } catch { setExpenseItems((prev) => ({ ...prev, [reportId]: [] })); }
      finally { setExpenseItemsLoading(null); }
    }
  };

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getFinanceVendors(),
      api.getFinanceInvoices(),
      api.getFinancePayments(),
      api.getFinanceCustomers(),
      api.getFinanceReceivables(),
      api.getFinanceBudgets(),
      api.getFinanceForecasts(),
      api.getFinanceExpenseReports(),
      api.getFinanceTaxFilings(),
      api.getFinanceTaxRules(),
      api.getFinanceAuditFindings(),
      api.getFinanceSOXControls(),
      api.getDomainWorkflows('finance'),
      api.getChartOfAccounts(),
      api.getFinanceBankAccounts(),
      api.getFinanceCashFlow(),
      api.getFinanceReports(),
      api.getFinanceComplianceRules(),
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setVendors(val(0)); setInvoices(val(1)); setPayments(val(2));
    setCustomers(val(3)); setReceivables(val(4)); setBudgets(val(5));
    setForecasts(val(6)); setExpenseReports(val(7)); setTaxFilings(val(8));
    setTaxRules(val(9)); setAuditFindings(val(10)); setSoxControls(val(11));
    if (results[12].status === 'fulfilled') setWorkflows((results[12] as any).value || {});
    setChartOfAccounts(val(13));
    setBankAccounts(val(14)); setCashFlows(val(15));
    setFinancialReports(val(16)); setComplianceRules(val(17));
    setLoading(false);
  };

  const handleRunAPAgent = async (invoiceId: string, invoiceLabel?: string) => {
    setRunningAgent(invoiceId); setActionMsg('');
    // Money moves through this path, so show the governance pipeline deciding
    // rather than only its verdict. Label reads as an invoice, never a UUID.
    const label = `Accounts payable 3-way match${invoiceLabel ? `, invoice ${invoiceLabel}` : ''}`;
    setTrace({ id: invoiceId, label, result: undefined });
    try {
      const res = await api.runFinanceAPAgent(invoiceId);
      setTrace({ id: invoiceId, label, result: res });
      setActionMsg(res?.status === 'PENDING_HITL' ? 'AP matching routed for human review.' : 'AP 3-way match complete.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`AP agent failed: ${e?.message || e}`);
      setTrace(null);
    }
    finally { setRunningAgent(null); }
  };

  const handleRunARAgent = async (invoiceId: string, invoiceLabel?: string) => {
    setRunningAgent(invoiceId); setActionMsg('');
    const label = `Accounts receivable collections${invoiceLabel ? `, invoice ${invoiceLabel}` : ''}`;
    setTrace({ id: invoiceId, label, result: undefined });
    try {
      const res = await api.runFinanceARAgent(invoiceId);
      setTrace({ id: invoiceId, label, result: res });
      setActionMsg(res?.letter ? 'Dunning letter generated.' : 'AR agent completed.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`AR agent failed: ${e?.message || e}`);
      setTrace(null);
    }
    finally { setRunningAgent(null); }
  };

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['PAID', 'APPROVED', 'ACTIVE', 'PASSED', 'EFFECTIVE', 'FILED', 'REMEDIATED'].includes(n)) return '#22c55e';
    if (['PENDING', 'PENDING_APPROVAL', 'DRAFT', 'IN_PROGRESS', 'OPEN', 'SCHEDULED'].includes(n)) return '#f59e0b';
    if (['OVERDUE', 'REJECTED', 'FAILED', 'CRITICAL', 'HIGH', 'CANCELLED'].includes(n)) return '#ef4444';
    if (['SENT', 'PARTIALLY_PAID', 'PROCESSING'].includes(n)) return '#3b82f6';
    return colors.inkSubtle;
  };

  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'N/A'}
    </span>
  );

  /** Live horizontal bars (animated width) for cash movement by category. */
  const TreasuryBars = ({ items }: { items: DonutItem[] }) => {
    const max = Math.max(...items.map(i => i.value), 1);
    return (
      <div className="space-y-2">
        {items.map((it, idx) => (
          <div key={it.label} className="flex items-center gap-2">
            <span className="text-[11px] w-28 truncate text-right shrink-0" style={{ color: colors.inkSubtle }} title={it.label}>{it.label}</span>
            <div className="flex-1 h-3.5 rounded" style={{ background: colors.canvas }}>
              <div className="h-3.5 rounded transition-all duration-500" style={{
                width: `${Math.max((it.value / max) * 100, it.value > 0 ? 2 : 0)}%`,
                background: DONUT_PALETTE[idx % DONUT_PALETTE.length],
              }} />
            </div>
            <span className="text-[11px] font-mono w-16 shrink-0 text-right" style={{ color: colors.ink }}>{fmt(it.value)}</span>
          </div>
        ))}
      </div>
    );
  };

  const TABS: { key: FinanceTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'ap', label: 'Accounts Payable', icon: Receipt, color: '#ec4899' },
    { key: 'ar', label: 'Accounts Receivable', icon: Landmark, color: '#3b82f6' },
    { key: 'budgets', label: 'Budgets', icon: BarChart3, color: '#8b5cf6' },
    { key: 'expenses', label: 'Expenses', icon: Wallet, color: '#22c55e' },
    { key: 'tax', label: 'Tax', icon: Scale, color: '#f59e0b' },
    { key: 'treasury', label: 'Treasury', icon: PiggyBank, color: '#14b8a6' },
    { key: 'audit', label: 'Audit & SOX', icon: ShieldAlert, color: '#ef4444' },
    { key: 'accounts', label: 'Chart of Accounts', icon: FileText, color: '#0ea5e9' },
    { key: 'analytics', label: 'Analytics', icon: TrendingUp, color: '#a855f7' },
  ];

  const activeTab = TABS.find(t => t.key === tab)!;
  const fmt = (v: number) => v >= 1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`;

  // Left/right arrows move between tabs, as a tablist is expected to.
  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.key);
    document.getElementById(`finance-tab-${next.key}`)?.focus();
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: activeTab.color }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Finance Department</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <PlusIcon className="w-3.5 h-3.5" /> New Expense Report
            </button>
            <button onClick={loadData} aria-label="Refresh finance data"
              className="p-2 rounded-lg hover:bg-opacity-10 transition-colors"
              style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
            title="New Expense Report" domain="finance" entityPath="expense-reports"
            fields={[
              { key: 'title', label: 'Title', type: 'text', required: true },
              { key: 'employee_id', label: 'Employee ID', type: 'text', required: true },
              { key: 'total_amount', label: 'Total Amount ($)', type: 'number', required: true },
              { key: 'department', label: 'Department', type: 'text' },
              { key: 'description', label: 'Description', type: 'textarea' },
            ]}
            onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label="Finance sections" style={{ background: colors.surface1 }}>
          {TABS.map((t, i) => (
            <button key={t.key} id={`finance-tab-${t.key}`} role="tab"
              aria-selected={tab === t.key}
              tabIndex={tab === t.key ? 0 : -1}
              onClick={() => setTab(t.key)}
              onKeyDown={e => moveTab(e, i)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap shrink-0"
              style={{
                background: tab === t.key ? colors.canvas : 'transparent',
                color: tab === t.key ? t.color : colors.inkSubtle,
                boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
              }}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>

        {/* Action feedback */}
        {actionMsg && (
          <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
            style={{ background: actionMsg.includes('failed') ? '#ef444415' : '#22c55e15',
                     color: actionMsg.includes('failed') ? '#ef4444' : '#22c55e' }}>
            {actionMsg.includes('failed') ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {actionMsg}
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60 hover:opacity-100">dismiss</button>
          </div>
        )}

        {/* Governance pipeline, live from the backend's gate events */}
        {trace && (
          <GateTrace
            running={runningAgent === trace.id}
            result={trace.result}
            skillLabel={trace.label}
          />
        )}

        {/* Search bar */}
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
          <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
            placeholder={`Search ${activeTab.label.toLowerCase()}...`}
            aria-label={`Search ${activeTab.label.toLowerCase()}`}
            className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
            style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
          </div>
        ) : (
          <>
            {/* ═══ ACCOUNTS PAYABLE ═══ */}
            {tab === 'ap' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <StatCard label="Vendors" value={vendors.length} icon={<Landmark className="w-4 h-4" />} accent="#3b82f6" />
                  <StatCard label="Open Invoices" value={invoices.filter(i => !['PAID','CANCELLED'].includes(i.status)).length} icon={<Receipt className="w-4 h-4" />} accent="#ec4899" />
                  <StatCard label="Total AP" value={invoices.reduce((s: number, i: any) => s + (i.balance || 0), 0)} format="currency" icon={<DollarSign className="w-4 h-4" />} accent="#f59e0b" />
                  {/* Governed payments live in the General Ledger workspace, not as a dead count. */}
                  <button type="button" onClick={() => navigate('/departments/finance/gl?tab=payments')}
                    className="rounded-xl p-5 text-left transition-shadow hover:shadow-md"
                    style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <div className="flex items-start justify-between gap-3">
                      <span className="text-[12px] font-medium uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Payments Made</span>
                      <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: '#22c55e1f', color: '#22c55e' }}>
                        <CheckCircle2 className="w-4 h-4" />
                      </span>
                    </div>
                    <div className="mt-2">
                      <CountUp value={payments.length} className="text-[26px] font-bold tabular-nums leading-none" />
                    </div>
                    <div className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold" style={{ color: colors.primary }}>
                      Open payments queue <ArrowUpRight className="w-3 h-3" />
                    </div>
                  </button>
                </div>
                <BulkActionBar domain="finance" entityType="invoice" noun="invoice"
                  ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
                <TableCard minWidth={860}>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <th className="px-3 py-3 w-8">
                          <input type="checkbox" aria-label="Select all invoices"
                            checked={bulk.allSelected} onChange={e => bulk.setAll(e.target.checked)} />
                        </th>
                        {['Invoice #', 'Vendor', 'Status', 'Total', 'Balance Due', 'Due Date', 'PO #', '3-Way Match', 'AI Action'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {invoices.filter(i => !searchQ || i.number?.toLowerCase().includes(searchQ.toLowerCase()) || i.po_number?.toLowerCase().includes(searchQ.toLowerCase())).map((inv: any) => (
                        <tr key={inv.id} className="hover:bg-opacity-50 transition-colors" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-3 py-3">
                            <input type="checkbox" aria-label={`Select invoice ${inv.number}`}
                              checked={bulk.isSelected(inv.id)} onChange={() => bulk.toggle(inv.id)} />
                          </td>
                          <td className="px-4 py-3 font-medium">{inv.number}</td>
                          <td className="px-4 py-3">{vendors.find(v => v.id === inv.vendor_id)?.name || inv.vendor_id?.slice(0, 8)}</td>
                          <td className="px-4 py-3"><Badge status={inv.status} /></td>
                          <td className="px-4 py-3 font-mono">${inv.total?.toLocaleString()}</td>
                          <td className="px-4 py-3 font-mono font-semibold" style={{ color: inv.balance > 0 ? '#ef4444' : '#22c55e' }}>${inv.balance?.toLocaleString()}</td>
                          <td className="px-4 py-3">{timeAgo(inv.due_date)}</td>
                          <td className="px-4 py-3">{inv.po_number || '-'}</td>
                          <td className="px-4 py-3"><Badge status={inv.three_way_match || 'PENDING'} /></td>
                          <td className="px-4 py-3">
                            <button onClick={() => handleRunAPAgent(inv.id, inv.number || inv.po_number)}
                              disabled={runningAgent === inv.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                              style={{ background: '#ec489915', color: '#ec4899' }}>
                              {runningAgent === inv.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                              Match
                            </button>
                            <div className="mt-1">
                              <WorkflowActions domain="finance" entityPath="invoices" entityId={inv.id}
                                currentState={inv.status} transitions={workflows['invoice']?.transitions}
                                onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {invoices.length === 0 && <EmptyState icon={Receipt} title="No invoices" sub="Invoices will appear here when created" />}
                </TableCard>
              </div>
            )}

            {/* ═══ ACCOUNTS RECEIVABLE ═══ */}
            {tab === 'ar' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <StatCard label="Customers" value={customers.length} icon={<Landmark className="w-4 h-4" />} accent="#3b82f6" />
                  <StatCard label="Open Receivables" value={receivables.filter(r => !['PAID','CANCELLED'].includes(r.status)).length} icon={<Receipt className="w-4 h-4" />} accent="#ec4899" />
                  <StatCard label="Total AR" value={receivables.reduce((s: number, r: any) => s + (r.balance || 0), 0)} format="currency" icon={<DollarSign className="w-4 h-4" />} accent="#f59e0b" />
                  <StatCard label="Avg DSO (days)" value={customers.length > 0 ? Math.round(customers.reduce((s: number, c: any) => s + (c.dso || 0), 0) / customers.length) : 0} icon={<Clock className="w-4 h-4" />} accent="#8b5cf6" />
                </div>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Invoice #', 'Customer', 'Status', 'Total', 'Balance', 'Due Date', 'Dunning Lvl', 'AI Action'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {receivables.filter(r => !searchQ || r.number?.toLowerCase().includes(searchQ.toLowerCase())).map((rec: any) => (
                        <tr key={rec.id} className="hover:bg-opacity-50 transition-colors" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{rec.number}</td>
                          <td className="px-4 py-3">{customers.find(c => c.id === rec.customer_id)?.name || rec.customer_id?.slice(0, 8)}</td>
                          <td className="px-4 py-3"><Badge status={rec.status} /></td>
                          <td className="px-4 py-3 font-mono">${rec.total?.toLocaleString()}</td>
                          <td className="px-4 py-3 font-mono font-semibold" style={{ color: rec.balance > 0 ? '#ef4444' : '#22c55e' }}>${rec.balance?.toLocaleString()}</td>
                          <td className="px-4 py-3">{timeAgo(rec.due_date)}</td>
                          <td className="px-4 py-3">
                            {rec.dunning_level > 0 ? (
                              <span className="px-2 py-0.5 rounded text-[11px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>Level {rec.dunning_level}</span>
                            ) : <span style={{ color: colors.inkTertiary }}>-</span>}
                          </td>
                          <td className="px-4 py-3">
                            <button onClick={() => handleRunARAgent(rec.id, rec.number)}
                              disabled={runningAgent === rec.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                              style={{ background: '#3b82f615', color: '#3b82f6' }}>
                              {runningAgent === rec.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                              Dunning
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {receivables.length === 0 && <EmptyState icon={Landmark} title="No receivables" sub="Customer invoices will appear here" />}
                </TableCard>
              </div>
            )}

            {/* ═══ BUDGETS & FORECASTS ═══ */}
            {tab === 'budgets' && (
              <div className="space-y-4">
                <h3 className="text-[14px] font-bold">Active Budgets</h3>
                <div className="grid grid-cols-1 gap-3">
                  {budgets.map((b: any) => {
                    const expanded = expandedBudget === b.id;
                    const lines = budgetLines[b.id] || [];
                    return (
                      <div key={b.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                        <button type="button" onClick={() => toggleBudget(b.id)}
                          className="w-full flex items-center justify-between mb-3 text-left">
                          <div className="flex items-center gap-3">
                            {expanded ? <ChevronDown className="w-4 h-4 shrink-0" style={{ color: colors.inkSubtle }} /> : <ChevronRight className="w-4 h-4 shrink-0" style={{ color: colors.inkSubtle }} />}
                            <BarChart3 className="w-5 h-5" style={{ color: '#8b5cf6' }} />
                            <div>
                              <span className="text-[14px] font-bold">{b.name}</span>
                              <span className="text-[11px] ml-2" style={{ color: colors.inkSubtle }}>FY{b.year} | {b.department || 'Company'}</span>
                            </div>
                          </div>
                          <Badge status={b.status} />
                        </button>
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                          <div>
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Planned</p>
                            <p className="text-[16px] font-bold font-mono">{fmt(b.planned)}</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Actual</p>
                            <p className="text-[16px] font-bold font-mono">{fmt(b.actual)}</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Variance</p>
                            <p className="text-[16px] font-bold font-mono" style={{ color: b.variance < 0 ? '#ef4444' : '#22c55e' }}>{fmt(Math.abs(b.variance))}</p>
                          </div>
                          <div>
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Variance %</p>
                            <p className="text-[16px] font-bold" style={{ color: (b.variance_pct || 0) < 0 ? '#ef4444' : '#22c55e' }}>{b.variance_pct?.toFixed(1)}%</p>
                          </div>
                        </div>
                        <div className="mt-3 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                          <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, (b.actual / (b.planned || 1)) * 100)}%`, background: (b.actual / (b.planned || 1)) > 1 ? '#ef4444' : '#8b5cf6' }} />
                        </div>
                        {expanded && (
                          <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                            {budgetLinesLoading === b.id ? (
                              <div className="flex items-center gap-2 py-3 text-[12px]" style={{ color: colors.inkSubtle }}>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading budget lines...
                              </div>
                            ) : lines.length === 0 ? (
                              <p className="text-[12px] py-2" style={{ color: colors.inkTertiary }}>No line items for this budget.</p>
                            ) : (
                              <div className="overflow-x-auto">
                                <table className="w-full text-[12px]">
                                  <thead>
                                    <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                      {['Period', 'Category', 'Planned', 'Actual', 'Committed', 'Variance'].map(h => (
                                        <th key={h} className="text-left px-3 py-2 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {lines.map((l: any) => (
                                      <tr key={l.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                        <td className="px-3 py-2" style={{ color: colors.inkSubtle }}>{l.label || l.period}</td>
                                        <td className="px-3 py-2">{l.category}</td>
                                        <td className="px-3 py-2 font-mono">{fmt(l.planned)}</td>
                                        <td className="px-3 py-2 font-mono">{fmt(l.actual)}</td>
                                        <td className="px-3 py-2 font-mono" style={{ color: colors.inkSubtle }}>{fmt(l.committed)}</td>
                                        <td className="px-3 py-2 font-mono font-semibold" style={{ color: l.variance < 0 ? '#ef4444' : '#22c55e' }}>{fmt(l.variance)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {budgets.length === 0 && <EmptyState icon={BarChart3} title="No budgets" sub="Budget allocations appear here when created" />}
                </div>
                <h3 className="text-[14px] font-bold mt-6">Forecasts</h3>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Forecast', 'Type', 'Scenario', 'Total', 'Confidence', 'Period'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {forecasts.map((f: any) => (
                        <tr key={f.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{f.name}</td>
                          <td className="px-4 py-3">{humanize(f.type)}</td>
                          <td className="px-4 py-3"><Badge status={f.scenario || 'BASE'} /></td>
                          <td className="px-4 py-3 font-mono font-bold">{fmt(f.total)}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                                <div className="h-full rounded-full" style={{ width: `${(f.confidence || 0) * 100}%`, background: '#8b5cf6' }} />
                              </div>
                              <span className="text-[11px]">{((f.confidence || 0) * 100).toFixed(0)}%</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>{f.period}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {forecasts.length === 0 && <EmptyState icon={TrendingUp} title="No forecasts" sub="Financial forecasts appear here" />}
                </TableCard>
              </div>
            )}

            {/* ═══ EXPENSE REPORTS ═══ */}
            {tab === 'expenses' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  <StatCard label="Total Reports" value={expenseReports.length} icon={<Wallet className="w-4 h-4" />} accent="#22c55e" />
                  <StatCard label="Pending Approval" value={expenseReports.filter(r => r.status === 'PENDING_APPROVAL').length} icon={<Clock className="w-4 h-4" />} accent="#f59e0b" />
                  <StatCard label="Total Amount" value={expenseReports.reduce((s: number, r: any) => s + (r.total || 0), 0)} format="currency" icon={<DollarSign className="w-4 h-4" />} accent="#8b5cf6" />
                </div>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['', 'Report #', 'Title', 'Status', 'Total', 'Approved', 'Compliance', 'Violations'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {expenseReports.filter(r => !searchQ || r.title?.toLowerCase().includes(searchQ.toLowerCase())).map((r: any) => {
                        const expanded = expandedReport === r.id;
                        const items = expenseItems[r.id] || [];
                        return (
                          <React.Fragment key={r.id}>
                            <tr style={{ borderBottom: expanded ? 'none' : `1px solid ${colors.hairline}` }}>
                              <td className="px-2 py-3">
                                <button type="button" onClick={() => toggleReport(r.id)} aria-label={`${expanded ? 'Collapse' : 'Expand'} line items for ${r.title}`}
                                  className="p-1 rounded-md" style={{ color: colors.inkSubtle }}>
                                  {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                                </button>
                              </td>
                              <td className="px-4 py-3 font-medium">{r.number}</td>
                              <td className="px-4 py-3">{r.title}</td>
                              <td className="px-4 py-3"><Badge status={r.status} /></td>
                              <td className="px-4 py-3 font-mono">${r.total?.toLocaleString()}</td>
                              <td className="px-4 py-3 font-mono">${r.approved?.toLocaleString()}</td>
                              <td className="px-4 py-3">
                                {r.compliance_score != null && (() => {
                                  const pct = toPct(r.compliance_score)!;
                                  return (
                                    <span className="text-[11px] font-bold" style={{ color: pct > 80 ? '#22c55e' : '#ef4444' }}>
                                      {pct.toFixed(0)}%
                                    </span>
                                  );
                                })()}
                              </td>
                              <td className="px-4 py-3">
                                {r.violations > 0 ? (
                                  <span className="px-2 py-0.5 rounded text-[11px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>{r.violations} issues</span>
                                ) : <CheckCircle2 className="w-4 h-4" style={{ color: '#22c55e' }} />}
                              </td>
                            </tr>
                            {expanded && (
                              <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                <td colSpan={8} className="px-4 pb-4 pt-0" style={{ background: colors.canvas }}>
                                  {expenseItemsLoading === r.id ? (
                                    <div className="flex items-center gap-2 py-3 text-[12px]" style={{ color: colors.inkSubtle }}>
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading line items...
                                    </div>
                                  ) : items.length === 0 ? (
                                    <p className="text-[12px] py-2" style={{ color: colors.inkTertiary }}>No line items for this report.</p>
                                  ) : (
                                    <div className="overflow-x-auto">
                                      <table className="w-full text-[11.5px]">
                                        <thead>
                                          <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                            {['Date', 'Category', 'Description', 'Merchant', 'Amount', 'Receipt', 'Policy', 'Billable'].map(h => (
                                              <th key={h} className="text-left px-3 py-2 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                                            ))}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {items.map((it: any) => (
                                            <tr key={it.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                              <td className="px-3 py-2" style={{ color: colors.inkSubtle }}>{it.date}</td>
                                              <td className="px-3 py-2">{humanize(it.category)}</td>
                                              <td className="px-3 py-2">{it.description}</td>
                                              <td className="px-3 py-2" style={{ color: colors.inkSubtle }}>{it.merchant || '-'}</td>
                                              <td className="px-3 py-2 font-mono font-semibold">${it.amount?.toLocaleString()}</td>
                                              <td className="px-3 py-2">{it.has_receipt ? <CheckCircle2 className="w-3.5 h-3.5" style={{ color: '#22c55e' }} /> : <span style={{ color: colors.inkTertiary }}>-</span>}</td>
                                              <td className="px-3 py-2">
                                                {it.within_policy
                                                  ? <span style={{ color: '#22c55e' }}>Within policy</span>
                                                  : <span style={{ color: '#ef4444' }}>Flagged</span>}
                                              </td>
                                              <td className="px-3 py-2" style={{ color: colors.inkSubtle }}>{it.billable ? 'Billable' : 'Internal'}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  )}
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                  {expenseReports.length === 0 && <EmptyState icon={Wallet} title="No expense reports" sub="Employee expense reports appear here" />}
                </TableCard>
              </div>
            )}

            {/* ═══ TAX ═══ */}
            {tab === 'tax' && (
              <div className="space-y-4">
                <h3 className="text-[14px] font-bold">Tax Filings</h3>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Filing Type', 'Jurisdiction', 'Period', 'Status', 'Liability', 'Paid', 'Due Date', 'Form'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {taxFilings.map((f: any) => (
                        <tr key={f.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{humanize(f.type)}</td>
                          <td className="px-4 py-3">{f.jurisdiction}</td>
                          <td className="px-4 py-3">{f.period}</td>
                          <td className="px-4 py-3"><Badge status={f.status} /></td>
                          <td className="px-4 py-3 font-mono">${f.liability?.toLocaleString()}</td>
                          <td className="px-4 py-3 font-mono">${f.paid?.toLocaleString()}</td>
                          <td className="px-4 py-3">{timeAgo(f.due_date)}</td>
                          <td className="px-4 py-3">{f.form || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {taxFilings.length === 0 && <EmptyState icon={Scale} title="No tax filings" sub="Tax filings appear here when created" />}
                </TableCard>
                <h3 className="text-[14px] font-bold mt-6">Tax Rules</h3>
                <div className="grid grid-cols-2 gap-3">
                  {taxRules.map((r: any) => (
                    <div key={r.id} className="rounded-xl p-4 flex items-center justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div>
                        <p className="text-[13px] font-semibold">{r.name}</p>
                        <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{humanize(r.type)} | {r.jurisdiction}</p>
                      </div>
                      <span className="text-[16px] font-bold font-mono" style={{ color: '#f59e0b' }}>{(r.rate * 100).toFixed(1)}%</span>
                    </div>
                  ))}
                  {taxRules.length === 0 && <EmptyState icon={Scale} title="No tax rules" sub="Tax rules appear here" />}
                </div>
              </div>
            )}

            {/* ═══ TREASURY ═══ */}
            {tab === 'treasury' && (() => {
              const totalCash = bankAccounts.reduce((s: number, a: any) => s + (a.balance || 0), 0);
              const totalAvailable = bankAccounts.reduce((s: number, a: any) => s + (a.available || 0), 0);
              const actualFlows = cashFlows.filter((f: any) => !f.is_forecast);
              const forecastFlows = cashFlows.filter((f: any) => f.is_forecast);
              const netActual = actualFlows.reduce((s: number, f: any) => s + (f.amount || 0), 0);
              const netForecast = forecastFlows.reduce((s: number, f: any) => s + (f.amount || 0), 0);
              const byCategory: Record<string, number> = {};
              actualFlows.forEach((f: any) => {
                const cat = f.category || 'Other';
                byCategory[cat] = (byCategory[cat] || 0) + Math.abs(f.amount || 0);
              });
              const flowBars: DonutItem[] = Object.entries(byCategory)
                .map(([label, value]) => ({ label, value }))
                .sort((a, b) => b.value - a.value)
                .slice(0, 8);
              const byClass: Record<string, number> = {};
              bankAccounts.forEach((a: any) => {
                const label = humanize(a.classification) || 'Other';
                byClass[label] = (byClass[label] || 0) + (a.balance || 0);
              });
              const classDonut: DonutItem[] = Object.entries(byClass).map(([label, value]) => ({ label, value }));

              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                    <StatCard label="Total Cash" value={totalCash} format="currency" icon={<PiggyBank className="w-4 h-4" />} accent="#14b8a6" />
                    <StatCard label="Available Balance" value={totalAvailable} format="currency" icon={<Wallet className="w-4 h-4" />} accent="#22c55e" />
                    <StatCard label="Net Cash Flow" value={netActual} format="currency" icon={netActual >= 0 ? <ArrowUpCircle className="w-4 h-4" /> : <ArrowDownCircle className="w-4 h-4" />} accent={netActual >= 0 ? '#22c55e' : '#ef4444'} />
                    <StatCard label="Forecasted Net" value={netForecast} format="currency" icon={<TrendingUp className="w-4 h-4" />} accent="#8b5cf6" />
                  </div>

                  <h3 className="text-[14px] font-bold">Bank Accounts</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {bankAccounts.map((a: any) => (
                      <div key={a.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                        <div className="flex items-center justify-between mb-2 gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <Building2 className="w-4 h-4 shrink-0" style={{ color: '#14b8a6' }} />
                            <div className="min-w-0">
                              <p className="text-[13px] font-semibold truncate">{a.name}</p>
                              <p className="text-[11px] truncate" style={{ color: colors.inkSubtle }}>{a.bank} &middot; {a.masked_number}</p>
                            </div>
                          </div>
                          <Badge status={a.classification} />
                        </div>
                        <div className="flex items-end justify-between mt-3">
                          <div>
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Balance</p>
                            <CountUp value={a.balance || 0} prefix="$" decimals={2} className="text-[18px] font-bold tabular-nums" />
                          </div>
                          <div className="text-right">
                            <p className="text-[11px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Available</p>
                            <p className="text-[13px] font-mono font-semibold" style={{ color: colors.inkSubtle }}>${(a.available || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</p>
                          </div>
                        </div>
                        <p className="text-[11px] mt-2" style={{ color: colors.inkTertiary }}>
                          {a.last_reconciled ? `Reconciled ${timeAgo(a.last_reconciled)}` : 'Not yet reconciled'}
                        </p>
                      </div>
                    ))}
                  </div>
                  {bankAccounts.length === 0 && <EmptyState icon={PiggyBank} title="No bank accounts" sub="Treasury accounts appear here once connected" />}

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-1.5">
                        <BarChart3 className="w-4 h-4" style={{ color: '#14b8a6' }} /> Cash Movement by Category
                      </h3>
                      {flowBars.length > 0
                        ? <TreasuryBars items={flowBars} />
                        : <div className="text-[12px] py-6" style={{ color: colors.inkTertiary }}>No posted cash movements.</div>}
                    </div>
                    <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-1.5">
                        <PiggyBank className="w-4 h-4" style={{ color: '#14b8a6' }} /> Cash by Account Classification
                      </h3>
                      {classDonut.length > 0
                        ? <MiniDonut items={classDonut} size={96} centerLabel="cash" />
                        : <div className="text-[12px] py-6" style={{ color: colors.inkTertiary }}>No bank accounts.</div>}
                    </div>
                  </div>

                  <h3 className="text-[14px] font-bold mt-2">Recent Cash Flow</h3>
                  <TableCard>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Date', 'Type', 'Category', 'Amount', 'Source', 'Status'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {cashFlows.map((f: any) => {
                          const inflow = String(f.type || '').includes('INFLOW');
                          return (
                            <tr key={f.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-3">{f.date || '-'}</td>
                              <td className="px-4 py-3">
                                <span className="inline-flex items-center gap-1" style={{ color: inflow ? '#22c55e' : '#ef4444' }}>
                                  {inflow ? <ArrowUpCircle className="w-3.5 h-3.5" /> : <ArrowDownCircle className="w-3.5 h-3.5" />}
                                  {humanize(f.type)}
                                </span>
                              </td>
                              <td className="px-4 py-3">{f.category || '-'}</td>
                              <td className="px-4 py-3 font-mono font-semibold" style={{ color: inflow ? '#22c55e' : '#ef4444' }}>
                                ${Math.abs(f.amount || 0).toLocaleString()}
                              </td>
                              <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{humanize(f.source) || 'Manual'}</td>
                              <td className="px-4 py-3">
                                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
                                  style={{ background: (f.is_forecast ? '#8b5cf6' : '#22c55e') + '18', color: f.is_forecast ? '#8b5cf6' : '#22c55e' }}>
                                  {f.is_forecast ? 'Forecast' : 'Actual'}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {cashFlows.length === 0 && <EmptyState icon={Wallet} title="No cash flow activity" sub="Treasury cash movements appear here" />}
                  </TableCard>
                </div>
              );
            })()}

            {/* ═══ AUDIT & SOX ═══ */}
            {tab === 'audit' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  <StatCard label="Open Findings" value={auditFindings.filter(f => ['OPEN','IN_PROGRESS'].includes(f.status)).length} icon={<AlertCircle className="w-4 h-4" />} accent="#ef4444" />
                  <StatCard label="SOX Controls" value={soxControls.length} icon={<ShieldCheck className="w-4 h-4" />} accent="#8b5cf6" />
                  <StatCard label="Financial Impact" value={auditFindings.reduce((s: number, f: any) => s + (f.impact || 0), 0)} format="currency" icon={<DollarSign className="w-4 h-4" />} accent="#f59e0b" />
                </div>
                <h3 className="text-[14px] font-bold">Audit Findings</h3>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Finding #', 'Title', 'Severity', 'Status', 'Area', 'Impact', 'Owner', 'AI Detected'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {auditFindings.map((f: any) => (
                        <tr key={f.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{f.number}</td>
                          <td className="px-4 py-3">{f.title}</td>
                          <td className="px-4 py-3"><Badge status={f.severity} /></td>
                          <td className="px-4 py-3"><Badge status={f.status} /></td>
                          <td className="px-4 py-3">{humanize(f.area)}</td>
                          <td className="px-4 py-3 font-mono">${f.impact?.toLocaleString()}</td>
                          <td className="px-4 py-3">{f.owner || '-'}</td>
                          <td className="px-4 py-3">{f.ai_detected ? <Bot className="w-4 h-4" style={{ color: '#8b5cf6' }} /> : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {auditFindings.length === 0 && <EmptyState icon={ShieldAlert} title="No audit findings" sub="Audit findings appear here" />}
                </TableCard>
                <h3 className="text-[14px] font-bold mt-6">SOX Controls</h3>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Control ID', 'Name', 'Type', 'Frequency', 'Status', 'Risk', 'AI Score'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {soxControls.map((c: any) => (
                        <tr key={c.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium font-mono">{c.code}</td>
                          <td className="px-4 py-3">{c.name}</td>
                          <td className="px-4 py-3">{humanize(c.type)}</td>
                          <td className="px-4 py-3">{humanize(c.frequency)}</td>
                          <td className="px-4 py-3"><Badge status={c.status} /></td>
                          <td className="px-4 py-3"><Badge status={c.risk_level} /></td>
                          <td className="px-4 py-3">
                            {c.ai_score != null && (() => {
                              const pct = toPct(c.ai_score)!;
                              return (
                                <span className="font-bold" style={{ color: pct > 80 ? '#22c55e' : pct > 50 ? '#f59e0b' : '#ef4444' }}>
                                  {pct.toFixed(0)}%
                                </span>
                              );
                            })()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {soxControls.length === 0 && <EmptyState icon={ShieldCheck} title="No SOX controls" sub="SOX controls appear here" />}
                </TableCard>

                <h3 className="text-[14px] font-bold mt-6">Financial Reports</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {financialReports.map((r: any) => (
                    <div key={r.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileBarChart2 className="w-4 h-4 shrink-0" style={{ color: '#ef4444' }} />
                          <div className="min-w-0">
                            <p className="text-[13px] font-semibold truncate">{r.title}</p>
                            <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{humanize(r.type)} &middot; {r.period}</p>
                          </div>
                        </div>
                        <Badge status={r.status} />
                      </div>
                      <div className="flex items-center justify-between mt-3">
                        <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
                          {r.generated_at ? `Generated ${timeAgo(r.generated_at)}` : 'Not yet generated'}
                        </span>
                        {r.ai_anomalies > 0 ? (
                          <span className="px-2 py-0.5 rounded text-[11px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>{r.ai_anomalies} anomal{r.ai_anomalies === 1 ? 'y' : 'ies'}</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-semibold" style={{ color: '#22c55e' }}><CheckCircle2 className="w-3.5 h-3.5" /> No anomalies</span>
                        )}
                      </div>
                    </div>
                  ))}
                  {financialReports.length === 0 && <EmptyState icon={FileBarChart2} title="No financial reports" sub="Generated financial reports appear here" />}
                </div>

                <h3 className="text-[14px] font-bold mt-6">Compliance Rules</h3>
                <TableCard>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Regulation', 'Section', 'Rule', 'Applies To', 'Severity', 'Blocking'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {complianceRules.map((r: any) => (
                        <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium flex items-center gap-1.5"><Gavel className="w-3.5 h-3.5" style={{ color: colors.inkTertiary }} />{r.regulation}</td>
                          <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{r.section}</td>
                          <td className="px-4 py-3">{r.name}</td>
                          <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{humanize(r.applies_to)}</td>
                          <td className="px-4 py-3"><Badge status={r.severity} /></td>
                          <td className="px-4 py-3">
                            {r.is_blocking
                              ? <span className="inline-flex items-center gap-1 text-[11px] font-semibold" style={{ color: '#ef4444' }}><ShieldAlert className="w-3.5 h-3.5" /> Blocking</span>
                              : <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Advisory</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {complianceRules.length === 0 && <EmptyState icon={FileCheck2} title="No compliance rules" sub="Finance compliance rules appear here" />}
                </TableCard>
              </div>
            )}

            {/* ═══ ANALYTICS ═══ */}
            {/* ═══ CHART OF ACCOUNTS ═══ */}
            {tab === 'accounts' && (() => {
              const filtered = chartOfAccounts.filter(a => !searchQ
                || a.name?.toLowerCase().includes(searchQ.toLowerCase())
                || a.code?.toLowerCase().includes(searchQ.toLowerCase()));
              // Group by accounting type so the ledger reads the way finance expects.
              const grouped = ACCOUNT_TYPE_ORDER
                .map(t => ({ type: t, rows: filtered.filter(a => a.type === t) }))
                .concat([{ type: 'OTHER', rows: filtered.filter(a => !ACCOUNT_TYPE_ORDER.includes(a.type)) }])
                .filter(g => g.rows.length > 0);
              return (
                <div className="space-y-4">
                  {chartOfAccounts.length === 0 ? (
                    <EmptyState icon={FileText} title="No accounts defined" sub="Your chart of accounts appears here once finance data is connected" />
                  ) : grouped.length === 0 ? (
                    <EmptyState icon={FileText} title="No accounts match your search" sub="Try a different account name or code" />
                  ) : grouped.map(g => {
                    const total = g.rows.reduce((s, a) => s + (a.balance || 0), 0);
                    return (
                      <TableCard key={g.type}>
                        <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>
                            {humanize(g.type)} accounts
                          </span>
                          <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{g.rows.length}</span>
                          <span className="ml-auto text-[12px] font-mono font-semibold" style={{ color: colors.ink }}>
                            ${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                          </span>
                        </div>
                        <table className="w-full text-[12px]">
                          <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            {['Code', 'Account', 'Balance', 'Department', 'Cost Centre', 'Status'].map(h => (
                              <th key={h} className="text-left px-4 py-2 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                            ))}
                          </tr></thead>
                          <tbody>
                            {g.rows.map(a => (
                              <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                <td className="px-4 py-2.5 font-mono">{a.code}</td>
                                <td className="px-4 py-2.5 font-medium">{a.name}</td>
                                <td className="px-4 py-2.5 font-mono font-semibold">
                                  ${(a.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                                  <span className="ml-1 text-[11px]" style={{ color: colors.inkTertiary }}>{a.currency || 'USD'}</span>
                                </td>
                                <td className="px-4 py-2.5" style={{ color: colors.inkSubtle }}>{a.department || 'Company-wide'}</td>
                                <td className="px-4 py-2.5" style={{ color: colors.inkSubtle }}>{a.cost_center || '-'}</td>
                                <td className="px-4 py-2.5"><Badge status={a.is_active ? 'ACTIVE' : 'CLOSED'} /></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableCard>
                    );
                  })}
                </div>
              );
            })()}

            {tab === 'analytics' && <DomainAnalytics domain="finance" />}
          </>
        )}
      </div>
    </div>
  );
};

export default FinanceView;
