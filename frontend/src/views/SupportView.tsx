import React, { useEffect, useState } from 'react';
import {
  Ticket, BookOpen, Clock, MessageSquare, BarChart3,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle, AlertTriangle,
  Wand2, FilePlus2, Star, ChevronDown, ChevronUp, Users, Sparkles,
  Eye, EyeOff, ArrowUpRight, Smile, Meh, Frown,
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import {
  supportApi,
  type TicketCommentRow, type TicketTagRow, type ArticleFeedbackRow,
} from '../api/endpoints/support';
import { useTheme } from '../context/ThemeContext';
import { humanize, measured, NOT_MEASURED } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import EmptyState from '../components/shared/EmptyState';
import GateTrace from '../components/GateTrace';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import BulkActionBar from '../components/BulkActionBar';
import { CountUp } from '../components/CountUp';
import { useBulkSelect } from '../hooks/useBulkSelect';
import { Plus as PlusIcon } from 'lucide-react';
import { fullTime, timeAgo } from '../lib/time';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { useTabParam } from '../hooks/useTabParam';

type SupportTab = 'tickets' | 'kb' | 'sla' | 'feedback' | 'team' | 'analytics';

interface SupportTicket { id: string; subject: string; status: string; priority: string; customer: string | null; assignee: string | null; created_at: string | null; }
interface KBArticleRow { id: string; title: string; category: string | null; status: string; views: number; helpful_pct: number; updated_at: string | null; }
interface SLAMetricRow {
  id: string; policy: string; priority: string; status: string;
  target_hours: number; actual_hours: number | null;
  compliance_pct: number | null; breached_count: number | null; note?: string;
}
interface CSATSurvey { id: string; customer: string; rating: number; sentiment: string; ticket_id: string | null; comment: string; created_at: string | null; }

const statusColor = (s: string, colors: ReturnType<typeof useTheme>['colors']) => {
  const n = (s || '').toUpperCase();
  if (['RESOLVED', 'CLOSED', 'PUBLISHED', 'MET', 'POSITIVE', 'ACTIVE'].includes(n)) return '#22c55e';
  if (['OPEN', 'IN_PROGRESS', 'PENDING', 'DRAFT', 'AT_RISK'].includes(n)) return '#f59e0b';
  if (['P0', 'P1', 'CRITICAL', 'URGENT', 'BREACHED', 'NEGATIVE', 'ESCALATED', 'NO_DATA'].includes(n)) return '#ef4444';
  if (['P2', 'P3', 'MEDIUM', 'LOW', 'NEUTRAL'].includes(n)) return '#3b82f6';
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

const SupportView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useTabParam<SupportTab>(
    ['tickets', 'kb', 'sla', 'feedback', 'team', 'analytics'], 'tickets', defaultTab);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);

  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const bulk = useBulkSelect(tickets, workflows['ticket'], t => t.status);
  const [kbArticles, setKbArticles] = useState<KBArticleRow[]>([]);
  const [slaMetrics, setSlaMetrics] = useState<SLAMetricRow[]>([]);
  const [surveys, setSurveys] = useState<CSATSurvey[]>([]);

  // Team tab data
  const [teams, setTeams] = useState<Awaited<ReturnType<typeof supportApi.getSupportTeams>>>([]);
  const [channels, setChannels] = useState<Awaited<ReturnType<typeof supportApi.getSupportChannels>>>([]);
  const [leaderboard, setLeaderboard] = useState<Awaited<ReturnType<typeof supportApi.getSupportAgentLeaderboard>>>([]);
  const [escalationRules, setEscalationRules] = useState<Awaited<ReturnType<typeof supportApi.getEscalationRules>>>([]);
  const [escalationEvents, setEscalationEvents] = useState<Awaited<ReturnType<typeof supportApi.getEscalationEvents>>>([]);

  // Feedback tab extras
  const [npsSurveys, setNpsSurveys] = useState<Awaited<ReturnType<typeof supportApi.getNPSSurveys>>>([]);
  const [feedbackThemes, setFeedbackThemes] = useState<Awaited<ReturnType<typeof supportApi.getFeedbackThemes>>>([]);

  // "Document" writes an unpublished KB draft rather than running the gates,
  // so its result gets its own card instead of a gate trace.
  const [draft, setDraft] = useState<{ ticket: string; result: any } | null>(null);
  // ResolutionAgent's KB-match result - a direct agent answer, not a gate trace.
  const [kbMatch, setKbMatch] = useState<{ ticket: string; result: any } | null>(null);

  // Ticket conversation thread (TicketComment/TicketTag) - expand-on-click,
  // fetched once per ticket and cached.
  const [expandedTicketId, setExpandedTicketId] = useState<string | null>(null);
  const [threadLoading, setThreadLoading] = useState<string | null>(null);
  const [ticketThreads, setTicketThreads] = useState<Record<string, { comments: TicketCommentRow[]; tags: TicketTagRow[] }>>({});

  // KB article feedback (ArticleFeedback) - same expand-on-click pattern.
  const [expandedArticleId, setExpandedArticleId] = useState<string | null>(null);
  const [feedbackLoading, setFeedbackLoading] = useState<string | null>(null);
  const [articleFeedback, setArticleFeedback] = useState<Record<string, ArticleFeedbackRow[]>>({});
  const [kbBusy, setKbBusy] = useState<string | null>(null);

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
      supportApi.getSupportTeams(), supportApi.getSupportChannels(),
      supportApi.getSupportAgentLeaderboard(),
      supportApi.getEscalationRules(), supportApi.getEscalationEvents(),
      supportApi.getNPSSurveys(), supportApi.getFeedbackThemes(),
    ]);

    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setTickets(val(0)); setKbArticles(val(1)); setSlaMetrics(val(2)); setSurveys(val(3));
    if (results[4].status === 'fulfilled') setWorkflows((results[4] as any).value || {});
    setTeams(val(5)); setChannels(val(6)); setLeaderboard(val(7));
    setEscalationRules(val(8)); setEscalationEvents(val(9));
    setNpsSurveys(val(10)); setFeedbackThemes(val(11));
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

  const documentTicket = async (t: SupportTicket) => {
    setRunningAgent(`${t.id}-document`);
    setActionMsg('');
    setDraft(null);
    try {
      const res = await api.runSupportDocumentAgent(t.id);
      setDraft({ ticket: t.subject, result: res });
      await loadData();
    } catch (e: any) {
      setActionMsg(`Documenting failed: ${e?.message || e}`);
    } finally {
      setRunningAgent(null);
    }
  };

  // ResolutionAgent: matches published KB articles against the ticket and
  // drafts a reply - a real, DB+LLM-backed capability that had no UI caller.
  const resolveViaKB = async (t: SupportTicket) => {
    setRunningAgent(`${t.id}-kbmatch`);
    setActionMsg('');
    setKbMatch(null);
    try {
      const res = await api.runSupportResolutionAgent(t.id);
      setKbMatch({ ticket: t.subject, result: res });
      await loadData();
    } catch (e: any) {
      setActionMsg(`KB match failed: ${e?.message || e}`);
    } finally {
      setRunningAgent(null);
    }
  };

  const toggleThread = async (ticketId: string) => {
    if (expandedTicketId === ticketId) { setExpandedTicketId(null); return; }
    setExpandedTicketId(ticketId);
    if (ticketThreads[ticketId]) return;
    setThreadLoading(ticketId);
    try {
      const [comments, tags] = await Promise.all([
        supportApi.getTicketComments(ticketId), supportApi.getTicketTags(ticketId),
      ]);
      setTicketThreads(prev => ({ ...prev, [ticketId]: { comments, tags } }));
    } catch {
      setTicketThreads(prev => ({ ...prev, [ticketId]: { comments: [], tags: [] } }));
    } finally {
      setThreadLoading(null);
    }
  };

  const toggleArticleFeedback = async (articleId: string) => {
    if (expandedArticleId === articleId) { setExpandedArticleId(null); return; }
    setExpandedArticleId(articleId);
    if (articleFeedback[articleId]) return;
    setFeedbackLoading(articleId);
    try {
      const rows = await supportApi.getKBArticleFeedback(articleId);
      setArticleFeedback(prev => ({ ...prev, [articleId]: rows }));
    } catch {
      setArticleFeedback(prev => ({ ...prev, [articleId]: [] }));
    } finally {
      setFeedbackLoading(null);
    }
  };

  const toggleKbPublish = async (a: KBArticleRow) => {
    setKbBusy(a.id);
    setActionMsg('');
    try {
      const res = a.status === 'PUBLISHED'
        ? await supportApi.unpublishKBArticle(a.id)
        : await supportApi.publishKBArticle(a.id);
      setActionMsg(`"${a.title}" is now ${humanize(res.status)}.`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Publish toggle failed: ${e?.message || e}`);
    } finally {
      setKbBusy(null);
    }
  };

  const npsIcon = (score: number) => score >= 9 ? Smile : score >= 7 ? Meh : Frown;
  const npsColor = (score: number) => score >= 9 ? '#22c55e' : score >= 7 ? '#f59e0b' : '#ef4444';

  const TABS: { key: SupportTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'tickets', label: 'Tickets', icon: Ticket, color: '#6366f1' },
    { key: 'kb', label: 'Knowledge Base', icon: BookOpen, color: '#22c55e' },
    { key: 'sla', label: 'SLA Monitoring', icon: Clock, color: '#f59e0b' },
    { key: 'feedback', label: 'CSAT', icon: MessageSquare, color: '#3b82f6' },
    { key: 'team', label: 'Team', icon: Users, color: '#14b8a6' },
    { key: 'analytics', label: 'Analytics', icon: BarChart3, color: '#a855f7' },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  // ArrowLeft/ArrowRight move between tabs, as a tablist is expected to.
  const onTabKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    const i = TABS.findIndex(t => t.key === tab);
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length].key;
    setTab(next);
    document.getElementById(`support-tab-${next}`)?.focus();
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
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Support Department</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <PlusIcon className="w-3.5 h-3.5" /> New Ticket
            </button>
            <button onClick={loadData} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}
              aria-label="Refresh support data" title="Refresh">
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

        <div className="flex gap-1 p-1 rounded-xl flex-wrap" style={{ background: colors.surface1 }}
          role="tablist" aria-label="Support sections" onKeyDown={onTabKey}>
          {TABS.map(t => (
            <button key={t.key} id={`support-tab-${t.key}`} role="tab" aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
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
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60">dismiss</button>
          </div>
        )}

        {trace && (
          <GateTrace
            running={runningAgent === trace.id}
            result={trace.result}
            skillLabel={trace.label}
          />
        )}

        {/* Knowledge base draft written from a ticket */}
        {draft && (
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-2">
              <FilePlus2 className="w-4 h-4" style={{ color: '#8b5cf6' }} />
              <span className="text-[13px] font-semibold">
                {draft.result?.article_title || 'Knowledge base draft'}
              </span>
              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                style={{ background: '#f59e0b20', color: '#f59e0b' }}>Unpublished draft</span>
              <button onClick={() => setDraft(null)} className="ml-auto text-[11px] opacity-60">dismiss</button>
            </div>
            <p className="text-[11px] mb-2" style={{ color: colors.inkTertiary }}>
              Written from "{draft.ticket}". It is saved as a draft in the Knowledge Base tab - open it there and click Publish when it is ready for customers.
            </p>
            {(draft.result?.categories || []).length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {(draft.result.categories as string[]).map(c => (
                  <span key={c} className="text-[11px] px-2 py-0.5 rounded-full"
                    style={{ background: colors.canvas, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>{c}</span>
                ))}
              </div>
            )}
            {draft.result?.content_markdown ? (
              <div className="text-[12px] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"
                style={{ color: colors.inkSubtle }}>
                {draft.result.content_markdown}
              </div>
            ) : (
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>The draft came back empty. Try again once the ticket has a resolution recorded.</p>
            )}
          </div>
        )}

        {/* Resolution agent's knowledge-base match */}
        {kbMatch && (
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-4 h-4" style={{ color: '#22c55e' }} />
              <span className="text-[13px] font-semibold">Resolve via KB match</span>
              {kbMatch.result?.resolved ? (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: '#22c55e20', color: '#22c55e' }}>
                  {Math.round((kbMatch.result?.confidence || 0) * 100)}% confidence
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: '#f59e0b20', color: '#f59e0b' }}>No match found</span>
              )}
              <button onClick={() => setKbMatch(null)} className="ml-auto text-[11px] opacity-60">dismiss</button>
            </div>
            <p className="text-[11px] mb-2" style={{ color: colors.inkTertiary }}>
              Ran against "{kbMatch.ticket}". {kbMatch.result?.article_matched && kbMatch.result.article_matched !== 'None'
                ? `Matched knowledge base article: "${kbMatch.result.article_matched}". `
                : 'No published article matched closely enough. '}
              {(kbMatch.result?.confidence || 0) > 0.85
                ? 'Confidence cleared the auto-resolve bar, so the ticket was marked resolved.'
                : 'Confidence did not clear the auto-resolve bar, so the ticket stays open for a human to confirm.'}
            </p>
            {kbMatch.result?.draft_reply && (
              <div className="text-[12px] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"
                style={{ color: colors.inkSubtle }}>
                {kbMatch.result.draft_reply}
              </div>
            )}
          </div>
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
                <BulkActionBar domain="support" entityType="ticket" noun="ticket"
                  ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className="px-3 py-3 w-8">
                      <input type="checkbox" aria-label="Select all tickets"
                        checked={bulk.allSelected}
                        onChange={e => bulk.setAll(e.target.checked)} />
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
                      <React.Fragment key={t.id}>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-3 py-3">
                          <input type="checkbox" aria-label={`Select ticket ${t.subject}`}
                            checked={bulk.isSelected(t.id)} onChange={() => bulk.toggle(t.id)} />
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px]">
                          <button onClick={() => toggleThread(t.id)}
                            className="flex items-center gap-1" style={{ color: colors.inkSubtle }}
                            title="View conversation thread">
                            {expandedTicketId === t.id ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            #{t.id?.toString().slice(-6)}
                          </button>
                        </td>
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
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#6366f115', color: '#6366f1' }}>
                              {runningAgent === `${t.id}-triage` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />} Triage
                            </button>
                            <button onClick={() => runAgent('Auto-resolve', `${t.id}-resolve`, () => api.runSupportAutoResolveAgent(t.id))}
                              disabled={!!runningAgent}
                              title="Draft and apply a full resolution. Customer-facing replies always stop for a human first."
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#22c55e15', color: '#22c55e' }}>
                              {runningAgent === `${t.id}-resolve` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />} Resolve
                            </button>
                            <button onClick={() => resolveViaKB(t)}
                              disabled={!!runningAgent}
                              title="Match this ticket against published knowledge base articles and draft a reply from the closest one."
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#0ea5e915', color: '#0ea5e9' }}>
                              {runningAgent === `${t.id}-kbmatch` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} KB Match
                            </button>
                            <button onClick={() => documentTicket(t)}
                              disabled={!!runningAgent}
                              title="Turn this ticket into a knowledge base draft so the next person does not have to ask"
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                              {runningAgent === `${t.id}-document` ? <Loader2 className="w-3 h-3 animate-spin" /> : <FilePlus2 className="w-3 h-3" />} Document
                            </button>
                            <button onClick={() => runAgent('Escalate', `${t.id}-escalate`, () => api.runSupportEscalationAgent(t.id))}
                              disabled={!!runningAgent}
                              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                              style={{ background: '#ef444415', color: '#ef4444' }}>
                              {runningAgent === `${t.id}-escalate` ? <Loader2 className="w-3 h-3 animate-spin" /> : <AlertTriangle className="w-3 h-3" />} Escalate
                            </button>
                            <WorkflowActions domain="support" entityPath="tickets" entityId={t.id}
                              currentState={t.status} transitions={workflows['ticket']?.transitions}
                              onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                          </div>
                        </td>
                      </tr>
                      {expandedTicketId === t.id && (
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td colSpan={9} className="px-4 py-3" style={{ background: colors.canvas }}>
                            {threadLoading === t.id ? (
                              <div className="flex items-center gap-2 text-[11px] py-2" style={{ color: colors.inkSubtle }}>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading conversation…
                              </div>
                            ) : (
                              <div className="space-y-2.5">
                                {(ticketThreads[t.id]?.tags.length ?? 0) > 0 && (
                                  <div className="flex flex-wrap gap-1.5">
                                    {ticketThreads[t.id]!.tags.map(tg => (
                                      <span key={tg.id} className="text-[11px] px-2 py-0.5 rounded-full"
                                        style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                                        {humanize(tg.tag)}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
                                  Conversation thread
                                </p>
                                {(ticketThreads[t.id]?.comments.length ?? 0) === 0 ? (
                                  <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No messages recorded on this ticket yet.</p>
                                ) : (
                                  <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                                    {ticketThreads[t.id]!.comments.map(c => (
                                      <div key={c.id} className="rounded-lg p-2.5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                                        <div className="flex items-center gap-2 text-[11px] mb-1 flex-wrap">
                                          <span className="font-semibold" style={{ color: colors.ink }}>{c.author}</span>
                                          <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold"
                                            style={{
                                              background: c.author_type === 'CUSTOMER' ? '#3b82f615' : c.author_type === 'AGENT' ? '#22c55e15' : colors.surface2,
                                              color: c.author_type === 'CUSTOMER' ? '#3b82f6' : c.author_type === 'AGENT' ? '#22c55e' : colors.inkSubtle,
                                            }}>{humanize(c.author_type)}</span>
                                          {c.is_internal && (
                                            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold" style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                                              Internal note
                                            </span>
                                          )}
                                          <span className="ml-auto" style={{ color: colors.inkTertiary }} title={fullTime(c.created_at)}>
                                            {timeAgo(c.created_at)}
                                          </span>
                                        </div>
                                        <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{c.body}</p>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                      </React.Fragment>
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
                    {['Title', 'Category', 'Status', 'Views', 'Helpful %', 'Updated', 'Actions'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    { }
            {kbArticles.filter(a => !searchQ || a.title?.toLowerCase().includes(searchQ.toLowerCase())).map((a) => (
                      <React.Fragment key={a.id}>
                      <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                        <td className="px-4 py-3 font-medium">
                          <button onClick={() => toggleArticleFeedback(a.id)} className="flex items-center gap-1 text-left"
                            style={{ color: colors.ink }} title="View reader feedback">
                            {expandedArticleId === a.id ? <ChevronUp className="w-3 h-3 shrink-0" style={{ color: colors.inkSubtle }} /> : <ChevronDown className="w-3 h-3 shrink-0" style={{ color: colors.inkSubtle }} />}
                            {a.title}
                          </button>
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{humanize(a.category) || '-'}</td>
                        <td className="px-4 py-3"><Badge status={a.status} /></td>
                        <td className="px-4 py-3 font-mono">{(a.views || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <span style={{ color: (a.helpful_pct || 0) > 80 ? '#22c55e' : (a.helpful_pct || 0) > 60 ? '#f59e0b' : '#ef4444' }}>
                            {a.helpful_pct || 0}%
                          </span>
                        </td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(a.updated_at)}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => toggleKbPublish(a)}
                            disabled={kbBusy === a.id}
                            title={a.status === 'PUBLISHED' ? 'Unpublish - hide this article from customers' : 'Publish - put this article in front of customers'}
                            className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                            style={a.status === 'PUBLISHED'
                              ? { background: '#f59e0b15', color: '#f59e0b' }
                              : { background: '#22c55e15', color: '#22c55e' }}>
                            {kbBusy === a.id ? <Loader2 className="w-3 h-3 animate-spin" />
                              : a.status === 'PUBLISHED' ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                            {a.status === 'PUBLISHED' ? 'Unpublish' : 'Publish'}
                          </button>
                        </td>
                      </tr>
                      {expandedArticleId === a.id && (
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td colSpan={7} className="px-4 py-3" style={{ background: colors.canvas }}>
                            {feedbackLoading === a.id ? (
                              <div className="flex items-center gap-2 text-[11px] py-2" style={{ color: colors.inkSubtle }}>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading feedback…
                              </div>
                            ) : (articleFeedback[a.id]?.length ?? 0) === 0 ? (
                              <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No reader feedback recorded on this article yet.</p>
                            ) : (
                              <div className="space-y-1.5">
                                {articleFeedback[a.id]!.map(f => (
                                  <div key={f.id} className="flex items-start gap-2 text-[12px]">
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold shrink-0"
                                      style={{ background: f.is_helpful ? '#22c55e15' : '#ef444415', color: f.is_helpful ? '#22c55e' : '#ef4444' }}>
                                      {f.is_helpful ? 'Helpful' : 'Not helpful'}
                                    </span>
                                    <span style={{ color: colors.inkSubtle }}>{f.comment || '(no comment)'}</span>
                                    <span className="ml-auto shrink-0" style={{ color: colors.inkTertiary }}>{timeAgo(f.created_at)}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                      </React.Fragment>
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
                      {slaMetrics.filter(m => !searchQ || m.policy?.toLowerCase().includes(searchQ.toLowerCase())).map((m, i: number) => (
                        <tr key={m.id || i} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          <td className="px-4 py-3 font-medium" title={m.note}>{m.policy}</td>
                          <td className="px-4 py-3"><Badge status={m.priority} /></td>
                          <td className="px-4 py-3"><Badge status={m.status} /></td>
                          <td className="px-4 py-3 font-mono">{m.target_hours}</td>
                          <td className="px-4 py-3 font-mono">{measured(m.actual_hours, v => v.toFixed(2))}</td>
                          <td className="px-4 py-3">
                            {m.compliance_pct == null ? (
                              <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{NOT_MEASURED}</span>
                            ) : (
                              <span className="font-bold" style={{ color: m.compliance_pct > 90 ? '#22c55e' : m.compliance_pct > 75 ? '#f59e0b' : '#ef4444' }}>
                                {m.compliance_pct}%
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 font-mono" style={{ color: (m.breached_count || 0) > 0 ? '#ef4444' : colors.inkSubtle }}>
                            {m.breached_count == null ? '-' : m.breached_count}
                          </td>
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
              <div className="space-y-5">
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
                            <div className="flex items-center gap-0.5" title={`${s.rating || 0} of 5`}>
                              {[1,2,3,4,5].map(r => {
                                const filled = (s.rating || 0) >= r;
                                return (
                                  <Star key={r} className="w-3.5 h-3.5"
                                    style={{ color: '#f59e0b' }}
                                    fill={filled ? '#f59e0b' : 'none'} />
                                );
                              })}
                            </div>
                          </td>
                          <td className="px-4 py-3"><Badge status={s.sentiment} /></td>
                          <td className="px-4 py-3 font-mono text-[11px]">{s.ticket_id ? `#${s.ticket_id.toString().slice(-6)}` : '-'}</td>
                          <td className="px-4 py-3 max-w-[160px]"><span className="block truncate" style={{ color: colors.inkSubtle }}>{s.comment || '-'}</span></td>
                          <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{timeAgo(s.created_at)}</td>
                          <td className="px-4 py-3">
                            <button onClick={() => runAgent('Feedback analysis', s.id, api.runSupportFeedbackAgent)}
                              disabled={runningAgent === s.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
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

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold mb-3" style={{ color: colors.ink }}>Net Promoter Score</h3>
                    {npsSurveys.length === 0 ? (
                      <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No NPS surveys recorded yet.</p>
                    ) : (
                      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                        {npsSurveys.map(n => {
                          const Icon = npsIcon(n.score);
                          return (
                            <div key={n.id} className="flex items-start gap-2.5 text-[12px]">
                              <Icon className="w-4 h-4 mt-0.5 shrink-0" style={{ color: npsColor(n.score) }} />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium" style={{ color: colors.ink }}>{n.customer}</span>
                                  <span className="font-bold ml-auto" style={{ color: npsColor(n.score) }}>{n.score}/10</span>
                                </div>
                                {n.feedback_text && <p className="truncate" style={{ color: colors.inkSubtle }}>{n.feedback_text}</p>}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold mb-3" style={{ color: colors.ink }}>Feedback Themes</h3>
                    {feedbackThemes.length === 0 ? (
                      <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No recurring themes identified yet.</p>
                    ) : (
                      <div className="space-y-2.5">
                        {feedbackThemes.map(th => (
                          <div key={th.id}>
                            <div className="flex items-center gap-2 text-[12px] mb-1">
                              <span className="flex-1 truncate" style={{ color: colors.ink }}>{th.theme}</span>
                              <Badge status={th.severity} />
                              <span className="font-mono w-10 text-right" style={{ color: colors.inkSubtle }}>
                                {th.volume_pct == null ? '-' : `${th.volume_pct}%`}
                              </span>
                            </div>
                            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: colors.canvas }}>
                              <div className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${th.volume_pct || 0}%`, background: statusColor(th.severity, colors) }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* TEAM */}
            {tab === 'team' && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold px-4 pt-4 pb-2" style={{ color: colors.ink }}>Support Teams</h3>
                    {teams.length === 0 ? <div className="px-4 pb-4"><EmptyState icon={Users} title="No teams" sub="Support teams appear here" /></div> : (
                      <table className="w-full text-[12px]">
                        <tbody>
                          {teams.map(t => (
                            <tr key={t.id} style={{ borderTop: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-2.5">
                                <p className="font-medium" style={{ color: colors.ink }}>{t.name}</p>
                                {t.description && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>{t.description}</p>}
                              </td>
                              <td className="px-4 py-2.5 text-right whitespace-nowrap" style={{ color: colors.inkSubtle }}>Tier {t.tier}</td>
                              <td className="px-4 py-2.5 text-right whitespace-nowrap font-mono" style={{ color: colors.ink }}>
                                <CountUp value={t.agent_count} /> agents
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>

                  <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold px-4 pt-4 pb-2" style={{ color: colors.ink }}>Channels</h3>
                    {channels.length === 0 ? <div className="px-4 pb-4"><EmptyState icon={MessageSquare} title="No channels" sub="Ingress channels appear here" /></div> : (
                      <table className="w-full text-[12px]">
                        <tbody>
                          {channels.map(c => (
                            <tr key={c.id} style={{ borderTop: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-2.5 font-medium" style={{ color: colors.ink }}>{c.name}</td>
                              <td className="px-4 py-2.5"><Badge status={c.type} /></td>
                              <td className="px-4 py-2.5" style={{ color: colors.inkSubtle }}>{c.routing_team || 'Unrouted'}</td>
                              <td className="px-4 py-2.5 text-right">
                                <Badge status={c.is_active ? 'ACTIVE' : 'INACTIVE'} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>

                <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <h3 className="text-[12px] font-semibold px-4 pt-4 pb-2" style={{ color: colors.ink }}>Agent CSAT Leaderboard</h3>
                  {leaderboard.length === 0 ? <div className="px-4 pb-4"><EmptyState icon={Star} title="No agents" sub="Agent performance appears here" /></div> : (
                    <table className="w-full text-[12px]">
                      <thead><tr style={{ borderTop: `1px solid ${colors.hairline}`, borderBottom: `1px solid ${colors.hairline}` }}>
                        {['Agent', 'Team', 'Tickets Handled', 'Surveys', 'Avg CSAT'].map(h => (
                          <th key={h} className="text-left px-4 py-2.5 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                        ))}
                      </tr></thead>
                      <tbody>
                        {leaderboard.map(a => (
                          <tr key={a.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-2.5 font-medium flex items-center gap-1.5" style={{ color: colors.ink }}>
                              {a.name}
                              {a.is_ai && <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold" style={{ background: '#6366f115', color: '#6366f1' }}>AI</span>}
                            </td>
                            <td className="px-4 py-2.5" style={{ color: colors.inkSubtle }}>{a.team || '-'}</td>
                            <td className="px-4 py-2.5 font-mono"><CountUp value={a.ticket_count} /></td>
                            <td className="px-4 py-2.5 font-mono" style={{ color: colors.inkSubtle }}>{a.survey_count}</td>
                            <td className="px-4 py-2.5">
                              {a.avg_csat == null ? (
                                <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{NOT_MEASURED}</span>
                              ) : (
                                <span className="flex items-center gap-1 font-bold" style={{ color: a.avg_csat >= 4 ? '#22c55e' : a.avg_csat >= 3 ? '#f59e0b' : '#ef4444' }}>
                                  <Star className="w-3 h-3" fill="currentColor" />
                                  <CountUp value={a.avg_csat} decimals={2} />
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold px-4 pt-4 pb-2" style={{ color: colors.ink }}>Escalation Rules</h3>
                    {escalationRules.length === 0 ? <div className="px-4 pb-4"><EmptyState icon={ArrowUpRight} title="No rules" sub="Escalation policy appears here" /></div> : (
                      <table className="w-full text-[12px]">
                        <tbody>
                          {escalationRules.map(r => (
                            <tr key={r.id} style={{ borderTop: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-2.5">
                                <p className="font-medium" style={{ color: colors.ink }}>{r.name}</p>
                                <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
                                  {humanize(r.trigger)} within {r.time_threshold_mins}m &rarr; {r.escalate_to_team || r.escalate_to_agent || 'unassigned'}
                                </p>
                              </td>
                              <td className="px-4 py-2.5 text-right"><Badge status={r.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>

                  <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <h3 className="text-[12px] font-semibold px-4 pt-4 pb-2" style={{ color: colors.ink }}>Recent Escalations</h3>
                    {escalationEvents.length === 0 ? <div className="px-4 pb-4"><EmptyState icon={AlertTriangle} title="No escalations" sub="Escalation events appear here" /></div> : (
                      <div className="divide-y" style={{ borderColor: colors.hairline }}>
                        {escalationEvents.map(e => (
                          <div key={e.id} className="px-4 py-2.5 text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                            <div className="flex items-center gap-2">
                              <span className="font-medium truncate" style={{ color: colors.ink }}>{e.ticket_subject || 'Ticket'}</span>
                              <span className="ml-auto shrink-0" style={{ color: colors.inkTertiary }}>{timeAgo(e.created_at)}</span>
                            </div>
                            <p style={{ color: colors.inkSubtle }}>
                              {e.from_agent || 'Unassigned'} <ArrowUpRight className="w-3 h-3 inline mx-0.5" /> {e.to_agent || 'Unassigned'}
                              {e.rule ? ` · ${e.rule}` : ''}
                            </p>
                            {e.reason && <p className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>{e.reason}</p>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
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
