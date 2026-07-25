import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { UserX, Clock, Webhook, Loader2, Trash2, Plus, DollarSign } from 'lucide-react';

/**
 * Data-governance settings: GDPR/DSAR erasure, data-retention windows, outbound
 * webhooks, and metered usage. Backs privacy.py / enterprise.py / billing.py —
 * previously orphaned (no UI).
 */
const DataGovernanceSettings: React.FC = () => {
  const { colors } = useTheme();

  const [eraseKey, setEraseKey] = useState('');
  const [eraseBusy, setEraseBusy] = useState(false);
  const [eraseMsg, setEraseMsg] = useState('');

  const [retention, setRetention] = useState<any>(null);
  const [webhooks, setWebhooks] = useState<any[]>([]);
  const [usage, setUsage] = useState<any>(null);
  const [wh, setWh] = useState({ name: '', endpoint: '', events: '' });
  const [whBusy, setWhBusy] = useState(false);

  const load = () => {
    api.getRetention().then(setRetention).catch(() => setRetention(null));
    api.getWebhooks().then(r => setWebhooks(r.subscriptions || [])).catch(() => setWebhooks([]));
    api.getBillingUsage().then(setUsage).catch(() => setUsage(null));
  };
  useEffect(() => { load(); }, []);

  const runErasure = async () => {
    if (!eraseKey.trim()) return;
    setEraseBusy(true); setEraseMsg('');
    try {
      const body = eraseKey.includes('@') ? { email: eraseKey.trim() } : { employee_id: eraseKey.trim() };
      const r = await api.privacyErasure(body);
      setEraseMsg(`Erasure complete: ${JSON.stringify(r.receipt || r)}`.slice(0, 200));
      setEraseKey('');
    } catch (e: any) { setEraseMsg(e?.message || 'Erasure failed'); }
    finally { setEraseBusy(false); }
  };

  const addWebhook = async () => {
    if (!wh.name || !wh.endpoint) return;
    setWhBusy(true);
    try {
      await api.createWebhook({ name: wh.name, endpoint: wh.endpoint, events: wh.events.split(',').map(s => s.trim()).filter(Boolean) });
      setWh({ name: '', endpoint: '', events: '' });
      await load();
    } catch { /* surfaced below via reload */ } finally { setWhBusy(false); }
  };

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 14 };
  const input: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, borderRadius: 8, padding: '8px 10px', fontSize: 13, width: '100%' };

  return (
    <div className="space-y-4">
      {/* Usage */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <DollarSign className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Metered Usage</span>
        </div>
        {usage ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[['Calls', usage.call_count], ['Total cost (USD)', usage.total_cost != null ? `$${Number(usage.total_cost).toFixed(4)}` : '-'],
              ['Input tokens', usage.input_tokens], ['Output tokens', usage.output_tokens]].map(([label, val]) => (
              <div key={String(label)} className="p-3 rounded-lg" style={{ background: colors.surface2 }}>
                <div className="text-[18px] font-bold tabular-nums" style={{ color: colors.ink }}>{val ?? '-'}</div>
                <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{label}</div>
              </div>
            ))}
          </div>
        ) : <p className="text-[12px]" style={{ color: colors.inkSubtle }}>No metered usage yet.</p>}
      </div>

      {/* DSAR erasure */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-2">
          <UserX className="w-5 h-5" style={{ color: colors.error }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>GDPR Erasure (DSAR)</span>
        </div>
        <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
          Irreversibly anonymise a data subject across the HR PII tables. Enter an employee id or email.
        </p>
        <div className="flex gap-2">
          <input style={input} placeholder="employee id or email" value={eraseKey} onChange={e => setEraseKey(e.target.value)} />
          <button onClick={runErasure} disabled={eraseBusy || !eraseKey.trim()}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium whitespace-nowrap"
            style={{ background: colors.error, color: '#fff' }}>
            {eraseBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserX className="w-4 h-4" />} Erase
          </button>
        </div>
        {eraseMsg && <p className="text-[11px] mt-2 break-all" style={{ color: colors.inkSubtle }}>{eraseMsg}</p>}
      </div>

      {/* Retention */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Data Retention</span>
        </div>
        {retention?.policies?.length ? (
          <div className="space-y-2">
            {retention.policies.map((p: any, i: number) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg text-[13px]" style={{ background: colors.surface2, color: colors.ink }}>
                <span>{p.data_class}</span>
                <span style={{ color: colors.inkSubtle }}>{p.enabled ? `${p.retain_days}d` : 'disabled'}</span>
              </div>
            ))}
          </div>
        ) : <p className="text-[12px]" style={{ color: colors.inkSubtle }}>No retention policies configured (data retained indefinitely).</p>}
      </div>

      {/* Webhooks */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <Webhook className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Outbound Webhooks</span>
        </div>
        {webhooks.length > 0 && (
          <div className="space-y-2 mb-3">
            {webhooks.map(w => (
              <div key={w.id} className="flex items-center justify-between px-3 py-2 rounded-lg text-[13px]" style={{ background: colors.surface2 }}>
                <div style={{ color: colors.ink }}>
                  <span className="font-medium">{w.name}</span>
                  <span className="ml-2" style={{ color: colors.inkSubtle }}>{w.endpoint} · {(w.events || []).join(', ')} · {w.delivery_count ?? 0} sent</span>
                </div>
                <button onClick={() => api.deleteWebhook(w.id).then(load)} className="p-1.5 rounded" style={{ color: colors.error }}><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <input style={input} placeholder="Name" value={wh.name} onChange={e => setWh({ ...wh, name: e.target.value })} />
          <input style={input} placeholder="https://endpoint" value={wh.endpoint} onChange={e => setWh({ ...wh, endpoint: e.target.value })} />
          <input style={input} placeholder="events (comma-separated)" value={wh.events} onChange={e => setWh({ ...wh, events: e.target.value })} />
        </div>
        <button onClick={addWebhook} disabled={whBusy || !wh.name || !wh.endpoint}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium mt-3"
          style={{ background: colors.primary, color: '#fff' }}>
          {whBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Add webhook
        </button>
      </div>
    </div>
  );
};

export default DataGovernanceSettings;
