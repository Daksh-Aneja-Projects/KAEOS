import { Lock, AlertTriangle } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';

/** Renders a mutationTone() result: a governance notice (primary + Lock) or
 * a real error (error + AlertTriangle) - never a red error for a 402/403. */
export function InlineFeedback({ notice, message }: { notice: boolean; message: string }) {
  const { colors } = useTheme();
  if (!message) return null;
  return (
    <div className="flex items-start gap-1.5 text-[12px]" style={{ color: notice ? colors.primary : colors.error }}>
      {notice ? <Lock className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
      <span>{message}</span>
    </div>
  );
}
