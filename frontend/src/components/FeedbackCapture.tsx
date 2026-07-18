import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Pencil, Check, X, Loader2, Sparkles } from 'lucide-react';
import { api } from '../api/client';

interface Props {
  /** The SkillExecution id this feedback attaches to. */
  executionId: string;
  /** The instruction/task the agent was given (grounds a correction). */
  instruction?: string;
  colors: Record<string, string>;
}

/**
 * Human feedback on a governed decision - the strongest signal the AI Foundry
 * collects. A thumb is a rating; a correction is expert ground truth. Both post
 * to /foundry/feedback and become tenant-scoped training data.
 */
export default function FeedbackCapture({ executionId, instruction, colors }: Props) {
  const [state, setState] = useState<'idle' | 'correcting' | 'saving' | 'done'>('idle');
  const [correction, setCorrection] = useState('');
  const [outcome, setOutcome] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (body: { rating?: number; corrected_answer?: string }) => {
    setState('saving'); setError(null);
    try {
      const r = await api.recordFoundryFeedback({ execution_id: executionId, instruction, ...body });
      setOutcome(r.evaluation_label);
      setState('done');
    } catch (e: any) {
      setError(e.message || 'Could not save feedback');
      setState('idle');
    }
  };

  if (state === 'done') {
    return (
      <div className="mt-4 flex items-center gap-2 px-4 py-3 rounded-xl text-[12px]"
        style={{ background: 'rgba(39,166,68,0.1)', border: '1px solid rgba(39,166,68,0.25)', color: colors.inkMuted }}>
        <Sparkles className="w-4 h-4 shrink-0" style={{ color: colors.success }} />
        <span>
          Thanks - this decision is now a <span className="font-semibold" style={{ color: colors.ink }}>{outcome.toLowerCase()}</span> training example in your AI Foundry.
        </span>
      </div>
    );
  }

  const btn = "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all hover:opacity-90 disabled:opacity-50";

  return (
    <div className="mt-4 p-4 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
      {state === 'correcting' ? (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Pencil className="w-3.5 h-3.5" style={{ color: colors.primary }} />
            <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>What should the answer have been?</span>
          </div>
          <textarea
            value={correction}
            onChange={e => setCorrection(e.target.value)}
            rows={3}
            autoFocus
            placeholder="The ideal answer or decision - this becomes expert ground truth for training."
            className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none focus:ring-1 resize-y"
            style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
          />
          <div className="flex items-center justify-end gap-2 mt-2">
            <button onClick={() => { setState('idle'); setCorrection(''); }} className={btn}
              style={{ background: 'transparent', color: colors.inkSubtle }}>
              <X className="w-3.5 h-3.5" /> Cancel
            </button>
            <button onClick={() => submit({ corrected_answer: correction.trim() })}
              disabled={!correction.trim() || (state as string) === 'saving'} className={btn}
              style={{ background: colors.primary, color: '#fff' }}>
              {(state as string) === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Save correction
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>Was this the right call?</span>
          <div className="flex items-center gap-2">
            <button onClick={() => submit({ rating: 5 })} disabled={state === 'saving'} className={btn}
              style={{ background: 'rgba(39,166,68,0.1)', color: colors.success, border: '1px solid rgba(39,166,68,0.2)' }}>
              <ThumbsUp className="w-3.5 h-3.5" /> Yes
            </button>
            <button onClick={() => submit({ rating: 1 })} disabled={state === 'saving'} className={btn}
              style={{ background: 'rgba(229,83,75,0.1)', color: colors.error, border: '1px solid rgba(229,83,75,0.2)' }}>
              <ThumbsDown className="w-3.5 h-3.5" /> No
            </button>
            <button onClick={() => setState('correcting')} disabled={state === 'saving'} className={btn}
              style={{ background: colors.surface3, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
              <Pencil className="w-3.5 h-3.5" /> Suggest correction
            </button>
          </div>
          {state === 'saving' && <Loader2 className="w-4 h-4 animate-spin" style={{ color: colors.primary }} />}
          <span className="text-[10px]" style={{ color: colors.inkTertiary }}>Feeds your AI Foundry training data</span>
        </div>
      )}
      {error && <div className="text-[11px] mt-2" style={{ color: colors.error }}>{error}</div>}
    </div>
  );
}
