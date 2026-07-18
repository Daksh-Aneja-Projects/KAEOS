import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Database, BookOpen, Workflow, Network, FileSearch, Users, UploadCloud, Plug } from 'lucide-react';

const ConnectorStudio = lazy(() => import('../pages/ConnectorStudio'));
const IntegrationsHub = lazy(() => import('../pages/IntegrationsHub'));
const RulesExplorer = lazy(() => import('../pages/RulesExplorer'));
const SkillsRegistry = lazy(() => import('../pages/SkillsRegistry'));
const TopologyVisualizer = lazy(() => import('../pages/TopologyVisualizer'));
const ExtractionHub = lazy(() => import('../pages/ExtractionHub'));
const ElicitationHub = lazy(() => import('../pages/ElicitationHub'));
const BYOKView = lazy(() => import('../pages/BYOKView'));

export default function KnowledgeView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('connector-studio');

  const tabs = [
    { id: 'connector-studio', label: 'Connector Studio', icon: Plug },
    { id: 'integrations', label: 'System Connections', icon: Database },
    { id: 'byok', label: 'Bring Your Own Knowledge', icon: UploadCloud },
    { id: 'topology', label: 'Topology Map', icon: Network },
    { id: 'extraction', label: 'Extraction Pipeline', icon: FileSearch },
    { id: 'rules', label: 'Discovered Rules', icon: BookOpen },
    { id: 'skills', label: 'Skill Builder', icon: Workflow },
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
          {activeTab === 'connector-studio' && <ConnectorStudio domain={domain} />}
          {activeTab === 'integrations' && <IntegrationsHub domain={domain} />}
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
