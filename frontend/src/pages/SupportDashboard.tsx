/**
 * KAEOS - Support Dashboard
 * Department-level overview for the Support domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError } from '../components/BrainStates';
import {
  LifeBuoy, MessageSquare, BookOpen, Clock, Heart,
  ArrowRight, Bot, Zap
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';

const ACCENT = DEPARTMENT_COLORS.support;

export default function SupportDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [supStats, setSupStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    Promise.allSettled([
      api.getWorkforceDepartment('support'),
      api.getSupportDashboard(),
    ]).then(([d, s]) => {
      if (d.status === 'fulfilled') setDept(d.value);
      if (s.status === 'fulfilled') { setSupStats(s.value); setError(null); }
      else if (d.status === 'rejected') setError((s.reason as any)?.message || 'Failed to load Support');
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);
  useLiveRefresh(load, { intervalMs: 20000 });

  if (loading) return <BrainLoading message="Loading Support Metrics..." />;
  if (error && !dept && !supStats) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  if (!dept && !supStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className={`${PAGE_PAD}`}>
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: ACCENT + '15' }}>
              <LifeBuoy className="w-10 h-10" style={{ color: ACCENT }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Support Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Customer Support pack to manage helpdesk queues, publish FAQs,
                monitor SLA guidelines, and run feedback sentiment analytics with digital twins.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: ACCENT }}>
              Deploy Support Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'Support Queue', path: '/departments/support/tickets', icon: MessageSquare, color: '#ec4899' },
    { label: 'Knowledge Base', path: '/departments/support/kb', icon: BookOpen, color: '#8b5cf6' },
    { label: 'SLA Dashboard', path: '/departments/support/sla', icon: Clock, color: '#3b82f6' },
    { label: 'CSAT Surveys', path: '/departments/support/feedback', icon: Heart, color: '#ef4444' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <DomainIcon hint="support" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Customer Support'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Helpdesk triage, automated KB lookup, SLA breach monitors, and CSAT analysis.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: ACCENT + '20', color: ACCENT }}>
                    {humanize(dept.status)}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold" style={{ background: ACCENT + '15', color: ACCENT }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[12px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>SLA Compliance:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                <CountUp value={Math.round((dept.health_score || 0) * 100)} suffix="%" />
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Total Tickets', value: supStats?.total_tickets ?? 0, icon: MessageSquare, color: '#ec4899' },
            { label: 'Open Incidents', value: supStats?.open_tickets ?? 0, icon: LifeBuoy, color: '#ef4444' },
            { label: 'KB Articles', value: supStats?.kb_articles ?? 0, icon: BookOpen, color: '#8b5cf6' },
            { label: 'Average CSAT Score', value: supStats?.avg_csat ? `${supStats.avg_csat} / 5` : '-', icon: Heart, color: '#22c55e' },
          ].map(kpi => (
            <div key={kpi.label} className="p-4 rounded-xl flex items-center justify-between" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <div>
                <div className="text-[22px] font-bold" style={{ color: kpi.color }}>{typeof kpi.value === 'number' ? <CountUp value={kpi.value} /> : kpi.value}</div>
                <div className="text-[11px] font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: kpi.color + '15' }}>
                <kpi.icon className="w-5 h-5" style={{ color: kpi.color }} />
              </div>
            </div>
          ))}
        </div>

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-sm group border"
              style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-bold group-hover:text-primary transition-colors truncate" title={link.label}>{link.label}</div>
                <div className="text-[11px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>View operations →</div>
              </div>
            </button>
          ))}
        </div>

        {/* Bottom Section */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            {/* Capabilities */}
            {(dept?.capabilities || []).length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-4 flex items-center gap-1.5">
                  <Zap className="w-4 h-4 text-amber-500" /> Support Capabilities
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {dept.capabilities.map((cap: any) => (
                    <div key={cap.id} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] font-semibold flex items-center gap-1.5">
                          <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={24} /> {cap.name}
                        </span>
                        <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: cap.status === 'ACTIVE' ? '#22c55e20' : '#f59e0b20', color: cap.status === 'ACTIVE' ? '#22c55e' : '#f59e0b' }}>
                          {humanize(cap.status)}
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
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Digital Reps
            </h3>
            <div className="space-y-3">
              {(dept?.agents || []).length === 0 && (
                <p className="text-[11px]" style={{ color: colors.inkSubtle }}>No agents deployed yet.</p>
              )}
              {(dept?.agents || []).map((agent: any) => (
                <div key={agent.id} className="flex items-center justify-between p-2.5 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <div className="w-6 h-6 rounded-md flex items-center justify-center text-[11px] font-bold flex-shrink-0" style={{ background: colors.primary + '18', color: colors.primary }}>{(agent.agent_name || '?').charAt(0)}</div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-bold truncate" title={agent.agent_name}>{agent.agent_name}</div>
                      <div className="text-[11px] truncate" title={agent.role_in_department} style={{ color: colors.inkSubtle }}>{agent.role_in_department}</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-green-500/10 text-green-500 flex-shrink-0 whitespace-nowrap ml-2">{agent.status === 'ACTIVE' || !agent.status ? 'Active' : humanize(agent.status)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
