/**
 * KAEOS - Support Dashboard
 * Department-level overview for the Support domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading } from '../components/BrainStates';
import {
  LifeBuoy, MessageSquare, BookOpen, Clock, Heart,
  ArrowRight, Bot, Zap, Shield, Users
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';

export default function SupportDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [supStats, setSupStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getWorkforceDepartment('support').catch(() => null),
      api.getSupportDashboard().catch(() => null),
    ]).then(([d, s]) => {
      setDept(d);
      setSupStats(s);
      setLoading(false);
    });
  }, []);

  if (loading) return <BrainLoading message="Loading Support Metrics..." />;

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
        <div className="max-w-7xl mx-auto p-6">
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: '#ec489915' }}>
              <LifeBuoy className="w-10 h-10" style={{ color: '#ec4899' }} />
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
              style={{ background: '#ec4899' }}>
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
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <DomainIcon hint="support" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Customer Support'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Helpdesk triage, automated KB lookup, SLA breach monitors, and CSAT analysis.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold" style={{ background: '#ec489920', color: '#ec4899' }}>
                    {dept.status}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#ec489915', color: '#ec4899' }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2">
              <span className="text-[12px]" style={{ color: colors.inkSubtle }}>SLA Compliance:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                {Math.round((dept.health_score || 0) * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Total Tickets', value: supStats?.total_tickets ?? '0', icon: MessageSquare, color: '#ec4899' },
            { label: 'Open Incidents', value: supStats?.open_tickets ?? '0', icon: LifeBuoy, color: '#ef4444' },
            { label: 'KB Articles', value: supStats?.kb_articles ?? '0', icon: BookOpen, color: '#8b5cf6' },
            { label: 'Average CSAT Score', value: supStats?.avg_csat ? `${supStats.avg_csat} / 5` : '-', icon: Heart, color: '#22c55e' },
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
        <div className="grid grid-cols-4 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-sm group border"
              style={{ background: colors.surface1, borderColor: colors.hairline }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1">
                <div className="text-[13px] font-bold group-hover:text-primary transition-colors">{link.label}</div>
                <div className="text-[10px]" style={{ color: colors.inkSubtle }}>View operations →</div>
              </div>
            </button>
          ))}
        </div>

        {/* Bottom Section */}
        <div className="grid grid-cols-3 gap-6">
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
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Digital Reps
            </h3>
            <div className="space-y-3">
              {(dept?.agent_definitions || []).length === 0 && (
                <p className="text-[11px]" style={{ color: colors.inkSubtle }}>No agents deployed yet.</p>
              )}
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
