import React, { useEffect, useState } from 'react';
import {
  FolderKanban, Users2, Building2, ShoppingCart, ClipboardCheck, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { timeAgo } from '../lib/time';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';

type OpsTab = 'projects' | 'resources' | 'vendors' | 'procurement' | 'quality' | 'analytics';

interface OpsProject { id: string; name: string; status: string; owner: string | null; budget: number; spent: number; completion_pct: number; start_date: string | null; end_date: string | null; }
interface OpsResource { id: string; name: string; type: string; project: string | null; utilization: number; available_from: string | null; }
interface OpsVendor { id: string; name: string; category: string; risk_level: string; contract_value: number; soc2_verified: boolean; contract_expiry: string | null; }
interface OpsProcurement { id: string; description: string; requestor: string; status: string; amount: number; vendor: string | null; submitted_at: string; }
interface OpsInspection { id: string; title: string; area: string | null; status: string; score: number; defects: number; inspector: string; date: string | null; }

const OperationsView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<OpsTab>(() => {
    const valid: OpsTab[] = ['projects', 'resources', 'vendors', 'procurement', 'quality', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as OpsTab)) return defaultTab as OpsTab;
    return 'projects';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [projects, setProjects] = useState<OpsProject[]>([]);
  const [resources, setResources] = useState<OpsResource[]>([]);
  const [vendors, setVendors] = useState<OpsVendor[]>([]);
  const [procurements, setProcurements] = useState<OpsProcurement[]>([]);
  const [inspections, setInspections] = useState<OpsInspection[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getOperationsProjects(), api.getOperationsResources(), api.getOperationsVendors(),
      api.getOperationsProcurements(), api.getOperationsInspections(),
      api.getDomainWorkflows('operations'),
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setProjects(val(0)); setResources(val(1)); setVendors(val(2)); setProcurements(val(3)); setInspections(val(4));
    if (results[5].status === 'fulfilled') setWorkflows((results[5] as any).value || {});
    setLoading(false);
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
    if (['ACTIVE', 'ON_TRACK', 'APPROVED', 'PASSED', 'COMPLETED', 'VERIFIED', 'LOW'].includes(n)) return '#22c55e';
    if (['IN_PROGRESS', 'PENDING', 'AT_RISK', 'DRAFT', 'MEDIUM', 'UNDER_REVIEW'].includes(n)) return '#f59e0b';
    if (['DELAYED', 'BLOCKED', 'REJECTED', 'FAILED', 'CRITICAL', 'HIGH', 'OVERDUE'].includes(n)) return '#ef4444';
    if (['PLANNING', 'NEW', 'SUBMITTED'].includes(n)) return '#3b82f6';
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

  const TABS: { key: OpsTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'projects', label: 'Projects', icon: FolderKanban, color: '#6366f1' },
    { key: 'resources', label: 'Resources', icon: Users2, color: '#22c55e' },
    { key: 'vendors', label: 'Vendors', icon: Building2, color: '#f59e0b' },
    { key: 'procurement', label: 'Procurement', icon: ShoppingCart, color: '#3b82f6' },
    { key: 'quality', label: 'Quality', icon: ClipboardCheck, color: '#ef4444' },
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
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Operations Department</p>
          </div>
          <button onClick={loadData} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" style={{ background: colors.surface1 }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
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
            className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none"
            style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>
        ) : (
          <>
            {/* PROJECTS */}
            {tab === 'projects' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Project', 'Status', 'Owner', 'Budget', 'Spent', 'Timeline', 'AI Evaluate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {projects.filter(p => !searchQ || p.name?.toLowerCase().includes(searchQ.toLowerCase())).map((p) => (
                      <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{p.name}</td>
                        <td className="px-4 py-3"><Badge status={p.status} /></td>
                        <td className="px-4 py-3">{p.owner || '-'}</td>
                        <td className="px-4 py-3 font-mono">{p.budget != null ? `$${p.budget.toLocaleString()}` : '-'}</td>
                        <td className="px-4 py-3">
                          <div className="space-y-1">
                            <div className="h-1.5 rounded-full w-20" style={{ background: colors.hairline }}>
                              <div className="h-full rounded-full" style={{ width: `${p.budget ? Math.min(100, Math.round((p.spent / p.budget) * 100)) : Math.min(100, Math.round(p.completion_pct || 0))}%`, background: p.budget && (p.spent / p.budget) > 0.9 ? '#ef4444' : '#6366f1' }} />
                            </div>
                            <span className="text-[10px] font-mono">${(p.spent || 0).toLocaleString()}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{p.start_date || '-'} → {p.end_date || '?'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Project eval', p.id, api.runOperationsProjectAgent)}
                            disabled={runningAgent === p.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#6366f115', color: '#6366f1' }}>
                            {runningAgent === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Evaluate
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {projects.length === 0 && <EmptyState icon={FolderKanban} title="No projects" sub="Operations projects appear here" />}
              </div>
            )}

            {/* RESOURCES */}
            {tab === 'resources' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Resource', 'Type', 'Project', 'Utilization', 'Available From', 'AI Check'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {resources.filter(r => !searchQ || r.name?.toLowerCase().includes(searchQ.toLowerCase())).map((r) => (
                      <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{r.name}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{r.type || '-'}</td>
                        <td className="px-4 py-3">{r.project || 'Unassigned'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 rounded-full" style={{ background: colors.hairline }}>
                              <div className="h-full rounded-full" style={{ width: `${r.utilization || 0}%`, background: (r.utilization || 0) > 90 ? '#ef4444' : (r.utilization || 0) > 70 ? '#f59e0b' : '#22c55e' }} />
                            </div>
                            <span className="font-mono text-[11px]">{r.utilization || 0}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{r.available_from || 'Now'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Resource check', r.id, api.runOperationsResourceAgent)}
                            disabled={runningAgent === r.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#22c55e15', color: '#22c55e' }}>
                            {runningAgent === r.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Check
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {resources.length === 0 && <EmptyState icon={Users2} title="No resources" sub="Resource allocations appear here" />}
              </div>
            )}

            {/* VENDORS */}
            {tab === 'vendors' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Vendor', 'Category', 'Risk Level', 'Contract Value', 'SOC2', 'Expiry', 'AI Evaluate'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {vendors.filter(v => !searchQ || v.name?.toLowerCase().includes(searchQ.toLowerCase())).map((v) => (
                      <tr key={v.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{v.name}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{v.category || '-'}</td>
                        <td className="px-4 py-3"><Badge status={v.risk_level || 'MEDIUM'} /></td>
                        <td className="px-4 py-3 font-mono">${(v.contract_value || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">
                          {v.soc2_verified
                            ? <span style={{ color: '#22c55e' }}>✓ Verified</span>
                            : <span style={{ color: '#f59e0b' }}>Pending</span>}
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{v.contract_expiry || '-'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Vendor eval', v.id, api.runOperationsVendorAgent)}
                            disabled={runningAgent === v.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                            {runningAgent === v.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Evaluate
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {vendors.length === 0 && <EmptyState icon={Building2} title="No vendors" sub="Vendor records appear here" />}
              </div>
            )}

            {/* PROCUREMENT */}
            {tab === 'procurement' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Request', 'Requestor', 'Status', 'Amount', 'Vendor', 'Submitted', 'AI Audit'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {procurements.filter(p => !searchQ || p.description?.toLowerCase().includes(searchQ.toLowerCase()) || p.requestor?.toLowerCase().includes(searchQ.toLowerCase())).map((p) => (
                      <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium max-w-[140px]"><span className="block truncate">{p.description}</span></td>
                        <td className="px-4 py-3">{p.requestor}</td>
                        <td className="px-4 py-3"><Badge status={p.status} /></td>
                        <td className="px-4 py-3 font-mono font-semibold">${(p.amount || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">{p.vendor || '-'}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(p.submitted_at)}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Procurement audit', p.id, api.runOperationsProcurementAgent)}
                            disabled={runningAgent === p.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#3b82f615', color: '#3b82f6' }}>
                            {runningAgent === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Audit
                          </button>
                          <div className="mt-1">
                            <WorkflowActions domain="operations" entityPath="purchase-requests" entityId={p.id}
                              currentState={p.status} transitions={workflows['purchase_request']?.transitions}
                              onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {procurements.length === 0 && <EmptyState icon={ShoppingCart} title="No procurement requests" sub="Purchase requests appear here" />}
              </div>
            )}

            {/* QUALITY */}
            {tab === 'quality' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Inspection', 'Area', 'Status', 'Score', 'Defects', 'Inspector', 'Date', 'AI Audit'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {inspections.filter(i => !searchQ || i.title?.toLowerCase().includes(searchQ.toLowerCase()) || i.area?.toLowerCase().includes(searchQ.toLowerCase())).map((i) => (
                      <tr key={i.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{i.title}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{i.area || '-'}</td>
                        <td className="px-4 py-3"><Badge status={i.status} /></td>
                        <td className="px-4 py-3">
                          <span className="font-bold" style={{ color: (i.score || 0) > 85 ? '#22c55e' : (i.score || 0) > 70 ? '#f59e0b' : '#ef4444' }}>
                            {i.score || 0}/100
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono" style={{ color: i.defects > 0 ? '#ef4444' : colors.inkSubtle }}>{i.defects || 0}</td>
                        <td className="px-4 py-3">{i.inspector || '-'}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{i.date || '-'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('QA audit', i.id, api.runOperationsQualityAgent)}
                            disabled={runningAgent === i.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#ef444415', color: '#ef4444' }}>
                            {runningAgent === i.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Audit
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {inspections.length === 0 && <EmptyState icon={ClipboardCheck} title="No inspections" sub="Quality inspections appear here" />}
              </div>
            )}

            {/* ANALYTICS */}
            {tab === 'analytics' && <DomainAnalytics domain="operations" />}
          </>
        )}
      </div>
    </div>
  );
};

export default OperationsView;
