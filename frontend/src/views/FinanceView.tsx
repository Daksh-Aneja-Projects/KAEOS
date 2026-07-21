import React, { useEffect, useState } from 'react';
import {
  Receipt, Landmark, BarChart3, Wallet, Scale, ShieldAlert,
  Search, Filter, RefreshCw, Loader2, Bot, ArrowUpRight,
  CheckCircle2, XCircle, AlertCircle, Clock, DollarSign,
  FileText, TrendingUp, ShieldCheck
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { toPct } from '../lib/format';
import { timeAgo } from '../lib/time';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import BulkActionBar from '../components/BulkActionBar';
import { useBulkSelect } from '../hooks/useBulkSelect';
import { Plus as PlusIcon } from 'lucide-react';

type FinanceTab = 'ap' | 'ar' | 'budgets' | 'expenses' | 'tax' | 'audit' | 'analytics';

const FinanceView: React.FC<{ domain?: string; defaultTab?: string }> = ({ domain, defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<FinanceTab>(() => {
    const valid: FinanceTab[] = ['ap', 'ar', 'budgets', 'expenses', 'tax', 'audit', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as FinanceTab)) return defaultTab as FinanceTab;
    return 'ap';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);

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
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const bulk = useBulkSelect(invoices, workflows['invoice'], (i: any) => i.status);

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
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setVendors(val(0)); setInvoices(val(1)); setPayments(val(2));
    setCustomers(val(3)); setReceivables(val(4)); setBudgets(val(5));
    setForecasts(val(6)); setExpenseReports(val(7)); setTaxFilings(val(8));
    setTaxRules(val(9)); setAuditFindings(val(10)); setSoxControls(val(11));
    if (results[12].status === 'fulfilled') setWorkflows((results[12] as any).value || {});
    setLoading(false);
  };

  const handleRunAPAgent = async (invoiceId: string) => {
    setRunningAgent(invoiceId); setActionMsg('');
    try {
      const res = await api.runFinanceAPAgent(invoiceId);
      setActionMsg(res?.status === 'PENDING_HITL' ? 'AP matching routed for human review.' : 'AP 3-way match complete.');
      await loadData();
    } catch (e: any) { setActionMsg(`AP agent failed: ${e?.message || e}`); }
    finally { setRunningAgent(null); }
  };

  const handleRunARAgent = async (invoiceId: string) => {
    setRunningAgent(invoiceId); setActionMsg('');
    try {
      const res = await api.runFinanceARAgent(invoiceId);
      setActionMsg(res?.letter ? 'Dunning letter generated.' : 'AR agent completed.');
      await loadData();
    } catch (e: any) { setActionMsg(`AR agent failed: ${e?.message || e}`); }
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
    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {(status || 'N/A').replace(/_/g, ' ')}
    </span>
  );

  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-16 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-12 h-12 mx-auto mb-4" style={{ color: colors.inkTertiary }} />
      <p className="text-[15px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  const TABS: { key: FinanceTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'ap', label: 'Accounts Payable', icon: Receipt, color: '#ec4899' },
    { key: 'ar', label: 'Accounts Receivable', icon: Landmark, color: '#3b82f6' },
    { key: 'budgets', label: 'Budgets', icon: BarChart3, color: '#8b5cf6' },
    { key: 'expenses', label: 'Expenses', icon: Wallet, color: '#22c55e' },
    { key: 'tax', label: 'Tax', icon: Scale, color: '#f59e0b' },
    { key: 'audit', label: 'Audit & SOX', icon: ShieldAlert, color: '#ef4444' },
    { key: 'analytics', label: 'Analytics', icon: TrendingUp, color: '#a855f7' },
  ];

  const activeTab = TABS.find(t => t.key === tab)!;
  const fmt = (v: number) => v >= 1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`;

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
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
            <button onClick={loadData} className="p-2 rounded-lg hover:bg-opacity-10 transition-colors"
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
        <div className="flex gap-1 p-1 rounded-xl" style={{ background: colors.surface1 }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all"
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
            <button onClick={() => setActionMsg('')} className="ml-auto text-[10px] opacity-60 hover:opacity-100">dismiss</button>
          </div>
        )}

        {/* Search bar */}
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
          <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
            placeholder={`Search ${activeTab.label.toLowerCase()}...`}
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
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Vendors', value: vendors.length, icon: Landmark, color: '#3b82f6' },
                    { label: 'Open Invoices', value: invoices.filter(i => !['PAID','CANCELLED'].includes(i.status)).length, icon: Receipt, color: '#ec4899' },
                    { label: 'Total AP', value: fmt(invoices.reduce((s: number, i: any) => s + (i.balance || 0), 0)), icon: DollarSign, color: '#f59e0b' },
                    { label: 'Payments Made', value: payments.length, icon: CheckCircle2, color: '#22c55e' },
                  ].map(kpi => (
                    <div key={kpi.label} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="text-[22px] font-bold" style={{ color: colors.ink }}>{kpi.value}</span>
                          <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</p>
                        </div>
                        <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
                      </div>
                    </div>
                  ))}
                </div>
                <BulkActionBar domain="finance" entityType="invoice" noun="invoice"
                  ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                            <button onClick={() => handleRunAPAgent(inv.id)}
                              disabled={runningAgent === inv.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold transition-colors"
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
                </div>
              </div>
            )}

            {/* ═══ ACCOUNTS RECEIVABLE ═══ */}
            {tab === 'ar' && (
              <div className="space-y-4">
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Customers', value: customers.length, icon: Landmark, color: '#3b82f6' },
                    { label: 'Open Receivables', value: receivables.filter(r => !['PAID','CANCELLED'].includes(r.status)).length, icon: Receipt, color: '#ec4899' },
                    { label: 'Total AR', value: fmt(receivables.reduce((s: number, r: any) => s + (r.balance || 0), 0)), icon: DollarSign, color: '#f59e0b' },
                    { label: 'Avg DSO', value: customers.length > 0 ? Math.round(customers.reduce((s: number, c: any) => s + (c.dso || 0), 0) / customers.length) + 'd' : '-', icon: Clock, color: '#8b5cf6' },
                  ].map(kpi => (
                    <div key={kpi.label} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="text-[22px] font-bold" style={{ color: colors.ink }}>{kpi.value}</span>
                          <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</p>
                        </div>
                        <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>Level {rec.dunning_level}</span>
                            ) : <span style={{ color: colors.inkTertiary }}>-</span>}
                          </td>
                          <td className="px-4 py-3">
                            <button onClick={() => handleRunARAgent(rec.id)}
                              disabled={runningAgent === rec.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold transition-colors"
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
                </div>
              </div>
            )}

            {/* ═══ BUDGETS & FORECASTS ═══ */}
            {tab === 'budgets' && (
              <div className="space-y-4">
                <h3 className="text-[14px] font-bold">Active Budgets</h3>
                <div className="grid grid-cols-1 gap-3">
                  {budgets.map((b: any) => (
                    <div key={b.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                          <BarChart3 className="w-5 h-5" style={{ color: '#8b5cf6' }} />
                          <div>
                            <span className="text-[14px] font-bold">{b.name}</span>
                            <span className="text-[11px] ml-2" style={{ color: colors.inkSubtle }}>FY{b.year} | {b.department || 'Company'}</span>
                          </div>
                        </div>
                        <Badge status={b.status} />
                      </div>
                      <div className="grid grid-cols-4 gap-4">
                        <div>
                          <p className="text-[10px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Planned</p>
                          <p className="text-[16px] font-bold font-mono">{fmt(b.planned)}</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Actual</p>
                          <p className="text-[16px] font-bold font-mono">{fmt(b.actual)}</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Variance</p>
                          <p className="text-[16px] font-bold font-mono" style={{ color: b.variance < 0 ? '#ef4444' : '#22c55e' }}>{fmt(Math.abs(b.variance))}</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase font-semibold" style={{ color: colors.inkSubtle }}>Variance %</p>
                          <p className="text-[16px] font-bold" style={{ color: (b.variance_pct || 0) < 0 ? '#ef4444' : '#22c55e' }}>{b.variance_pct?.toFixed(1)}%</p>
                        </div>
                      </div>
                      <div className="mt-3 h-2 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, (b.actual / (b.planned || 1)) * 100)}%`, background: (b.actual / (b.planned || 1)) > 1 ? '#ef4444' : '#8b5cf6' }} />
                      </div>
                    </div>
                  ))}
                  {budgets.length === 0 && <EmptyState icon={BarChart3} title="No budgets" sub="Budget allocations appear here when created" />}
                </div>
                <h3 className="text-[14px] font-bold mt-6">Forecasts</h3>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                          <td className="px-4 py-3">{f.type}</td>
                          <td className="px-4 py-3"><Badge status={f.scenario || 'BASE'} /></td>
                          <td className="px-4 py-3 font-mono font-bold">{fmt(f.total)}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                                <div className="h-full rounded-full" style={{ width: `${(f.confidence || 0) * 100}%`, background: '#8b5cf6' }} />
                              </div>
                              <span className="text-[10px]">{((f.confidence || 0) * 100).toFixed(0)}%</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>{f.period}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {forecasts.length === 0 && <EmptyState icon={TrendingUp} title="No forecasts" sub="Financial forecasts appear here" />}
                </div>
              </div>
            )}

            {/* ═══ EXPENSE REPORTS ═══ */}
            {tab === 'expenses' && (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: 'Total Reports', value: expenseReports.length, color: '#22c55e' },
                    { label: 'Pending Approval', value: expenseReports.filter(r => r.status === 'PENDING_APPROVAL').length, color: '#f59e0b' },
                    { label: 'Total Amount', value: fmt(expenseReports.reduce((s: number, r: any) => s + (r.total || 0), 0)), color: '#8b5cf6' },
                  ].map(kpi => (
                    <div key={kpi.label} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <span className="text-[22px] font-bold" style={{ color: kpi.color }}>{kpi.value}</span>
                      <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</p>
                    </div>
                  ))}
                </div>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Report #', 'Title', 'Status', 'Total', 'Approved', 'Compliance', 'Violations'].map(h => (
                          <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {expenseReports.filter(r => !searchQ || r.title?.toLowerCase().includes(searchQ.toLowerCase())).map((r: any) => (
                        <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{r.number}</td>
                          <td className="px-4 py-3">{r.title}</td>
                          <td className="px-4 py-3"><Badge status={r.status} /></td>
                          <td className="px-4 py-3 font-mono">${r.total?.toLocaleString()}</td>
                          <td className="px-4 py-3 font-mono">${r.approved?.toLocaleString()}</td>
                          <td className="px-4 py-3">
                            {r.compliance_score != null && (() => {
                              const pct = toPct(r.compliance_score)!;
                              return (
                                <span className="text-[10px] font-bold" style={{ color: pct > 80 ? '#22c55e' : '#ef4444' }}>
                                  {pct.toFixed(0)}%
                                </span>
                              );
                            })()}
                          </td>
                          <td className="px-4 py-3">
                            {r.violations > 0 ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: '#ef444415', color: '#ef4444' }}>{r.violations} issues</span>
                            ) : <CheckCircle2 className="w-4 h-4" style={{ color: '#22c55e' }} />}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {expenseReports.length === 0 && <EmptyState icon={Wallet} title="No expense reports" sub="Employee expense reports appear here" />}
                </div>
              </div>
            )}

            {/* ═══ TAX ═══ */}
            {tab === 'tax' && (
              <div className="space-y-4">
                <h3 className="text-[14px] font-bold">Tax Filings</h3>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                          <td className="px-4 py-3 font-medium">{f.type}</td>
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
                </div>
                <h3 className="text-[14px] font-bold mt-6">Tax Rules</h3>
                <div className="grid grid-cols-2 gap-3">
                  {taxRules.map((r: any) => (
                    <div key={r.id} className="rounded-xl p-4 flex items-center justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <div>
                        <p className="text-[13px] font-semibold">{r.name}</p>
                        <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{r.type} | {r.jurisdiction}</p>
                      </div>
                      <span className="text-[16px] font-bold font-mono" style={{ color: '#f59e0b' }}>{(r.rate * 100).toFixed(1)}%</span>
                    </div>
                  ))}
                  {taxRules.length === 0 && <EmptyState icon={Scale} title="No tax rules" sub="Tax rules appear here" />}
                </div>
              </div>
            )}

            {/* ═══ AUDIT & SOX ═══ */}
            {tab === 'audit' && (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: 'Open Findings', value: auditFindings.filter(f => ['OPEN','IN_PROGRESS'].includes(f.status)).length, color: '#ef4444' },
                    { label: 'SOX Controls', value: soxControls.length, color: '#8b5cf6' },
                    { label: 'Financial Impact', value: fmt(auditFindings.reduce((s: number, f: any) => s + (f.impact || 0), 0)), color: '#f59e0b' },
                  ].map(kpi => (
                    <div key={kpi.label} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                      <span className="text-[22px] font-bold" style={{ color: kpi.color }}>{kpi.value}</span>
                      <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</p>
                    </div>
                  ))}
                </div>
                <h3 className="text-[14px] font-bold">Audit Findings</h3>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                          <td className="px-4 py-3">{f.area}</td>
                          <td className="px-4 py-3 font-mono">${f.impact?.toLocaleString()}</td>
                          <td className="px-4 py-3">{f.owner || '-'}</td>
                          <td className="px-4 py-3">{f.ai_detected ? <Bot className="w-4 h-4" style={{ color: '#8b5cf6' }} /> : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {auditFindings.length === 0 && <EmptyState icon={ShieldAlert} title="No audit findings" sub="Audit findings appear here" />}
                </div>
                <h3 className="text-[14px] font-bold mt-6">SOX Controls</h3>
                <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                          <td className="px-4 py-3">{c.type}</td>
                          <td className="px-4 py-3">{c.frequency}</td>
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
                </div>
              </div>
            )}

            {/* ═══ ANALYTICS ═══ */}
            {tab === 'analytics' && <DomainAnalytics domain="finance" />}
          </>
        )}
      </div>
    </div>
  );
};

export default FinanceView;
