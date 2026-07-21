import React, { useEffect, useState } from 'react';
import {
  Ticket, BookOpen, Clock, MessageSquare, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle, AlertTriangle
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import GateTrace from '../components/GateTrace';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';
import { fullTime, timeAgo } from '../lib/time';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

type SupportTab = 'tickets' | 'kb' | 'sla' | 'feedback' | 'analytics';

interface SupportTicket { id: string; subject: string; status: string; priority: string; customer: string | null; assignee: string | null; created_at: string | null; }
interface KBArticle { id: string; title: string; category: string | null; status: string; views: number; helpful_pct: number; updated_at: string | null; }
interface SLAMetric { id: string; policy: string; priority: string; status: string; target_hours: number; actual_hours: number; compliance_pct: number; breached_count: number; }
interface CSATSurvey { id: string; customer: string; rating: number; sentiment: string; ticket_id: string | null; comment: string; created_at: string | null; }

const SupportView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<SupportTab>(() => {
    const valid: SupportTab[] = ['tickets', 'kb', 'sla', 'feedback', 'analytics'];
    if (defaultTab && valid.includes(defaultTab as SupportTab)) return defaultTab as SupportTab;
    return 'tickets';
  });
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState<string | null>(null);

  const toggleSelected = (id: string) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Bulk actions offer only moves legal for EVERY selected ticket.
  const bulkAllowed = (() => {
    const map = workflows['ticket']?.transitions;
    if (!map || selected.size === 0) return [] as string[];
    const picked = tickets.filter(t => selected.has(t.id));
    let common: string[] | null = null;
    for (const t of picked) {
      const allowed = map[(t.status || '').toUpperCase()] || [];
      common = common === null ? allowed : common.filter(s => allowed.includes(s));
    }
    return common || [];
  })();

  const runBulk = async (state: string) => {
    setBulkBusy(state);
    try {
      const res = await api.bulkTransition('support', 'ticket', Array.from(selected), state);
      setActionMsg(`Bulk ${state.replace(/_/g, ' ')}: ${res.succeeded} succeeded${res.failed ? `, ${res.failed} failed` : ''}`);
      setSelected(new Set());
      await loadData();
    } catch (e: any) {
      setActionMsg(`Bulk transition failed: ${e?.message || e}`);
    } finally {
      setBulkBusy(null);
    }
  };
  const [kbArticles, setKbArticles] = useState<KBArticle[]>([]);
  const [slaMetrics, setSlaMetrics] = useState<SLAMetric[]>([]);
  const [surveys, setSurveys] = useState<CSATSurvey[]>([]);

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  async function loadData() {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getSupportTickets(), api.getSupportKBArticles(),
      api.getSupportSLAMetrics(), api.getSupportCSATSurveys(),
      api.getDomainWorkflows('support'),
    ]);

    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setTickets(val(0)); setKbArticles(val(1)); setSlaMetrics(val(2)); setSurveys(val(3));
    if (results[4].status === 'fulfilled') setWorkflows((results[4] as any).value || {});
    setLoading(false);
  };

   
  const runAgent = async (label: string, id: string, fn: (id: string) => Promise<any>) => {
    setRunningAgent(id); setActionMsg('');
    // The trace renders next to the row that was clicked - the old banner
    // appeared at the top of the page, often off-screen from the action.
    setTrace({ id, label, result: undefined });
    try {
      const res = await fn(id);
      setTrace({ id, label, result: res });
      await loadData();
    } catch (e: any) {
      setActionMsg(`${label} failed: ${e?.message || e}`);
      setTrace(null);
    } finally { setRunningAgent(null); }
  };

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['RESOLVED', 'CLOSED', 'PUBLISHED', 'MET', 'POSITIVE'].includes(n)) return '#22c55e';
    if (['OPEN', 'IN_PROGRESS', 'PENDING', 'DRAFT', 'AT_RISK'].includes(n)) return '#f59e0b';
    if (['P0', 'P1', 'CRITICAL', 'URGENT', 'BREACHED', 'NEGATIVE', 'ESCALATED'].includes(n)) return '#ef4444';
    if (['P2', 'P3', 'MEDIUM', 'LOW', 'NEUTRAL'].includes(n)) return '#3b82f6';
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

  const TABS: { key: SupportTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'tickets', label: 'Tickets', icon: Ticket, color: '#6366f1' },
    { key: 'kb', label: 'Knowledge Base', icon: BookOpen, color: '#22c55e' },
    { key: 'sla', label: 'SLA Monitoring', icon: Clock, color: '#f59e0b' },
    { key: 'feedback', label: 'CSAT', icon: MessageSquare, color: '#3b82f6' },
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
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Support Department</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <PlusIcon className="w-3.5 h-3.5" /> New Ticket
            </button>
            <button onClick={loadData} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
            title="New Ticket" domain="support" entityPath="tickets"
            fields={[
              { key: 'subject', label: 'Subject', type: 'text', required: true },
              { key: 'description', label: 'Description', type: 'textarea', required: true },
              { key: 'priority', label: 'Priority', type: 'select', options: ['LOW', 'MEDIUM', 'HIGH', 'URGENT'], defaultValue: 'MEDIUM' },
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
          <GateTrace
            running={runningAgent === trace.id}
            result={trace.result}
            skillLabel={trace.label}
          />
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
            {/* TICKETS */}
            {tab === 'tickets' && (
              <div className="space-y-3">
                {selected.size > 0 && (
                  <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg flex-wrap"
                    style={{ background: `${colors.primary}12`, border: `1px solid ${colors.primary}30` }}>
                    <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>
                      {selected.size} selected
                    </span>
                    {bulkAllowed.map(state => (
                      <button key={state} onClick={() => runBulk(state)} disabled={!!bulkBusy}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-semibold disabled:opacity-50"
                        style={{ background: `${colors.primary}18`, color: colors.primary }}>
                        {bulkBusy === state ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                        Move all to {state.replace(/_/g, ' ')}
                      </button>
                    ))}
                    {bulkAllowed.length === 0 && (
                      <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
                        No transition is legal for every selected ticket - narrow the selection.
                      </span>
                    )}
                    <button onClick={() => setSelected(new Set())}
                      className="ml-auto text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
                      Clear
                    </button>
                  </div>
                )}
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className="px-3 py-3 w-8">
                      <input type="checkbox" aria-label="Select all tickets"
                        checked={tickets.length > 0 && selected.size === tickets.length}
                        onChange={e => setSelected(e.target.checked ? new Set(tickets.map(t => t.id)) : new Set())} />
                    </th>
                    {['ID', 'Subject', 'Status', 'Priority', 'Customer', 'Assignee', 'Created', 'Actions'].map(h => (
                      <th key={h}
                        className={`text-left px-4 py-3 font-semibold ${h === 'Actions' ? 'sticky right-0' : ''}`}
                        style={{
                          color: colors.inkSubtle,
                          // Actions must never scroll out of reach: they were
                          // hidden behind horizontal overflow on narrow viewports.
                          ...(h === 'Actions' ? { background: colors.surface1 } : {}),
                        }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {tickets.filter(t => !searchQ || t.subject?.toLowerCase().includes(searchQ.toLowerCase()) || t.customer?.toLowerCase().includes(searchQ.toLowerCase())).map((t) => (
                      <tr key={t.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-3 py-3">
                          <input type="checkbox" aria-label={`Select ticket ${t.subject}`}
                            checked={selected.has(t.id)} onChange={() => toggleSelected(t.id)} />
                        </td>
                        <td className="px-4 py-3 font-mono text-[10px]">#{t.id?.toString().slice(-6)}</td>
                        <td className="px-4 py-3 font-medium max-w-[160px]"><span className="block truncate">{t.subject}</span></td>
                        <td className="px-4 py-3"><Badge status={t.status} /></td>
                        <td className="px-4 py-3"><Badge status={t.priority} /></td>
                        <td className="px-4 py-3">{t.customer || '-'}</td>
                        <td className="px-4 py-3">{t.assignee || 'Unassigned'}</td>
                        <td className="px-4 py-3 whitespace-nowrap" style={{ color: colors.inkSubtle }}
                          title={fullTime(t.created_at)}>
                          {timeAgo(t.created_at)}
                        </td>
                        <td className="px-4 py-3 sticky right-0" style={{ background: colors.surface1 }}>
                          <div className="flex gap-1">
                            <button onClick={() => runAgent('Triage', `${t.id}-triage`, () => api.runSupportTriageAgent(t.id))}
                              disabled={!!runningAgent}
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                              style={{ background: '#6366f115', color: '#6366f1' }}>
                              {runningAgent === `${t.id}-triage` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />} Triage
                            </button>
                            <button onClick={() => runAgent('Escalate', `${t.id}-escalate`, () => api.runSupportEscalationAgent(t.id))}
                              disabled={!!runningAgent}
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                              style={{ background: '#ef444415', color: '#ef4444' }}>
                              {runningAgent === `${t.id}-escalate` ? <Loader2 className="w-3 h-3 animate-spin" /> : <AlertTriangle className="w-3 h-3" />} Escalate
                            </button>
                            <WorkflowActions domain="support" entityPath="tickets" entityId={t.id}
                              currentState={t.status} transitions={workflows['ticket']?.transitions}
                              onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {tickets.length === 0 && <EmptyState icon={Ticket} title="No tickets" sub="Support tickets appear here" />}
              </div>
              </div>
            )}

            {/* KNOWLEDGE BASE */}
            {tab === 'kb' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Title', 'Category', 'Status', 'Views', 'Helpful %', 'Updated'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    { }
            {kbArticles.filter(a => !searchQ || a.title?.toLowerCase().includes(searchQ.toLowerCase())).map((a: any) => (
                      <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{a.title}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{a.category || '-'}</td>
                        <td className="px-4 py-3"><Badge status={a.status} /></td>
                        <td className="px-4 py-3 font-mono">{(a.views || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <span style={{ color: (a.helpful_pct || 0) > 80 ? '#22c55e' : (a.helpful_pct || 0) > 60 ? '#f59e0b' : '#ef4444' }}>
                            {a.helpful_pct || 0}%
                          </span>
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(a.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {kbArticles.length === 0 && <EmptyState icon={BookOpen} title="No articles" sub="Knowledge base articles appear here" />}
              </div>
            )}

            {/* SLA */}
            {tab === 'sla' && (
              <div className="space-y-4">
                <div className="flex justify-end">
                  <button onClick={() => runAgent('SLA check', 'global', () => api.runSupportSLACheck())}
                    disabled={!!runningAgent}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50"
                    style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                    {runningAgent ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bot className="w-4 h-4" />}
                    Run SLA Check
                  </button>
                </div>
                <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <table className="w-full text-[12px]">
                    <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                      {['Policy', 'Priority', 'Status', 'Target (hrs)', 'Actual (hrs)', 'Compliance', 'Breached Count'].map(h => (
                        <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {slaMetrics.filter(m => !searchQ || m.policy?.toLowerCase().includes(searchQ.toLowerCase())).map((m: any, i: number) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium">{m.policy}</td>
                          <td className="px-4 py-3"><Badge status={m.priority} /></td>
                          <td className="px-4 py-3"><Badge status={m.status} /></td>
                          <td className="px-4 py-3 font-mono">{m.target_hours}</td>
                          <td className="px-4 py-3 font-mono">{m.actual_hours?.toFixed(1) || '-'}</td>
                          <td className="px-4 py-3">
                            <span className="font-bold" style={{ color: (m.compliance_pct || 0) > 90 ? '#22c55e' : (m.compliance_pct || 0) > 75 ? '#f59e0b' : '#ef4444' }}>
                              {m.compliance_pct || 0}%
                            </span>
                          </td>
                          <td className="px-4 py-3 font-mono" style={{ color: m.breached_count > 0 ? '#ef4444' : colors.inkSubtle }}>{m.breached_count || 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {slaMetrics.length === 0 && <EmptyState icon={Clock} title="No SLA metrics" sub="SLA metrics appear here" />}
                </div>
              </div>
            )}

            {/* CSAT / FEEDBACK */}
            {tab === 'feedback' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Customer', 'Rating', 'Sentiment', 'Ticket Ref', 'Comment', 'Date', 'AI Analyze'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {surveys.filter(s => !searchQ || s.customer?.toLowerCase().includes(searchQ.toLowerCase())).map((s) => (
                      <tr key={s.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">{s.customer}</td>
                        <td className="px-4 py-3">
                          <div className="flex">
                            {[1,2,3,4,5].map(r => (
                              <span key={r} className="text-[14px]">{(s.rating || 0) >= r ? '★' : '☆'}</span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3"><Badge status={s.sentiment} /></td>
                        <td className="px-4 py-3 font-mono text-[10px]">{s.ticket_id ? `#${s.ticket_id.toString().slice(-6)}` : '-'}</td>
                        <td className="px-4 py-3 max-w-[160px]"><span className="block truncate" style={{ color: colors.inkSubtle }}>{s.comment || '-'}</span></td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(s.created_at)}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Feedback analysis', s.id, api.runSupportFeedbackAgent)}
                            disabled={runningAgent === s.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#3b82f615', color: '#3b82f6' }}>
                            {runningAgent === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Analyze
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {surveys.length === 0 && <EmptyState icon={MessageSquare} title="No feedback" sub="CSAT surveys appear here" />}
              </div>
            )}

            {/* ANALYTICS */}
            {tab === 'analytics' && <DomainAnalytics domain="support" />}
          </>
        )}
      </div>
    </div>
  );
};

export default SupportView;
