import React, { useEffect, useState, useCallback } from 'react';
import {
  UserPlus, ShieldAlert, KeyRound, Eye, EyeOff, Building2, ArrowRight, ArrowLeft,
  CheckCircle2, Copy, RefreshCw, Rocket, Plug, Map, ScanSearch,
  Network, Brain, Bot, MessageSquare, PartyPopper, Loader2, Check,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

// The backend onboarding state machine (app/services/onboarding_engine.py).
// Order + human labels + the icon shown in the ladder.
const STAGES: { key: string; label: string; icon: React.ElementType; who: string }[] = [
  { key: 'INITIATED', label: 'Initiated', icon: Rocket, who: 'Platform' },
  { key: 'CONNECTORS_CONFIGURED', label: 'Systems connected', icon: Plug, who: 'Client' },
  { key: 'SCHEMA_MAPPED', label: 'Schema mapped', icon: Map, who: 'Client' },
  { key: 'PII_CLASSIFIED', label: 'PII classified', icon: ScanSearch, who: 'Auto' },
  { key: 'FULL_CRAWL_RUNNING', label: 'Data crawl', icon: RefreshCw, who: 'Auto' },
  { key: 'KG_POPULATED', label: 'Knowledge graph', icon: Network, who: 'Auto' },
  { key: 'CONFIDENCE_ASSIGNED', label: 'Confidence assigned', icon: Brain, who: 'Auto' },
  { key: 'AGENTS_ACTIVATED', label: 'Agents activated', icon: Bot, who: 'Client' },
  { key: 'ELICITATION_STARTED', label: 'Elicitation started', icon: MessageSquare, who: 'Auto' },
  { key: 'FULLY_ONBOARDED', label: 'Fully onboarded', icon: PartyPopper, who: 'Done' },
];
const stageIndex = (key?: string) => Math.max(0, STAGES.findIndex(s => s.key === key));

function slugify(name: string): string {
  const base = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return base ? `tenant_${base}`.slice(0, 48) : '';
}
function genPassword(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  let out = '';
  const arr = new Uint32Array(14);
  crypto.getRandomValues(arr);
  for (let i = 0; i < 14; i++) out += chars[arr[i] % chars.length];
  return out + '!7';
}

export default function ClientOnboarding() {
  const { colors } = useTheme();
  const { isAdmin } = useAuth();

  const [adminSecret, setAdminSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [tenants, setTenants] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [mode, setMode] = useState<'list' | 'wizard'>('list');
  const [advancing, setAdvancing] = useState<string | null>(null);

  const loadTenants = useCallback(async () => {
    if (!adminSecret) { setTenants([]); return; }
    setLoading(true); setListError(null);
    try {
      const list = await api.getOnboardingList(adminSecret);
      setTenants(Array.isArray(list) ? list : []);
    } catch (e: any) {
      setListError(e.message || 'Could not load onboarding records');
      setTenants([]);
    } finally {
      setLoading(false);
    }
  }, [adminSecret]);

  useEffect(() => {
    const t = setTimeout(() => { if (adminSecret) loadTenants(); }, 400);
    return () => clearTimeout(t);
  }, [adminSecret, loadTenants]);

  const advance = async (tenantId: string) => {
    setAdvancing(tenantId);
    try {
      await api.advanceOnboarding(tenantId, undefined, adminSecret);
      await loadTenants();
    } catch (e: any) {
      setListError(e.message);
    } finally {
      setAdvancing(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="h-full flex items-center justify-center" style={{ background: colors.canvas }}>
        <div className="text-center max-w-sm px-6">
          <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4" style={{ background: 'rgba(229,83,75,0.1)' }}>
            <ShieldAlert className="w-7 h-7" style={{ color: colors.error }} />
          </div>
          <h2 className="text-[17px] font-semibold" style={{ color: colors.ink }}>Access restricted</h2>
          <p className="text-[13px] mt-1.5" style={{ color: colors.inkSubtle }}>
            Client onboarding is a platform-operator function. Ask an administrator for access.
          </p>
        </div>
      </div>
    );
  }

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px',
    border: `1px solid ${colors.hairline}`, padding: '20px',
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <UserPlus className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Client Onboarding</h1>
              <p className="text-[13px] mt-1 max-w-2xl" style={{ color: colors.inkSubtle }}>
                Provision a new client tenant and hand off a secure first login. The client then self-serves
                the rest - connecting systems, deploying departments, and configuring their AI.
              </p>
            </div>
          </div>
          {mode === 'list' && (
            <button onClick={() => setMode('wizard')}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
              <UserPlus className="w-4 h-4" /> Onboard a client
            </button>
          )}
        </div>

        {/* Platform secret */}
        <div style={card}>
          <div className="flex items-center gap-2 mb-2">
            <KeyRound className="w-4 h-4" style={{ color: colors.warning }} />
            <span className="text-[13px] font-semibold">Platform admin secret</span>
          </div>
          <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
            Cross-tenant provisioning is a platform operation. Your secret is held only in this browser tab
            for this session, sent as a request header, and never stored. It is required to list, provision, or advance tenants.
          </p>
          <div className="relative max-w-md">
            <input
              type={showSecret ? 'text' : 'password'}
              value={adminSecret}
              onChange={e => setAdminSecret(e.target.value)}
              placeholder="Enter platform admin secret"
              autoComplete="off"
              className="w-full pl-3 pr-10 py-2 rounded-lg text-[13px] focus:outline-none focus:ring-1"
              style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
            />
            <button onClick={() => setShowSecret(s => !s)} className="absolute right-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }}>
              {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          {listError && <div className="text-[12px] mt-2" style={{ color: colors.error }}>{listError}</div>}
        </div>

        {mode === 'wizard' ? (
          <ProvisionWizard
            colors={colors}
            adminSecret={adminSecret}
            onCancel={() => setMode('list')}
            onDone={() => { setMode('list'); loadTenants(); }}
          />
        ) : (
          <TenantList
            colors={colors} tenants={tenants} loading={loading}
            hasSecret={!!adminSecret} advancing={advancing} onAdvance={advance} onRefresh={loadTenants}
          />
        )}
      </div>
    </div>
  );
}

// ─── Control tower: all onboarding tenants ───────────────────────────────────
function TenantList({ colors, tenants, loading, hasSecret, advancing, onAdvance, onRefresh }: any) {
  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`, padding: '20px',
  };
  if (!hasSecret) {
    return (
      <div style={card} className="text-center py-12">
        <KeyRound className="w-8 h-8 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
        <div className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>Enter your platform admin secret to view tenants</div>
      </div>
    );
  }
  if (loading) {
    return <div style={card} className="flex items-center justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" style={{ color: colors.primary }} /></div>;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
          Onboarding tenants ({tenants.length})
        </span>
        <button onClick={onRefresh} className="flex items-center gap-1.5 text-[12px] hover:opacity-80" style={{ color: colors.inkSubtle }}>
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>
      {tenants.length === 0 ? (
        <div style={card} className="text-center py-12">
          <Building2 className="w-8 h-8 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
          <div className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>No tenants onboarding yet</div>
          <div className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>Click “Onboard a client” to provision your first tenant.</div>
        </div>
      ) : tenants.map((t: any) => {
        const idx = stageIndex(t.current_stage);
        const pct = t.stage_progress_pct != null ? Math.round(t.stage_progress_pct)
          : Math.round((idx / (STAGES.length - 1)) * 100);
        const done = t.current_stage === 'FULLY_ONBOARDED';
        return (
          <div key={t.tenant_id} style={card}>
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: colors.primary + '15' }}>
                  <Building2 className="w-4.5 h-4.5" style={{ color: colors.primary }} />
                </div>
                <div className="min-w-0">
                  <div className="text-[14px] font-semibold truncate">{t.tenant_name || t.tenant_id}</div>
                  <div className="text-[11px] truncate" style={{ color: colors.inkSubtle }}>
                    {t.tenant_id}{t.industry_vertical ? ` · ${t.industry_vertical}` : ''}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[11px] px-2.5 py-1 rounded-full font-medium"
                  style={{ background: done ? 'rgba(39,166,68,0.12)' : colors.primary + '15', color: done ? colors.success : colors.primary }}>
                  {STAGES[idx]?.label || t.current_stage}
                </span>
                {!done && (
                  <button onClick={() => onAdvance(t.tenant_id)} disabled={advancing === t.tenant_id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all hover:opacity-90 disabled:opacity-50"
                    style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairlineStrong}` }}>
                    {advancing === t.tenant_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
                    Advance
                  </button>
                )}
              </div>
            </div>
            {/* Progress */}
            <div className="mt-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px]" style={{ color: colors.inkTertiary }}>Stage {idx + 1} of {STAGES.length}</span>
                <span className="text-[10px] tabular-nums" style={{ color: colors.inkTertiary }}>{pct}%</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: done ? colors.success : colors.primary }} />
              </div>
            </div>
            {/* Stage ladder */}
            <div className="flex items-center gap-1 mt-3 overflow-x-auto pb-1">
              {STAGES.map((s, i) => {
                const state = i < idx ? 'done' : i === idx ? 'current' : 'todo';
                const c = state === 'done' ? colors.success : state === 'current' ? colors.primary : colors.inkTertiary;
                return (
                  <div key={s.key} className="flex items-center gap-1 shrink-0" title={`${s.label} · ${s.who}`}>
                    <div className="w-6 h-6 rounded-md flex items-center justify-center"
                      style={{ background: state === 'todo' ? colors.surface2 : c + '18', border: `1px solid ${state === 'current' ? c : 'transparent'}` }}>
                      <s.icon className="w-3 h-3" style={{ color: c }} />
                    </div>
                    {i < STAGES.length - 1 && <div className="w-3 h-px" style={{ background: colors.hairline }} />}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Provisioning wizard ─────────────────────────────────────────────────────
function ProvisionWizard({ colors, adminSecret, onCancel, onDone }: any) {
  const [step, setStep] = useState(1);
  const [companyName, setCompanyName] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [tenantIdEdited, setTenantIdEdited] = useState(false);
  const [industry, setIndustry] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminName, setAdminName] = useState('');
  const [password, setPassword] = useState(genPassword());
  const [showPw, setShowPw] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const effectiveTenantId = tenantIdEdited ? tenantId : slugify(companyName);

  const copy = (label: string, value: string) => {
    navigator.clipboard?.writeText(value);
    setCopied(label); setTimeout(() => setCopied(null), 1500);
  };

  const canStep1 = companyName.trim() && effectiveTenantId;
  const canStep2 = /.+@.+\..+/.test(adminEmail) && password.length >= 8;

  const provision = async () => {
    setBusy(true); setError(null);
    try {
      if (!adminSecret) throw new Error('Enter the platform admin secret first (top of the page).');
      await api.initiateOnboarding(
        { tenant_id: effectiveTenantId, tenant_name: companyName.trim(), industry_vertical: industry.trim() || undefined },
        adminSecret,
      );
      const admin = await api.bootstrapTenantAdmin(
        effectiveTenantId,
        { email: adminEmail.trim().toLowerCase(), display_name: adminName.trim() || adminEmail.split('@')[0], password },
        adminSecret,
      );
      setResult({ admin, tenant_id: effectiveTenantId, tenant_name: companyName.trim() });
      setStep(4);
    } catch (e: any) {
      setError(e.message || 'Provisioning failed');
    } finally {
      setBusy(false);
    }
  };

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`, padding: '24px',
  };
  const input = "w-full px-3 py-2 rounded-lg text-[13px] focus:outline-none focus:ring-1";
  const inputStyle = { background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;
  const labelCls = "text-[12px] font-medium mb-1.5 block";

  const WSTEPS = [
    { n: 1, label: 'Company', icon: Building2 },
    { n: 2, label: 'First admin', icon: UserPlus },
    { n: 3, label: 'Review', icon: CheckCircle2 },
  ];

  return (
    <div style={card}>
      {/* Step indicator */}
      {step < 4 && (
        <div className="flex items-center gap-2 mb-6">
          {WSTEPS.map((s, i) => (
            <React.Fragment key={s.n}>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{
                background: step >= s.n ? colors.primary + '15' : colors.surface2,
                color: step >= s.n ? colors.primary : colors.inkSubtle,
                border: `1px solid ${step >= s.n ? colors.primary + '30' : colors.hairline}`,
              }}>
                {step > s.n ? <CheckCircle2 className="w-4 h-4" /> : <s.icon className="w-4 h-4" />}
                <span className="text-[12px] font-medium">{s.label}</span>
              </div>
              {i < WSTEPS.length - 1 && <ArrowRight className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />}
            </React.Fragment>
          ))}
        </div>
      )}

      {/* Step 1: Company */}
      {step === 1 && (
        <div className="space-y-4 max-w-lg">
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Company name</label>
            <input className={input} style={inputStyle} value={companyName}
              onChange={e => setCompanyName(e.target.value)} placeholder="Acme Corporation" autoFocus />
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Tenant ID</label>
            <input className={input} style={inputStyle} value={effectiveTenantId}
              onChange={e => { setTenantIdEdited(true); setTenantId(e.target.value.replace(/[^a-z0-9_]/g, '')); }}
              placeholder="tenant_acme" />
            <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
              A permanent, unique identifier. Auto-derived from the company name; edit if needed.
            </p>
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Industry vertical <span style={{ color: colors.inkTertiary }}>(optional)</span></label>
            <input className={input} style={inputStyle} value={industry}
              onChange={e => setIndustry(e.target.value)} placeholder="SaaS · Manufacturing · Financial Services" />
          </div>
        </div>
      )}

      {/* Step 2: First admin */}
      {step === 2 && (
        <div className="space-y-4 max-w-lg">
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
            This creates the client’s first administrator login. They’ll use it to sign in and complete setup.
          </p>
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Admin email</label>
            <input className={input} style={inputStyle} value={adminEmail} type="email"
              onChange={e => setAdminEmail(e.target.value)} placeholder="admin@acme.com" autoFocus />
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Admin name <span style={{ color: colors.inkTertiary }}>(optional)</span></label>
            <input className={input} style={inputStyle} value={adminName}
              onChange={e => setAdminName(e.target.value)} placeholder="Jordan Rivera" />
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkMuted }}>Temporary password</label>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <input className={input} style={inputStyle} value={password} type={showPw ? 'text' : 'password'}
                  onChange={e => setPassword(e.target.value)} />
                <button onClick={() => setShowPw(s => !s)} className="absolute right-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }}>
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <button onClick={() => setPassword(genPassword())}
                className="px-3 py-2 rounded-lg text-[12px] font-medium whitespace-nowrap hover:opacity-80"
                style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                Regenerate
              </button>
            </div>
            <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
              Share this over a secure channel. The client should change it on first sign-in.
            </p>
          </div>
        </div>
      )}

      {/* Step 3: Review */}
      {step === 3 && (
        <div className="space-y-4 max-w-lg">
          <div className="grid grid-cols-2 gap-3">
            {[
              ['Company', companyName],
              ['Tenant ID', effectiveTenantId],
              ['Industry', industry || '-'],
              ['Admin email', adminEmail],
            ].map(([k, v]) => (
              <div key={k} className="p-3 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                <div className="text-[10px] uppercase tracking-wider" style={{ color: colors.inkTertiary }}>{k}</div>
                <div className="text-[13px] font-medium mt-0.5 truncate" style={{ color: colors.ink }}>{v}</div>
              </div>
            ))}
          </div>
          <div className="p-3 rounded-lg flex items-start gap-2" style={{ background: colors.primary + '10', border: `1px solid ${colors.primary}25` }}>
            <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" style={{ color: colors.primary }} />
            <p className="text-[11px]" style={{ color: colors.inkMuted }}>
              This provisions the tenant’s onboarding record and its first admin login. Connecting data,
              deploying departments, and configuring AI are done by the client in their own session - you never touch their data.
            </p>
          </div>
          {error && <div className="text-[12px] px-3 py-2 rounded-lg" style={{ background: 'rgba(229,83,75,0.1)', color: colors.error }}>{error}</div>}
        </div>
      )}

      {/* Step 4: Success / handoff */}
      {step === 4 && result && (
        <div className="max-w-lg">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: 'rgba(39,166,68,0.12)' }}>
              <PartyPopper className="w-6 h-6" style={{ color: colors.success }} />
            </div>
            <div>
              <div className="text-[16px] font-semibold">{result.tenant_name} is provisioned</div>
              <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Hand these credentials to the client over a secure channel.</div>
            </div>
          </div>
          <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
            {[
              ['Sign-in URL', window.location.origin],
              ['Admin email', result.admin.email],
              ['Temporary password', password],
              ['Tenant ID', result.tenant_id],
            ].map(([k, v], i) => (
              <div key={k} className="flex items-center justify-between px-4 py-3"
                style={{ background: i % 2 ? colors.surface2 : colors.surface1, borderTop: i ? `1px solid ${colors.hairline}` : 'none' }}>
                <div className="min-w-0">
                  <div className="text-[10px] uppercase tracking-wider" style={{ color: colors.inkTertiary }}>{k}</div>
                  <div className="text-[13px] font-mono mt-0.5 truncate" style={{ color: colors.ink }}>{v}</div>
                </div>
                <button onClick={() => copy(k as string, v as string)} className="shrink-0 ml-3 p-1.5 rounded hover:opacity-70" style={{ color: colors.inkSubtle }}>
                  {copied === k ? <Check className="w-4 h-4" style={{ color: colors.success }} /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            ))}
          </div>
          <p className="text-[11px] mt-3" style={{ color: colors.inkTertiary }}>
            The password is shown once. When the client signs in, their Getting Started checklist walks them
            through connecting data, deploying a department, and running their first governed decision.
          </p>
        </div>
      )}

      {/* Footer nav */}
      <div className="flex items-center justify-between mt-6 pt-4 border-t" style={{ borderColor: colors.hairline }}>
        {step < 4 ? (
          <>
            <button onClick={step === 1 ? onCancel : () => setStep(step - 1)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium hover:opacity-80"
              style={{ color: colors.inkSubtle }}>
              <ArrowLeft className="w-4 h-4" /> {step === 1 ? 'Cancel' : 'Back'}
            </button>
            {step < 3 ? (
              <button onClick={() => setStep(step + 1)} disabled={step === 1 ? !canStep1 : !canStep2}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90 disabled:opacity-40"
                style={{ background: colors.primary }}>
                Next <ArrowRight className="w-4 h-4" />
              </button>
            ) : (
              <button onClick={provision} disabled={busy}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50"
                style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
                {busy ? 'Provisioning…' : 'Provision client'}
              </button>
            )}
          </>
        ) : (
          <>
            <span />
            <button onClick={onDone}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-semibold text-white hover:opacity-90"
              style={{ background: colors.primary }}>
              Done <CheckCircle2 className="w-4 h-4" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
