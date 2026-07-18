import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ConnectorItem, ConnectorCredentialStatus } from '../api/client';
import { KeyRound, X, ShieldCheck, ShieldAlert, Loader2, Trash2, PlugZap } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

/**
 * Self-service live-integration setup.
 *
 * Security posture:
 *  - Secret values are write-only: they are sent once over the authenticated
 *    HTTPS channel and encrypted at rest server-side (Fernet/SECRET_KEY).
 *  - The status endpoint only ever returns secret KEY NAMES, never values,
 *    so nothing sensitive is rendered back into the DOM.
 */

type FieldSpec = { key: string; label: string; placeholder?: string; optional?: boolean };

const PROVIDER_FIELDS: Record<string, { label: string; config: FieldSpec[]; secrets: FieldSpec[] }> = {
  jira: {
    label: 'Jira Cloud',
    config: [{ key: 'base_url', label: 'Site URL', placeholder: 'https://yourcompany.atlassian.net' }],
    secrets: [
      { key: 'email', label: 'Account email' },
      { key: 'api_token', label: 'API token' },
    ],
  },
  salesforce: {
    label: 'Salesforce',
    config: [{ key: 'instance_url', label: 'Instance URL', placeholder: 'https://yourorg.my.salesforce.com' }],
    secrets: [
      { key: 'client_id', label: 'Connected-app client ID' },
      { key: 'client_secret', label: 'Connected-app client secret' },
      { key: 'access_token', label: 'Access token (instead of client creds)', optional: true },
    ],
  },
  workday: {
    label: 'Workday',
    config: [{ key: 'report_url', label: 'RaaS report URL', placeholder: 'https://wd2-impl.workday.com/ccx/service/customreport2/…' }],
    secrets: [
      { key: 'username', label: 'ISU username' },
      { key: 'password', label: 'ISU password' },
    ],
  },
  sap: {
    label: 'SAP (OData)',
    config: [
      { key: 'service_url', label: 'OData service URL', placeholder: 'https://api.sap.example.com/sap/opu/odata/sap/API_SUPPLIERINVOICE' },
      { key: 'entity_set', label: 'Entity set', placeholder: 'A_SupplierInvoice', optional: true },
    ],
    secrets: [
      { key: 'username', label: 'Username', optional: true },
      { key: 'password', label: 'Password', optional: true },
      { key: 'api_key', label: 'API key (instead of user/pass)', optional: true },
    ],
  },
  generic_rest: {
    label: 'Generic REST API',
    config: [
      { key: 'base_url', label: 'Base URL', placeholder: 'https://api.example.com' },
      { key: 'endpoint', label: 'Endpoint path', placeholder: '/v1/records', optional: true },
      { key: 'items_key', label: 'Items key in response', placeholder: 'items', optional: true },
    ],
    secrets: [
      { key: 'bearer_token', label: 'Bearer token', optional: true },
      { key: 'api_key', label: 'API key (X-API-Key header)', optional: true },
    ],
  },
};

interface Props {
  connector: ConnectorItem;
  onClose: () => void;
  onSaved: () => void;
}

