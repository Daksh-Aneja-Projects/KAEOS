import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { Eye, EyeOff, Loader2, ArrowRight, Sun, Moon } from 'lucide-react';
import KaeosLogo from '../components/KaeosLogo';

export default function LoginPage() {
  const { login } = useAuth();
  const { colors, theme, toggle } = useTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPw, setShowPw] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    const result = await login(email.trim(), password);
    if (!result.ok) setError(result.error || 'Login failed');
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{ background: colors.canvas, fontFamily: '"Inter", -apple-system, sans-serif' }}>
      
      {/* Subtle animated gradient background */}
      <div className="absolute inset-0 opacity-30" style={{
        background: `radial-gradient(ellipse at 20% 50%, ${colors.primary}15 0%, transparent 50%),
                     radial-gradient(ellipse at 80% 20%, ${colors.primary}10 0%, transparent 50%),
                     radial-gradient(ellipse at 50% 80%, ${colors.primary}08 0%, transparent 50%)`
      }} />

      {/* Theme toggle */}
      <button onClick={toggle} className="absolute top-6 right-6 p-2 rounded-lg transition-colors"
        style={{ color: colors.inkSubtle, background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>

      {/* Login Card */}
      <div className="relative z-10 w-full max-w-[400px] mx-4">
        {/* Logo */}
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

        {/* Form Card */}
        <form onSubmit={handleSubmit} className="rounded-2xl p-8 space-y-5"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`,
            boxShadow: theme === 'dark' ? '0 25px 50px rgba(0,0,0,0.5)' : '0 25px 50px rgba(0,0,0,0.08)' }}>
          
          <div className="text-center mb-2">
            <h2 className="text-[18px] font-semibold" style={{ color: colors.ink }}>Sign in</h2>
            <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>
              Enter your credentials to access the platform
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="px-3 py-2 rounded-lg text-[12px] font-medium"
              style={{ background: '#ef444415', color: '#ef4444', border: '1px solid #ef444425' }}>
              {error}
            </div>
          )}

          {/* Email */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1.5"
              style={{ color: colors.inkSubtle }}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              autoComplete="email" required
              className="w-full px-3.5 py-2.5 rounded-lg border text-[14px] transition-all focus:outline-none focus:ring-2"
              style={{
                background: colors.canvas, borderColor: colors.hairline, color: colors.ink,
              }}
              placeholder="you@company.com" />
          </div>

          {/* Password */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1.5"
              style={{ color: colors.inkSubtle }}>Password</label>
            <div className="relative">
              <input type={showPw ? 'text' : 'password'} value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password" required
                className="w-full px-3.5 py-2.5 rounded-lg border text-[14px] pr-10 transition-all focus:outline-none focus:ring-2"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                placeholder="••••••" />
              <button type="button" onClick={() => setShowPw(!showPw)}
                className="absolute right-3 top-1/2 -translate-y-1/2"
                style={{ color: colors.inkSubtle }}>
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Submit */}
          <button type="submit" disabled={loading}
            className="w-full py-2.5 rounded-lg text-[14px] font-semibold text-white flex items-center justify-center gap-2 transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}dd)` }}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Sign in <ArrowRight className="w-4 h-4" /></>}
          </button>
        </form>

        {/* First-run hint: there is no default/public login — the root admin is
            provisioned from ADMIN_EMAIL / ADMIN_PASSWORD in .env. */}
        <div className="mt-5 text-center px-2">
          <p className="text-[11px] leading-relaxed" style={{ color: colors.inkSubtle }}>
            <span className="font-semibold" style={{ color: colors.primary }}>First run?</span>{' '}
            Sign in with the <span className="font-mono">ADMIN_EMAIL</span> /{' '}
            <span className="font-mono">ADMIN_PASSWORD</span> you set in{' '}
            <span className="font-mono">.env</span>
          </p>
        </div>

        {/* Footer */}
        <p className="text-center mt-6 text-[10px] tracking-wider uppercase" style={{ color: colors.inkTertiary }}>
          Governed Enterprise AI
        </p>
      </div>
    </div>
  );
}
