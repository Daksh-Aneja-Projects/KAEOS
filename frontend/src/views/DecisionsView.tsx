import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Activity, Users, TrendingUp, Shield, FileText, Target, Gauge, Scale } from 'lucide-react';

const CommandCenter = lazy(() => import('../views/CommandCenter'));
const ExecutiveCockpit = lazy(() => import('../pages/ExecutiveCockpit'));
const HITLQueue = lazy(() => import('../pages/HITLQueue'));
const EvolutionTimeline = lazy(() => import('../pages/EvolutionTimeline'));
const ComplianceDashboard = lazy(() => import('../pages/ComplianceDashboard'));
const ProvenanceLedger = lazy(() => import('../pages/ProvenanceLedger'));
const RedTeamDashboard = lazy(() => import('../pages/RedTeamDashboard'));
const TrustGovernance = lazy(() => import('./TrustGovernance'));

export default function DecisionsView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('cockpit');

  const tabs = [
    { id: 'cockpit', label: 'Executive Cockpit', icon: Gauge },
    { id: 'live', label: 'Execution Monitor', icon: Activity },
    { id: 'hitl', label: 'HITL Queue', icon: Users },
    { id: 'performance', label: 'Feedback & Evolution', icon: TrendingUp },
    { id: 'compliance', label: 'Compliance', icon: Shield },
    { id: 'provenance', label: 'Provenance Ledger', icon: FileText },
    { id: 'redteam', label: 'Red Team Ops', icon: Target },
    { id: 'governance', label: 'Fairness & Debates', icon: Scale }
  ];

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="flex items-center gap-6 px-8 border-b overflow-x-auto no-scrollbar" style={{ borderColor: colors.hairline, background: colors.surface1, minHeight: '48px' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="text-[13px] h-full flex items-center gap-2 relative transition-colors whitespace-nowrap"
            style={{ 
              color: activeTab === tab.id ? colors.ink : colors.inkSubtle,
              fontWeight: activeTab === tab.id ? 600 : 400
            }}
          >
            <tab.icon className="w-3.5 h-3.5" />
            {tab.label}
            {activeTab === tab.id && (
              <div className="absolute bottom-0 left-0 right-0 h-[2px] rounded-t" style={{ background: colors.primary }} />
            )}
          </button>
        ))}
        {activeTab === 'live' && (
          <div className="ml-auto flex items-center gap-2 text-[11px] font-bold text-green-500 bg-green-500/10 px-2.5 py-1 rounded-full uppercase tracking-wider whitespace-nowrap">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live Feed
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Decisions Module...</div>}>
          {activeTab === 'cockpit' && <ExecutiveCockpit domain={domain} />}
          {activeTab === 'live' && <CommandCenter domain={domain} />}
          {activeTab === 'hitl' && <HITLQueue domain={domain} />}
          {activeTab === 'performance' && <EvolutionTimeline domain={domain} />}
          {activeTab === 'compliance' && <ComplianceDashboard />}
          {activeTab === 'provenance' && <ProvenanceLedger />}
          {activeTab === 'redteam' && <RedTeamDashboard />}
          {activeTab === 'governance' && <TrustGovernance only={['fairness','debates']} />}
        </Suspense>
      </div>
    </div>
  );
}
