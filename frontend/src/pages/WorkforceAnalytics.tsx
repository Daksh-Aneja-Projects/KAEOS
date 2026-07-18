/**
 * KAEOS - Workforce Analytics
 * ROI dashboard: tasks automated, hours saved, cost savings.
 * Per-department breakdown with bar charts.
 * 
 * API: GET /workforce/analytics
 */
import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';
import {
  BarChart3, Clock, DollarSign, TrendingUp, Building2,
  Users, Zap, Heart, AlertTriangle, CheckCircle
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';

export default function WorkforceAnalytics({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getWorkforceAnalytics()
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <BrainLoading message="Computing ROI analytics..." />;
  if (!data) return <BrainEmpty title="No analytics data yet" action="Deploy a department and complete tasks to generate analytics" />;

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };
  const healthColor = (h: number) => h > 70 ? '#22c55e' : h > 40 ? '#f59e0b' : '#ef4444';

  // Calculate max for bar sizing
  const maxTasks = Math.max(...(data.departments || []).map((d: any) => d.tasks_completed || 0), 1);
  const maxHours = Math.max(...(data.departments || []).map((d: any) => d.hours_saved || 0), 1);

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-[24px] font-bold tracking-tight">Workforce Analytics</h1>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
            Enterprise ROI - real-time metrics from all deployed departments.
          </p>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-5 gap-4">
          {[
            // Deltas were hardcoded ("+12%", "+8.2%", "+15%") and presented as real
            // trends. There is no period-over-period series behind them, so they are
            // omitted rather than fabricated.
            { label: 'Tasks Completed', value: (data.total_tasks_completed || 0).toLocaleString(), icon: CheckCircle, color: '#22c55e', delta: '' },
            { label: 'Hours Saved', value: `${data.total_hours_saved || 0}h`, icon: Clock, color: '#f59e0b', delta: '' },
            { label: 'Cost Saved', value: `$${(data.total_cost_saved || 0).toLocaleString()}`, icon: DollarSign, color: '#22c55e', delta: '' },
            { label: 'Automation', value: `${data.automation_coverage_pct || 0}%`, icon: Zap, color: '#8b5cf6', delta: '' },
            { label: 'Health Score', value: `${data.avg_health_score || 0}%`, icon: Heart, color: healthColor(data.avg_health_score || 0), delta: '' },
          ].map(kpi => (
            <div key={kpi.label} style={card} className="relative overflow-hidden">
              {/* Background glow */}
              <div className="absolute -top-6 -right-6 w-20 h-20 rounded-full opacity-5" style={{ background: kpi.color }} />
              <div className="flex items-center justify-between mb-2">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                  <kpi.icon className="w-4.5 h-4.5" style={{ color: kpi.color }} />
                </div>
                {kpi.delta && (
                  <span className="flex items-center gap-0.5 text-[10px] font-bold" style={{ color: '#22c55e' }}>
                    <TrendingUp className="w-3 h-3" /> {kpi.delta}
                  </span>
                )}
              </div>
              <div className="text-[24px] font-bold mt-2" style={{ color: kpi.color }}>{kpi.value}</div>
              <div className="text-[10px] uppercase tracking-wider mt-0.5" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
            </div>
          ))}
        </div>

        {/* Operational Metrics */}
        <div className="grid grid-cols-3 gap-4">
          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <Users className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Agent Fleet
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Active Agents</span>
                <span className="text-[16px] font-bold">{data.agents_active || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Utilization</span>
                <span className="text-[16px] font-bold" style={{ color: colors.primary }}>{data.agent_utilization_pct || 0}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Agent Health</span>
                <span className="text-[16px] font-bold" style={{ color: healthColor(data.avg_agent_health || 0) }}>{data.avg_agent_health || 0}%</span>
              </div>
            </div>
          </div>

          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} /> Escalation
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Human Escalation Rate</span>
                <span className="text-[16px] font-bold" style={{ color: (data.human_escalation_rate_pct || 0) < 15 ? '#22c55e' : '#f59e0b' }}>
                  {data.human_escalation_rate_pct || 0}%
                </span>
              </div>
              <div className="h-2 rounded-full" style={{ background: colors.hairline }}>
                <div className="h-full rounded-full" style={{
                  width: `${Math.min(data.human_escalation_rate_pct || 0, 100)}%`,
                  background: (data.human_escalation_rate_pct || 0) < 15 ? '#22c55e' : '#f59e0b',
                }} />
              </div>
              <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
                {(data.human_escalation_rate_pct || 0) < 15
                  ? '✓ Within target - below 15% threshold'
                  : '⚠ Above 15% target - review agent capabilities'}
              </div>
            </div>
          </div>

          <div style={card}>
            <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
              <Building2 className="w-4 h-4" style={{ color: colors.primary }} /> Departments
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Active</span>
                <span className="text-[16px] font-bold" style={{ color: colors.primary }}>{data.departments_active || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Avg Automation</span>
                <span className="text-[16px] font-bold">{data.automation_coverage_pct || 0}%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Per-Department Breakdown */}
        {(data.departments || []).length > 0 && (
          <div style={card}>
            <h3 className="text-[15px] font-semibold mb-4">Per-Department Breakdown</h3>
            <div className="space-y-4">
              {data.departments.map((dept: any) => (
                <div key={dept.id} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <DomainIcon hint={dept.slug || dept.icon} fallbackHint={dept.name} size={26} />
                      <span className="text-[14px] font-semibold">{dept.name}</span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full" style={{ background: healthColor(dept.health_score) + '15', color: healthColor(dept.health_score) }}>
                        {dept.health_score}% health
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <span>{dept.agent_count} agents</span>
                      <span>{dept.automation_coverage}% automated</span>
                    </div>
                  </div>
                  {/* Task bar */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="flex items-center justify-between text-[10px] mb-0.5" style={{ color: colors.inkSubtle }}>
                        <span>Tasks Completed</span>
                        <span className="font-mono">{(dept.tasks_completed || 0).toLocaleString()}</span>
                      </div>
                      <div className="h-2.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full transition-all" style={{
                          width: `${((dept.tasks_completed || 0) / maxTasks) * 100}%`,
                          background: `linear-gradient(90deg, ${colors.primary}, #22c55e)`,
                        }} />
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-[10px] mb-0.5" style={{ color: colors.inkSubtle }}>
                        <span>Hours Saved</span>
                        <span className="font-mono">{dept.hours_saved}h</span>
                      </div>
                      <div className="h-2.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                        <div className="h-full rounded-full transition-all" style={{
                          width: `${((dept.hours_saved || 0) / maxHours) * 100}%`,
                          background: `linear-gradient(90deg, #f59e0b, #ec4899)`,
                        }} />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
