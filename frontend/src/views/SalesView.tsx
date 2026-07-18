import React, { useEffect, useState } from 'react';
import {
  TrendingUp, Users, BarChart2, Briefcase,
  Search, RefreshCw, Loader2, Bot, CheckCircle2, XCircle, Star
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { timeAgo } from '../lib/time';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

type SalesTab = 'opportunities' | 'leads' | 'forecasts' | 'accounts';

interface Opportunity { id: string; name: string; account: string | null; stage: string; value: number; close_date: string | null; win_probability: number; next_step: string | null; }
interface Lead { id: string; name: string; company: string; email: string; source: string; status: string; score: number; }
interface Forecast { id: string; period: string; rep: string | null; committed: number; best_case: number; pipeline: number; quota: number; }
interface SalesAccount { id: string; name: string; industry: string; arr: number; health: string; owner: string | null; last_activity: string | null; }

const SalesView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<SalesTab>(() => {
    const valid: SalesTab[] = ['opportunities', 'leads', 'forecasts', 'accounts'];
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
    ]);
    const val = (i: number) => results[i].status === 'fulfilled' ? (results[i] as any).value || [] : [];
    setOpportunities(val(0)); setLeads(val(1)); setForecasts(val(2)); setAccounts(val(3));
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
    if (['WON', 'ACTIVE', 'QUALIFIED', 'HOT', 'CLOSED_WON', 'HEALTHY'].includes(n)) return '#22c55e';
    if (['PROPOSAL', 'NEGOTIATION', 'IN_PROGRESS', 'WARM', 'DEMO', 'DISCOVERY'].includes(n)) return '#f59e0b';
    if (['LOST', 'CHURNED', 'COLD', 'CLOSED_LOST', 'AT_RISK'].includes(n)) return '#ef4444';
    if (['PROSPECTING', 'NEW', 'PENDING'].includes(n)) return '#3b82f6';
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

  const TABS: { key: SalesTab; label: string; icon: React.ElementType; color: string }[] = [
    { key: 'opportunities', label: 'Pipeline', icon: TrendingUp, color: '#6366f1' },
    { key: 'leads', label: 'Leads', icon: Users, color: '#f59e0b' },
    { key: 'forecasts', label: 'Forecasts', icon: BarChart2, color: '#22c55e' },
    { key: 'accounts', label: 'Accounts', icon: Briefcase, color: '#3b82f6' },
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
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>Sales Department</p>
          </div>
          <button onClick={loadData} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
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
            className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none"
            style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>
        ) : (
          <>
            {/* OPPORTUNITIES (Pipeline) */}
            {tab === 'opportunities' && (
              <div className="rounded-xl overflow-x-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <table className="w-full text-[12px]">
                  <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    {['Opportunity', 'Account', 'Stage', 'Value', 'Close Date', 'Win %', 'AI Coach'].map(h => (
                      <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {opportunities.filter(o => !searchQ || o.name?.toLowerCase().includes(searchQ.toLowerCase()) || o.account?.toLowerCase().includes(searchQ.toLowerCase())).map((o) => (
                      <tr key={o.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
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
                          <button onClick={() => runAgent('Pipeline coach', o.id, api.runSalesPipelineAgent)}
                            disabled={runningAgent === o.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#6366f115', color: '#6366f1' }}>
                            {runningAgent === o.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Coach
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {opportunities.length === 0 && <EmptyState icon={TrendingUp} title="No opportunities" sub="Pipeline opportunities appear here" />}
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
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{l.source || '-'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            {[1,2,3,4,5].map(s => (
                              <Star key={s} className="w-3 h-3" fill={(l.score || 0) >= s ? '#f59e0b' : 'none'} style={{ color: '#f59e0b' }} />
                            ))}
                            <span className="ml-1 font-mono text-[10px]">{l.score || 0}/5</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Lead scoring', l.id, api.runSalesLeadScoringAgent)}
                            disabled={runningAgent === l.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
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
                          <div className="space-y-1">
                            <div className="flex justify-between text-[10px]">
                              <span>${(f.quota || 0).toLocaleString()}</span>
                              <span style={{ color: (f.committed / f.quota) > 0.8 ? '#22c55e' : '#f59e0b' }}>
                                {f.quota ? Math.round((f.committed / f.quota) * 100) : 0}%
                              </span>
                            </div>
                            <div className="h-1 rounded-full w-24" style={{ background: colors.hairline }}>
                              <div className="h-full rounded-full" style={{ width: `${Math.min(100, f.quota ? Math.round((f.committed / f.quota) * 100) : 0)}%`, background: '#22c55e' }} />
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Forecast predict', f.id, api.runSalesForecastAgent)}
                            disabled={runningAgent === f.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
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
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{a.industry || '-'}</td>
                        <td className="px-4 py-3"><Badge status={a.health} /></td>
                        <td className="px-4 py-3 font-mono font-semibold">${(a.arr || 0).toLocaleString()}</td>
                        <td className="px-4 py-3">{a.owner || '-'}</td>
                        <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{a.last_activity || '-'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => runAgent('Account health', a.id, api.runSalesAccountAgent)}
                            disabled={runningAgent === a.id}
                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
                            style={{ background: '#3b82f615', color: '#3b82f6' }}>
                            {runningAgent === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
                            Health
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {accounts.length === 0 && <EmptyState icon={Briefcase} title="No accounts" sub="Sales accounts appear here" />}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default SalesView;
