import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { Swords, Loader2, ShieldAlert, Play } from 'lucide-react';

/**
 * Autonomy Wargaming (IP-4). Run an adversarial CASCADE of shocks against the twin
 * and score how it holds up: a resilience gauge, the integrity curve as each shock
 * compounds, the weakest link, and how safely the agents respond under stress.
 * Fragility and damage come from the real twin (skill confidence + adverse history).
 */
const GRADE_COLOR: Record<string, string> = { A: '#22c55e', B: '#84cc16', C: '#f59e0b', D: '#f97316', F: '#ef4444' };

const WargamePanel: React.FC<{ colors: any; onImpact?: (result: any) => void }> = ({ colors, onImpact }) => {
  const [playbooks, setPlaybooks] = useState<any[]>([]);
  const [playbook, setPlaybook] = useState('cyber_cascade');
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    api.getWargamePlaybooks().then(d => setPlaybooks(d.playbooks || [])).catch(() => {});
  }, []);

  const run = async () => {
    setRunning(true); setResult(null);
    try {
      const r = await api.runWargame(playbook);
      setResult(r);
      onImpact?.(r);   // let the parent cascade the blast across the live twin
    }
    catch (e) { console.error(e); }
    finally { setRunning(false); }
  };

  const gradeColor = result ? (GRADE_COLOR[result.grade] || colors.inkSubtle) : colors.inkSubtle;
  const res = result?.resilience_score ?? 0;

  return (
    <div className="space-y-3">
      <style>{`@keyframes wgRing { from { stroke-dashoffset: 264; } }`}</style>
      <div className="flex items-center gap-2">
        <Swords className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[13px] font-semibold" style={{ color: colors.ink }}>Autonomy Wargame</span>
      </div>
      <p className="text-[11px]" style={{ color: colors.inkSubtle }}>
        Stress the twin with an adversarial cascade and score organizational resilience.
      </p>

      <div>
        <label className="text-[11px] font-semibold mb-1 block" style={{ color: colors.inkSubtle }}>Adversarial playbook</label>
        <select value={playbook} onChange={e => setPlaybook(e.target.value)}
          className="w-full text-sm p-2 rounded outline-none"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
          {playbooks.map(p => <option key={p.id} value={p.id}>{p.id.replace(/_/g, ' ')} ({p.steps.length} shocks)</option>)}
        </select>
      </div>
      <button onClick={run} disabled={running}
        className="w-full py-2 rounded text-white font-semibold text-sm flex items-center justify-center gap-1.5"
        style={{ background: running ? colors.inkSubtle : colors.primary, opacity: running ? 0.7 : 1 }}>
        {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        {running ? 'Wargaming…' : 'Run Wargame'}
      </button>

      {result && (
        <div className="space-y-3">
          {/* Resilience gauge */}
          <div className="rounded-lg p-3 flex items-center gap-3" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
            <div className="w-20 h-20 relative shrink-0">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke={colors.hairline} strokeWidth="8" />
                <circle cx="50" cy="50" r="42" fill="none" stroke={gradeColor} strokeWidth="8" strokeLinecap="round"
                  strokeDasharray={`${(res / 100) * 264} 264`} style={{ animation: 'wgRing 1s ease-out' }} />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-[20px] font-bold" style={{ color: gradeColor }}>{result.grade}</span>
              </div>
            </div>
            <div>
              <div className="text-[22px] font-bold" style={{ color: gradeColor }}>{res}%</div>
              <div className="text-[10px]" style={{ color: colors.inkSubtle }}>integrity retained</div>
              {result.safe_response_rate != null && (
                <div className="text-[10px] mt-1" style={{ color: colors.inkSubtle }}>
                  {(result.safe_response_rate * 100).toFixed(0)}% handled autonomously
                </div>
              )}
            </div>
          </div>

          {/* Cascade — integrity dropping per shock */}
          <div className="space-y-1.5">
            {result.steps.map((s: any) => (
              <div key={s.step} className="rounded-lg p-2" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-medium" style={{ color: colors.ink }}>{s.shock.replace(/_/g, ' ')}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full"
                    style={{ background: s.response === 'autonomous' ? '#22c55e18' : '#f59e0b18', color: s.response === 'autonomous' ? '#22c55e' : '#f59e0b' }}>
                    {s.response === 'autonomous' ? 'autonomous' : 'human'}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[9px] w-16 truncate" style={{ color: colors.inkSubtle }}>{s.department}</span>
                  <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: colors.hairline }}>
                    <div className="h-full rounded-full transition-all" style={{ width: `${s.integrity_after}%`, background: s.integrity_after >= 65 ? '#22c55e' : s.integrity_after >= 40 ? '#f59e0b' : '#ef4444' }} />
                  </div>
                  <span className="text-[9px] font-mono w-16 text-right" style={{ color: colors.inkSubtle }}>-{s.damage} → {s.integrity_after}%</span>
                </div>
              </div>
            ))}
          </div>

          {/* Weakest link + verdict */}
          <div className="rounded-lg p-2.5 flex items-start gap-2" style={{ background: '#ef444410', border: `1px solid #ef444433` }}>
            <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" style={{ color: '#ef4444' }} />
            <div className="text-[11px]" style={{ color: colors.ink }}>
              Weakest link: <span className="font-semibold">{result.weakest_link?.department}</span>
              <span style={{ color: colors.inkSubtle }}> (−{result.weakest_link?.damage} integrity)</span>
              <div className="text-[10px] mt-1" style={{ color: colors.inkSubtle }}>{result.verdict}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default WargamePanel;
