/**
 * PioneerLab — extracted parts.
 *
 * Lane catalog + form constants, two small formatting helpers, the shared UI
 * atoms (each reads the theme from context so call sites stay prop-free), and
 * the self-contained Engine-Ledgers lane. Kept out of the page component so
 * PioneerLab.tsx stays under the size budget; behavior is unchanged.
 */
import React from 'react';
import { useTheme } from '../context/ThemeContext';
import { humanize, toPct } from '../lib/format';
import { BrainLoading } from '../components/BrainStates';
import {
  Satellite, Users, Zap, TrendingUp, Database, Loader2,
  Scale, Share2, Code2, GitBranch,
} from 'lucide-react';

export const SIGNAL_TYPES = ['REGULATORY', 'VENDOR', 'MARKET', 'THREAT', 'ECONOMIC'];
export const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH'];
export const SHOCKS = [
  'MACRO_RATE_HIKE_50BPS', 'SUPPLY_CHAIN_DISRUPTION', 'TALENT_EXODUS',
  'BUDGET_CUT', 'MERGER_INTEGRATION', 'CYBER_INCIDENT',
];

export type Lane = 'intelligence' | 'organization' | 'simulation' | 'benchmark' | 'ledgers';

export const LANES: { key: Lane; label: string; icon: React.ElementType }[] = [
  { key: 'intelligence', label: 'External Intelligence', icon: Satellite },
  { key: 'organization', label: 'Org Intelligence', icon: Users },
  { key: 'simulation', label: 'Simulation', icon: Zap },
  { key: 'benchmark', label: 'Benchmark', icon: TrendingUp },
  { key: 'ledgers', label: 'Engine Ledgers', icon: Database },
];

export const riskColor = (level: string | undefined, colors: any) =>
  level === 'HIGH' ? colors.error : level === 'MEDIUM' ? colors.warning : colors.success;

// Ledger reasoning arrives with machine tails ("... | PAYLOAD: {...}") and
// SCREAMING_SNAKE status tokens; strip the payload and humanize the tokens.
export const cleanReason = (s: string | null | undefined) =>
  (s || '').split(' | PAYLOAD:')[0].replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, m => humanize(m));

const cardStyle = (colors: any): React.CSSProperties => ({
  background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 12,
});

// ─── Shared UI atoms (theme read from context; call sites stay prop-free) ───
export const SectionTitle = ({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) => {
  const { colors } = useTheme();
  return (
    <h3 className="text-[13px] font-semibold flex items-center gap-2 mb-3" style={{ color: colors.ink }}>
      <Icon className="w-4 h-4" style={{ color: colors.primary }} />
      {children}
    </h3>
  );
};

export const ErrorBanner = ({ message }: { message: string | null }) => {
  const { colors } = useTheme();
  return message ? (
    <div className="px-4 py-3 rounded-lg text-[12px]" style={{ background: `${colors.error}15`, color: colors.error }}>
      {message}
    </div>
  ) : null;
};

export const ActionButton = ({ busy, onClick, disabled, children }: {
  busy: boolean; onClick: () => void; disabled?: boolean; children: React.ReactNode;
}) => {
  const { colors } = useTheme();
  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      className="px-4 py-2 text-[12px] font-semibold rounded-lg whitespace-nowrap flex items-center gap-2"
      style={{ background: colors.primary, color: '#fff', opacity: disabled ? 0.4 : busy ? 0.6 : 1 }}
    >
      {busy && <Loader2 className="w-4 h-4 animate-spin" />}
      {children}
    </button>
  );
};

export const Badge = ({ tone, children }: { tone: string; children: React.ReactNode }) => (
  <span className="px-2 py-0.5 text-[11px] font-semibold rounded whitespace-nowrap"
    style={{ background: `${tone}20`, color: tone }}>
    {children}
  </span>
);

