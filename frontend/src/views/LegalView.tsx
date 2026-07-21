import React, { useEffect, useState } from 'react';
import {
  FileText, ShieldCheck, Landmark, Lock, Lightbulb, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { toPct } from '../lib/format';
import { timeAgo } from '../lib/time';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';

type LegalTab = 'contracts' | 'compliance' | 'litigation' | 'privacy' | 'ip' | 'analytics';

const LegalView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<LegalTab>(() => {
    const valid: LegalTab[] = ['contracts', 'compliance', 'litigation', 'privacy', 'ip', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as LegalTab)) return defaultTab as LegalTab;
    return 'contracts';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [contracts, setContracts] = useState<any[]>([]);
  const [obligations, setObligations] = useState<any[]>([]);
  const [cases, setCases] = useState<any[]>([]);
  const [dsars, setDsars] = useState<any[]>([]);
  const [patents, setPatents] = useState<any[]>([]);
  const [matters, setMatters] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getLegalContracts(), api.getLegalObligations(), api.getLegalCases(),
      api.getLegalDsars(), api.getLegalPatents(), api.getLegalMatters(),
      api.getDomainWorkflows('legal'),
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setContracts(val(0)); setObligations(val(1)); setCases(val(2));
    setDsars(val(3)); setPatents(val(4)); setMatters(val(5));
    if (results[6].status === 'fulfilled') setWorkflows((results[6] as any).value || {});
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

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['ACTIVE', 'COMPLIANT', 'PASSED', 'COMPLETED', 'GRANTED', 'SETTLED'].includes(n)) return '#22c55e';
    if (['PENDING', 'DRAFT', 'UNDER_REVIEW', 'RECEIVED', 'IN_PROGRESS', 'FILED'].includes(n)) return '#f59e0b';
    if (['EXPIRED', 'NON_COMPLIANT', 'OVERDUE', 'REJECTED', 'HIGH', 'CRITICAL'].includes(n)) return '#ef4444';
    if (['NEGOTIATION', 'DISCOVERY', 'PLEADING', 'MOTION', 'TRIAL'].includes(n)) return '#3b82f6';
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

  const TABS: { key: LegalTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'contracts', label: 'Contracts', icon: FileText, color: '#6366f1' },
    { key: 'compliance', label: 'Compliance', icon: ShieldCheck, color: '#22c55e' },
    { key: 'litigation', label: 'Litigation', icon: Landmark, color: '#ef4444' },
    { key: 'privacy', label: 'Privacy / DSAR', icon: Lock, color: '#3b82f6' },
    { key: 'ip', label: 'Intellectual Property', icon: Lightbulb, color: '#f59e0b' },
    { key: 'analytics', label: 'Analytics', icon: BarChart3, color: '#a855f7' },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: activeTab.color }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Legal & Compliance Department</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <PlusIcon className="w-3.5 h-3.5" /> New Contract
            </button>
            <button onClick={loadData} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
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
        </div>

        <div className="flex gap-1 p-1 rounded-xl" style={{ background: colors.surface1 }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all"
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
            <button onClick={() => setActionMsg('')} className="ml-auto text-[10px] opacity-60">dismiss</button>
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
            {tab === 'contracts' && (
              <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Title', 'Counterparty', 'Status', 'Value', 'Risk Score', 'Expiry', 'AI Review'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {contracts.filter(c => !searchQ || c.title?.toLowerCase().includes(searchQ.toLowerCase()) || c.counterparty?.toLowerCase().includes(searchQ.toLowerCase())).map((c: any) => (
                      <tr key={c.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
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
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold"
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
                      </tr>
                    ))}
                  </tbody>
                </table>
                {contracts.length === 0 && <EmptyState icon={FileText} title="No contracts" sub="Contracts appear here when created" />}
              </div>
            )}

            {tab === 'compliance' && (
              <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Obligation', 'Description', 'Status', 'Owner', 'Due Date', 'AI Audit'].map(h => (
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
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold"
                            style={{ background: '#22c55e15', color: '#22c55e' }}>
                            {runningAgent === o.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Audit
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {obligations.length === 0 && <EmptyState icon={ShieldCheck} title="No obligations" sub="Compliance obligations appear here" />}
              </div>
            )}

            {tab === 'litigation' && (
              <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Case Name', 'Stage', 'Opposing Party', 'Court', 'Exposure', 'AI Evaluate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {cases.filter(c => !searchQ || c.name?.toLowerCase().includes(searchQ.toLowerCase())).map((c: any) => (
                      <tr key={c.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{c.name}</td>
                        <td className="px-4 py-3"><Badge status={c.stage} /></td>
                        <td className="px-4 py-3">{c.opposing_party}</td>
                        <td className="px-4 py-3">{c.court || '-'}</td>
                        <td className="px-4 py-3 font-mono font-semibold" style={{ color: '#ef4444' }}>${c.exposure?.toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Case evaluation', c.id, api.runLitigationAgent)}
                            disabled={runningAgent === c.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold"
                            style={{ background: '#ef444415', color: '#ef4444' }}>
                            {runningAgent === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Evaluate
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {cases.length === 0 && <EmptyState icon={Landmark} title="No cases" sub="Litigation cases appear here" />}
              </div>
            )}

            {tab === 'privacy' && (
              <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold"
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
              </div>
            )}

            {tab === 'ip' && (
              <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold"
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
