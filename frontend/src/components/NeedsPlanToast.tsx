import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowUpRight, Lock, X } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { announce } from './a11y/LiveRegion';

/**
 * Consumer for the backend's 402 "needs-plan" contract.
 *
 * Entitlement-gated endpoints answer with a 402 and a human message ("Feature X
 * requires the Growth plan"). Until now nothing surfaced it — the request just
 * threw a generic ApiError. This host listens for the `kaeos:needs-plan` window
 * event (fired from the shared API error path in api/http.ts), shows a
 * dismissible upgrade toast with the backend's own message, and offers a CTA to
 * the billing tab. Also announced assertively for screen-reader users.
 */
const NEEDS_PLAN_EVENT = 'kaeos:needs-plan';

export default function NeedsPlanToast() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const onNeedsPlan = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string }>).detail;
      const text = detail?.message?.trim() || 'This feature requires a plan upgrade.';
      setMsg(text);
      announce(text, 'assertive');
    };
    window.addEventListener(NEEDS_PLAN_EVENT, onNeedsPlan);
    return () => window.removeEventListener(NEEDS_PLAN_EVENT, onNeedsPlan);
  }, []);

  // Auto-dismiss so it never sticks; re-armed each time a new message arrives.
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 9000);
    return () => clearTimeout(t);
  }, [msg]);

  if (!msg) return null;

  return (
    <div role="alertdialog" aria-label="Plan upgrade required"
      className="fixed bottom-5 right-5 z-[9999] max-w-sm rounded-xl shadow-lg"
      style={{ background: colors.surface1, border: `1px solid ${colors.hairlineStrong || colors.hairline}` }}>
      <div className="flex items-start gap-3 p-4">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: colors.primary + '18' }}>
          <Lock className="w-4.5 h-4.5" style={{ color: colors.primary }} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>Plan upgrade required</div>
          <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{msg}</p>
          <button
            onClick={() => { setMsg(null); navigate('/platform/settings?tab=billing'); }}
            className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white transition-all hover:opacity-90"
            style={{ background: colors.primary }}>
            View plans <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>
        <button onClick={() => setMsg(null)} aria-label="Dismiss" className="shrink-0 p-1 rounded hover:opacity-70" style={{ color: colors.inkSubtle }}>
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
