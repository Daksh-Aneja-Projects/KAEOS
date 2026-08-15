import React, { useEffect, useState } from 'react';
import {
  FileText, ShieldCheck, Landmark, Lock, Lightbulb, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle, Briefcase,
  ChevronDown, ChevronUp, Award, Fingerprint, ClipboardList, ClipboardCheck,
  CalendarClock, FileStack, Database,
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { legalApi } from '../api/endpoints/legal';
import { useTheme } from '../context/ThemeContext';
import { humanize } from '../lib/format';
import { toPct } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import TableCard from '../components/shared/TableCard';
import StatCard from '../components/shared/StatCard';
import { timeAgo } from '../lib/time';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import BulkActionBar from '../components/BulkActionBar';
import { useBulkSelect } from '../hooks/useBulkSelect';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';

type LegalTab = 'matters' | 'contracts' | 'compliance' | 'litigation' | 'privacy' | 'ip' | 'analytics';

const LegalView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<LegalTab>(() => {
    const valid: LegalTab[] = ['matters', 'contracts', 'compliance', 'litigation', 'privacy', 'ip', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as LegalTab)) return defaultTab as LegalTab;
    return 'contracts';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [matters, setMatters] = useState<any[]>([]);
  const [contracts, setContracts] = useState<any[]>([]);
  const [obligations, setObligations] = useState<any[]>([]);
  const [requirements, setRequirements] = useState<any[]>([]);
  const [assessments, setAssessments] = useState<any[]>([]);
  const [cases, setCases] = useState<any[]>([]);
  const [dsars, setDsars] = useState<any[]>([]);
  const [pias, setPias] = useState<any[]>([]);
  const [ropa, setRopa] = useState<any[]>([]);
  const [patents, setPatents] = useState<any[]>([]);
  const [trademarks, setTrademarks] = useState<any[]>([]);
  const [tradeSecrets, setTradeSecrets] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const bulk = useBulkSelect(contracts, workflows['contract'], c => c.status);
  const [createOpen, setCreateOpen] = useState(false);
  const [matterCreateOpen, setMatterCreateOpen] = useState(false);

  // Drill-downs: which row is expanded, plus a per-id cache so re-expanding
  // doesn't re-fetch.
  const [expandedContract, setExpandedContract] = useState<string | null>(null);
  const [clausesByContract, setClausesByContract] = useState<Record<string, any[]>>({});
  const [expandedCase, setExpandedCase] = useState<string | null>(null);
  const [caseDetail, setCaseDetail] = useState<Record<string, { events: any[]; filings: any[] }>>({});

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getLegalMatters(), api.getLegalContracts(), api.getLegalObligations(),
      api.getLegalCases(), api.getLegalDsars(), api.getLegalPatents(),
      api.getDomainWorkflows('legal'),
      legalApi.getLegalComplianceRequirements(), legalApi.getLegalComplianceAssessments(),
      legalApi.getLegalPias(), legalApi.getLegalRopa(),
      legalApi.getLegalTrademarks(), legalApi.getLegalTradeSecrets(),
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setMatters(val(0)); setContracts(val(1)); setObligations(val(2));
    setCases(val(3)); setDsars(val(4)); setPatents(val(5));
    if (results[6].status === 'fulfilled') setWorkflows((results[6] as any).value || {});
    setRequirements(val(7)); setAssessments(val(8));
    setPias(val(9)); setRopa(val(10));
    setTrademarks(val(11)); setTradeSecrets(val(12));
    setLoading(false);
  };

  const runAgent = async (type: string, id: string, fn: (id: string) => Promise<any>) => {
    setRunningAgent(id); setActionMsg('');
    // Show the gate pipeline where the action was clicked, not as a banner
    // at the top of the page.
    setTrace({ id, label: type, result: undefined });
    try {
      const res = await fn(id);
      setTrace({ id, label: type, result: res });
      await loadData();
    } catch (e: any) {
      setActionMsg(`${type} failed: ${e?.message || e}`);
      setTrace(null);
    }
    finally { setRunningAgent(null); }
  };

  const toggleContract = async (contractId: string) => {
    if (expandedContract === contractId) { setExpandedContract(null); return; }
    setExpandedContract(contractId);
    if (!clausesByContract[contractId]) {
      try {
        const rows = await api.getLegalClauses(contractId);
        setClausesByContract(prev => ({ ...prev, [contractId]: rows || [] }));
      } catch {
        setClausesByContract(prev => ({ ...prev, [contractId]: [] }));
      }
    }
  };

  const toggleCase = async (caseId: string) => {
    if (expandedCase === caseId) { setExpandedCase(null); return; }
    setExpandedCase(caseId);
    if (!caseDetail[caseId]) {
      try {
        const [events, filings] = await Promise.all([
          legalApi.getLegalCaseEvents(caseId), legalApi.getLegalCaseFilings(caseId),
        ]);
        setCaseDetail(prev => ({ ...prev, [caseId]: { events: events || [], filings: filings || [] } }));
      } catch {
        setCaseDetail(prev => ({ ...prev, [caseId]: { events: [], filings: [] } }));
      }
    }
  };

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['ACTIVE', 'COMPLIANT', 'PASSED', 'COMPLETED', 'GRANTED', 'SETTLED', 'RESOLVED', 'SIGNED_OFF'].includes(n)) return '#22c55e';
    if (['PENDING', 'DRAFT', 'UNDER_REVIEW', 'RECEIVED', 'IN_PROGRESS', 'FILED', 'NEW', 'PROCESSING', 'IDENTITY_VERIFIED'].includes(n)) return '#f59e0b';
    if (['EXPIRED', 'NON_COMPLIANT', 'OVERDUE', 'REJECTED', 'HIGH', 'CRITICAL', 'ABANDONED', 'FAILED'].includes(n)) return '#ef4444';
    if (['NEGOTIATION', 'DISCOVERY', 'PLEADING', 'MOTION', 'TRIAL', 'ON_HOLD'].includes(n)) return '#3b82f6';
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

  const SubSection = ({ icon: Icon, title, count }: { icon: React.ElementType; title: string; count: number }) => (
    <div className="flex items-center gap-1.5 pt-1">
      <Icon className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
      <h3 className="text-[12px] font-bold" style={{ color: colors.ink }}>{title}</h3>
      <span className="text-[11px]" style={{ color: colors.inkTertiary }}>({count})</span>
    </div>
  );

  const TABS: { key: LegalTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'matters', label: 'Matters', icon: Briefcase, color: '#14b8a6' },
    { key: 'contracts', label: 'Contracts', icon: FileText, color: '#6366f1' },
    { key: 'compliance', label: 'Compliance', icon: ShieldCheck, color: '#22c55e' },
    { key: 'litigation', label: 'Litigation', icon: Landmark, color: '#ef4444' },
    { key: 'privacy', label: 'Privacy / DSAR', icon: Lock, color: '#3b82f6' },
    { key: 'ip', label: 'Intellectual Property', icon: Lightbulb, color: '#f59e0b' },
    { key: 'analytics', label: 'Analytics', icon: BarChart3, color: '#a855f7' },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  // Arrow keys move between tabs, as a tablist is expected to.
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const i = TABS.findIndex(t => t.key === tab);
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length].key;
    setTab(next);
    document.getElementById(`legal-tab-${next}`)?.focus();
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
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Legal & Compliance Department</p>
          </div>
          <div className="flex items-center gap-2">
            {tab === 'matters' && (
              <button onClick={() => setMatterCreateOpen(true)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
                style={{ background: colors.primary }}>
                <PlusIcon className="w-3.5 h-3.5" /> New Matter
              </button>
            )}
            {tab === 'contracts' && (
              <button onClick={() => setCreateOpen(true)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
                style={{ background: colors.primary }}>
                <PlusIcon className="w-3.5 h-3.5" /> New Contract
              </button>
            )}
            <button onClick={loadData} aria-label="Refresh legal data" title="Refresh legal data"
              className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
            title="New Contract" domain="legal" entityPath="contracts"
            fields={[
              { key: 'title', label: 'Title', type: 'text', required: true },
              { key: 'counterparty', label: 'Counterparty', type: 'text', required: true },
              { key: 'contract_type', label: 'Type', type: 'select', options: ['NDA', 'MSA', 'SOW', 'License', 'Employment'], defaultValue: 'NDA' },
              { key: 'contract_value', label: 'Contract Value ($)', type: 'number' },
              { key: 'expiry_date', label: 'Expiry Date', type: 'date' },
            ]}
            onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
          <CreateEntityModal open={matterCreateOpen} onClose={() => setMatterCreateOpen(false)}
            title="New Matter" domain="legal" entityPath="matters"
            fields={[
              { key: 'title', label: 'Title', type: 'text', required: true },
              { key: 'matter_type', label: 'Type', type: 'select', options: ['M&A', 'Employment', 'Intellectual Property', 'Corporate', 'Litigation'], defaultValue: 'Corporate' },
              { key: 'priority', label: 'Priority', type: 'select', options: ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'], defaultValue: 'MEDIUM' },
              { key: 'description', label: 'Description', type: 'textarea' },
              { key: 'external_counsel', label: 'External Counsel', type: 'text' },
              { key: 'parties', label: 'Parties (comma-separated)', type: 'text', placeholder: 'Acme Corp, Jane Roe' },
              { key: 'adverse_parties', label: 'Adverse Parties (comma-separated)', type: 'text', placeholder: 'screened for conflicts of interest' },
            ]}
            onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
        </div>

        <div role="tablist" aria-label="Legal sections" onKeyDown={onTabKeyDown}
          className="flex gap-1 p-1 rounded-xl overflow-x-auto" style={{ background: colors.surface1 }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              id={`legal-tab-${t.key}`} role="tab" aria-selected={tab === t.key} tabIndex={tab === t.key ? 0 : -1}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
              style={{ background: tab === t.key ? colors.canvas : 'transparent', color: tab === t.key ? t.color : colors.inkSubtle, boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none' }}>
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard label="Matters" value={matters.length} accent="#14b8a6"
            icon={<Briefcase className="w-4 h-4" />} />
          <StatCard label="Contracts" value={contracts.length} accent="#6366f1"
            icon={<FileText className="w-4 h-4" />} />
          <StatCard label="Open Cases" value={cases.length} accent="#ef4444"
            icon={<Landmark className="w-4 h-4" />} />
          <StatCard label="Litigation Exposure" format="currency"
            value={cases.reduce((s: number, c: any) => s + (c.exposure || 0), 0)}
            accent="#f59e0b" icon={<Landmark className="w-4 h-4" />} />
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

        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
          <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
            placeholder={`Search ${activeTab.label.toLowerCase()}...`}
            className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
            style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>
        ) : (
          <>
            {tab === 'matters' && (
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Title', 'Type', 'Status', 'Priority', 'Exposure', 'Assigned Attorney', 'Lifecycle'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {matters.filter(m => !searchQ || m.title?.toLowerCase().includes(searchQ.toLowerCase())).map((m: any) => (
                      <tr key={m.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{m.title}</td>
                        <td className="px-4 py-3">{m.type}</td>
                        <td className="px-4 py-3"><Badge status={m.status} /></td>
                        <td className="px-4 py-3"><Badge status={m.priority} /></td>
                        <td className="px-4 py-3 max-w-[180px] truncate" style={{ color: colors.inkSubtle }}>{m.exposure || '-'}</td>
                        <td className="px-4 py-3">{m.assigned_attorney || '-'}</td>
                        <td className="px-4 py-3">
                          <WorkflowActions domain="legal" entityPath="matters" entityId={m.id}
                            currentState={m.status} transitions={workflows['matter']?.transitions}
                            onDone={async (msg) => { setActionMsg(msg); await loadData(); }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {matters.length === 0 && <EmptyState icon={Briefcase} title="No matters" sub="Legal matters (M&A, employment disputes, corporate work) appear here" />}
              </TableCard>
            )}

            {tab === 'contracts' && (
              <div className="space-y-3">
                <BulkActionBar domain="legal" entityType="contract" noun="contract"
                  ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className="px-3 py-3 w-8">
                      <input type="checkbox" aria-label="Select all contracts"
                        checked={bulk.allSelected} onChange={e => bulk.setAll(e.target.checked)} />
                    </th>
                    {['Title', 'Counterparty', 'Status', 'Value', 'Risk Score', 'Expiry', 'AI Review'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                    <th className="w-8" />
                  </tr></thead>
                  <tbody>
                    {contracts.filter(c => !searchQ || c.title?.toLowerCase().includes(searchQ.toLowerCase()) || c.counterparty?.toLowerCase().includes(searchQ.toLowerCase())).map((c: any) => (
                      <React.Fragment key={c.id}>
                      <tr style={{ borderBottom: expandedContract === c.id ? 'none' : `1px solid ${colors.hairline}` }}>
                        <td className="px-3 py-3">
                          <input type="checkbox" aria-label={`Select ${c.title}`}
                            checked={bulk.isSelected(c.id)} onChange={() => bulk.toggle(c.id)} />
                        </td>
                        <td className="px-4 py-3 font-medium">{c.title}</td>
                        <td className="px-4 py-3">{c.counterparty}</td>
                        <td className="px-4 py-3"><Badge status={c.status} /></td>
                        <td className="px-4 py-3 font-mono">${c.value?.toLocaleString()}</td>
                        <td className="px-4 py-3">
                          {(() => {
                            const pct = toPct(c.risk_score) ?? 0;
                            return (
                              <span className="font-bold" style={{ color: pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#22c55e' }}>
                                {pct.toFixed(0)}%
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3">{c.expiry || '-'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Contract review', c.id, api.runContractReviewAgent)}
                            disabled={runningAgent === c.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                            style={{ background: '#6366f115', color: '#6366f1' }}>
                            {runningAgent === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Review
                          </button>
                          <div className="mt-1">
                            <WorkflowActions domain="legal" entityPath="contracts" entityId={c.id}
                              currentState={c.status} transitions={workflows['contract']?.transitions}
                              onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                          </div>
                        </td>
                        <td className="px-2 py-3">
                          <button onClick={() => toggleContract(c.id)} aria-label={`Toggle clauses for ${c.title}`}
                            className="p-1 rounded" style={{ color: colors.inkSubtle }}>
                            {expandedContract === c.id ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                          </button>
                        </td>
                      </tr>
                      {expandedContract === c.id && (
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td colSpan={9} className="px-4 pb-4">
                            <div className="rounded-lg p-3 space-y-2" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                              {clausesByContract[c.id] === undefined && (
                                <Loader2 className="w-4 h-4 animate-spin" style={{ color: colors.inkSubtle }} />
                              )}
                              {clausesByContract[c.id]?.length === 0 && (
                                <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No clauses have been extracted for this contract yet.</p>
                              )}
                              {(clausesByContract[c.id] || []).map((cl: any) => (
                                <div key={cl.id} className="text-[11px] pb-2" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                                  <div className="flex items-center gap-2 mb-1">
                                    <span className="font-bold">{cl.type}</span>
                                    <Badge status={cl.risk} />
                                  </div>
                                  {cl.analysis && <p style={{ color: colors.inkSubtle }}>{cl.analysis}</p>}
                                  {!cl.analysis && <p style={{ color: colors.inkTertiary }}>Not yet analyzed by AI - run Review to generate clause-level risk analysis.</p>}
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
                {contracts.length === 0 && <EmptyState icon={FileText} title="No contracts" sub="Contracts appear here when created" />}
              </TableCard>
              </div>
            )}

            {tab === 'compliance' && (
              <div className="space-y-4">
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Obligation', 'Description', 'Status', 'Owner', 'Due Date', 'AI Audit', 'Lifecycle'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {obligations.filter(o => !searchQ || o.title?.toLowerCase().includes(searchQ.toLowerCase())).map((o: any) => (
                      <tr key={o.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{o.title}</td>
                        <td className="px-4 py-3 max-w-[200px] truncate" style={{ color: colors.inkSubtle }}>{o.description}</td>
                        <td className="px-4 py-3"><Badge status={o.status} /></td>
                        <td className="px-4 py-3">{o.owner || '-'}</td>
                        <td className="px-4 py-3">{timeAgo(o.due_date)}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Compliance audit', o.id, api.runComplianceAuditAgent)}
                            disabled={runningAgent === o.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                            style={{ background: '#22c55e15', color: '#22c55e' }}>
                            {runningAgent === o.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Audit
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <WorkflowActions domain="legal" entityPath="compliance/obligations" entityId={o.id}
                            currentState={o.status} transitions={workflows['obligation']?.transitions}
                            onDone={async (msg) => { setActionMsg(msg); await loadData(); }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {obligations.length === 0 && <EmptyState icon={ShieldCheck} title="No obligations" sub="Compliance obligations appear here" />}
              </TableCard>

              <SubSection icon={ClipboardCheck} title="Compliance Assessments" count={assessments.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Framework', 'Assessor', 'Date', 'Score', 'Findings'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {assessments.map((a: any) => (
                      <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{a.framework}</td>
                        <td className="px-4 py-3">{a.assessor}</td>
                        <td className="px-4 py-3">{a.assessment_date}</td>
                        <td className="px-4 py-3 font-bold" style={{ color: (a.score ?? 0) >= 90 ? '#22c55e' : (a.score ?? 0) >= 75 ? '#f59e0b' : '#ef4444' }}>
                          {a.score != null ? `${Number(a.score).toFixed(1)}%` : '-'}
                        </td>
                        <td className="px-4 py-3">{a.findings_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {assessments.length === 0 && <EmptyState icon={ClipboardCheck} title="No assessments" sub="Compliance audit assessments appear here" />}
              </TableCard>

              <SubSection icon={ClipboardList} title="Regulatory Requirements" count={requirements.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Regulation', 'Section', 'Title', 'Jurisdiction'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {requirements.map((r: any) => (
                      <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{r.regulation}</td>
                        <td className="px-4 py-3 font-mono">{r.section}</td>
                        <td className="px-4 py-3">{r.title}</td>
                        <td className="px-4 py-3">{r.jurisdiction}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {requirements.length === 0 && <EmptyState icon={ClipboardList} title="No requirements" sub="Regulatory requirements appear here" />}
              </TableCard>
              </div>
            )}

            {tab === 'litigation' && (
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Case Name', 'Stage', 'Opposing Party', 'Court', 'Exposure', 'AI Evaluate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                    <th className="w-8" />
                  </tr></thead>
                  <tbody>
                    {cases.filter(c => !searchQ || c.name?.toLowerCase().includes(searchQ.toLowerCase())).map((c: any) => (
                      <React.Fragment key={c.id}>
                      <tr style={{ borderBottom: expandedCase === c.id ? 'none' : `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{c.name}</td>
                        <td className="px-4 py-3"><Badge status={c.stage} /></td>
                        <td className="px-4 py-3">{c.opposing_party}</td>
                        <td className="px-4 py-3">{c.court || '-'}</td>
                        <td className="px-4 py-3 font-mono font-semibold" style={{ color: '#ef4444' }}>${c.exposure?.toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Case evaluation', c.id, api.runLitigationAgent)}
                            disabled={runningAgent === c.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                            style={{ background: '#ef444415', color: '#ef4444' }}>
                            {runningAgent === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Evaluate
                          </button>
                        </td>
                        <td className="px-2 py-3">
                          <button onClick={() => toggleCase(c.id)} aria-label={`Toggle timeline for ${c.name}`}
                            className="p-1 rounded" style={{ color: colors.inkSubtle }}>
                            {expandedCase === c.id ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                          </button>
                        </td>
                      </tr>
                      {expandedCase === c.id && (
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td colSpan={7} className="px-4 pb-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              <div className="rounded-lg p-3" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                                <div className="flex items-center gap-1.5 mb-2">
                                  <CalendarClock className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
                                  <span className="text-[11px] font-bold">Timeline</span>
                                </div>
                                {caseDetail[c.id] === undefined && <Loader2 className="w-4 h-4 animate-spin" style={{ color: colors.inkSubtle }} />}
                                {caseDetail[c.id]?.events.length === 0 && (
                                  <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No events recorded yet.</p>
                                )}
                                <div className="space-y-1.5">
                                  {(caseDetail[c.id]?.events || []).map((e: any) => (
                                    <div key={e.id} className="text-[11px]">
                                      <span className="font-semibold">{e.title}</span>
                                      {e.is_milestone && <span className="ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: '#a855f718', color: '#a855f7' }}>Milestone</span>}
                                      <div style={{ color: colors.inkSubtle }}>{e.date}{e.description ? `: ${e.description}` : ''}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              <div className="rounded-lg p-3" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                                <div className="flex items-center gap-1.5 mb-2">
                                  <FileStack className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
                                  <span className="text-[11px] font-bold">Court Filings</span>
                                </div>
                                {caseDetail[c.id] === undefined && <Loader2 className="w-4 h-4 animate-spin" style={{ color: colors.inkSubtle }} />}
                                {caseDetail[c.id]?.filings.length === 0 && (
                                  <p className="text-[11px]" style={{ color: colors.inkTertiary }}>No filings recorded yet.</p>
                                )}
                                <div className="space-y-1.5">
                                  {(caseDetail[c.id]?.filings || []).map((f: any) => (
                                    <div key={f.id} className="text-[11px]">
                                      <span className="font-semibold">{f.document_name}</span>
                                      <div style={{ color: colors.inkSubtle }}>{f.filing_date}{f.filed_by ? `, filed by ${f.filed_by}` : ''}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
                {cases.length === 0 && <EmptyState icon={Landmark} title="No cases" sub="Litigation cases appear here" />}
              </TableCard>
            )}

            {tab === 'privacy' && (
              <div className="space-y-4">
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Requestor', 'Email', 'Type', 'Status', 'Deadline', 'AI Validate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {dsars.filter(d => !searchQ || d.name?.toLowerCase().includes(searchQ.toLowerCase())).map((d: any) => (
                      <tr key={d.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{d.name}</td>
                        <td className="px-4 py-3">{d.email}</td>
                        <td className="px-4 py-3"><Badge status={d.type} /></td>
                        <td className="px-4 py-3"><Badge status={d.status} /></td>
                        <td className="px-4 py-3">{d.deadline}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('DSAR validation', d.id, api.runPrivacyDsarAgent)}
                            disabled={runningAgent === d.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                            style={{ background: '#3b82f615', color: '#3b82f6' }}>
                            {runningAgent === d.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Validate
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {dsars.length === 0 && <EmptyState icon={Lock} title="No DSARs" sub="Data subject requests appear here" />}
              </TableCard>

              <SubSection icon={ShieldCheck} title="Privacy Impact Assessments" count={pias.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['System', 'PII Elements', 'Risk', 'Status', 'Sign-off'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {pias.map((p: any) => (
                      <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{p.system_name}</td>
                        <td className="px-4 py-3 max-w-[220px] truncate" style={{ color: colors.inkSubtle }}>{p.pii_elements}</td>
                        <td className="px-4 py-3"><Badge status={p.risk_rating} /></td>
                        <td className="px-4 py-3"><Badge status={p.status} /></td>
                        <td className="px-4 py-3">{p.signoff_date || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {pias.length === 0 && <EmptyState icon={ShieldCheck} title="No assessments" sub="Privacy impact assessments appear here" />}
              </TableCard>

              <SubSection icon={Database} title="Records of Processing Activities" count={ropa.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Controller', 'Purpose', 'Subjects', 'Retention'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {ropa.map((r: any) => (
                      <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{r.data_controller}</td>
                        <td className="px-4 py-3 max-w-[240px] truncate" style={{ color: colors.inkSubtle }}>{r.purpose}</td>
                        <td className="px-4 py-3 max-w-[160px] truncate" style={{ color: colors.inkSubtle }}>{r.subjects || '-'}</td>
                        <td className="px-4 py-3 max-w-[200px] truncate" style={{ color: colors.inkSubtle }}>{r.retention_period || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {ropa.length === 0 && <EmptyState icon={Database} title="No ROPA records" sub="Records of processing activities appear here" />}
              </TableCard>
              </div>
            )}

            {tab === 'ip' && (
              <div className="space-y-4">
              <TableCard>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Title', 'Patent #', 'Status', 'Filing Date', 'Jurisdiction', 'AI Evaluate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {patents.filter(p => !searchQ || p.title?.toLowerCase().includes(searchQ.toLowerCase())).map((p: any) => (
                      <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{p.title}</td>
                        <td className="px-4 py-3 font-mono">{p.number || '-'}</td>
                        <td className="px-4 py-3"><Badge status={p.status} /></td>
                        <td className="px-4 py-3">{p.filing_date || '-'}</td>
                        <td className="px-4 py-3">{p.jurisdiction}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Patent eval', p.id, api.runPatentEvalAgent)}
                            disabled={runningAgent === p.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold"
                            style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                            {runningAgent === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Evaluate
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {patents.length === 0 && <EmptyState icon={Lightbulb} title="No patents" sub="IP portfolio appears here" />}
              </TableCard>

              <SubSection icon={Award} title="Trademarks" count={trademarks.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Mark', 'Registration #', 'Status', 'Class', 'Renewal'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {trademarks.map((t: any) => (
                      <tr key={t.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{t.mark_name}</td>
                        <td className="px-4 py-3 font-mono">{t.registration_number || '-'}</td>
                        <td className="px-4 py-3"><Badge status={t.status} /></td>
                        <td className="px-4 py-3">{t.class_code || '-'}</td>
                        <td className="px-4 py-3">{t.renewal_date || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {trademarks.length === 0 && <EmptyState icon={Award} title="No trademarks" sub="Registered marks appear here" />}
              </TableCard>

              <SubSection icon={Fingerprint} title="Trade Secrets" count={tradeSecrets.length} />
              <TableCard minWidth={560}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Asset', 'Description', 'Custodian', 'Security Level'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {tradeSecrets.map((s: any) => (
                      <tr key={s.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{s.asset_name}</td>
                        <td className="px-4 py-3 max-w-[260px] truncate" style={{ color: colors.inkSubtle }}>{s.description}</td>
                        <td className="px-4 py-3">{s.custodian || '-'}</td>
                        <td className="px-4 py-3"><Badge status={s.security_level} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {tradeSecrets.length === 0 && <EmptyState icon={Fingerprint} title="No trade secrets" sub="Proprietary assets tracked as trade secrets appear here" />}
              </TableCard>
              </div>
            )}

            {/* ANALYTICS */}
            {tab === 'analytics' && <DomainAnalytics domain="legal" />}
          </>
        )}
      </div>
    </div>
  );
};

export default LegalView;
