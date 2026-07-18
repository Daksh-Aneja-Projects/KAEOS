/**
 * KAEOS - Department Detail
 * Single department deep-dive with three sections:
 * 1. Capability map - grid of capabilities with status badges
 * 2. Agent fleet - cards for each deployed agent
 * 3. Process overview - list of business processes with metrics
 *
 * API: GET /workforce/departments/{id}
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import DomainIcon from '../components/DomainIcon';
import {
  ArrowLeft, Bot, Zap, BarChart3, Heart, CheckCircle,
  Clock, Activity, Shield, AlertTriangle, Cpu, TrendingUp
} from 'lucide-react';

export default function DepartmentDetail({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const { deptId } = useParams<{ deptId: string }>();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'capabilities' | 'agents' | 'processes'>('capabilities');

  useEffect(() => {
    if (!deptId) return;
    api.getWorkforceDepartment(deptId)
      .then(d => { setDept(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [deptId]);

  if (loading) return <BrainLoading message="Loading department intelligence..." />;
  if (error) return <BrainError message={error} onRetry={() => window.location.reload()} />;
  if (!dept) return <BrainEmpty title="Department not found" />;

  const statusColor = (s: string) => {
    if (s === 'ACTIVE') return '#22c55e';
    if (s === 'DEPLOYING' || s === 'PLANNED') return '#f59e0b';
    if (s === 'DEGRADED' || s === 'DISABLED') return '#ef4444';
    return colors.inkSubtle;
  };
  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };
  const tabs = [
    { id: 'capabilities' as const, label: 'Capabilities', icon: Zap, count: dept.capabilities?.length || 0 },
    { id: 'agents' as const, label: 'Agent Fleet', icon: Bot, count: dept.agents?.length || 0 },
    { id: 'processes' as const, label: 'Processes', icon: Activity, count: dept.processes?.length || 0 },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Back + Header */}
        <div>
          <button onClick={() => navigate('/')} className="flex items-center gap-1.5 text-[12px] mb-3 transition-colors hover:opacity-80" style={{ color: colors.inkSubtle }}>
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Workforce
          </button>
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <DomainIcon hint={dept.slug || dept.icon} fallbackHint={dept.name} size={56} />
              <div>
                <h1 className="text-[24px] font-bold tracking-tight">{dept.name}</h1>
                <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                  {dept.description || `Digital ${dept.name} department`}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: statusColor(dept.status) + '20', color: statusColor(dept.status) }}>
                    {dept.status}
                  </span>
                  {dept.compliance_frameworks?.map((f: string) => (
                    <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                      <Shield className="w-2.5 h-2.5" /> {f}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Heart className="w-5 h-5" style={{ color: healthColor(dept.health_score || 0) }} />
              <span className="text-[18px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                {Math.round((dept.health_score || 0) * 100)}%
              </span>
              <span className="text-[11px]" style={{ color: colors.inkSubtle }}>Health</span>
            </div>
          </div>
        </div>

        {/* KPI Row */}
        <div className="grid grid-cols-6 gap-3">
          {[
            { label: 'Employees Served', value: (dept.employee_count || 0).toLocaleString(), color: colors.primary },
            { label: 'Agents Active', value: dept.agent_count || 0, color: '#8b5cf6' },
            { label: 'Capabilities', value: dept.capability_count || 0, color: '#06b6d4' },
            { label: 'Processes', value: dept.process_count || 0, color: '#f59e0b' },
            { label: 'Tasks Completed', value: (dept.tasks_completed_total || 0).toLocaleString(), color: '#22c55e' },
            { label: 'Hours Saved', value: `${dept.hours_saved_total || 0}h`, color: '#ec4899' },
          ].map(kpi => (
            <div key={kpi.label} className="p-3 rounded-xl text-center" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}15` }}>
              <div className="text-[20px] font-bold" style={{ color: kpi.color }}>{kpi.value}</div>
              <div className="text-[9px] uppercase tracking-wider mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
            </div>
          ))}
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center gap-1 border-b" style={{ borderColor: colors.hairline }}>
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className="flex items-center gap-2 px-4 py-2.5 text-[13px] font-medium transition-all border-b-2"
              style={{
                borderColor: activeTab === tab.id ? colors.primary : 'transparent',
                color: activeTab === tab.id ? colors.primary : colors.inkSubtle,
              }}>
              <tab.icon className="w-4 h-4" />
              {tab.label}
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: colors.surface1 }}>{tab.count}</span>
            </button>
          ))}
        </div>

        {/* Capabilities Tab */}
        {activeTab === 'capabilities' && (
          <div className="grid grid-cols-3 gap-4">
            {(dept.capabilities || []).length === 0 ? (
              <div className="col-span-3"><BrainEmpty title="No capabilities defined yet" action="Deploy from a domain pack to activate capabilities" /></div>
            ) : (dept.capabilities || []).map((cap: any) => (
              <div key={cap.id} style={card}>
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={30} />
                    <h3 className="text-[14px] font-semibold">{cap.name}</h3>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: statusColor(cap.status) + '20', color: statusColor(cap.status) }}>
                    {cap.status}
                  </span>
                </div>
                <p className="text-[11px] mb-3 line-clamp-2" style={{ color: colors.inkSubtle }}>{cap.description}</p>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-[14px] font-bold">{Math.round((cap.automation_pct || 0) * 100)}%</div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Automated</div>
                  </div>
                  <div>
                    <div className="text-[14px] font-bold">{cap.tasks_completed || 0}</div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Tasks</div>
                  </div>
                  <div>
                    <div className="text-[14px] font-bold">{cap.active_agents || 0}</div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Agents</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Agent Fleet Tab */}
        {activeTab === 'agents' && (
          <div className="grid grid-cols-2 gap-4">
            {(dept.agents || []).length === 0 ? (
              <div className="col-span-2"><BrainEmpty title="No agents deployed yet" action="Deploy from a domain pack to create the agent fleet" /></div>
            ) : (dept.agents || []).map((agent: any) => (
              <div key={agent.id} className="flex items-center gap-4 p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: healthColor(agent.health_score || 0) + '15' }}>
                  <Bot className="w-6 h-6" style={{ color: healthColor(agent.health_score || 0) }} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-semibold">{agent.agent_name}</span>
                    <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: colors.primary + '15', color: colors.primary }}>{agent.agent_type}</span>
                    <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: statusColor(agent.status) + '20', color: statusColor(agent.status) }}>{agent.status}</span>
                  </div>
                  <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>{agent.role_in_department || 'General agent'}</div>
                </div>
                <div className="flex items-center gap-5 text-center">
                  <div>
                    <div className="text-[14px] font-bold font-mono">{agent.tasks_handled || 0}</div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Tasks</div>
                  </div>
                  <div>
                    <div className="text-[14px] font-bold font-mono" style={{ color: healthColor(agent.health_score || 0) }}>{Math.round((agent.health_score || 0) * 100)}%</div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Health</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono" style={{ color: colors.inkSubtle }}>
                      {agent.last_active_at ? new Date(agent.last_active_at).toLocaleDateString() : '-'}
                    </div>
                    <div className="text-[9px]" style={{ color: colors.inkSubtle }}>Last Active</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Processes Tab */}
        {activeTab === 'processes' && (
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
            <div className="grid grid-cols-8 text-[10px] font-semibold uppercase tracking-wider px-4 py-2.5" style={{ background: colors.surface1, color: colors.inkSubtle }}>
              <div className="col-span-2">Process</div>
              <div>Status</div>
              <div>Trigger</div>
              <div className="text-center">Executions</div>
              <div className="text-center">Success Rate</div>
              <div className="text-center">Avg Duration</div>
              <div className="text-center">SLA</div>
            </div>
            {(dept.processes || []).length === 0 ? (
              <div className="p-8"><BrainEmpty title="No processes defined" action="Processes are created during department deployment" /></div>
            ) : (dept.processes || []).map((proc: any, i: number) => (
              <div key={proc.id} className="grid grid-cols-8 items-center px-4 py-3 text-[12px]"
                style={{ borderTop: `1px solid ${colors.hairline}`, background: i % 2 === 0 ? 'transparent' : colors.surface1 + '40' }}>
                <div className="col-span-2">
                  <div className="font-medium">{proc.name}</div>
                  <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{proc.description?.slice(0, 50)}</div>
                </div>
                <div><span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: statusColor(proc.status) + '20', color: statusColor(proc.status) }}>{proc.status}</span></div>
                <div className="text-[11px] capitalize" style={{ color: colors.inkSubtle }}>{proc.trigger_type?.toLowerCase() || 'manual'}</div>
                <div className="text-center font-mono">{proc.execution_count || 0}</div>
                <div className="text-center font-mono" style={{ color: (proc.success_rate || 0) > 0.9 ? '#22c55e' : '#f59e0b' }}>
                  {((proc.success_rate || 0) * 100).toFixed(1)}%
                </div>
                <div className="text-center font-mono">{proc.avg_duration_ms ? `${(proc.avg_duration_ms / 1000).toFixed(1)}s` : '-'}</div>
                <div className="text-center font-mono">{proc.sla_hours ? `${proc.sla_hours}h` : '-'}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
