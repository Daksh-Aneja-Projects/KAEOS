import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { ShieldCheck, KeyRound, Loader2, Trash2, Plus, Check } from 'lucide-react';

/**
 * Security settings: self-service MFA (TOTP) and admin SSO (OIDC) configuration.
 * Backs the real /auth/mfa/* and /auth/sso/connections endpoints.
 */
const SecuritySettings: React.FC = () => {
  const { colors } = useTheme();

  // ── MFA ──
  const [mfa, setMfa] = useState<{ enrolled: boolean; enabled: boolean } | null>(null);
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaMsg, setMfaMsg] = useState('');

  // ── SSO ──
  const [conns, setConns] = useState<any[]>([]);
  const [ssoBusy, setSsoBusy] = useState(false);
  const [ssoMsg, setSsoMsg] = useState('');
  const [protocol, setProtocol] = useState<'OIDC' | 'SAML'>('OIDC');
  const [form, setForm] = useState({
    provider_label: '', issuer: '', client_id: '', client_secret: '',
    idp_sso_url: '', idp_x509_cert: '',
    email_domain: '', default_role: 'VIEWER',
  });

  const loadMfa = () => api.mfaStatus().then(setMfa).catch(() => setMfa(null));
  const loadSso = () => api.getSSOConnections().then(r => setConns(r.connections || [])).catch(() => setConns([]));

  useEffect(() => { loadMfa(); loadSso(); }, []);

  const startEnroll = async () => {
    setMfaBusy(true); setMfaMsg('');
    try { setEnroll(await api.mfaEnroll()); }
    catch (e: any) { setMfaMsg(e?.message || 'Enrollment failed'); }
    finally { setMfaBusy(false); }
  };
  const confirmEnroll = async () => {
    setMfaBusy(true); setMfaMsg('');
    try {
      await api.mfaConfirm(code.trim());
      setEnroll(null); setCode(''); setMfaMsg('MFA enabled.'); await loadMfa();
    } catch (e: any) { setMfaMsg(e?.message || 'Invalid code'); }
    finally { setMfaBusy(false); }
  };
  const disableMfa = async () => {
    setMfaBusy(true); setMfaMsg('');
    try { await api.mfaDisable(); setEnroll(null); await loadMfa(); }
    catch (e: any) { setMfaMsg(e?.message || 'Failed'); }
    finally { setMfaBusy(false); }
  };

  const saveConnection = async () => {
    setSsoBusy(true); setSsoMsg('');
    try {
      await api.upsertSSOConnection({ protocol, ...form, is_enabled: true });
      setSsoMsg('Connection saved.');
      setForm({ provider_label: '', issuer: '', client_id: '', client_secret: '', idp_sso_url: '', idp_x509_cert: '', email_domain: '', default_role: 'VIEWER' });
      await loadSso();
    } catch (e: any) { setSsoMsg(e?.message || 'Save failed'); }
    finally { setSsoBusy(false); }
  };
  const deleteConnection = async (id: string) => {
    setSsoBusy(true);
    try { await api.deleteSSOConnection(id); await loadSso(); }
    catch { /* ignore */ } finally { setSsoBusy(false); }
  };

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 14 };
  const input: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, borderRadius: 8, padding: '8px 10px', fontSize: 13, width: '100%' };

  return (
    <div className="space-y-4">
      {/* MFA */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <KeyRound className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Multi-Factor Authentication (TOTP)</span>
          {mfa?.enabled && <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: colors.success + '1f', color: colors.success }}>Enabled</span>}
        </div>
        {!mfa?.enabled && !enroll && (
          <button onClick={startEnroll} disabled={mfaBusy}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium"
            style={{ background: colors.primary, color: '#fff' }}>
            {mfaBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />} Enable MFA
          </button>
        )}
        {enroll && (
          <div className="space-y-3">
            <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
              Add this secret to your authenticator app, then enter the 6-digit code to confirm.
            </p>
            <div className="font-mono text-[13px] p-2 rounded break-all" style={{ background: colors.surface2, color: colors.ink }}>{enroll.secret}</div>
            <div className="flex gap-2">
              <input value={code} onChange={e => setCode(e.target.value)} placeholder="123456" style={{ ...input, width: 140 }} />
              <button onClick={confirmEnroll} disabled={mfaBusy}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium"
                style={{ background: colors.success, color: '#fff' }}>
                <Check className="w-4 h-4" /> Confirm
              </button>
            </div>
          </div>
        )}
        {mfa?.enabled && (
          <button onClick={disableMfa} disabled={mfaBusy}
            className="px-3 py-2 rounded-lg text-[13px] font-medium"
            style={{ background: colors.surface2, color: colors.error, border: `1px solid ${colors.hairline}` }}>
            Disable MFA
          </button>
        )}
        {mfaMsg && <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>{mfaMsg}</p>}
      </div>

      {/* SSO (OIDC) */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Enterprise SSO (OpenID Connect &amp; SAML 2.0)</span>
        </div>

        {conns.length > 0 && (
          <div className="space-y-2 mb-4">
            {conns.map(c => (
              <div key={c.id} className="flex items-center justify-between px-3 py-2 rounded-lg" style={{ background: colors.surface2 }}>
                <div className="text-[13px]" style={{ color: colors.ink }}>
                  <span className="font-medium">{c.provider_label || c.protocol}</span>
                  <span className="ml-1.5 text-[11px] px-1.5 py-0.5 rounded" style={{ background: colors.primary + '1f', color: colors.primary }}>{c.protocol}</span>
                  <span className="ml-2" style={{ color: colors.inkSubtle }}>
                    {c.email_domain || 'no domain'} · {c.protocol === 'SAML' ? (c.idp_x509_cert_set ? 'cert set' : 'no cert') : (c.client_secret_set ? 'secret set' : 'no secret')} · {c.is_enabled ? 'enabled' : 'disabled'}
                  </span>
                </div>
                <button onClick={() => deleteConnection(c.id)} className="p-1.5 rounded" style={{ color: colors.error }}><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        )}

        {/* Protocol toggle */}
        <div className="flex gap-1 mb-3 p-1 rounded-lg w-fit" style={{ background: colors.surface2 }}>
          {(['OIDC', 'SAML'] as const).map(p => (
            <button key={p} onClick={() => setProtocol(p)}
              className="px-3 py-1 rounded-md text-[12px] font-medium"
              style={protocol === p ? { background: colors.primary, color: '#fff' } : { color: colors.inkSubtle }}>
              {p}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <input style={input} placeholder="Provider label (e.g. Okta)" value={form.provider_label} onChange={e => setForm({ ...form, provider_label: e.target.value })} />
          <input style={input} placeholder="Email domain (e.g. acme.com)" value={form.email_domain} onChange={e => setForm({ ...form, email_domain: e.target.value })} />
          {protocol === 'OIDC' ? (
            <>
              <input style={input} placeholder="Issuer URL (https://…)" value={form.issuer} onChange={e => setForm({ ...form, issuer: e.target.value })} />
              <input style={input} placeholder="Client ID" value={form.client_id} onChange={e => setForm({ ...form, client_id: e.target.value })} />
              <input style={input} type="password" placeholder="Client secret" value={form.client_secret} onChange={e => setForm({ ...form, client_secret: e.target.value })} />
            </>
          ) : (
            <>
              <input style={input} placeholder="IdP EntityID / Issuer" value={form.issuer} onChange={e => setForm({ ...form, issuer: e.target.value })} />
              <input style={input} placeholder="IdP SSO URL (https://…)" value={form.idp_sso_url} onChange={e => setForm({ ...form, idp_sso_url: e.target.value })} />
              <textarea style={{ ...input, minHeight: 72, resize: 'vertical' }} className="md:col-span-2" placeholder="IdP X.509 signing certificate (PEM or base64 body)" value={form.idp_x509_cert} onChange={e => setForm({ ...form, idp_x509_cert: e.target.value })} />
            </>
          )}
          <select style={input} value={form.default_role} onChange={e => setForm({ ...form, default_role: e.target.value })}>
            <option value="VIEWER">New users → Viewer</option>
            <option value="ANALYST">New users → Analyst</option>
            <option value="ADMIN">New users → Admin</option>
          </select>
        </div>
        {protocol === 'SAML' && (
          <p className="text-[11px] mt-2" style={{ color: colors.inkSubtle }}>
            Give your IdP the SP metadata at <span className="font-mono">/api/v1/auth/sso/saml/metadata</span>. KAEOS requires signed assertions.
          </p>
        )}
        <button onClick={saveConnection}
          disabled={ssoBusy || !form.issuer || (protocol === 'OIDC' ? !form.client_id : (!form.idp_sso_url || !form.idp_x509_cert))}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium mt-3"
          style={{ background: colors.primary, color: '#fff' }}>
          {ssoBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Save connection
        </button>
        {ssoMsg && <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>{ssoMsg}</p>}
      </div>
    </div>
  );
};

export default SecuritySettings;
