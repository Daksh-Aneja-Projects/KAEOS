import { useEffect, useRef, useState } from 'react';
import { Palette, Save, Check, AlertCircle, RotateCcw, Lock } from 'lucide-react';
import { api, type Branding } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useBranding } from '../context/BrandingContext';
import { useAuth } from '../context/AuthContext';

// Mirror the backend validators (app/api/routes/branding.py) so the form fails
// fast client-side instead of round-tripping a 400.
const HEX = /^#[0-9a-fA-F]{6}$/;
const validHex = (v: string) => HEX.test(v);
const validLogo = (v: string): boolean => {
  if (!v) return true; // optional
  try {
    const u = new URL(v);
    // http(s) with a host only. new URL() rejects relative paths (no base); a
    // javascript:/data: URL parses but fails the scheme+host test below.
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.host;
  } catch {
    return false;
  }
};

type Form = {
  product_name: string;
  primary_color: string;
  accent_color: string;
  logo_url: string;
  login_subtitle: string;
};

const fromBrand = (b: Branding): Form => ({
  product_name: b.product_name,
  primary_color: b.primary_color,
  accent_color: b.accent_color,
  logo_url: b.logo_url || '',
  login_subtitle: b.login_subtitle || '',
});

export default function BrandingSettings() {
  const { colors } = useTheme();
  const { brand, reloadBranding } = useBranding();
  const { isAdmin } = useAuth();

  const [form, setForm] = useState<Form>(fromBrand(brand));
  const dirtyRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed from the live brand, but never clobber an in-progress edit. Handles the
  // provider resolving its fetch after this tab has already mounted.
  useEffect(() => {
    if (!dirtyRef.current) setForm(fromBrand(brand));
  }, [brand]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    dirtyRef.current = true;
    setSaved(false);
    setForm(f => ({ ...f, [k]: v }));
  };

  const nameError = !form.product_name.trim();
  const primaryError = !validHex(form.primary_color);
  const accentError = !validHex(form.accent_color);
  const logoError = !validLogo(form.logo_url.trim());
  const hasError = nameError || primaryError || accentError || logoError;

  const reset = () => { dirtyRef.current = false; setForm(fromBrand(brand)); setError(null); setSaved(false); };

  const save = async () => {
    if (hasError || !isAdmin) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateBranding({
        product_name: form.product_name.trim(),
        primary_color: form.primary_color.toLowerCase(),
        accent_color: form.accent_color.toLowerCase(),
        logo_url: form.logo_url.trim() || null,
        login_subtitle: form.login_subtitle.trim() || null,
      });
      dirtyRef.current = false;
      await reloadBranding(); // re-fetch + re-apply the brand app-wide
      setSaved(true);
    } catch (e: any) {
      setError(e?.message || 'Could not save branding.');
    } finally {
      setSaving(false);
    }
  };

  const field = {
    background: colors.inputBg,
    border: `1px solid ${colors.hairline}`,
    color: colors.ink,
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Form */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-2 mb-1">
          <Palette className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>White-label branding</span>
        </div>
        <p className="text-[13px] mb-4" style={{ color: colors.inkSubtle }}>
          Make KAEOS your own. Your brand applies to the app shell and the sign-in screen for everyone in your workspace.
        </p>

        {!isAdmin && (
          <div className="flex items-start gap-2 mb-4 p-3 rounded-lg text-[12px]"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
            <Lock className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>Only workspace admins can change branding. You can review the current brand below.</span>
          </div>
        )}

        <fieldset disabled={!isAdmin} className="space-y-4" style={{ opacity: isAdmin ? 1 : 0.7 }}>
          {/* Product name */}
          <div>
            <label htmlFor="b-name" className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>Product name</label>
            <input id="b-name" type="text" value={form.product_name} onChange={e => set('product_name', e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-lg text-[13px] focus:outline-none focus:ring-1"
              style={{ ...field, borderColor: nameError ? colors.error : colors.hairline }} />
            {nameError && <FieldError colors={colors}>Product name is required.</FieldError>}
          </div>

          {/* Colors */}
          <div className="grid grid-cols-2 gap-3">
            <ColorField id="b-primary" label="Primary color" value={form.primary_color}
              invalid={primaryError} onChange={v => set('primary_color', v)} colors={colors} field={field} />
            <ColorField id="b-accent" label="Accent color" value={form.accent_color}
              invalid={accentError} onChange={v => set('accent_color', v)} colors={colors} field={field} />
          </div>

          {/* Logo URL */}
          <div>
            <label htmlFor="b-logo" className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>Logo URL</label>
            <input id="b-logo" type="url" inputMode="url" placeholder="https://cdn.example.com/logo.svg"
              value={form.logo_url} onChange={e => set('logo_url', e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-lg text-[13px] focus:outline-none focus:ring-1"
              style={{ ...field, borderColor: logoError ? colors.error : colors.hairline }} />
            {logoError
              ? <FieldError colors={colors}>Must be an http(s) URL. Inline (data:) and script (javascript:) URLs are rejected.</FieldError>
              : <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>Optional. Shown in the sidebar and on sign-in.</p>}
          </div>

          {/* Login subtitle */}
          <div>
            <label htmlFor="b-subtitle" className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>Sign-in subtitle</label>
            <input id="b-subtitle" type="text" placeholder="The Governed AI Workforce"
              value={form.login_subtitle} onChange={e => set('login_subtitle', e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-lg text-[13px] focus:outline-none focus:ring-1"
              style={field} />
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2 text-[12px]" style={{ color: colors.error }}>
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" /><span>{error}</span>
            </div>
          )}

          {isAdmin && (
            <div className="flex items-center gap-2 pt-1">
              <button type="button" onClick={save} disabled={saving || hasError || !dirtyRef.current}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-semibold text-white disabled:opacity-50"
                style={{ background: colors.primary }}>
                {saving ? <span className="w-4 h-4 border-2 border-white/60 border-t-transparent rounded-full animate-spin" />
                  : saved ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
                {saving ? 'Saving…' : saved ? 'Saved' : 'Save branding'}
              </button>
              <button type="button" onClick={reset}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium"
                style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                <RotateCcw className="w-3.5 h-3.5" /> Reset
              </button>
            </div>
          )}
        </fieldset>
      </div>

      {/* Live preview */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <span className="text-[12px] font-bold uppercase tracking-wide" style={{ color: colors.inkTertiary }}>Live preview</span>
        <div className="mt-3 rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.canvas }}>
          {/* Shell header mock */}
          <div className="flex items-center gap-2.5 px-4 py-3 border-b" style={{ borderColor: colors.hairline }}>
            <BrandMark logoUrl={validLogo(form.logo_url) ? form.logo_url.trim() : ''}
              name={form.product_name} color={validHex(form.primary_color) ? form.primary_color : colors.primary} />
            <span className="text-[15px] font-semibold tracking-tight" style={{ color: colors.ink }}>
              {form.product_name || 'KAEOS'}
            </span>
          </div>
          {/* Sign-in mock */}
          <div className="px-5 py-6 text-center">
            <BrandMark logoUrl={validLogo(form.logo_url) ? form.logo_url.trim() : ''}
              name={form.product_name} color={validHex(form.primary_color) ? form.primary_color : colors.primary} size={44} center />
            <div className="mt-3 text-[17px] font-semibold" style={{ color: colors.ink }}>{form.product_name || 'KAEOS'}</div>
            <div className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{form.login_subtitle || 'The Governed AI Workforce'}</div>
            <button className="mt-4 w-full py-2 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: validHex(form.primary_color) ? form.primary_color : colors.primary }}>
              Sign in
            </button>
            <div className="mt-3 flex items-center justify-center gap-2">
              <span className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                style={{ background: (validHex(form.accent_color) ? form.accent_color : colors.info) + '22', color: validHex(form.accent_color) ? form.accent_color : colors.info }}>
                Accent
              </span>
              <span className="w-4 h-4 rounded" style={{ background: validHex(form.primary_color) ? form.primary_color : colors.primary }} />
              <span className="w-4 h-4 rounded" style={{ background: validHex(form.accent_color) ? form.accent_color : colors.info }} />
            </div>
          </div>
        </div>
        <p className="text-[11px] mt-3" style={{ color: colors.inkTertiary }}>
          The preview updates as you type. Saving applies your brand for the whole workspace.
        </p>
      </div>
    </div>
  );
}

function BrandMark({ logoUrl, name, color, size = 28, center = false }: {
  logoUrl: string; name: string; color: string; size?: number; center?: boolean;
}) {
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [logoUrl]);
  const initial = (name || 'K').charAt(0).toUpperCase();
  if (logoUrl && !broken) {
    return (
      <img src={logoUrl} alt="" onError={() => setBroken(true)}
        className={`rounded object-contain ${center ? 'mx-auto' : ''}`}
        style={{ width: size, height: size, background: '#ffffff' }} />
    );
  }
  return (
    <div className={`rounded flex items-center justify-center font-bold text-white ${center ? 'mx-auto' : ''}`}
      style={{ width: size, height: size, background: color, fontSize: size * 0.45 }}>
      {initial}
    </div>
  );
}

function ColorField({ id, label, value, invalid, onChange, colors, field }: {
  id: string; label: string; value: string; invalid: boolean;
  onChange: (v: string) => void; colors: Record<string, string>; field: React.CSSProperties;
}) {
  const safe = HEX.test(value) ? value : '#000000';
  return (
    <div>
      <label htmlFor={id} className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>{label}</label>
      <div className="mt-1 flex items-center gap-2">
        <input aria-label={`${label} picker`} type="color" value={safe} onChange={e => onChange(e.target.value)}
          className="w-9 h-9 rounded-lg cursor-pointer flex-shrink-0 p-0"
          style={{ border: `1px solid ${colors.hairline}`, background: 'transparent' }} />
        <input id={id} type="text" value={value} onChange={e => onChange(e.target.value)}
          spellCheck={false} placeholder="#5e6ad2"
          className="flex-1 min-w-0 px-3 py-2 rounded-lg text-[13px] font-mono focus:outline-none focus:ring-1"
          style={{ ...field, borderColor: invalid ? colors.error : colors.hairline }} />
      </div>
      {invalid && <FieldError colors={colors}>Use a #RRGGBB hex color.</FieldError>}
    </div>
  );
}

function FieldError({ children, colors }: { children: React.ReactNode; colors: Record<string, string> }) {
  return <p className="text-[11px] mt-1" style={{ color: colors.error }}>{children}</p>;
}
