import React, { useCallback, useEffect, useState } from 'react';
import { Bot, Loader2, Play, Plus, RefreshCw, Trash2, Zap } from 'lucide-react';
import { api } from '../api/client';
import type { AutomationRule, WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import LiveBadge from '../components/LiveBadge';

/**
 * Automation rules (Sprint 8): declarative "when an entity sits in a state
 * past N hours, do X" rules. The builder is driven by the live workflow specs
 * so the state/target dropdowns only ever offer legal choices; the backend
 * validates again on save.
 */

const DOMAINS = ['finance', 'hr', 'sales', 'support', 'operations', 'legal', 'engineering'];

const MyAutomation: React.FC<{ domain?: string }> = () => {
  const { colors } = useTheme();
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [specs, setSpecs] = useState<Record<string, WorkflowSpec>>({});
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);

  // Builder state
  const [name, setName] = useState('');
  const [entityType, setEntityType] = useState('');
  const [triggerState, setTriggerState] = useState('');
  const [dwellHours, setDwellHours] = useState(24);
  const [actionType, setActionType] = useState<'transition' | 'assign' | 'escalate'>('escalate');
  const [toState, setToState] = useState('');
  const [assignee, setAssignee] = useState('');
  const [saving, setSaving] = useState(false);

  const loadRules = useCallback(async () => {
    try { setRules(await api.getAutomationRules()); setLastSync(Date.now()); } catch { /* noop */ }
    setLoading(false);
  }, []);

  const loadSpecs = useCallback(async () => {
    const merged: Record<string, WorkflowSpec> = {};
    const results = await Promise.allSettled(DOMAINS.map(d => api.getDomainWorkflows(d)));
    results.forEach(r => { if (r.status === 'fulfilled') Object.assign(merged, r.value); });
    setSpecs(merged);
  }, []);

  useEffect(() => { loadRules(); loadSpecs(); }, [loadRules, loadSpecs]);

  const spec = specs[entityType];
  const states = spec?.states || [];
  const targets = spec && triggerState ? (spec.transitions[triggerState] || []) : [];

  const create = async () => {
    if (!name.trim() || !entityType || !triggerState) { setMsg('Name, entity and trigger state are required.'); return; }
    setSaving(true); setMsg('');
    try {
      await api.createAutomationRule({
        name: name.trim(), entity_type: entityType, trigger_state: triggerState,
        dwell_hours: dwellHours, action_type: actionType,
        action_to_state: actionType === 'transition' ? toState : null,
        action_assignee: actionType === 'assign' ? assignee.trim() : null,
      });
      setName(''); setTriggerState(''); setToState(''); setAssignee('');
      setMsg('Rule created.');
      await loadRules();
    } catch (e: any) { setMsg(`Create failed: ${e?.message || e}`); }
    finally { setSaving(false); }
  };

  const runAll = async () => {
    setRunning(true); setMsg('');
    try {
      const res = await api.runAutomationRules();
      setMsg(`Evaluated ${res.rules_evaluated} rule(s), fired ${res.actions_fired} action(s).`);
      await loadRules();
    } catch (e: any) { setMsg(`Run failed: ${e?.message || e}`); }
    finally { setRunning(false); }
  };

  const toggle = async (r: AutomationRule) => {
    try { await api.toggleAutomationRule(r.id, !r.is_active); await loadRules(); } catch { /* noop */ }
  };
  const remove = async (r: AutomationRule) => {
    try { await api.deleteAutomationRule(r.id); await loadRules(); } catch { /* noop */ }
  };

  const inputStyle = { background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6" style={{ color: colors.ink }}>
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight flex items-center gap-2">
            <Zap className="w-6 h-6" style={{ color: '#f59e0b' }} /> Automation
          </h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
            When an entity sits in a state past a threshold, act automatically - transition, assign, or escalate
          </p>
        </div>
        <div className="flex items-center gap-2">
          <LiveBadge lastSync={lastSync} />
          <button onClick={runAll} disabled={running}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50"
            style={{ background: colors.primary }}>
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Run all now
          </button>
          <button onClick={loadRules} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {msg && (
        <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium"
          style={{ background: msg.includes('failed') ? '#ef444415' : '#22c55e15', color: msg.includes('failed') ? '#ef4444' : '#22c55e' }}>
          {msg}
        </div>
      )}

      {/* Builder */}
      <div className="rounded-xl p-5 space-y-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <h2 className="text-[13px] font-bold flex items-center gap-1.5"><Plus className="w-4 h-4" /> New rule</h2>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Rule name"
            className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} />
          <select value={entityType} onChange={e => { setEntityType(e.target.value); setTriggerState(''); setToState(''); }}
            className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
            <option value="">Entity type…</option>
            {Object.keys(specs).map(k => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
          </select>
          <select value={triggerState} onChange={e => setTriggerState(e.target.value)} disabled={!spec}
            className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
            <option value="">When in state…</option>
            {states.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
          <label className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkSubtle }}>
            for &gt;
            <input type="number" value={dwellHours} min={0} onChange={e => setDwellHours(Number(e.target.value))}
              className="w-20 px-2 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} /> hours
          </label>
          <select value={actionType} onChange={e => setActionType(e.target.value as any)}
            className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
            <option value="escalate">→ escalate (alert)</option>
            <option value="transition">→ transition to…</option>
            <option value="assign">→ assign to…</option>
          </select>
          {actionType === 'transition' && (
            <select value={toState} onChange={e => setToState(e.target.value)}
              className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
              <option value="">Target state…</option>
              {targets.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
          )}
          {actionType === 'assign' && (
            <input value={assignee} onChange={e => setAssignee(e.target.value)} placeholder="assignee"
              className="px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} />
          )}
        </div>
        <button onClick={create} disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50"
          style={{ background: colors.primary }}>
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create rule
        </button>
      </div>

      {/* Rule list */}
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {loading ? (
          <div className="flex items-center justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" style={{ color: colors.primary }} /></div>
        ) : rules.length === 0 ? (
          <p className="text-[12px] py-10 text-center" style={{ color: colors.inkTertiary }}>No automation rules yet.</p>
        ) : (
          <table className="w-full text-[12px]">
            <thead><tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
              {['Rule', 'When', 'Action', 'Fired', 'Active', ''].map(h => (
                <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {rules.map(r => (
                <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className="px-4 py-3 font-medium">{r.name}</td>
                  <td className="px-4 py-3 font-mono text-[11px]" style={{ color: colors.inkSubtle }}>
                    {r.entity_type.replace(/_/g, ' ')} in {r.trigger_state} &gt; {r.dwell_hours}h
                  </td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1"><Bot className="w-3 h-3" style={{ color: colors.primary }} />
                      {r.action_type === 'transition' ? `→ ${r.action_to_state}`
                        : r.action_type === 'assign' ? `assign → ${r.action_assignee}` : 'escalate'}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono">{r.times_fired}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => toggle(r)}
                      className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
                      style={{ background: r.is_active ? '#22c55e18' : colors.surface2, color: r.is_active ? '#22c55e' : colors.inkSubtle }}>
                      {r.is_active ? 'active' : 'paused'}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={() => remove(r)} style={{ color: colors.inkTertiary }}><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default MyAutomation;
