/**
 * ConnectorCredentials — the credentials panel that makes a connector REAL (H14).
 *
 * Before this, the "Connect" button flipped a connector to CONNECTED with no
 * ConnectorCredential, so the scheduler pull (which inner-joins credentials)
 * never fetched anything and the six credential API functions were dead
 * client-side. This modal stores credentials (encrypted at rest server-side),
 * tests the connection, and drives sync / disconnect — the full lifecycle.
 *
 * Secret VALUES are typed by the user into password fields and posted straight
 * to the backend; they are never logged, echoed, or returned by the API.
 */
import React, { useEffect, useState } from 'react';
import { KeyRound, Loader2, CheckCircle, XCircle, RefreshCw, Trash2, X, Plus } from 'lucide-react';
import { api } from '../api/client';
import type { ConnectorCredentialStatus } from '../api/types';

type KV = { key: string; value: string };

export function ConnectorCredentialsModal(
  { connector, colors, onClose, onChanged }:
  { connector: any; colors: any; onClose: () => void; onChanged: () => void },
) {
  const [status, setStatus] = useState<ConnectorCredentialStatus | null>(null);
  const [provider, setProvider] = useState('');
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<KV[]>([{ key: '', value: '' }]);
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; detail: string } | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    let live = true;
    api.getConnectorCredentialStatus(connector.id).then(s => {
      if (!live) return;
      setStatus(s);
      setProvider(s.provider || s.inferred_provider || '');
      const c: Record<string, string> = {};
      (s.required_config || []).forEach(k => { c[k] = String((s.config as any)?.[k] ?? ''); });
      setConfig(c);
      if (s.secret_keys?.length) setSecrets(s.secret_keys.map(k => ({ key: k, value: '' })));
    }).catch(() => setErr('Could not load credential status.'));
    return () => { live = false; };
  }, [connector.id]);

  const save = async () => {
    setBusy(true); setErr(''); setTest(null);
    try {
      const secretMap: Record<string, string> = {};
      secrets.forEach(s => { if (s.key.trim()) secretMap[s.key.trim()] = s.value; });
      await api.storeConnectorCredentials(connector.id, {
        provider: provider.trim() || undefined, config, secrets: secretMap,
      });
      const t = await api.testConnector(connector.id);
      setTest({ ok: t.ok, detail: t.detail });
      if (t.ok) { await api.connectConnector(connector.id); onChanged(); }
    } catch (e: any) { setErr(e?.message || 'Failed to store credentials.'); }
    setBusy(false);
  };

  const syncNow = async () => {
    setBusy(true); setErr(''); setTest(null);
    try {
      const r = await api.syncConnector(connector.id);
      setTest({ ok: true, detail: `${r.mode} sync: ${r.events_synced} event(s).` });
      onChanged();
    } catch (e: any) { setErr(e?.message || 'Sync failed.'); }
    setBusy(false);
  };

  const disconnect = async () => {
    setBusy(true); setErr('');
    try { await api.deleteConnectorCredentials(connector.id); onChanged(); onClose(); }
    catch (e: any) { setErr(e?.message || 'Could not remove credentials.'); }
    setBusy(false);
  };

  const field = { background: colors.surface1, color: colors.ink, border: `1px solid ${colors.hairline}` };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.55)' }} onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl overflow-hidden flex flex-col max-h-[90vh]"
        style={{ background: colors.surface0, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-2">
            <KeyRound className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[15px] font-semibold" style={{ color: colors.ink }}>
              Connect {connector.name}
            </span>
          </div>
          <button onClick={onClose} aria-label="Close"><X className="w-4 h-4" style={{ color: colors.inkSubtle }} /></button>
        </div>

        <div className="px-5 py-4 overflow-y-auto space-y-4">
          {status?.configured && (
            <div className="flex items-center gap-2 text-[12px] px-3 py-2 rounded"
              style={{ background: colors.surface1, color: colors.inkSubtle }}>
              {status.last_test_ok == null ? <RefreshCw className="w-3.5 h-3.5" />
                : status.last_test_ok ? <CheckCircle className="w-3.5 h-3.5" style={{ color: '#22c55e' }} />
                : <XCircle className="w-3.5 h-3.5" style={{ color: '#ef4444' }} />}
              Credentials configured{status.last_test_detail ? ` — ${status.last_test_detail}` : ''}
            </div>
          )}

          <label className="block">
            <span className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>Provider</span>
            <input value={provider} onChange={e => setProvider(e.target.value)}
              placeholder="e.g. servicenow, jira, workday"
              className="mt-1 w-full px-3 py-2 rounded text-[13px]" style={field} />
          </label>

          {Object.keys(config).length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>Configuration</span>
              {Object.keys(config).map(k => (
                <input key={k} value={config[k]} onChange={e => setConfig({ ...config, [k]: e.target.value })}
                  placeholder={k} aria-label={k}
                  className="w-full px-3 py-2 rounded text-[13px]" style={field} />
              ))}
            </div>
          )}

          <div className="space-y-2">
            <span className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
              Secrets (encrypted at rest, never returned)
            </span>
            {secrets.map((s, i) => (
              <div key={i} className="flex gap-2">
                <input value={s.key} onChange={e => setSecrets(secrets.map((x, j) => j === i ? { ...x, key: e.target.value } : x))}
                  placeholder="key e.g. api_token" aria-label="secret key"
                  className="w-2/5 px-3 py-2 rounded text-[13px]" style={field} />
                <input type="password" value={s.value} autoComplete="new-password"
                  onChange={e => setSecrets(secrets.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
                  placeholder="value" aria-label="secret value"
                  className="flex-1 px-3 py-2 rounded text-[13px]" style={field} />
              </div>
            ))}
            <button onClick={() => setSecrets([...secrets, { key: '', value: '' }])}
              className="flex items-center gap-1 text-[11px]" style={{ color: colors.primary }}>
              <Plus className="w-3 h-3" /> Add secret
            </button>
          </div>

          {test && (
            <div className="flex items-center gap-2 text-[12px] px-3 py-2 rounded"
              style={{ background: test.ok ? '#22c55e15' : '#ef444415', color: test.ok ? '#22c55e' : '#ef4444' }}>
              {test.ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
              {test.detail}
            </div>
          )}
          {err && <div className="text-[12px]" style={{ color: '#ef4444' }}>{err}</div>}
        </div>

        <div className="flex items-center justify-between px-5 py-4" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          {status?.configured ? (
            <button onClick={disconnect} disabled={busy}
              className="flex items-center gap-1 px-3 py-2 rounded text-[12px] font-medium"
              style={{ color: '#ef4444', background: '#ef444410' }}>
              <Trash2 className="w-3.5 h-3.5" /> Remove
            </button>
          ) : <span />}
          <div className="flex items-center gap-2">
            {status?.configured && (
              <button onClick={syncNow} disabled={busy}
                className="flex items-center gap-1 px-3 py-2 rounded text-[12px] font-medium"
                style={{ background: colors.surface1, color: colors.ink }}>
                <RefreshCw className="w-3.5 h-3.5" /> Sync now
              </button>
            )}
            <button onClick={save} disabled={busy}
              className="flex items-center gap-1 px-4 py-2 rounded text-[12px] font-semibold"
              style={{ background: colors.primary, color: '#fff' }}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />}
              Save &amp; test
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