// ─── Engine Ledgers lane (consumes the loaded ledger payload) ───
export function LedgersLane({ ledgers, ledgerState }: { ledgers: any; ledgerState: 'loading' | 'ready' }) {
  const { colors } = useTheme();
  const card = cardStyle(colors);
  return (
    <>
      {ledgerState === 'loading' && <BrainLoading message="Opening the engine ledgers…" />}
      {ledgerState === 'ready' && ledgers && (
       <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {[
         {
          title: 'Tamper-evident ledger', icon: Database,
          empty: 'No hash-chained events yet. Governance events land here as the engines run.',
          items: ledgers.quantum, render: (e: any) => ({
           head: humanize(e.event_type), body: cleanReason(e.reasoning),
           meta: e.timestamp ? new Date(e.timestamp).toLocaleString() : '',
          }),
         },
         {
          title: 'Auto-synthesized compliance rules', icon: Scale,
          empty: 'No regulation has been ingested yet. Feed one from a signal or the regulatory engine.',
          items: ledgers.regulatory, render: (r: any) => ({
           head: humanize(r.domain || 'Compliance'), body: r.statement,
           meta: r.created_at ? new Date(r.created_at).toLocaleString() : '',
          }),
         },
         {
          title: 'Skills shared with the federation', icon: Share2,
          empty: 'No skills have been exported to the network yet.',
          items: ledgers.federated, render: (s: any) => ({
           head: humanize(s.skill_id), body: `Domain ${humanize(s.domain || '')}, success rate ${toPct(s.success_rate) !== null ? Math.round(toPct(s.success_rate)!) + '%' : 'unknown'}`,
           meta: s.timestamp ? new Date(s.timestamp).toLocaleString() : '',
          }),
         },
         {
          title: 'Generated tooling events', icon: Code2,
          empty: 'The polymorphic engine has not generated tooling yet.',
          items: ledgers.polymorphic, render: (p: any) => ({
           head: humanize(p.tool || p.event_type), body: `${humanize(p.event_type || '')} for ${humanize(p.skill_id)}`,
           meta: p.timestamp ? new Date(p.timestamp).toLocaleString() : '',
          }),
         },
        ].map(l => (
         <div key={l.title} className="p-5" style={card}>
          <div className="flex items-center justify-between mb-3">
           <SectionTitle icon={l.icon}>{l.title}</SectionTitle>
           <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{(l.items || []).length} on record</span>
          </div>
          {(l.items || []).length === 0 ? (
           <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{l.empty}</p>
          ) : (
           <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
            {l.items.slice(0, 50).map((item: any, i: number) => {
             const r = l.render(item);
             return (
              <div key={i} className="px-3 py-2 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
               <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-semibold truncate" style={{ color: colors.ink }}>{r.head}</span>
                {r.meta && <span className="text-[11px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>{r.meta}</span>}
               </div>
               {r.body && <div className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{r.body}</div>}
              </div>
             );
            })}
           </div>
          )}
         </div>
        ))}

        {/* Pipeline catalogs */}
        <div className="p-5 lg:col-span-2" style={card}>
         <SectionTitle icon={GitBranch}>Data pipeline building blocks</SectionTitle>
         <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
           <div className="text-[11px] uppercase tracking-wide mb-2" style={{ color: colors.inkSubtle }}>
            Connectors available ({(ledgers.connectors || []).length})
           </div>
           <div className="flex gap-1.5 flex-wrap">
            {(ledgers.connectors || []).map((c: any) => (
             <span key={c.slug} className="px-2 py-1 text-[11px] rounded-lg" title={`${humanize(c.category)}, ${humanize(c.auth_type)} auth`}
              style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
              {c.name}
             </span>
            ))}
           </div>
          </div>
          <div>
           <div className="text-[11px] uppercase tracking-wide mb-2" style={{ color: colors.inkSubtle }}>
            Transforms available ({(ledgers.transforms || []).length})
           </div>
           <div className="flex gap-1.5 flex-wrap">
            {(ledgers.transforms || []).map((t: any) => (
             <span key={t.type} className="px-2 py-1 text-[11px] rounded-lg" title={t.description}
              style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
              {t.name || humanize(t.type)}
             </span>
            ))}
           </div>
          </div>
         </div>
        </div>
       </div>
      )}
    </>
  );
}
