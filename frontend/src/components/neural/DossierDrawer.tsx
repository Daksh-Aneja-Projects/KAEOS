import React, { useEffect, useState } from 'react';
import {
  X, Bot, Zap, Shield, User, ListOrdered, Replace, Clock,
  CheckCircle, Layers, Wrench, Activity,
} from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { api } from '../../api/client';
import { CountUp } from '../CountUp';
import { humanize } from '../../lib/format';

export type DossierTarget =
  | { kind: 'agent'; id: string; label: string }
  | { kind: 'task'; id: string; label: string };

/**
 * The trust card for one agent or task: who it is, how autonomous it is
 * allowed to be (the ladder), what it replaces, the human's role, and its
 * standard operating procedure - everything derived live from the runtime.
 */
export default function DossierDrawer({
  target,
  onClose,
}: {
  target: DossierTarget;
  onClose: () => void;
}) {
  const { colors } = useTheme();
  const [dossier, setDossier] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDossier(null);
    setError(null);
    const load = target.kind === 'agent'
      ? api.getAgentDossier(target.id)
      : api.getSkillDossier(target.id);
    load.then(setDossier).catch(e => setError(e?.message || 'Could not load the dossier'));
  }, [target]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const section = (title: string, icon: React.ReactNode, body: React.ReactNode) => (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>
        {icon} {title}
      </div>
      {body}
    </div>
  );

  const autonomy = dossier?.autonomy;
  const stats = dossier?.execution_stats;

  return (
    <div
      className="absolute top-0 right-0 bottom-0 w-[380px] max-w-full flex flex-col z-20 shadow-2xl"
      style={{ background: colors.surface1, borderLeft: `1px solid ${colors.hairline}` }}
      role="dialog"
      aria-label={`${target.label} dossier`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 p-4" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${colors.primary}22`, color: colors.primary }}>
            {target.kind === 'agent' ? <Bot className="w-5 h-5" /> : <Zap className="w-5 h-5" />}
          </div>
          <div className="min-w-0">
            <div className="text-[15px] font-bold truncate" style={{ color: colors.ink }}>
              {dossier?.name || dossier?.label || target.label}
            </div>
            <div className="text-[12px] truncate" style={{ color: colors.inkSubtle }}>
              {target.kind === 'agent'
                ? (dossier?.department?.name ? `${dossier.department.name} agent` : 'Department agent')
                : `Task${dossier?.department ? ` in ${humanize(dossier.department)}` : ''}`}
            </div>
          </div>
        </div>
        <button onClick={onClose} aria-label="Close dossier"
          className="p-1.5 rounded-lg transition-colors hover:opacity-70" style={{ color: colors.inkSubtle }}>
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {error ? (
          <div className="text-[13px]" style={{ color: colors.error }}>{error}</div>
        ) : !dossier ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-5 h-5 border-2 rounded-full animate-spin"
              style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
          </div>
        ) : (
          <>
            {/* Status + role */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                style={{
                  background: (dossier.status === 'ACTIVE' ? colors.success : colors.warning) + '22',
                  color: dossier.status === 'ACTIVE' ? colors.success : colors.warning,
                }}>
                {humanize(dossier.status || 'Active')}
              </span>
              {autonomy?.always_hitl && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: `${colors.info}22`, color: colors.info }}>
                  <Shield className="w-3 h-3" /> Human always approves
                </span>
              )}
            </div>
            {(dossier.role || dossier.persona) && (
              <p className="text-[13px] leading-relaxed" style={{ color: colors.inkSubtle }}>
                {dossier.role || dossier.persona}
              </p>
            )}

            {/* The autonomy ladder */}
            {autonomy?.ladder && section('The ladder', <Layers className="w-3.5 h-3.5" />, (
              <div className="space-y-0">
                {autonomy.ladder.map((rung: any, i: number) => (
                  <div key={rung.level} className="flex gap-3">
                    {/* Rail */}
                    <div className="flex flex-col items-center">
                      <div className="w-3 h-3 rounded-full shrink-0 mt-1"
                        style={{
                          background: rung.current ? colors.primary : 'transparent',
                          border: `2px solid ${rung.current ? colors.primary : colors.hairline}`,
                          boxShadow: rung.current ? `0 0 8px ${colors.primary}88` : 'none',
                        }} />
                      {i < autonomy.ladder.length - 1 && (
                        <div className="w-px flex-1 my-0.5" style={{ background: colors.hairline }} />
                      )}
                    </div>
                    <div className="pb-3 min-w-0">
                      <div className="text-[12px] font-bold" style={{ color: rung.current ? colors.primary : colors.ink }}>
                        {rung.label}
                        {rung.current && <span className="ml-1.5 text-[10px] font-semibold px-1.5 py-px rounded-full"
                          style={{ background: `${colors.primary}22` }}>current</span>}
                      </div>
                      <div className="text-[12px] leading-snug" style={{ color: colors.inkSubtle }}>
                        {rung.description}
                      </div>
                    </div>
                  </div>
                ))}
                <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
                  Confidence {Math.round((autonomy.avg_confidence ?? dossier.confidence ?? 0) * 100)}% vs the
                  {' '}{Math.round((autonomy.required_confidence || 0) * 100)}% autonomy bar.
                </div>
              </div>
            ))}

            {/* What it replaces */}
            {dossier.replaces && section('What it replaces', <Replace className="w-3.5 h-3.5" />, (
              <div className="text-[13px] p-3 rounded-lg leading-relaxed"
                style={{ background: colors.surface2 || colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                {dossier.replaces}
              </div>
            ))}

            {/* The human's role */}
            {dossier.human_role && section('The human', <User className="w-3.5 h-3.5" />, (
              <p className="text-[13px] leading-relaxed" style={{ color: colors.inkSubtle }}>{dossier.human_role}</p>
            ))}

            {/* SOP */}
            {dossier.sop?.length > 0 && section('The procedure, written out', <ListOrdered className="w-3.5 h-3.5" />, (
              <ol className="space-y-1.5">
                {dossier.sop.map((s: any) => (
                  <li key={s.order} className="flex gap-2 text-[13px]" style={{ color: colors.ink }}>
                    <span className="shrink-0 w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center"
                      style={{ background: `${colors.primary}18`, color: colors.primary }}>
                      {s.order}
                    </span>
                    <span className="leading-snug">
                      {s.action}
                      {s.tool && <span className="ml-1.5 text-[11px] px-1.5 py-px rounded"
                        style={{ background: colors.surface2 || colors.canvas, color: colors.inkSubtle }}>{humanize(s.tool)}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            ))}

            {/* Breaks into (agent) / Done by (task) */}
            {dossier.breaks_into?.length > 0 && section('Breaks into', <Zap className="w-3.5 h-3.5" />, (
              <div className="flex flex-wrap gap-1.5">
                {dossier.breaks_into.map((s: any) => (
                  <span key={s.skill_id} className="px-2 py-1 rounded-md text-[11px] font-semibold"
                    style={{ background: colors.surface2 || colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                    {s.label}
                  </span>
                ))}
              </div>
            ))}
            {dossier.done_by && section('Done by', <Bot className="w-3.5 h-3.5" />, (
              <div className="text-[13px]" style={{ color: colors.ink }}>
                {dossier.done_by.name}
                <span className="ml-1.5" style={{ color: colors.inkSubtle }}>{dossier.done_by.role}</span>
              </div>
            ))}

            {/* Builds on */}
            {dossier.builds_on?.length > 0 && section('Builds on', <Wrench className="w-3.5 h-3.5" />, (
              <div className="flex flex-wrap gap-1.5">
                {dossier.builds_on.map((t: string) => (
                  <span key={t} className="px-2 py-1 rounded-md text-[11px] font-mono"
                    style={{ background: colors.surface2 || colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                    {t}
                  </span>
                ))}
              </div>
            ))}

            {/* Live record */}
            {stats && section('Live record', <Activity className="w-3.5 h-3.5" />, (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Runs', value: stats.executions, color: colors.primary },
                  { label: 'Succeeded', value: stats.succeeded, color: colors.success },
                  { label: 'Human reviews', value: stats.hitl_reviews, color: colors.info },
                ].map(x => (
                  <div key={x.label} className="p-2.5 rounded-lg text-center"
                    style={{ background: colors.surface2 || colors.canvas, border: `1px solid ${colors.hairline}` }}>
                    <div className="text-[17px] font-bold" style={{ color: x.color }}>
                      <CountUp value={x.value || 0} />
                    </div>
                    <div className="text-[10px] font-semibold" style={{ color: colors.inkSubtle }}>{x.label}</div>
                  </div>
                ))}
              </div>
            ))}

            {/* Schedule */}
            {dossier.schedule && (
              <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkSubtle }}>
                <Clock className="w-3.5 h-3.5 shrink-0" /> {dossier.schedule}
              </div>
            )}
            {stats?.last_run && (
              <div className="flex items-center gap-2 text-[12px]" style={{ color: colors.inkTertiary }}>
                <CheckCircle className="w-3.5 h-3.5 shrink-0" /> Last ran {new Date(stats.last_run).toLocaleString()}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
