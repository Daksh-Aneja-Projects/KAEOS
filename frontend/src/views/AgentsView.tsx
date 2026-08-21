import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Rocket, Wrench, ShoppingBag, Activity, Swords, CircuitBoard, Target, BrainCircuit } from 'lucide-react';
import { PAGE_PAD_X } from '../lib/layout';

// "Agent Fleet" (AgentMonitor) read the same skills+executions as the Knowledge
// "Skill Builder" (SkillsRegistry) — the single home for skills & their runs.
const AgentFactory = lazy(() => import('../views/AgentFactory'));
const MissionControl = lazy(() => import('../pages/MissionControl'));
const BrainCommand = lazy(() => import('../pages/BrainCommand'));
const MCPToolManager = lazy(() => import('../pages/MCPToolManager'));
const SkillTemplates = lazy(() => import('../pages/SkillTemplates'));
const ConflictArena = lazy(() => import('../pages/ConflictArena'));
const OODAMonitor = lazy(() => import('../pages/OODAMonitor'));
const InfrastructureDashboard = lazy(() => import('../pages/InfrastructureDashboard'));

export default function AgentsView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('deployment');

  const tabs = [
    { id: 'deployment', label: 'Agent Deployment', icon: Rocket },
    { id: 'missions', label: 'Missions', icon: Target },
    { id: 'brain', label: 'Company Brain', icon: BrainCircuit },
    { id: 'ooda', label: 'OODA Monitor', icon: Activity },
    { id: 'infrastructure', label: 'Infrastructure', icon: CircuitBoard },
    { id: 'mcp', label: 'MCP Tools', icon: Wrench },
    { id: 'skill-templates', label: 'Skill Templates', icon: ShoppingBag },
    { id: 'conflict', label: 'Conflict Arena', icon: Swords }
  ];

  // ArrowLeft / ArrowRight move between tabs, then focus follows selection.
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = tabs[(tabs.findIndex(t => t.id === activeTab) + step + tabs.length) % tabs.length];
    setActiveTab(next.id);
    document.getElementById(`agents-tab-${next.id}`)?.focus();
  };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`flex items-center gap-6 ${PAGE_PAD_X} border-b overflow-x-auto no-scrollbar`}
        role="tablist" aria-label="Agents sections" onKeyDown={onTabKeyDown}
        style={{ borderColor: colors.hairline, background: colors.surface1, minHeight: '48px' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            id={`agents-tab-${tab.id}`}
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
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Agents Module...</div>}>
          {activeTab === 'deployment' && <AgentFactory domain={domain} />}
          {activeTab === 'missions' && <MissionControl domain={domain} />}
          {activeTab === 'brain' && <BrainCommand />}
          {activeTab === 'ooda' && <OODAMonitor domain={domain} />}
          {activeTab === 'infrastructure' && <InfrastructureDashboard domain={domain} />}
          {activeTab === 'mcp' && <MCPToolManager />}
          {activeTab === 'skill-templates' && <SkillTemplates />}
          {activeTab === 'conflict' && <ConflictArena />}
        </Suspense>
      </div>
    </div>
  );
}
