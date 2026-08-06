import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { humanize } from '../lib/format';
import {
  Activity, Webhook, KeyRound, Plus, Trash2, Loader2, Copy, Check, ShieldAlert,
} from 'lucide-react';

/**
 * Platform access surface: metered usage + ROI (billing.py), outbound webhooks
 * (enterprise.py), and self-service platform API keys (enterprise.py). Admin
 * only; the backend gates every mutation with require_role("admin").
 */

// Curated subset of the event_bus EventType enum - the events integrators
// actually subscribe to. The backend validates against the full enum.
const WEBHOOK_EVENTS = [
  'rule.validated', 'skill.executed', 'hitl.requested', 'hitl.approved',
  'compliance.violation', 'decay.alert', 'department.deployed', 'system.health',
];

const fmtInt = (n: any) => (typeof n === 'number' ? n.toLocaleString() : (n ?? '-'));
const fmtMoney = (n: any) => (typeof n === 'number' ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : (n ?? '-'));

const PlatformAccessSettings: React.FC = () => {
  const { colors } = useTheme();

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 14 };
  const input: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, borderRadius: 8, padding: '8px 10px', fontSize: 13, width: '100%' };

  // ── usage / ROI ──
  const [usage, setUsage] = useState<any>(null);
  const [roi, setRoi] = useState<any>(null);

  // ── webhooks ──
  const [hooks, setHooks] = useState<any[]>([]);
  const [hookForm, setHookForm] = useState({ name: '', endpoint: '', events: [] as string[] });
  const [hookBusy, setHookBusy] = useState(false);
  const [hookMsg, setHookMsg] = useState('');

  // ── api keys ──
  const [keys, setKeys] = useState<any[]>([]);
  const [keyForm, setKeyForm] = useState({ name: '', role: 'operator' });
  const [keyBusy, setKeyBusy] = useState(false);
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const loadAll = useCallback(() => {
    api.getBillingUsage().then(setUsage).catch(() => setUsage(null));
    api.getBillingRoi().then(setRoi).catch(() => setRoi(null));
    api.getWebhooks().then(r => setHooks(r.subscriptions || [])).catch(() => setHooks([]));
    api.getApiKeys().then(r => setKeys(r.keys || [])).catch(() => setKeys([]));
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const toggleEvent = (e: string) =>
    setHookForm(f => ({ ...f, events: f.events.includes(e) ? f.events.filter(x => x !== e) : [...f.events, e] }));

  const saveHook = async () => {
    setHookBusy(true); setHookMsg('');
    try {
      await api.createWebhook(hookForm);
      setHookForm({ name: '', endpoint: '', events: [] });
      setHooks((await api.getWebhooks()).subscriptions || []);
    } catch (e: any) { setHookMsg(e?.message || 'Failed to save webhook'); }
    finally { setHookBusy(false); }
  };
  const deleteHook = async (id: string) => {
    try { await api.deleteWebhook(id); setHooks(hooks.filter(h => h.id !== id)); } catch { /* ignore */ }
  };

  const createKey = async () => {
    setKeyBusy(true); setFreshKey(null); setCopied(false);
    try {
      const res = await api.createApiKey(keyForm);
      setFreshKey(res.api_key);
      setKeyForm({ name: '', role: 'operator' });
      setKeys((await api.getApiKeys()).keys || []);
    } catch { /* surfaced by empty freshKey */ }
    finally { setKeyBusy(false); }
  };
  const revokeKey = async (id: string) => {
    try { await api.revokeApiKey(id); setKeys((await api.getApiKeys()).keys || []); } catch { /* ignore */ }
  };
  const copyKey = () => {
    if (freshKey) { navigator.clipboard?.writeText(freshKey); setCopied(true); }
  };

  const stat = (label: string, value: string) => (
    <div className="flex-1 min-w-[120px]">
      <div className="text-[20px] font-bold" style={{ color: colors.ink }}>{value}</div>
      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{label}</div>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Usage & ROI */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Metered Usage &amp; ROI</span>
        </div>
        {!usage && !roi ? (
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>No usage recorded yet.</p>
        ) : (
          <div className="flex flex-wrap gap-4">
            {stat('Skill executions', fmtInt(usage?.total_executions ?? usage?.executions))}
            {stat('LLM tokens', fmtInt(usage?.total_tokens ?? usage?.tokens))}
            {stat('Est. cost', fmtMoney(usage?.total_cost_usd ?? usage?.cost_usd))}
            {stat('Safe autonomous runs', fmtInt(roi?.safe_autonomous_executions))}
            {stat('Value delivered', fmtMoney(roi?.value_delivered_usd ?? roi?.roi_usd))}
          </div>
        )}
      </div>

      {/* Webhooks */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <Webhook className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Outbound Webhooks</span>
        </div>

        {hooks.length > 0 && (
          <div className="space-y-2 mb-4">
            {hooks.map(h => (
              <div key={h.id} className="flex items-center justify-between px-3 py-2 rounded-lg" style={{ background: colors.surface2 }}>
                <div className="text-[13px] min-w-0" style={{ color: colors.ink }}>
                  <span className="font-medium">{h.name || 'webhook'}</span>
                  <span className="ml-2 font-mono text-[11px] truncate" style={{ color: colors.inkSubtle }}>{h.endpoint}</span>
                  <span className="ml-2 text-[11px]" style={{ color: colors.inkSubtle }}>
                    {(h.events || []).length} events · {h.delivery_count ?? 0} sent{h.failure_count ? ` · ${h.failure_count} failed` : ''}
                  </span>
                </div>
                <button onClick={() => deleteHook(h.id)} aria-label={`Delete webhook ${h.name || h.endpoint}`} className="p-1.5 rounded shrink-0" style={{ color: colors.error }}><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <input style={input} placeholder="Name (e.g. Ops Slack relay)" value={hookForm.name} onChange={e => setHookForm({ ...hookForm, name: e.target.value })} />
          <input style={input} placeholder="Endpoint URL (https://…)" value={hookForm.endpoint} onChange={e => setHookForm({ ...hookForm, endpoint: e.target.value })} />
        </div>
        <div className="flex flex-wrap gap-1.5 mt-3">
          {WEBHOOK_EVENTS.map(e => {
            const on = hookForm.events.includes(e);
            return (
              <button key={e} onClick={() => toggleEvent(e)}
                className="px-2.5 py-1 rounded-full text-[11px] font-medium transition-all"
                style={on
                  ? { background: colors.primary, color: '#fff' }
                  : { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                {e}
              </button>
            );
          })}
        </div>
        <button onClick={saveHook} disabled={hookBusy || !hookForm.endpoint || hookForm.events.length === 0}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium mt-3"
          style={{ background: colors.primary, color: '#fff', opacity: (!hookForm.endpoint || hookForm.events.length === 0) ? 0.5 : 1 }}>
          {hookBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Add webhook
        </button>
        {hookMsg && <p className="text-[12px] mt-2" style={{ color: colors.error }}>{hookMsg}</p>}
      </div>

      {/* API Keys */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <KeyRound className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Platform API Keys</span>
        </div>

        {freshKey && (
          <div className="mb-4 p-3 rounded-lg" style={{ background: colors.success + '14', border: `1px solid ${colors.success}40` }}>
            <div className="flex items-center gap-2 mb-2 text-[12px] font-medium" style={{ color: colors.success }}>
              <ShieldAlert className="w-4 h-4" /> Copy this key now. It is shown once and cannot be recovered.
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-[12px] p-2 rounded break-all" style={{ background: colors.surface2, color: colors.ink }}>{freshKey}</code>
              <button onClick={copyKey} aria-label={copied ? 'API key copied' : 'Copy API key'} className="p-2 rounded-lg shrink-0" style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
                {copied ? <Check className="w-4 h-4" style={{ color: colors.success }} /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        {keys.length > 0 && (
          <div className="space-y-2 mb-4">
            {keys.map(k => (
              <div key={k.key_id} className="flex items-center justify-between px-3 py-2 rounded-lg" style={{ background: colors.surface2 }}>
                <div className="text-[13px]" style={{ color: colors.ink }}>
                  <span className="font-medium">{k.name || 'unnamed'}</span>
                  <span className="ml-2 font-mono text-[11px]" style={{ color: colors.inkSubtle }}>{k.key_id}…</span>
                  <span className="ml-2 text-[11px] px-1.5 py-0.5 rounded" style={{ background: colors.primary + '1f', color: colors.primary }}>{humanize(k.role)}</span>
                  {!k.active && <span className="ml-2 text-[11px]" style={{ color: colors.error }}>revoked</span>}
                </div>
                {k.active && (
                  <button onClick={() => revokeKey(k.key_id)} aria-label={`Revoke API key ${k.name || k.key_id}`} className="p-1.5 rounded" style={{ color: colors.error }}><Trash2 className="w-4 h-4" /></button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <input style={input} placeholder="Key name (e.g. CI pipeline)" value={keyForm.name} onChange={e => setKeyForm({ ...keyForm, name: e.target.value })} />
          <select style={input} value={keyForm.role} onChange={e => setKeyForm({ ...keyForm, role: e.target.value })}>
            <option value="viewer">Viewer (read-only)</option>
            <option value="operator">Operator (read + act)</option>
            <option value="admin">Admin (full access)</option>
          </select>
        </div>
        <button onClick={createKey} disabled={keyBusy || !keyForm.name}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium mt-3"
          style={{ background: colors.primary, color: '#fff', opacity: !keyForm.name ? 0.5 : 1 }}>
          {keyBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Issue key
        </button>
      </div>
    </div>
  );
};

export default PlatformAccessSettings;
