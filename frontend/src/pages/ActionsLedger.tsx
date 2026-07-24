import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { Zap, Undo2, ShieldCheck, AlertTriangle, RefreshCw } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

/**
 * The Actions Ledger — what KAEOS actually DID to a system of record (governed,
 * idempotent, reversible), distinct from the Provenance decision ledger. Sits as
 * a tab beside Provenance in the Decisions view. Reads real ActionRecords.
 */
const ActionsLedger = () => {
  const { colors } = useTheme();
  const [data, setData] = useState<any>(null);
  const [drift, setDrift] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reversing, setReversing] = useState<string | null>(null);

  const load = () => {
    setError(null);
    Promise.all([api.getActionsLedger(50), api.getActuationDrift()])
      .then(([l, d]) => { setData(l); setDrift(d); setLoading(false); })
      .catch((e: any) => { setError(e?.message || 'Failed to load the actions ledger'); setLoading(false); });
  };

  useEffect(() => { load(); }, []);

  const reverse = async (id: string) => {
    setReversing(id);
    try {
      await api.reverseAction(id);
      load();
    } catch (e) {
      console.error('Reverse failed', e);
    } finally {
      setReversing(null);
    }
  };

  const opStyle = (op: string): React.CSSProperties => {
    if (op === 'CREATE') return { background: colors.success + '1f', color: colors.success, border: `1px solid ${colors.success}40` };
    if (op === 'UPDATE') return { background: colors.info + '1f', color: colors.info, border: `1px solid ${colors.info}40` };
    if (op === 'DELETE') return { background: colors.error + '1f', color: colors.error, border: `1px solid ${colors.error}40` };
    return { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` };
  };

  const statusStyle = (s: string): React.CSSProperties => {
    if (s === 'APPLIED') return { color: colors.success };
    if (s === 'REVERSED') return { color: colors.warning };
    if (s === 'FAILED') return { color: colors.error };
    return { color: colors.inkSubtle };
  };

  if (loading) return <BrainLoading message="Loading the Actions Ledger…" />;
  if (error) return <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />;

  const summary = data?.summary || { total: 0, applied: 0, reversed: 0, failed: 0 };
  const actions = data?.actions || [];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
            <Zap className="w-6 h-6 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="text-[24px] font-bold tracking-tight">Actions Ledger</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              What KAEOS did to your systems of record, governed and reversible. Distinct from the decision ledger.
            </p>
          </div>
          <button onClick={() => { setLoading(true); load(); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium self-center"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>

        {/* Summary + drift */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Actions taken', value: summary.total, color: colors.ink },
            { label: 'Applied', value: summary.applied, color: colors.success },
            { label: 'Reversed', value: summary.reversed, color: colors.warning },
            { label: 'Failed', value: summary.failed, color: colors.error },
          ].map(s => (
            <div key={s.label} className="p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="text-[22px] font-bold" style={{ color: s.color }}>{s.value}</div>
              <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Reconciliation banner */}
        {drift && (
          <div className="flex items-center gap-3 p-4 rounded-xl"
            style={{ background: colors.surface1, border: `1px solid ${drift.drift_count > 0 ? colors.warning + '55' : colors.hairline}` }}>
            {drift.drift_count > 0
              ? <AlertTriangle className="w-5 h-5 shrink-0" style={{ color: colors.warning }} />
              : <ShieldCheck className="w-5 h-5 shrink-0" style={{ color: colors.success }} />}
            <div className="text-[13px]">
              <span className="font-semibold">{drift.in_sync}/{drift.objects_tracked}</span> records in sync with the system of record.
              {drift.drift_count > 0
                ? <span style={{ color: colors.warning }}> {drift.drift_count} drifted (changed outside the governed path) and need reconciliation.</span>
                : <span style={{ color: colors.inkSubtle }}> No drift detected.</span>}
            </div>
          </div>
        )}

        {actions.length === 0 ? (
          <BrainEmpty title="No governed actions yet" action="When an agent acts on a system of record through the gates, the reversible action is recorded here." icon={Zap} />
        ) : (
          <div className="overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: '14px' }}>
            <div className="overflow-x-auto">
              <div className="min-w-[900px]">
                <div className="grid grid-cols-[100px_1fr_1fr_110px_120px_140px] gap-4 px-6 py-3 text-[11px] uppercase tracking-wider font-semibold"
                  style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
                  <span>Operation</span><span>Target</span><span>Actor</span><span>Status</span><span>When</span><span>Reverse</span>
                </div>
                {actions.map((a: any) => (
                  <div key={a.id} className="grid grid-cols-[100px_1fr_1fr_110px_120px_140px] gap-4 px-6 py-4 transition-colors items-center"
                    style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <span className="px-2 py-0.5 rounded text-[11px] font-medium inline-block w-fit" style={opStyle(a.operation)}>{a.operation}</span>
                    <span className="text-[13px] truncate" style={{ color: colors.inkMuted }}>
                      <span className="font-mono">{a.system}</span> · {a.object_type}:{a.external_id}
                    </span>
                    <span className="text-[12px] truncate" style={{ color: colors.inkSubtle }}>{a.actor || 'system'}</span>
                    <span className="text-[12px] font-semibold" style={statusStyle(a.status)}>{a.status}</span>
                    <span className="text-[12px]" style={{ color: colors.inkSubtle }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : '-'}
                    </span>
                    <span>
                      {a.reversible ? (
                        <button onClick={() => reverse(a.id)} disabled={reversing === a.id}
                          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold"
                          style={{ background: colors.warning + '18', color: colors.warning, opacity: reversing === a.id ? 0.5 : 1 }}>
                          <Undo2 className="w-3.5 h-3.5" /> {reversing === a.id ? 'Reversing…' : 'Reverse'}
                        </button>
                      ) : (
                        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
                          {a.status === 'REVERSED' ? 'Reversed' : '—'}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ActionsLedger;