const ConnectorCredentialsModal: React.FC<Props> = ({ connector, onClose, onSaved }) => {
  const { colors } = useTheme();
  const [status, setStatus] = useState<ConnectorCredentialStatus | null>(null);
  const [provider, setProvider] = useState<string>('generic_rest');
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<'save' | 'test' | 'delete' | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api.getConnectorCredentialStatus(connector.id).then(s => {
      setStatus(s);
      const p = s.provider || s.inferred_provider || 'generic_rest';
      setProvider(p);
      if (s.config) {
        const cfg: Record<string, string> = {};
        Object.entries(s.config).forEach(([k, v]) => { cfg[k] = String(v ?? ''); });
        setConfig(cfg);
      }
    }).catch(() => setStatus({ configured: false }));
  }, [connector.id]);

  const fields = useMemo(() => PROVIDER_FIELDS[provider] || PROVIDER_FIELDS.generic_rest, [provider]);

  const save = async () => {
    setBusy('save'); setMessage(null);
    try {
      const cleanSecrets: Record<string, string> = {};
      Object.entries(secrets).forEach(([k, v]) => { if (v) cleanSecrets[k] = v; });
      await api.storeConnectorCredentials(connector.id, { provider, config, secrets: cleanSecrets });
      setSecrets({});           // never keep secret values in memory longer than needed
      setMessage({ ok: true, text: 'Credentials stored securely (encrypted at rest). Run a test to verify.' });
      const s = await api.getConnectorCredentialStatus(connector.id);
      setStatus(s);
      onSaved();
    } catch (e: any) {
      setMessage({ ok: false, text: e?.message || 'Failed to store credentials' });
    } finally { setBusy(null); }
  };

  const test = async () => {
    setBusy('test'); setMessage(null);
    try {
      const r = await api.testConnector(connector.id);
      setMessage({ ok: r.ok, text: r.detail });
      const s = await api.getConnectorCredentialStatus(connector.id);
      setStatus(s);
    } catch (e: any) {
      setMessage({ ok: false, text: e?.message || 'Connection test failed' });
    } finally { setBusy(null); }
  };

  const remove = async () => {
    setBusy('delete'); setMessage(null);
    try {
      await api.deleteConnectorCredentials(connector.id);
      setStatus({ configured: false });
      setMessage({ ok: true, text: 'Credentials removed - connector reverted to demo feed.' });
      onSaved();
    } catch (e: any) {
      setMessage({ ok: false, text: e?.message || 'Failed to delete credentials' });
    } finally { setBusy(null); }
  };

  const inputStyle: React.CSSProperties = {
    background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink,
  };

  const statusBanner = (): React.CSSProperties => {
    const c = status?.last_test_ok ? colors.success : status?.last_test_ok === false ? colors.warning : colors.inkSubtle;
    return { background: c + '14', color: c, border: `1px solid ${c}33` };
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl max-h-[90vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: colors.primary + '1a' }}>
              <KeyRound className="w-4 h-4" style={{ color: colors.primary }} />
            </div>
            <div>
              <h2 className="font-semibold" style={{ color: colors.ink }}>Live integration - {connector.name}</h2>
              <p className="text-xs" style={{ color: colors.inkSubtle }}>Your keys are encrypted at rest and never displayed back.</p>
            </div>
          </div>
          <button onClick={onClose} className="transition-colors hover:opacity-70" style={{ color: colors.inkSubtle }}><X className="w-5 h-5" /></button>
        </div>

        <div className="p-6 space-y-5">
          {status?.configured && (
            <div className="flex items-start gap-2 rounded-xl px-4 py-3 text-sm" style={statusBanner()}>
              {status.last_test_ok ? <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0" /> : <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />}
              <div>
                <div className="font-medium">
                  {status.provider} credentials on file
                  {status.secret_keys?.length ? ` (${status.secret_keys.join(', ')})` : ''}
                </div>
                {status.last_test_detail && <div className="text-xs opacity-80 mt-0.5">{status.last_test_detail}</div>}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Provider</label>
            <select value={provider} onChange={e => { setProvider(e.target.value); setMessage(null); }}
              className="mt-1 w-full rounded-xl px-3 py-2 text-sm focus:outline-none" style={inputStyle}>
              {Object.entries(PROVIDER_FIELDS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Connection settings</div>
            {fields.config.map(f => (
              <div key={f.key}>
                <label className="text-xs" style={{ color: colors.inkSubtle }}>{f.label}{f.optional ? ' (optional)' : ''}</label>
                <input type="text" value={config[f.key] || ''} placeholder={f.placeholder}
                  onChange={e => setConfig({ ...config, [f.key]: e.target.value })}
                  className="mt-1 w-full rounded-xl px-3 py-2 text-sm focus:outline-none" style={inputStyle} />
              </div>
            ))}
          </div>

          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Secrets (write-only)</div>
            {fields.secrets.map(f => (
              <div key={f.key}>
                <label className="text-xs" style={{ color: colors.inkSubtle }}>{f.label}{f.optional ? ' (optional)' : ''}</label>
                <input type="password" autoComplete="new-password" value={secrets[f.key] || ''}
                  placeholder={status?.secret_keys?.includes(f.key) ? '•••••••• (stored - enter to replace)' : ''}
                  onChange={e => setSecrets({ ...secrets, [f.key]: e.target.value })}
                  className="mt-1 w-full rounded-xl px-3 py-2 text-sm focus:outline-none" style={inputStyle} />
              </div>
            ))}
          </div>

          {message && (
            <div className="rounded-xl px-4 py-3 text-sm" style={message.ok
              ? { background: colors.success + '14', color: colors.success, border: `1px solid ${colors.success}33` }
              : { background: colors.error + '14', color: colors.error, border: `1px solid ${colors.error}33` }}>
              {message.text}
            </div>
          )}

          <div className="flex items-center justify-between pt-2">
            {status?.configured ? (
              <button onClick={remove} disabled={busy !== null}
                className="flex items-center gap-1.5 text-xs transition-colors hover:opacity-70 disabled:opacity-50"
                style={{ color: colors.error }}>
                {busy === 'delete' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                Remove credentials
              </button>
            ) : <span />}
            <div className="flex gap-2">
              <button onClick={test} disabled={busy !== null || !status?.configured}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-all hover:opacity-80 disabled:opacity-50"
                style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                {busy === 'test' ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlugZap className="w-4 h-4" />}
                Test connection
              </button>
              <button onClick={save} disabled={busy !== null}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-all hover:opacity-90 disabled:opacity-50"
                style={{ background: colors.primary, color: '#fff' }}>
                {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <KeyRound className="w-4 h-4" />}
                Save securely
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConnectorCredentialsModal;
