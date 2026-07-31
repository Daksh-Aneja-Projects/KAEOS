import React, { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Eye, EyeOff, Loader2, ArrowRight, CheckCircle2, AlertTriangle, Sun, Moon } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import KaeosLogo from '../components/KaeosLogo';

/**
 * Invite redemption. This is the ONE page that has to render for a signed-out
 * visitor, so it lives on a public route outside the auth gate in App.tsx.
 * POST /auth/accept-invite takes { token, password } and activates the account.
 */

// The backend returns machine slugs; a person reading the screen gets English.
const ERROR_COPY: Record<string, string> = {
  invalid_or_expired_invite: 'This invitation link is no longer valid. It may have expired or already been used. Ask your administrator to send a new one.',
  weak_password: 'That password is too weak. Use at least 8 characters and mix letters, numbers, and a symbol.',
  user_not_found: 'We could not find an account for this invitation. Ask your administrator to re-send it.',
};

export default function AcceptInvite() {
  const { colors, theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  // Accept the token from the link, but let the user paste it if the mail
  // client mangled the URL.
  const [token, setToken] = useState(params.get('token') || '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<{ email: string } | null>(null);

  const mismatch = confirm.length > 0 && password !== confirm;
  const valid = token.trim().length > 0 && password.length >= 8 && !mismatch;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.acceptInvite({ token: token.trim(), password });
      setDone({ email: res.email });
      // Give the confirmation a beat to register, then hand off to sign-in.
      setTimeout(() => navigate('/', { replace: true }), 2200);
    } catch (err: any) {
      const raw = String(err?.message || 'Something went wrong');
      setError(ERROR_COPY[raw] || raw);
    } finally {
      setBusy(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    background: colors.canvas, borderColor: colors.hairline, color: colors.ink,
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{ background: colors.canvas, fontFamily: '"Inter", -apple-system, sans-serif' }}>

      <div className="absolute inset-0 opacity-30" style={{
        background: `radial-gradient(ellipse at 20% 50%, ${colors.primary}15 0%, transparent 50%),
                     radial-gradient(ellipse at 80% 20%, ${colors.primary}10 0%, transparent 50%)`,
      }} />

      <button onClick={toggle} aria-label="Toggle theme"
        className="absolute top-6 right-6 p-2 rounded-lg transition-colors"
        style={{ color: colors.inkSubtle, background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>

      <div className="relative z-10 w-full max-w-[420px] mx-4">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
            <KaeosLogo className="w-8 h-8" color="#ffffff" />
          </div>
          <h1 className="text-[28px] font-bold tracking-tight" style={{ color: colors.ink }}>KAEOS</h1>
          <p className="text-[13px] mt-1 tracking-wide" style={{ color: colors.inkSubtle }}>
            Knowledge-Augmented Enterprise OS
          </p>
        </div>

        {done ? (
          <div className="rounded-2xl p-8 text-center space-y-3"
            style={{ background: colors.surface1, border: `1px solid ${colors.success}55` }}>
            <CheckCircle2 className="w-10 h-10 mx-auto" style={{ color: colors.success }} />
            <h2 className="text-[18px] font-semibold" style={{ color: colors.ink }}>Your account is active</h2>
            <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
              <span className="font-medium" style={{ color: colors.ink }}>{done.email}</span> is ready. Taking you to sign in.
            </p>
            <button onClick={() => navigate('/', { replace: true })}
              className="mt-2 w-full py-2.5 rounded-lg text-[14px] font-semibold text-white flex items-center justify-center gap-2"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}dd)` }}>
              Go to sign in <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="rounded-2xl p-8 space-y-5"
            style={{
              background: colors.surface1, border: `1px solid ${colors.hairline}`,
              boxShadow: theme === 'dark' ? '0 25px 50px rgba(0,0,0,0.5)' : '0 25px 50px rgba(0,0,0,0.08)',
            }}>

            <div className="text-center mb-2">
              <h2 className="text-[18px] font-semibold" style={{ color: colors.ink }}>Accept your invitation</h2>
              <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>
                Choose a password to activate your account
              </p>
            </div>

            {error && (
              <div className="px-3 py-2 rounded-lg text-[12px] font-medium flex items-start gap-2"
                style={{ background: colors.error + '15', color: colors.error, border: `1px solid ${colors.error}25` }}>
                <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
                <span>{error}</span>
              </div>
            )}

            {/* Only shown when the link did not carry a token. */}
            {!params.get('token') && (
              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1.5"
                  style={{ color: colors.inkSubtle }}>Invitation code</label>
                <input value={token} onChange={e => setToken(e.target.value)} required
                  className="w-full px-3.5 py-2.5 rounded-lg border text-[14px] font-mono transition-all focus:outline-none focus:ring-2"
                  style={inputStyle}
                  placeholder="Paste the code from your invitation email" />
              </div>
            )}

            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1.5"
                style={{ color: colors.inkSubtle }}>New password</label>
              <div className="relative">
                <input type={showPw ? 'text' : 'password'} value={password}
                  onChange={e => setPassword(e.target.value)}
                  autoComplete="new-password" required minLength={8}
                  className="w-full px-3.5 py-2.5 rounded-lg border text-[14px] pr-10 transition-all focus:outline-none focus:ring-2"
                  style={inputStyle}
                  placeholder="At least 8 characters" />
                <button type="button" onClick={() => setShowPw(!showPw)}
                  aria-label={showPw ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: colors.inkSubtle }}>
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1.5"
                style={{ color: colors.inkSubtle }}>Confirm password</label>
              <input type={showPw ? 'text' : 'password'} value={confirm}
                onChange={e => setConfirm(e.target.value)}
                autoComplete="new-password" required
                className="w-full px-3.5 py-2.5 rounded-lg border text-[14px] transition-all focus:outline-none focus:ring-2"
                style={{ ...inputStyle, borderColor: mismatch ? colors.error : colors.hairline }}
                placeholder="Type it once more" />
              {mismatch && (
                <p className="text-[11px] mt-1.5" style={{ color: colors.error }}>The two passwords do not match.</p>
              )}
            </div>

            <button type="submit" disabled={busy || !valid}
              className="w-full py-2.5 rounded-lg text-[14px] font-semibold text-white flex items-center justify-center gap-2 transition-all hover:brightness-110 disabled:opacity-50"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}dd)` }}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Activate account <ArrowRight className="w-4 h-4" /></>}
            </button>

            <button type="button" onClick={() => navigate('/', { replace: true })}
              className="w-full text-[12px] transition-opacity hover:opacity-80"
              style={{ color: colors.inkSubtle }}>
              Already have an account? Sign in
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
