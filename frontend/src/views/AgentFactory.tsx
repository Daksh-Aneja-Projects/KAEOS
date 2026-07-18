import React, { useEffect, useState } from 'react';
import { Bot, Plus, Play, Square, Pause, CheckCircle2, Clock, AlertTriangle, Sparkles, Send, ChevronRight, Loader2, Workflow } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import DeployConfigModal from '../components/DeployConfigModal';
import type { DeployConfig } from '../components/DeployConfigModal';

const AgentFactory: React.FC<{ domain?: string }> = ({ domain = 'All Domains' }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<'create' | 'blueprints' | 'deployed'>('create');
  const [prompt, setPrompt] = useState('');
  const [creating, setCreating] = useState(false);
  const [blueprints, setBlueprints] = useState<any[]>([]);
  const [deployed, setDeployed] = useState<any[]>([]);
  const [selectedBp, setSelectedBp] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [deployTarget, setDeployTarget] = useState<any>(null);

  const loadData = async () => {
    setLoading(true);
    const [bp, dp] = await Promise.allSettled([api.listBlueprints(), api.listDeployedAgents()]);
    if (bp.status === 'fulfilled') setBlueprints(bp.value?.blueprints || []);
    if (dp.status === 'fulfilled') setDeployed(dp.value?.agents || []);
    setLoading(false);
  };

  useEffect(() => { loadData(); }, []);

  const handleCreate = async () => {
    if (!prompt.trim()) return;
    setCreating(true);
    try {
      const res = await api.createBlueprint(prompt);
      if (res?.blueprint) { setSelectedBp(res.blueprint); setTab('blueprints'); }
      await loadData();
      setPrompt('');
    } catch (e) { console.error(e); }
    setCreating(false);
  };

  const handleApprove = async (id: string) => {
    await api.approveBlueprint(id, 'admin');
    await loadData();
  };

  const handleCompile = async (id: string) => {
    await api.compileBlueprint(id);
    await loadData();
  };

  const handleDeploy = async (id: string, config?: DeployConfig) => {
    await api.deployBlueprint(id, config ? { risk_level: config.risk_level, confidence_threshold: config.confidence_threshold, hitl_mode: config.hitl_mode, hitl_threshold: config.hitl_threshold } : undefined);
    setDeployTarget(null);
    await loadData();
    setTab('deployed');
  };

  const handleStop = async (id: string) => {
    await api.stopAgent(id);
    await loadData();
  };

  const statusBadge = (s: string) => {
    const map: Record<string, { bg: string; text: string }> = {
      DRAFT: { bg: 'rgba(138,143,152,0.12)', text: colors.inkSubtle },
      APPROVED: { bg: 'rgba(94,106,210,0.12)', text: colors.primaryHover },
      COMPILED: { bg: 'rgba(83,155,245,0.12)', text: colors.info },
      DEPLOYED: { bg: 'rgba(39,166,68,0.12)', text: colors.success },
      RUNNING: { bg: 'rgba(39,166,68,0.12)', text: colors.success },
      STOPPED: { bg: 'rgba(229,83,75,0.12)', text: colors.error },
      PAUSED: { bg: 'rgba(245,166,35,0.12)', text: colors.warning },
    };
    const c = map[s] || map.DRAFT;
    return <span className="text-[11px] font-medium px-2 py-0.5 rounded-full" style={{ background: c.bg, color: c.text }}>{s}</span>;
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>Agent Factory</h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>Build, compile, and deploy agents from natural language</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {(['create', 'blueprints', 'deployed'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="px-4 py-1.5 rounded-md text-[13px] font-medium transition-all"
            style={{ background: tab === t ? colors.primary : 'transparent', color: tab === t ? '#fff' : colors.inkSubtle }}>
            {t === 'create' ? 'Create Agent' : t === 'blueprints' ? `Blueprints (${blueprints.length})` : `Deployed (${deployed.length})`}
          </button>
        ))}
      </div>

      {/* Create Tab */}
      {tab === 'create' && (
        <div className="rounded-xl p-6" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="w-5 h-5" style={{ color: colors.primary }} />
            <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Describe your agent</span>
          </div>
          <p className="text-[13px] mb-4" style={{ color: colors.inkSubtle }}>
            Tell us what you need in plain language. The Blueprint Generator will decompose it into a DAG of tasks, wire Company Brain context, and produce an approval-ready blueprint.
          </p>
          <div className="relative">
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={4} placeholder="e.g. Create a compliance review agent that checks all new hire contracts against our employment policies, flags GDPR issues, and notifies Legal via Slack..."
              className="w-full rounded-lg p-4 pr-14 text-[14px] resize-none outline-none transition-all"
              style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
              onFocus={e => (e.target.style.borderColor = colors.primary)}
              onBlur={e => (e.target.style.borderColor = colors.hairline)} />
            <button onClick={handleCreate} disabled={creating || !prompt.trim()}
              className="absolute bottom-3 right-3 w-9 h-9 rounded-lg flex items-center justify-center transition-all disabled:opacity-30"
              style={{ background: colors.primary, color: '#fff' }}>
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {/* Blueprints Tab */}
      {tab === 'blueprints' && (
        <div className="space-y-3">
          {blueprints.length === 0 && !loading && (
            <div className="rounded-xl p-12 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <Bot className="w-10 h-10 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
              <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>No blueprints yet</p>
              <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>Create your first agent above</p>
            </div>
          )}
          {blueprints.map(bp => (
            <div key={bp.id} className="rounded-xl p-5 transition-all duration-200"
              style={{ background: colors.surface1, border: `1px solid ${selectedBp?.id === bp.id ? colors.primary : colors.hairline}` }}
              onClick={() => setSelectedBp(bp)}>
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[15px] font-medium" style={{ color: colors.ink }}>{bp.name || bp.id?.slice(0, 8)}</span>
                    {statusBadge(bp.status)}
                  </div>
                  {(bp.description || bp.original_prompt) && (
                    <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{(bp.description || bp.original_prompt).slice(0, 120)}…</p>
                  )}
                  {(() => {
                    const nodes = bp.blueprint_graph?.nodes || bp.dag_nodes;
                    return nodes?.length
                      ? <p className="text-[11px] mt-2" style={{ color: colors.inkTertiary }}>{nodes.length} tasks in pipeline</p>
                      : null;
                  })()}
                </div>
                <div className="flex gap-2 ml-4">
                  {['BLUEPRINT_READY', 'DRAFTING', 'DRAFT'].includes(bp.status) && (
                    <button onClick={(e) => { e.stopPropagation(); handleApprove(bp.id); }}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                      style={{ background: 'rgba(94,106,210,0.12)', color: colors.primaryHover }}>
                      <CheckCircle2 className="w-3 h-3" /> Approve
                    </button>
                  )}
                  {bp.status === 'APPROVED' && (
                    <button onClick={(e) => { e.stopPropagation(); handleCompile(bp.id); }}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                      style={{ background: 'rgba(83,155,245,0.12)', color: colors.info }}>
                      <Workflow className="w-3 h-3" /> Compile
                    </button>
                  )}
                  {bp.status === 'COMPILED' && (
                    <button onClick={(e) => { e.stopPropagation(); setDeployTarget(bp); }}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                      style={{ background: 'rgba(39,166,68,0.12)', color: colors.success }}>
                      <Play className="w-3 h-3" /> Deploy
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Deployed Tab */}
      {tab === 'deployed' && (
        <div className="space-y-3">
          {deployed.length === 0 && !loading && (
            <div className="rounded-xl p-12 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <Bot className="w-10 h-10 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
              <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>No deployed agents</p>
            </div>
          )}
          {deployed.map(ag => (
            <div key={ag.id} className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: ag.status === 'RUNNING' ? 'rgba(39,166,68,0.12)' : 'rgba(229,83,75,0.12)' }}>
                    <Bot className="w-4 h-4" style={{ color: ag.status === 'RUNNING' ? colors.success : colors.error }} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium" style={{ color: colors.ink }}>{ag.agent_name || ag.id?.slice(0, 12)}</span>
                      {statusBadge(ag.status)}
                    </div>
                    <p className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>
                      {ag.total_executions || 0} executions · {ag.success_count || 0} success
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  {ag.status === 'RUNNING' && (
                    <button onClick={() => handleStop(ag.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                      style={{ background: 'rgba(229,83,75,0.12)', color: colors.error }}>
                      <Square className="w-3 h-3" /> Stop
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Deploy Config Modal */}
      {deployTarget && (
        <DeployConfigModal
          blueprintId={deployTarget.id}
          blueprintName={deployTarget.name || deployTarget.id?.slice(0, 12)}
          colors={colors}
          onDeploy={(config) => handleDeploy(deployTarget.id, config)}
          onCancel={() => setDeployTarget(null)}
        />
      )}
    </div>
  );
};

export default AgentFactory;
