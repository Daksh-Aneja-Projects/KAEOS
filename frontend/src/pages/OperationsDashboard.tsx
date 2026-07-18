/**
 * KAEOS - Operations Dashboard
 * Department-level overview for the Operations domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading } from '../components/BrainStates';
import {
  Wrench, CheckSquare, Clipboard, Users, ShieldAlert,
  ArrowRight, Bot, Zap, Shield, Sparkles
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';

export default function OperationsDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [opsStats, setOpsStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getWorkforceDepartment('operations').catch(() => null),
      api.getOperationsDashboard().catch(() => null),
    ]).then(([d, o]) => {
      setDept(d);
      setOpsStats(o);
      setLoading(false);
    });
  }, []);

  if (loading) return <BrainLoading message="Loading Operational Infrastructure status..." />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  if (!dept && !opsStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className="max-w-7xl mx-auto p-6">
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: '#10b98115' }}>
              <Wrench className="w-10 h-10" style={{ color: '#10b981' }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Operations Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Operations & PMO pack to track project progress, audit developer
                utilization, manage subcontracts, and perform QA inspections with digital twins.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: '#10b981' }}>
              Deploy Operations Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Project Portfolio', path: '/departments/operations/projects', icon: CheckSquare, color: '#10b981' },
    { label: 'Team Allocations', path: '/departments/operations/resources', icon: Users, color: '#8b5cf6' },
    { label: 'Supplier Operations', path: '/departments/operations/vendors', icon: Clipboard, color: '#3b82f6' },
    { label: 'Procurements', path: '/departments/operations/procurement', icon: Wrench, color: '#f59e0b' },
    { label: 'QA Inspections', path: '/departments/operations/quality', icon: ShieldAlert, color: '#ef4444' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <DomainIcon hint="operations" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Operations & PMO'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Project deliverables, team capacities, supplier scorecards, and QA conformance auditing.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold" style={{ background: '#10b98120', color: '#10b981' }}>
                    {dept.status}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#10b98115', color: '#10b981' }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2">
              <span className="text-[12px]" style={{ color: colors.inkSubtle }}>PMO Health:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                {Math.round((dept.health_score || 0) * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Active Projects', value: opsStats?.active_projects ?? '0', icon: CheckSquare, color: '#10b981' },
            { label: 'Warning tasks', value: opsStats?.blocked_tasks ?? '0', icon: ShieldAlert, color: '#ef4444' },
            { label: 'Pending Purchases', value: opsStats?.pending_purchases ?? '0', icon: Wrench, color: '#f59e0b' },
            { label: 'Failed QA Checks', value: opsStats?.failed_inspections ?? '0', icon: Clipboard, color: '#ec4899' },
          ].map(kpi => (
            <div key={kpi.label} className="p-4 rounded-xl flex items-center justify-between" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <div>
                <div className="text-[22px] font-bold" style={{ color: kpi.color }}>{kpi.value}</div>
                <div className="text-[11px] font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
              </div>
            </div>
          ))}
        </div>

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-5 gap-3">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex flex-col items-center p-4 rounded-xl text-center transition-all hover:shadow-sm group border"
              style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center mb-2.5" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="text-[12px] font-bold group-hover:text-primary transition-colors">{link.label}</div>
            </button>
          ))}
        </div>

        {/* Bottom Section */}
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            {/* Capabilities */}
            {dept?.capabilities && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-4 flex items-center gap-1.5">
                  <Zap className="w-4 h-4 text-amber-500" /> Operations Capabilities
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {dept.capabilities.map((cap: any) => (
                    <div key={cap.id} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] font-semibold flex items-center gap-1.5">
                          <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={24} /> {cap.name}
                        </span>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: cap.status === 'ACTIVE' ? '#22c55e20' : '#f59e0b20', color: cap.status === 'ACTIVE' ? '#22c55e' : '#f59e0b' }}>
                          {cap.status}
                        </span>
                      </div>
                      <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{cap.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div style={card} className="space-y-4">
            <h3 className="text-[14px] font-bold flex items-center gap-1.5">
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Ops Agents
            </h3>
            <div className="space-y-3">
              {(dept?.agent_definitions || []).map((agent: any) => (
                <div key={agent.name} className="flex items-center justify-between p-2.5 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex items-center gap-2">
                    <span className="text-[16px]">{agent.icon}</span>
                    <div>
                      <div className="text-[12px] font-bold">{agent.name}</div>
                      <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{agent.role}</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-green-500/10 text-green-500">Active</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
