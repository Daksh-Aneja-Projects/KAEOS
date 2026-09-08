import { Lock } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

/**
 * A 402 (capability boundary) or 403 (permission boundary) is not a
 * failure: it is the governance model working. Both render as a calm
 * notice with the backend's own sentence, never a red error with a
 * pointless retry.
 *
 * Extracted from GovernedExecution.tsx so a second Enterprise page (Object
 * Explorer, F13) shows the identical notice, not a re-typed variant.
 */
export function EnterpriseNotice({ message }: { message: string }) {
  const { colors } = useTheme();
  return (
    <div className="rounded-xl p-5 flex items-start gap-3"
      style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Lock className="w-5 h-5 shrink-0 mt-0.5" style={{ color: colors.primary }} />
      <div>
        <div className="text-[14px] font-semibold" style={{ color: colors.ink }}>Not available here</div>
        <p className="text-[13px] mt-1 leading-relaxed" style={{ color: colors.inkSubtle }}>{message}</p>
      </div>
    </div>
  );
}
