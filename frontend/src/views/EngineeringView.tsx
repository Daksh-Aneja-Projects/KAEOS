import React, { useEffect, useState } from 'react';
import {
  Code2, Server, GitPullRequest, Rocket, Siren, FileText,
  Bot, Loader2, CheckCircle2, XCircle, RefreshCw, ShieldAlert,
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import GateTrace from '../components/GateTrace';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';

type EngTab = 'services' | 'pull-requests' | 'deployments' | 'incidents' | 'postmortems' | 'analytics';

const TAB_LABEL: Record<EngTab, string> = {
  services: 'Service Catalog',
  'pull-requests': 'Pull Requests',
  deployments: 'Deployments',
  incidents: 'Incidents',
  postmortems: 'Postmortems',
  analytics: 'Analytics',
};

const EngineeringView: React.FC<{ domain?: string; defaultTab?: EngTab }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const valid: EngTab[] = ['services', 'pull-requests', 'deployments', 'incidents', 'postmortems', 'analytics'];
  const [tab, setTab] = useState<EngTab>(
    defaultTab && valid.includes(defaultTab) ? defaultTab : 'services'
  );

  const [dashboard, setDashboard] = useState<any>(null);
  const [services, setServices] = useState<any[]>([]);
  const [prs, setPrs] = useState<any[]>([]);
  const [deployments, setDeployments] = useState<any[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [postmortems, setPostmortems] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [runningAgent, setRunningAgent] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);
  const [actionMsg, setActionMsg] = useState('');

  const loadData = async () => {
    const [d, s, p, dep, inc, pm, wf] = await Promise.allSettled([
      api.getEngineeringDashboard(),
      api.getEngineeringServices(),
      api.getPullRequests(),
      api.getDeployments(),
      api.getIncidents(),
      api.getPostmortems(),
      api.getDomainWorkflows('engineering'),
    ]);
    if (d.status === 'fulfilled') setDashboard(d.value);
    if (s.status === 'fulfilled') setServices(s.value || []);
    if (p.status === 'fulfilled') setPrs(p.value || []);
    if (dep.status === 'fulfilled') setDeployments(dep.value || []);
    if (inc.status === 'fulfilled') setIncidents(inc.value || []);
    if (pm.status === 'fulfilled') setPostmortems(pm.value || []);
    if (wf.status === 'fulfilled') setWorkflows(wf.value || {});
    setLoading(false);
  };

  useEffect(() => { loadData(); }, []);

  // Live: any tenant event (an agent finishing, a gate pausing) refreshes this
  // view. Previously it fetched once on mount and went stale until the user
  // hit the refresh icon.
  useLiveRefresh(loadData);


  const runAgent = async (label: string, id: string, fn: (id: string) => Promise<any>) => {
    setRunningAgent(id); setActionMsg('');
    setTrace({ id, label, result: undefined });
    try {
      const res = await fn(id);
      setTrace({ id, label, result: res });
      setActionMsg(
        res?.status === 'PENDING_HITL'
          ? `${label} complete - routed for human approval.`
          : `${label} complete.`
      );
      await loadData();
    } catch (e: any) {
      setActionMsg(`${label} failed: ${e?.message || e}`);
    } finally {
      setRunningAgent(null);
    }
  };

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
  };

  const riskColor = (r?: string | null) =>
    r === 'CRITICAL' ? '#ef4444' : r === 'HIGH' ? '#f59e0b'
      : r === 'MEDIUM' ? '#eab308' : r === 'LOW' ? '#22c55e' : colors.inkTertiary;

  const sevColor = (s?: string) =>
    s === 'SEV1' ? '#ef4444' : s === 'SEV2' ? '#f59e0b' : s === 'SEV3' ? '#eab308' : '#6b7280';

  const healthColor = (h?: string) =>
    h === 'HEALTHY' ? '#22c55e' : h === 'DEGRADED' ? '#f59e0b'
      : h === 'OUTAGE' ? '#ef4444' : '#6b7280';

  const Badge: React.FC<{ text?: string | null; color: string }> = ({ text, color }) => (
    <span className="px-2 py-0.5 rounded text-[10px] font-bold"
      style={{ background: color + '18', color }}>
      {text || '-'}
    </span>
  );

  const AgentButton: React.FC<{ id: string; label: string; onRun: () => void }> = ({ id, label, onRun }) => (
    <button onClick={onRun} disabled={runningAgent === id}
      className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50"
      style={{ background: '#6366f115', color: '#6366f1' }}>
      {runningAgent === id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Bot className="w-3 h-3" />}
      {label}
    </button>
  );

  const stats = dashboard ? [
    { label: 'Services', value: dashboard.total_services, icon: Server, color: '#6366f1' },
    { label: 'Open PRs', value: dashboard.open_pull_requests, icon: GitPullRequest, color: '#8b5cf6' },
    { label: 'Open Incidents', value: dashboard.open_incidents, icon: Siren, color: dashboard.sev1_open > 0 ? '#ef4444' : '#f59e0b' },
    {
      label: 'Change Fail Rate',
      value: dashboard.change_failure_rate_pct != null ? `${dashboard.change_failure_rate_pct}%` : '-',
      icon: Rocket, color: '#ec4899',
    },
    {
      label: 'MTTR',
      value: dashboard.mttr_minutes != null ? `${dashboard.mttr_minutes}m` : '-',
      icon: RefreshCw, color: '#06b6d4',
    },
    { label: 'On Call', value: dashboard.engineers_on_call, icon: ShieldAlert, color: '#22c55e' },
  ] : [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[22px] font-bold flex items-center gap-2" style={{ color: colors.ink }}>
            <Code2 className="w-6 h-6" style={{ color: colors.primary }} />
            {TAB_LABEL[tab]}
          </h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
            Engineering &amp; IT Ops - service catalog, code review, deployments, and incident response
          </p>
        </div>
        <button onClick={() => setCreateOpen(true)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
          style={{ background: colors.primary }}>
          <PlusIcon className="w-3.5 h-3.5" /> Declare Incident
        </button>
        <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
          title="Declare Incident" domain="engineering" entityPath="incidents"
          fields={[
            { key: 'title', label: 'Title', type: 'text', required: true },
            { key: 'description', label: 'What is happening?', type: 'textarea' },
            { key: 'severity', label: 'Severity', type: 'select', defaultValue: 'SEV3',
              options: ['SEV1', 'SEV2', 'SEV3', 'SEV4'] },
            { key: 'affected_users', label: 'Affected Users (est.)', type: 'number' },
          ]}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
      </div>

      {/* Live DORA posture */}
      {dashboard && (
        <div className="grid grid-cols-6 gap-3">
          {stats.map(({ label, value, icon: Icon, color }) => (
            <div key={label} style={card} className="p-3.5">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-bold uppercase tracking-wide" style={{ color: colors.inkTertiary }}>{label}</span>
                <Icon className="w-3.5 h-3.5" style={{ color }} />
              </div>
              <div className="text-[22px] font-bold font-mono" style={{ color: colors.ink }}>{value ?? '-'}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: colors.surface2 }}>
        {valid.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className="px-3.5 py-1.5 rounded-md text-[12px] font-semibold transition-colors"
            style={{
              background: tab === t ? colors.surface1 : 'transparent',
              color: tab === t ? colors.ink : colors.inkSubtle,
            }}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {actionMsg && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-[12px] font-medium"
          style={{
            background: actionMsg.includes('failed') ? '#ef444415' : '#22c55e15',
            color: actionMsg.includes('failed') ? '#ef4444' : '#22c55e',
          }}>
          {actionMsg.includes('failed') ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
          {actionMsg}
        </div>
      )}

        {trace && (
          <GateTrace running={runningAgent === trace.id} result={trace.result} skillLabel={trace.label} />
        )}

      {loading && (
        <div className="p-8 flex items-center gap-2 text-[13px]" style={{ color: colors.inkSubtle }}>
          <Loader2 className="w-4 h-4 animate-spin" /> Loading engineering data…
        </div>
      )}

      {/* Service Catalog */}
      {!loading && tab === 'services' && (
        <div style={card} className="overflow-hidden">
          <table className="w-full text-[12px]" style={{ color: colors.ink }}>
            <thead>
              <tr style={{ background: colors.surface2, color: colors.inkSubtle }}>
                {['Service', 'Tier', 'Health', 'Squad', 'SLO Target', 'SLO Actual', 'Error Budget', 'Deploys 30d'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {services.map((s) => (
                <tr key={s.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{s.name}</div>
                    <div className="text-[10px]" style={{ color: colors.inkTertiary }}>{s.description}</div>
                  </td>
                  <td className="px-4 py-3"><Badge text={s.tier} color={s.tier === 'TIER_1' ? '#ef4444' : s.tier === 'TIER_2' ? '#f59e0b' : '#6b7280'} /></td>
                  <td className="px-4 py-3"><Badge text={s.health} color={healthColor(s.health)} /></td>
                  <td className="px-4 py-3">{s.owning_squad || '-'}</td>
                  <td className="px-4 py-3 font-mono">{s.slo_target != null ? `${s.slo_target}%` : '-'}</td>
                  <td className="px-4 py-3 font-mono"
                    style={{ color: s.slo_actual != null && s.slo_target != null && s.slo_actual < s.slo_target ? '#ef4444' : colors.ink }}>
                    {s.slo_actual != null ? `${s.slo_actual}%` : '-'}
                  </td>
                  <td className="px-4 py-3">
                    {s.error_budget_remaining_pct != null ? (
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 rounded-full w-16" style={{ background: colors.hairline }}>
                          <div className="h-full rounded-full"
                            style={{
                              width: `${Math.max(0, Math.min(100, s.error_budget_remaining_pct))}%`,
                              background: s.error_budget_remaining_pct < 25 ? '#ef4444' : '#22c55e',
                            }} />
                        </div>
                        <span className="font-mono text-[11px]">{s.error_budget_remaining_pct}%</span>
                      </div>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-3 font-mono">{s.deploys_last_30d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pull Requests */}
      {!loading && tab === 'pull-requests' && (
        <div style={card} className="overflow-hidden">
          <table className="w-full text-[12px]" style={{ color: colors.ink }}>
            <thead>
              <tr style={{ background: colors.surface2, color: colors.inkSubtle }}>
                {['PR', 'Title', 'Status', 'Diff', 'CI', 'Flags', 'AI Risk', 'AI Review'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {prs.map((p) => (
                <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className="px-4 py-3 font-mono">#{p.number}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{p.title}</div>
                    {p.ai_summary && (
                      <div className="text-[10px] mt-0.5" style={{ color: colors.inkTertiary }}>{p.ai_summary}</div>
                    )}
                  </td>
                  <td className="px-4 py-3"><Badge text={p.status} color="#6366f1" /></td>
                  <td className="px-4 py-3 font-mono text-[11px]">
                    <span style={{ color: '#22c55e' }}>+{p.additions}</span>{' '}
                    <span style={{ color: '#ef4444' }}>-{p.deletions}</span>
                    <div style={{ color: colors.inkTertiary }}>{p.files_changed} files</div>
                  </td>
                  <td className="px-4 py-3">
                    {p.ci_passing
                      ? <CheckCircle2 className="w-4 h-4" style={{ color: '#22c55e' }} />
                      : <XCircle className="w-4 h-4" style={{ color: '#ef4444' }} />}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-0.5">
                      {p.touches_auth && <Badge text="AUTH" color="#ef4444" />}
                      {p.touches_migrations && <Badge text="MIGRATION" color="#f59e0b" />}
                      {p.test_coverage_delta != null && p.test_coverage_delta < 0 && (
                        <Badge text={`COV ${p.test_coverage_delta}`} color="#f59e0b" />
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3"><Badge text={p.ai_risk_level} color={riskColor(p.ai_risk_level)} /></td>
                  <td className="px-4 py-3">
                    <AgentButton id={p.id} label="Review" onRun={() => runAgent('Code review', p.id, api.runCodeReviewAgent)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Deployments */}
      {!loading && tab === 'deployments' && (
        <div style={card} className="overflow-hidden">
          <table className="w-full text-[12px]" style={{ color: colors.ink }}>
            <thead>
              <tr style={{ background: colors.surface2, color: colors.inkSubtle }}>
                {['Version', 'Env', 'Status', 'Deployed By', 'AI Risk', 'Score', 'Rationale', 'Assess'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {deployments.map((d) => (
                <tr key={d.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className="px-4 py-3 font-mono font-medium">{d.version}</td>
                  <td className="px-4 py-3">{d.environment}</td>
                  <td className="px-4 py-3">
                    <Badge text={d.status} color={
                      d.status === 'SUCCEEDED' ? '#22c55e'
                        : d.status === 'PENDING_APPROVAL' ? '#f59e0b' : '#ef4444'
                    } />
                  </td>
                  <td className="px-4 py-3 text-[11px]">{d.deployed_by || '-'}</td>
                  <td className="px-4 py-3"><Badge text={d.ai_risk_level} color={riskColor(d.ai_risk_level)} /></td>
                  <td className="px-4 py-3 font-mono font-bold"
                    style={{ color: riskColor(d.ai_risk_level) }}>
                    {d.ai_risk_score != null ? `${d.ai_risk_score}` : '-'}
                  </td>
                  <td className="px-4 py-3 text-[11px] max-w-xs" style={{ color: colors.inkSubtle }}>
                    {d.ai_rationale || '-'}
                  </td>
                  <td className="px-4 py-3">
                    <AgentButton id={d.id} label="Assess" onRun={() => runAgent('Deploy risk', d.id, api.runDeployRiskAgent)} />
                    <div className="mt-1">
                      <WorkflowActions domain="engineering" entityPath="deployments" entityId={d.id}
                        currentState={d.status} transitions={workflows['deployment']?.transitions}
                        onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Incidents */}
      {!loading && tab === 'incidents' && (
        <div style={card} className="overflow-hidden">
          <table className="w-full text-[12px]" style={{ color: colors.ink }}>
            <thead>
              <tr style={{ background: colors.surface2, color: colors.inkSubtle }}>
                {['Incident', 'Title', 'Sev', 'Status', 'Impact', 'TTR', 'AI Assessment', 'Triage'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className="px-4 py-3 font-mono">{i.number}</td>
                  <td className="px-4 py-3 font-medium">{i.title}</td>
                  <td className="px-4 py-3"><Badge text={i.severity} color={sevColor(i.severity)} /></td>
                  <td className="px-4 py-3"><Badge text={i.status} color="#6366f1" /></td>
                  <td className="px-4 py-3 text-[11px]">
                    {i.customer_impacting
                      ? <span style={{ color: '#ef4444' }}>{(i.affected_users ?? 0).toLocaleString()} users</span>
                      : <span style={{ color: colors.inkTertiary }}>internal</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px]">
                    {i.time_to_resolve_mins != null ? `${i.time_to_resolve_mins}m` : '-'}
                  </td>
                  <td className="px-4 py-3 text-[11px] max-w-xs" style={{ color: colors.inkSubtle }}>
                    {i.ai_probable_cause || '-'}
                    {i.ai_recommended_action && (
                      <div className="mt-0.5 font-medium" style={{ color: colors.ink }}>→ {i.ai_recommended_action}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <AgentButton id={i.id} label="Triage" onRun={() => runAgent('Incident triage', i.id, api.runIncidentTriageAgent)} />
                    <div className="mt-1">
                      <WorkflowActions domain="engineering" entityPath="incidents" entityId={i.id}
                        currentState={i.status} transitions={workflows['incident']?.transitions}
                        onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Postmortems */}
      {!loading && tab === 'postmortems' && (
        <div className="space-y-3">
          {postmortems.map((pm) => (
            <div key={pm.id} style={card} className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <FileText className="w-4 h-4" style={{ color: colors.primary }} />
                <span className="text-[13px] font-bold" style={{ color: colors.ink }}>{pm.summary}</span>
                {pm.published && <Badge text="PUBLISHED" color="#22c55e" />}
              </div>
              <div className="text-[12px] mb-2" style={{ color: colors.inkSubtle }}>
                <span className="font-semibold" style={{ color: colors.ink }}>Root cause: </span>{pm.root_cause}
              </div>
              {(pm.contributing_factors || []).length > 0 && (
                <ul className="text-[11px] mb-2 list-disc pl-5" style={{ color: colors.inkSubtle }}>
                  {pm.contributing_factors.map((f: string, idx: number) => <li key={idx}>{f}</li>)}
                </ul>
              )}
              {(pm.action_items || []).length > 0 && (
                <div className="mt-2">
                  <div className="text-[10px] font-bold uppercase mb-1" style={{ color: colors.inkTertiary }}>Action items</div>
                  {pm.action_items.map((a: any, idx: number) => (
                    <div key={idx} className="flex items-center gap-2 text-[11px] py-0.5">
                      {a.done
                        ? <CheckCircle2 className="w-3 h-3" style={{ color: '#22c55e' }} />
                        : <div className="w-3 h-3 rounded-full border" style={{ borderColor: colors.hairline }} />}
                      <span style={{ color: colors.ink }}>{a.action}</span>
                      <span style={{ color: colors.inkTertiary }}>· {a.owner} · due {a.due}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {postmortems.length === 0 && (
            <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>
              No postmortems recorded.
            </div>
          )}
        </div>
      )}

      {/* Analytics */}
      {!loading && tab === 'analytics' && <DomainAnalytics domain="engineering" />}
    </div>
  );
};

export default EngineeringView;
