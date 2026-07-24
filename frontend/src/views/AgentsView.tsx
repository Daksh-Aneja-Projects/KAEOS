import React, { useState, Suspense, lazy } from 'react';
import { useTheme } from '../context/ThemeContext';
import { Rocket, Wrench, ShoppingBag, Activity, Swords, CircuitBoard, Target } from 'lucide-react';

// "Agent Fleet" (AgentMonitor) read the same skills+executions as the Knowledge
// "Skill Builder" (SkillsRegistry) — the single home for skills & their runs.
const AgentFactory = lazy(() => import('../views/AgentFactory'));
const MissionControl = lazy(() => import('../pages/MissionControl'));
const MCPToolManager = lazy(() => import('../pages/MCPToolManager'));
const Marketplace = lazy(() => import('../pages/Marketplace'));
const ConflictArena = lazy(() => import('../pages/ConflictArena'));
const OODAMonitor = lazy(() => import('../pages/OODAMonitor'));
const InfrastructureDashboard = lazy(() => import('../pages/InfrastructureDashboard'));

export default function AgentsView({ domain }: { domain: string }) {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState('deployment');

  const tabs = [
    { id: 'deployment', label: 'Agent Deployment', icon: Rocket },
    { id: 'missions', label: 'Missions', icon: Target },
    { id: 'ooda', label: 'OODA Monitor', icon: Activity },
    { id: 'infrastructure', label: 'Infrastructure', icon: CircuitBoard },
    { id: 'mcp', label: 'MCP Tools', icon: Wrench },
    { id: 'marketplace', label: 'Skill Templates', icon: ShoppingBag },
    { id: 'conflict', label: 'Conflict Arena', icon: Swords }
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
        <Suspense fallback={<div className="p-8 text-inkSubtle animate-pulse text-[13px]">Loading Agents Module...</div>}>
          {activeTab === 'deployment' && <AgentFactory domain={domain} />}
          {activeTab === 'missions' && <MissionControl domain={domain} />}
          {activeTab === 'ooda' && <OODAMonitor domain={domain} />}
          {activeTab === 'infrastructure' && <InfrastructureDashboard domain={domain} />}
          {activeTab === 'mcp' && <MCPToolManager />}
          {activeTab === 'marketplace' && <Marketplace />}
          {activeTab === 'conflict' && <ConflictArena />}
        </Suspense>
      </div>
    </div>
  );
}
