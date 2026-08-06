import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { BookOpen, Workflow, Network, FileSearch, Users, UploadCloud, GitFork } from 'lucide-react';
import { PAGE_PAD_X } from '../lib/layout';

// Connector management lives in ONE place — the top-level "Integrations" sidebar
// item (ConnectorStudio). It is not duplicated as Knowledge tabs (the old
// "Connector Studio" + "System Connections" tabs both managed connectors).
const RulesExplorer = lazy(() => import('../pages/RulesExplorer'));
const SkillsRegistry = lazy(() => import('../pages/SkillsRegistry'));
const TopologyVisualizer = lazy(() => import('../pages/TopologyVisualizer'));
const CausalDiscovery = lazy(() => import('../pages/CausalDiscovery'));
const ExtractionHub = lazy(() => import('../pages/ExtractionHub'));
const ElicitationHub = lazy(() => import('../pages/ElicitationHub'));
const BYOKView = lazy(() => import('../pages/BYOKView'));

export default function KnowledgeView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('topology');

  const tabs = [
    { id: 'topology', label: 'Topology Map', icon: Network },
    { id: 'causal', label: 'Causal Discovery', icon: GitFork },
    { id: 'rules', label: 'Discovered Rules', icon: BookOpen },
    { id: 'skills', label: 'Skill Builder', icon: Workflow },
    { id: 'extraction', label: 'Extraction Pipeline', icon: FileSearch },
    { id: 'byok', label: 'Bring Your Own Knowledge', icon: UploadCloud },
    { id: 'elicitation', label: 'Elicitation Hub', icon: Users }
  ];

  // ArrowLeft / ArrowRight move between tabs, then focus follows selection.
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = tabs[(tabs.findIndex(t => t.id === activeTab) + step + tabs.length) % tabs.length];
    setActiveTab(next.id);
    document.getElementById(`knowledge-tab-${next.id}`)?.focus();
  };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`flex items-center gap-6 ${PAGE_PAD_X} border-b overflow-x-auto no-scrollbar`}
        role="tablist" aria-label="Knowledge sections" onKeyDown={onTabKeyDown}
        style={{ borderColor: colors.hairline, background: colors.surface1, minHeight: '48px' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            id={`knowledge-tab-${tab.id}`}
            role="tab"
            aria-selected={activeTab === tab.id}
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

      <div className="flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Knowledge Module...</div>}>
          {activeTab === 'byok' && <BYOKView domain={domain} />}
          {activeTab === 'topology' && <TopologyVisualizer />}
          {activeTab === 'causal' && <CausalDiscovery />}
          {activeTab === 'extraction' && <ExtractionHub />}
          {activeTab === 'rules' && <RulesExplorer domain={domain} />}
          {activeTab === 'skills' && <SkillsRegistry domain={domain} />}
          {activeTab === 'elicitation' && <ElicitationHub />}
        </Suspense>
      </div>
    </div>
  );
}
