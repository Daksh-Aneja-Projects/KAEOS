import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Activity, Users, TrendingUp, Shield, FileText, Target, Gauge, Scale, Zap, Dna, Cpu } from 'lucide-react';
import { PAGE_PAD_X } from '../lib/layout';

const CommandCenter = lazy(() => import('../views/CommandCenter'));
const ExecutiveCockpit = lazy(() => import('../pages/ExecutiveCockpit'));
const HITLQueue = lazy(() => import('../pages/HITLQueue'));
const EvolutionTimeline = lazy(() => import('../pages/EvolutionTimeline'));
const ComplianceDashboard = lazy(() => import('../pages/ComplianceDashboard'));
const ProvenanceLedger = lazy(() => import('../pages/ProvenanceLedger'));
const ActionsLedger = lazy(() => import('../pages/ActionsLedger'));
const RedTeamDashboard = lazy(() => import('../pages/RedTeamDashboard'));
const TrustGovernance = lazy(() => import('./TrustGovernance'));
// The genome + fitness studios read /genome/state and /evolution/state. They
// sit next to the evolution timeline, the other view of how the org changes
// over time.
const GenomeStudio = lazy(() => import('../components/GenomeStudio'));
const EvolutionStudio = lazy(() => import('../components/EvolutionStudio'));

export default function DecisionsView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('cockpit');

  // Left/right arrows move between tabs, the way a tablist is expected to behave.
  const onTabKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const els = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const i = els.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    e.preventDefault();
    const next = els[(i + (e.key === 'ArrowRight' ? 1 : -1) + els.length) % els.length];
    next.focus();
    next.click();
  };

  const tabs = [
    { id: 'cockpit', label: 'Executive Cockpit', icon: Gauge },
    { id: 'live', label: 'Execution Monitor', icon: Activity },
    { id: 'hitl', label: 'HITL Queue', icon: Users },
    { id: 'performance', label: 'Feedback & Evolution', icon: TrendingUp },
    { id: 'genome', label: 'Enterprise Genome', icon: Dna },
    { id: 'fitness', label: 'Evolution Studio', icon: Cpu },
    { id: 'compliance', label: 'Compliance', icon: Shield },
    { id: 'provenance', label: 'Provenance Ledger', icon: FileText },
    { id: 'actions', label: 'Actions Ledger', icon: Zap },
    { id: 'redteam', label: 'Red Team Ops', icon: Target },
    { id: 'governance', label: 'Fairness & Debates', icon: Scale }
  ];

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`flex items-center ${PAGE_PAD_X} border-b overflow-x-auto no-scrollbar`}
        style={{ borderColor: colors.hairline, background: colors.surface1, minHeight: '48px' }}>
        {/* The live-feed badge is not a tab, so it sits outside the tablist;
            self-stretch keeps the tabs full height so the active underline
            still lands on the bottom border. */}
        <div className="flex items-center gap-6 self-stretch"
          role="tablist" aria-label="Decisions sections" onKeyDown={onTabKey}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            id={`decisions-tab-${tab.id}`}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls="decisions-tab-panel"
            tabIndex={activeTab === tab.id ? 0 : -1}
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
        </div>
        {activeTab === 'live' && (
          <div className="ml-auto flex items-center gap-2 text-[11px] font-bold text-green-500 bg-green-500/10 px-2.5 py-1 rounded-full uppercase tracking-wider whitespace-nowrap">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live Feed
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto"
        id="decisions-tab-panel" role="tabpanel" aria-labelledby={`decisions-tab-${activeTab}`}>
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Decisions Module...</div>}>
          {activeTab === 'cockpit' && <ExecutiveCockpit domain={domain} />}
          {activeTab === 'live' && <CommandCenter domain={domain} />}
          {activeTab === 'hitl' && <HITLQueue domain={domain} />}
          {activeTab === 'performance' && <EvolutionTimeline domain={domain} />}
          {activeTab === 'genome' && <GenomeStudio />}
          {activeTab === 'fitness' && <EvolutionStudio />}
          {activeTab === 'compliance' && <ComplianceDashboard />}
          {activeTab === 'provenance' && <ProvenanceLedger />}
          {activeTab === 'actions' && <ActionsLedger />}
          {activeTab === 'redteam' && <RedTeamDashboard />}
          {activeTab === 'governance' && <TrustGovernance only={['fairness','debates']} />}
        </Suspense>
      </div>
    </div>
  );
}
