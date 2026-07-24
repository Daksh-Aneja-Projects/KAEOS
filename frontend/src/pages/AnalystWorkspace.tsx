import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { FileText, Loader2, Download } from 'lucide-react';

// The Knowledge Graph lives in ONE place (Topology Map, under Knowledge) — it is
// not duplicated here. Analyst Workspace focuses on the audit-log browser.
type Tab = 'audit';

export default function AnalystWorkspace({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [tab] = useState<Tab>('audit');
  const [ledger, setLedger] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getGlobalLedger().catch(() => ({ ledger: [] })).then((l: any) => {
      setLedger(l?.ledger || []);
      setLoading(false);
    });
  }, []);

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: 'audit', label: 'Audit Log Browser', icon: FileText },
  ];

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px',
  };

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Tab Bar */}
      <div className="flex items-center gap-1 px-6 py-2 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        {tabs.map(t => (
          <div key={t.id}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-medium"
            style={{
              background: tab === t.id ? colors.primary + '18' : 'transparent',
              color: tab === t.id ? colors.primary : colors.inkSubtle,
            }}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
          </div>
        )}


        {/* Audit Log Browser */}
        {!loading && tab === 'audit' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">Provenance Audit Log</h2>
                <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                  Immutable ledger: {ledger.length} entries with SHA-256 chain hashing
                </p>
              </div>
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-medium"
                style={{ background: colors.primary + '15', color: colors.primary }}>
                <Download className="w-3.5 h-3.5" /> Export PDF
              </button>
            </div>

            <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
              <div className="grid grid-cols-12 gap-0 text-[10px] font-semibold uppercase tracking-wider px-4 py-2.5"
                style={{ background: colors.surface1, color: colors.inkSubtle }}>
                <div className="col-span-2">Timestamp</div>
                <div className="col-span-2">Event Type</div>
                <div className="col-span-1">Actor</div>
                <div className="col-span-1">Confidence</div>
                <div className="col-span-4">Reasoning</div>
                <div className="col-span-2">Chain Hash</div>
              </div>
              {ledger.slice(0, 20).map((e, i) => {
                const typeColor = e.event_type === 'CREATION' ? '#22c55e' : e.event_type === 'VALIDATION' ? '#3b82f6' :
                  e.event_type === 'DECAY' ? '#f59e0b' : colors.primary;
                return (
                  <div key={i} className="grid grid-cols-12 gap-0 items-center px-4 py-2 text-[11px]"
                    style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <div className="col-span-2 font-mono text-[10px]" style={{ color: colors.inkSubtle }}>
                      {e.timestamp ? new Date(e.timestamp).toLocaleString() : '-'}
                    </div>
                    <div className="col-span-2">
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: typeColor + '20', color: typeColor }}>
                        {e.event_type}
                      </span>
                    </div>
                    <div className="col-span-1 text-[10px]" style={{ color: colors.inkSubtle }}>{e.actor_role || '-'}</div>
                    <div className="col-span-1 font-mono">{e.confidence_at?.toFixed(2) || '-'}</div>
                    <div className="col-span-4 truncate" style={{ color: colors.inkSubtle }}>{e.reasoning || '-'}</div>
                    <div className="col-span-2 font-mono text-[9px] truncate" style={{ color: colors.inkSubtle }}>
                      {e.chain_hash?.substring(0, 16) || '-'}…
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
