import React, { useEffect, useState } from 'react';
import { Settings as SettingsIcon, Cpu, Plug, Calendar, Globe2, Shield, RefreshCw, Save, Check, ExternalLink, Moon, Sun } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';

const SettingsView: React.FC<{ domain?: string }> = ({ domain }) => {
  const { colors, theme, toggle } = useTheme();
  const [tab, setTab] = useState<'llm' | 'integrations' | 'calendar' | 'platform'>('llm');
  const [llmConfig, setLlmConfig] = useState<any>(null);
  const [connectors, setConnectors] = useState<any[]>([]);
  const [calEvents, setCalEvents] = useState<any[]>([]);
  const [platformStats, setPlatformStats] = useState<any>(null);
  const [autonomy, setAutonomyRows] = useState<any[]>([]);
  const [savingDomain, setSavingDomain] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState<string | null>(null);

  const updateAutonomy = async (d: string, val: number) => {
    setSavingDomain(d);
    try {
      await api.setAutonomy(d, val);
      setAutonomyRows(prev => prev.map(r => (r.domain === d ? { ...r, min_confidence: val, is_default: false } : r)));
    } catch (e) {
      console.error('Autonomy update failed', e);
    } finally {
      setSavingDomain(null);
    }
  };

  const runProbe = async (layer: string) => {
    setProbing(layer);
    try {
      const res = await api.probeLLMModel(layer);
      setLlmConfig((prev: any) =>
        (Array.isArray(prev) ? prev : []).map((c: any) =>
          c.layer === layer ? { ...c, capability_profile: res.profile } : c
        )
      );
    } catch (e) {
      console.error('Model probe failed', e);
    } finally {
      setProbing(null);
    }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      const [l, c, cal, p, a] = await Promise.allSettled([
        api.getLLMConfig(),
        api.getConnectors(),
        api.getCalendarEvents(),
        api.getSystemStats(),
        api.getAutonomy(),
      ]);
      if (l.status === 'fulfilled') setLlmConfig(l.value);
      if (c.status === 'fulfilled') setConnectors(c.value?.connectors || []);
      if (cal.status === 'fulfilled') setCalEvents(cal.value?.events || []);
      if (p.status === 'fulfilled') setPlatformStats(p.value);
      if (a.status === 'fulfilled') setAutonomyRows(a.value || []);
      setLoading(false);
    })();
  }, []);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>Settings</h1>
        <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>LLM routing, integrations, enterprise calendar, and platform config</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {([['llm', 'LLM Routing', Cpu], ['integrations', 'Integrations', Plug], ['calendar', 'Calendar', Calendar], ['platform', 'Platform', Globe2]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id as any)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition-all"
            style={{ background: tab === id ? colors.primary : 'transparent', color: tab === id ? '#fff' : colors.inkSubtle }}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {/* LLM Routing */}
      {tab === 'llm' && (
        <div className="space-y-4">
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-1">
              <Cpu className="w-5 h-5" style={{ color: colors.primary }} />
              <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Model Tier Routing (BYOK)</span>
            </div>
            <p className="text-[13px] mb-4" style={{ color: colors.inkSubtle }}>
              Which model powers each routing tier. Bring your own model - KAEOS probes it and adapts:
              the capability score caps how much autonomy that model is granted, so a weaker model
              automatically routes more decisions to human review. Keys are encrypted server-side and never displayed.
            </p>
            <div className="space-y-3">
              {(Array.isArray(llmConfig) ? llmConfig : []).map((cfg: any) => {
                const tierMeta: Record<string, { label: string; desc: string; color: string }> = {
                  TIER_1_COMPLEX: { label: 'Complex Reasoning', desc: 'Debates, fairness scoring, blueprint generation', color: '#8b5cf6' },
                  TIER_2_STANDARD: { label: 'Standard', desc: 'Extraction, summarization, explainability', color: '#06b6d4' },
                  TIER_3_FAST: { label: 'Fast', desc: 'Intent routing, formatting, simple operations', color: '#22c55e' },
                  TIER_EMBEDDING: { label: 'Embeddings', desc: 'Vector search and retrieval', color: '#f59e0b' },
                };
                const meta = tierMeta[cfg.layer] || { label: cfg.layer, desc: '', color: colors.primary };
                const keyConfigured = !!cfg.key_configured;
                const profile = cfg.capability_profile || {};
                const ceiling = profile.tier_ceiling;
                const ceilingColor = ceiling == null ? colors.inkTertiary
                  : ceiling >= 0.85 ? '#22c55e' : ceiling >= 0.6 ? '#f59e0b' : '#ef4444';
                return (
                  <div key={cfg.id || cfg.layer} className="p-3.5 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                    <div className="flex items-center gap-4">
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: meta.color + '18' }}>
                        <Cpu className="w-4 h-4" style={{ color: meta.color }} />
                      </div>
                      <div className="w-40 flex-shrink-0">
                        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>{meta.label}</div>
                        <div className="text-[10px] font-mono" style={{ color: colors.inkTertiary }}>{cfg.layer}</div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-[13px] font-mono truncate block" style={{ color: colors.ink }}>{cfg.model_name}</span>
                        <p className="text-[11px] truncate" style={{ color: colors.inkTertiary }}>{meta.desc}</p>
                      </div>
                      <span className="text-[11px] px-2 py-0.5 rounded-full font-medium flex-shrink-0"
                        style={{ background: 'rgba(94,106,210,0.12)', color: colors.primary }}>
                        {cfg.provider}
                      </span>
                      <span className="text-[11px] px-2 py-0.5 rounded-full font-medium flex-shrink-0 flex items-center gap-1"
                        style={{
                          background: keyConfigured ? 'rgba(39,166,68,0.12)' : 'rgba(245,158,11,0.12)',
                          color: keyConfigured ? '#22c55e' : '#f59e0b',
                        }}>
                        <Shield className="w-3 h-3" />
                        {keyConfigured ? 'Key configured' : 'No key (local)'}
                      </span>
                      <button
                        onClick={() => runProbe(cfg.layer)}
                        disabled={probing === cfg.layer}
                        className="text-[11px] px-2.5 py-1 rounded-md font-semibold flex-shrink-0 disabled:opacity-50"
                        style={{ background: meta.color + '18', color: meta.color }}>
                        {probing === cfg.layer ? 'Probing…' : 'Probe model'}
                      </button>
                    </div>

                    {/* Capability profile - what the probe earned this model */}
                    <div className="mt-3 pl-[52px] flex items-center gap-5 flex-wrap">
                      {ceiling != null ? (
                        <>
                          <div>
                            <div className="text-[9px] font-bold uppercase tracking-wide" style={{ color: colors.inkTertiary }}>Autonomy ceiling</div>
                            <div className="text-[14px] font-bold font-mono" style={{ color: ceilingColor }}>{(ceiling * 100).toFixed(0)}%</div>
                          </div>
                          {[['JSON', profile.json_compliance], ['Reasoning', profile.reasoning_depth], ['Instructions', profile.instruction_following]].map(([label, val]: any) => (
                            <div key={label}>
                              <div className="text-[9px] font-bold uppercase tracking-wide" style={{ color: colors.inkTertiary }}>{label}</div>
                              <div className="text-[12px] font-mono" style={{ color: val >= 0.8 ? '#22c55e' : val >= 0.5 ? '#f59e0b' : '#ef4444' }}>
                                {val != null ? `${(val * 100).toFixed(0)}%` : '-'}
                              </div>
                            </div>
                          ))}
                          {profile.latency_ms != null && (
                            <div>
                              <div className="text-[9px] font-bold uppercase tracking-wide" style={{ color: colors.inkTertiary }}>Latency</div>
                              <div className="text-[12px] font-mono" style={{ color: colors.inkSubtle }}>{profile.latency_ms}ms</div>
                            </div>
                          )}
                          {profile.recommendation && (
                            <p className="text-[11px] w-full mt-1" style={{ color: colors.inkSubtle }}>{profile.recommendation}</p>
                          )}
                        </>
                      ) : (
                        <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
                          Not probed yet - this model runs at full autonomy until calibrated.
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
              {(!Array.isArray(llmConfig) || llmConfig.length === 0) && !loading && (
                <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>
                  No routing tiers configured yet.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Integrations */}
      {tab === 'integrations' && (
        <div className="space-y-3">
          {connectors.length === 0 && !loading && (
            <div className="rounded-xl p-12 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <Plug className="w-10 h-10 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
              <p className="text-[14px]" style={{ color: colors.inkSubtle }}>No connectors configured</p>
            </div>
          )}
          {connectors.map((c: any, i: number) => (
            <div key={i} className="rounded-xl p-4 flex items-center justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: c.status === 'ACTIVE' ? 'rgba(39,166,68,0.12)' : colors.surface2 }}>
                  <Plug className="w-4 h-4" style={{ color: c.status === 'ACTIVE' ? colors.success : colors.inkTertiary }} />
                </div>
                <div>
                  <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{c.name || c.connector_type}</span>
                  <p className="text-[11px]" style={{ color: colors.inkTertiary }}>{c.connector_type}</p>
                </div>
              </div>
              <span className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                style={{ background: c.status === 'ACTIVE' ? 'rgba(39,166,68,0.12)' : 'rgba(138,143,152,0.12)', color: c.status === 'ACTIVE' ? colors.success : colors.inkSubtle }}>
                {c.status}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Calendar */}
      {tab === 'calendar' && (
        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 border-b" style={{ borderColor: colors.hairline }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Enterprise Calendar</span>
          </div>
          {calEvents.length === 0 && <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No calendar events configured</div>}
          {calEvents.map((ev: any, i: number) => (
            <div key={i} className="px-5 py-3 border-b flex items-center gap-3" style={{ borderColor: colors.hairline }}>
              <Calendar className="w-4 h-4 flex-shrink-0" style={{ color: ev.is_blocking ? colors.error : colors.info }} />
              <div className="flex-1">
                <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{ev.event_name}</span>
                <p className="text-[11px]" style={{ color: colors.inkTertiary }}>{ev.department} · {ev.event_type}</p>
              </div>
              {ev.is_blocking && <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(229,83,75,0.12)', color: colors.error }}>Blocking</span>}
            </div>
          ))}
        </div>
      )}

      {/* Platform */}
      {tab === 'platform' && (
        <div className="space-y-4">
          {/* Theme Toggle */}
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Appearance</span>
            <div className="flex items-center justify-between mt-3">
              <span className="text-[13px]" style={{ color: colors.inkSubtle }}>Theme</span>
              <button onClick={toggle} className="px-4 py-1.5 rounded-lg text-[13px] font-medium transition-all flex items-center gap-2"
                style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                {theme === 'dark' ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}
                {theme === 'dark' ? 'Dark' : 'Light'}
              </button>
            </div>
          </div>

          {/* Autonomy Dial — per-department risk appetite, wired to Gate 3 */}
          <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Autonomy Dial</span>
            </div>
            <p className="text-[12px] mt-1 mb-4" style={{ color: colors.inkSubtle }}>
              The confidence a department's decisions must clear to run without a human. Higher means more oversight, lower means more autonomy. High-consequence actions always require a human, whatever the dial.
            </p>
            <div className="space-y-3">
              {autonomy.map(a => (
                <div key={a.domain} className="flex items-center gap-4">
                  <div className="w-28 text-[13px] font-medium capitalize" style={{ color: colors.ink }}>{a.domain}</div>
                  <input
                    type="range" min={0.5} max={0.99} step={0.01} value={a.min_confidence}
                    onChange={e => {
                      const v = parseFloat(e.target.value);
                      setAutonomyRows(prev => prev.map(r => (r.domain === a.domain ? { ...r, min_confidence: v } : r)));
                    }}
                    onMouseUp={e => updateAutonomy(a.domain, parseFloat((e.target as HTMLInputElement).value))}
                    onTouchEnd={e => updateAutonomy(a.domain, parseFloat((e.target as HTMLInputElement).value))}
                    className="flex-1 accent-current"
                    style={{ accentColor: colors.primary }}
                  />
                  <div className="w-12 text-right text-[13px] font-mono font-bold" style={{ color: colors.primary }}>
                    {(a.min_confidence * 100).toFixed(0)}%
                  </div>
                  <div className="w-16 text-[10px]" style={{ color: colors.inkSubtle }}>
                    {savingDomain === a.domain ? 'saving…' : a.is_default ? 'default' : 'custom'}
                  </div>
                </div>
              ))}
              {autonomy.length === 0 && (
                <div className="text-[12px] italic" style={{ color: colors.inkSubtle }}>Loading autonomy policy…</div>
              )}
            </div>
          </div>

          {/* System Stats */}
          {platformStats && (
            <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>System Stats</span>
              <div className="mt-3 space-y-2">
                {Object.entries(platformStats).flatMap(([k, v]: [string, any]) =>
                  v && typeof v === 'object' && !Array.isArray(v)
                    ? Object.entries(v).map(([k2, v2]: [string, any]) => [`${k} · ${k2}`, v2] as const)
                    : [[k, v] as const]
                ).map(([k, v]) => (
                  <div key={k} className="flex justify-between py-1 border-b last:border-0" style={{ borderColor: colors.hairline }}>
                    <span className="text-[12px] capitalize" style={{ color: colors.inkSubtle }}>{String(k).replace(/_/g, ' ')}</span>
                    <span className="text-[12px] font-medium font-mono" style={{ color: colors.ink }}>
                      {Array.isArray(v) ? v.length : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SettingsView;
