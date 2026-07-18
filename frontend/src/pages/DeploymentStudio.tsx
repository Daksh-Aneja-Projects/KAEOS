/**
 * KAEOS - Deployment Studio
 * The 4-step wizard - the core Department-as-a-Service experience.
 *
 * Step 1: Select Department Pack - Cards from GET /workforce/packs/
 * Step 2: Connect Systems - Required/optional integrations
 * Step 3: Review Workforce - Preview agents, capabilities, processes
 * Step 4: Deploy - Progress bar tracking the 8-state FSM
 *
 * API: GET /workforce/packs/ → POST /workforce/deployments/start → poll GET /workforce/deployments/{id}
 */
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';
import DomainIcon from '../components/DomainIcon';
import {
  Package, Plug, Eye, Rocket, CheckCircle, ArrowRight, ArrowLeft,
  Shield, Bot, Zap, AlertTriangle, Loader2, Users
} from 'lucide-react';

type Step = 1 | 2 | 3 | 4;

export default function DeploymentStudio({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(1);
  const [packs, setPacks] = useState<any[]>([]);
  const [selectedPack, setSelectedPack] = useState<any>(null);
  const [connectors, setConnectors] = useState<any[]>([]);
  const [employeeCount, setEmployeeCount] = useState(0);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [deployStatus, setDeployStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<any>(null);

  useEffect(() => {
    Promise.all([
      api.getDomainPacks().catch(() => ({ packs: [] })),
      api.getConnectors().catch(() => ({ connectors: [] })),
    ]).then(([p, c]) => {
      setPacks(p?.packs || []);
      setConnectors(c?.connectors || []);
      setLoading(false);
    });
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const startDeployment = async () => {
    if (!selectedPack) return;
    setDeploying(true);
    setError(null);
    try {
      const result = await api.startDeployment({
        domain_pack_id: selectedPack.id,
        domain_pack_slug: selectedPack.slug,
        selected_capabilities: (selectedPack.capabilities || []).map((c: any) => c.id || c.name),
        connected_systems: connectors.filter(c => c.status === 'CONNECTED').map(c => c.id),
        employee_count: employeeCount,
      });
      setDeploymentId(result.id);
      setStep(4);
      // The backend DeploymentStudio pipeline is the SINGLE OWNER of the FSM and
      // auto-advances through all states in the background (see Task 7). The UI
      // only polls for live step progress - it does NOT drive the state machine.
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getDeployment(result.id);
          setDeployStatus(status);
          if (status.status === 'ACTIVE' || status.status === 'FAILED' || status.status === 'ROLLED_BACK') {
            clearInterval(pollRef.current);
            setDeploying(false);
          }
        } catch { /* keep polling */ }
      }, 2000);
    } catch (e: any) {
      setError(e.message);
      setDeploying(false);
    }
  };

  const steps = [
    { num: 1, label: 'Select Pack', icon: Package },
    { num: 2, label: 'Connect Systems', icon: Plug },
    { num: 3, label: 'Review', icon: Eye },
    { num: 4, label: 'Deploy', icon: Rocket },
  ];

  const card = { background: colors.surface1, borderRadius: '12px', border: `1px solid ${colors.hairline}`, padding: '20px' };

  if (loading) return <BrainLoading message="Loading deployment studio..." />;

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-[24px] font-bold tracking-tight">Deploy Department</h1>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
            Department-as-a-Service - select a pack, connect systems, and deploy.
          </p>
        </div>

        {/* Step Indicator */}
        <div className="flex items-center gap-2">
          {steps.map((s, i) => (
            <React.Fragment key={s.num}>
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg transition-all"
                style={{
                  background: step >= s.num ? colors.primary + '15' : colors.surface1,
                  color: step >= s.num ? colors.primary : colors.inkSubtle,
                  border: `1px solid ${step >= s.num ? colors.primary + '30' : colors.hairline}`,
                }}>
                {step > s.num ? <CheckCircle className="w-4 h-4" /> : <s.icon className="w-4 h-4" />}
                <span className="text-[12px] font-medium">{s.label}</span>
              </div>
              {i < steps.length - 1 && <ArrowRight className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />}
            </React.Fragment>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[12px]" style={{ background: '#ef444415', color: '#ef4444', border: '1px solid #ef444430' }}>
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        )}

        {/* Step 1: Select Pack */}
        {step === 1 && (
          <div className="space-y-4">
            <h2 className="text-[16px] font-semibold">Choose a Department Pack</h2>
            {packs.length === 0 ? (
              <BrainEmpty title="No domain packs available" action="Domain packs are loaded at startup. Check backend configuration." />
            ) : (
              <div className="grid grid-cols-2 gap-4">
                {packs.map(pack => (
                  <div key={pack.id} onClick={() => setSelectedPack(pack)}
                    className="cursor-pointer transition-all hover:shadow-lg"
                    style={{
                      ...card,
                      border: selectedPack?.id === pack.id ? `2px solid ${colors.primary}` : `1px solid ${colors.hairline}`,
                    }}>
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <DomainIcon hint={pack.slug || pack.icon} fallbackHint={pack.name} size={48} />
                        <div>
                          <h3 className="text-[16px] font-bold">{pack.name}</h3>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>v{pack.version}</span>
                            <span className="text-[10px]" style={{ color: colors.inkSubtle }}>by {pack.author}</span>
                          </div>
                        </div>
                      </div>
                      {selectedPack?.id === pack.id && <CheckCircle className="w-5 h-5" style={{ color: colors.primary }} />}
                    </div>
                    <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>{pack.description}</p>
                    <div className="flex items-center gap-4 text-[10px]" style={{ color: colors.inkSubtle }}>
                      <span className="flex items-center gap-1"><Zap className="w-3 h-3" /> {(pack.capabilities || []).length} capabilities</span>
                      <span className="flex items-center gap-1"><Bot className="w-3 h-3" /> {(pack.agent_definitions || []).length} agents</span>
                      {(pack.compliance_frameworks || []).length > 0 && (
                        <span className="flex items-center gap-1"><Shield className="w-3 h-3" /> {pack.compliance_frameworks.join(', ')}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="flex justify-end">
              <button onClick={() => selectedPack && setStep(2)} disabled={!selectedPack}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white disabled:opacity-40"
                style={{ background: colors.primary }}>
                Continue <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Connect Systems */}
        {step === 2 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Connect Systems</h2>
              <button onClick={() => setStep(1)} className="text-[12px] flex items-center gap-1" style={{ color: colors.inkSubtle }}>
                <ArrowLeft className="w-3 h-3" /> Back
              </button>
            </div>
            <div className="space-y-3">
              {/* Required Integrations */}
              {(selectedPack?.required_integrations || []).length > 0 && (
                <div style={card}>
                  <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} /> Required Integrations
                  </h3>
                  <div className="grid grid-cols-2 gap-3">
                    {(selectedPack?.required_integrations || []).map((req: any, i: number) => {
                      const connected = connectors.find(c => c.category === req.category && c.status === 'CONNECTED');
                      return (
                        <div key={i} className="flex items-center gap-3 p-3 rounded-lg border" style={{ borderColor: colors.hairline }}>
                          <Plug className="w-4 h-4" style={{ color: connected ? '#22c55e' : '#f59e0b' }} />
                          <div className="flex-1">
                            <div className="text-[12px] font-medium capitalize">{req.category}</div>
                            <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{(req.examples || []).join(', ')}</div>
                          </div>
                          {connected ? (
                            <span className="flex items-center gap-1 text-[10px] font-bold" style={{ color: '#22c55e' }}><CheckCircle className="w-3 h-3" /> {connected.name}</span>
                          ) : (
                            <button onClick={() => navigate('/integrations')} className="px-2 py-1 rounded text-[10px] font-medium" style={{ background: '#f59e0b15', color: '#f59e0b' }}>Connect</button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {/* Employee Count */}
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-2">Employee Count</h3>
                <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>How many employees will this department serve?</p>
                <input type="number" value={employeeCount} onChange={e => setEmployeeCount(parseInt(e.target.value) || 0)}
                  className="px-3 py-2 rounded-lg border text-[13px] w-40" style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
              </div>
            </div>
            <div className="flex justify-end">
              <button onClick={() => setStep(3)}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
                style={{ background: colors.primary }}>
                Review Workforce <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Review */}
        {step === 3 && selectedPack && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Review Workforce Configuration</h2>
              <button onClick={() => setStep(2)} className="text-[12px] flex items-center gap-1" style={{ color: colors.inkSubtle }}>
                <ArrowLeft className="w-3 h-3" /> Back
              </button>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {/* Pack Summary */}
              <div style={card}>
                <DomainIcon hint={selectedPack.slug || selectedPack.icon} fallbackHint={selectedPack.name} size={44} />
                <h3 className="text-[15px] font-bold mt-2">{selectedPack.name}</h3>
                <p className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>{selectedPack.description}</p>
                <div className="mt-3 flex items-center gap-1 text-[10px]" style={{ color: colors.inkSubtle }}>
                  <Users className="w-3 h-3" /> {employeeCount.toLocaleString()} employees
                </div>
              </div>
              {/* Capabilities */}
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-2 flex items-center gap-1"><Zap className="w-4 h-4" style={{ color: '#f59e0b' }} /> Capabilities ({(selectedPack.capabilities || []).length})</h3>
                <div className="space-y-1.5">
                  {(selectedPack.capabilities || []).map((cap: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[12px]">
                      <CheckCircle className="w-3 h-3" style={{ color: '#22c55e' }} />
                      {cap.name || cap}
                    </div>
                  ))}
                </div>
              </div>
              {/* Agents */}
              <div style={card}>
                <h3 className="text-[13px] font-semibold mb-2 flex items-center gap-1"><Bot className="w-4 h-4" style={{ color: '#8b5cf6' }} /> Agents ({(selectedPack.agent_definitions || []).length})</h3>
                <div className="space-y-1.5">
                  {(selectedPack.agent_definitions || []).map((agent: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-[12px]">
                      <Bot className="w-3 h-3" style={{ color: colors.primary }} />
                      {agent.name || agent}
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={startDeployment} disabled={deploying}
                className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-[13px] font-bold text-white disabled:opacity-50"
                style={{ background: `linear-gradient(135deg, #22c55e, #16a34a)` }}>
                {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
                {deploying ? 'Deploying...' : 'Deploy Department'}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Deployment Progress */}
        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-[16px] font-semibold">Deployment in Progress</h2>
            <div style={card}>
              {/* Progress bar */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[12px] font-medium">{deployStatus?.current_step || 'Initializing...'}</span>
                  <span className="text-[12px] font-mono" style={{ color: colors.primary }}>{(deployStatus?.progress_pct || 0).toFixed(0)}%</span>
                </div>
                <div className="h-3 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                  <div className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${deployStatus?.progress_pct || 0}%`, background: `linear-gradient(90deg, ${colors.primary}, #22c55e)` }} />
                </div>
              </div>
              {/* Status */}
              <div className="flex items-center gap-2 mb-4">
                {deployStatus?.status === 'ACTIVE' ? (
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>
                    <CheckCircle className="w-3.5 h-3.5" /> Deployment Complete!
                  </span>
                ) : deployStatus?.status === 'FAILED' ? (
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold" style={{ background: '#ef444420', color: '#ef4444' }}>
                    <AlertTriangle className="w-3.5 h-3.5" /> Deployment Failed
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold" style={{ background: colors.primary + '20', color: colors.primary }}>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> {deployStatus?.status || 'INIT'}
                  </span>
                )}
              </div>
              {/* Step log */}
              <div className="space-y-1">
                {(deployStatus?.deployment_steps || []).map((s: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    {s.status === 'COMPLETED' ? (
                      <CheckCircle className="w-3 h-3 flex-shrink-0" style={{ color: '#22c55e' }} />
                    ) : (
                      <Loader2 className="w-3 h-3 flex-shrink-0 animate-spin" style={{ color: colors.primary }} />
                    )}
                    <span style={{ color: s.status === 'COMPLETED' ? colors.ink : colors.inkSubtle }}>{s.step}</span>
                    {s.completed_at && <span className="font-mono text-[9px]" style={{ color: colors.inkSubtle }}>{new Date(s.completed_at).toLocaleTimeString()}</span>}
                  </div>
                ))}
              </div>
              {/* Error log */}
              {(deployStatus?.error_log || []).length > 0 && (
                <div className="mt-3 space-y-1">
                  {deployStatus.error_log.map((err: any, i: number) => (
                    <div key={i} className="text-[11px] px-3 py-1.5 rounded" style={{ background: '#ef444410', color: '#ef4444' }}>
                      [{err.step}] {err.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
            {deployStatus?.status === 'ACTIVE' && (
              <div className="flex justify-end">
                <button onClick={() => navigate('/')} className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white" style={{ background: colors.primary }}>
                  View Workforce <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
