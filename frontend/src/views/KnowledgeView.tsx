import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { BookOpen, Workflow, Network, FileSearch, Users, UploadCloud } from 'lucide-react';

// Connector management lives in ONE place — the top-level "Integrations" sidebar
// item (ConnectorStudio). It is not duplicated as Knowledge tabs (the old
// "Connector Studio" + "System Connections" tabs both managed connectors).
const RulesExplorer = lazy(() => import('../pages/RulesExplorer'));
const SkillsRegistry = lazy(() => import('../pages/SkillsRegistry'));
const TopologyVisualizer = lazy(() => import('../pages/TopologyVisualizer'));
const ExtractionHub = lazy(() => import('../pages/ExtractionHub'));
const ElicitationHub = lazy(() => import('../pages/ElicitationHub'));
const BYOKView = lazy(() => import('../pages/BYOKView'));

export default function KnowledgeView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('topology');

  const tabs = [
    { id: 'topology', label: 'Topology Map', icon: Network },
    { id: 'rules', label: 'Discovered Rules', icon: BookOpen },
    { id: 'skills', label: 'Skill Builder', icon: Workflow },
    { id: 'extraction', label: 'Extraction Pipeline', icon: FileSearch },
    { id: 'byok', label: 'Bring Your Own Knowledge', icon: UploadCloud },
    { id: 'elicitation', label: 'Elicitation Hub', icon: Users }
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
      </div>

      <div className="flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Knowledge Module...</div>}>
          {activeTab === 'byok' && <BYOKView domain={domain} />}
          {activeTab === 'topology' && <TopologyVisualizer />}
          {activeTab === 'extraction' && <ExtractionHub />}
          {activeTab === 'rules' && <RulesExplorer domain={domain} />}
          {activeTab === 'skills' && <SkillsRegistry domain={domain} />}
          {activeTab === 'elicitation' && <ElicitationHub />}
        </Suspense>
      </div>
    </div>
  );
}
