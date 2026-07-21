import React, { useCallback, useEffect, useState } from 'react';
import { Briefcase, Download, Loader2, RefreshCw, Trash2, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { MyWorkItem, SavedSegment } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import LiveBadge from '../components/LiveBadge';
import { timeAgo } from '../lib/time';

/**
 * Workspace home (Sprints 6 & 10): everything assigned to the caller across
 * every domain, the team workload, saved views, and one-click CSV export of
 * any workflow entity type.
 */

const DOMAIN_ROUTE: Record<string, string> = {
  finance: '/departments/finance', hr: '/departments/hr', sales: '/departments/sales',
  support: '/departments/support', operations: '/departments/operations',
  legal: '/departments/legal', engineering: '/departments/engineering',
};

const EXPORTABLE = [
  { entity: 'ticket', label: 'Support Tickets' },
  { entity: 'opportunity', label: 'Sales Opportunities' },
  { entity: 'invoice', label: 'AP Invoices' },
  { entity: 'expense_report', label: 'Expense Reports' },
  { entity: 'contract', label: 'Contracts' },
  { entity: 'incident', label: 'Incidents' },
  { entity: 'purchase_request', label: 'Purchase Requests' },
  { entity: 'time_off_request', label: 'Time-Off Requests' },
];

const MyWork: React.FC<{ domain?: string }> = () => {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [items, setItems] = useState<MyWorkItem[]>([]);
  const [me, setMe] = useState('');
  const [workload, setWorkload] = useState<{ assignee: string; count: number }[]>([]);
  const [segments, setSegments] = useState<SavedSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastSync, setLastSync] = useState<number | null>(null);

  const load = useCallback(async () => {
    const [w, wl, seg] = await Promise.allSettled([
      api.getMyWork(), api.getWorkload(), api.getSegments(),
    ]);
    if (w.status === 'fulfilled') { setItems(w.value.items || []); setMe(w.value.assignee); }
    if (wl.status === 'fulfilled') setWorkload(wl.value.workload || []);
    if (seg.status === 'fulfilled') setSegments(seg.value || []);
    setLastSync(Date.now());
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load);

  const maxLoad = Math.max(...workload.map(w => w.count), 1);

  const removeSegment = async (id: string) => {
    try { await api.deleteSegment(id); setSegments(prev => prev.filter(s => s.id !== id)); } catch { /* noop */ }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-24"><Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} /></div>;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6" style={{ color: colors.ink }}>
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight flex items-center gap-2">
            <Briefcase className="w-6 h-6" style={{ color: colors.primary }} /> My Work
          </h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
            Everything assigned to <span className="font-mono">{me}</span> across every department
          </p>
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge lastSync={lastSync} />
          <button onClick={load} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }}>
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Assigned items */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <h2 className="text-[13px] font-bold mb-3">Assigned to me ({items.length})</h2>
        {items.length === 0 ? (
          <p className="text-[12px] py-6 text-center" style={{ color: colors.inkTertiary }}>
            Nothing assigned to you yet — assign work from any department's row actions.
          </p>
        ) : (
          <div className="space-y-1.5">
            {items.map(it => (
              <div key={`${it.entity_type}-${it.entity_id}`}
                onClick={() => navigate(DOMAIN_ROUTE[it.domain] || '/pulse')}
                className="flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors hover:brightness-110 text-[12px]"
                style={{ background: colors.canvas }}>
                <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded"
                  style={{ background: `${colors.primary}15`, color: colors.primary }}>{it.domain}</span>
                <span className="font-medium truncate max-w-[280px]">{it.title || it.entity_id}</span>
                <span style={{ color: colors.inkTertiary }}>{it.entity_type.replace(/_/g, ' ')}</span>
                {it.state && (
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded"
                    style={{ background: colors.surface2, color: colors.inkSubtle }}>{it.state}</span>
                )}
                <span className="ml-auto whitespace-nowrap" style={{ color: colors.inkTertiary }}>{timeAgo(it.at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Team workload */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h2 className="text-[13px] font-bold mb-3 flex items-center gap-1.5">
            <Users className="w-4 h-4" style={{ color: colors.primary }} /> Team Workload
          </h2>
          {workload.length === 0 ? (
            <p className="text-[12px] py-4 text-center" style={{ color: colors.inkTertiary }}>No assignments yet.</p>
          ) : (
            <div className="space-y-2">
              {workload.map(w => (
                <div key={w.assignee} className="flex items-center gap-2">
                  <span className="text-[11px] w-40 truncate" style={{ color: colors.inkSubtle }}>{w.assignee}</span>
                  <div className="flex-1 h-4 rounded" style={{ background: colors.canvas }}>
                    <div className="h-4 rounded" style={{ width: `${(w.count / maxLoad) * 100}%`, background: colors.primary }} />
                  </div>
                  <span className="text-[11px] font-mono w-6 text-right">{w.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* CSV export */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h2 className="text-[13px] font-bold mb-3 flex items-center gap-1.5">
            <Download className="w-4 h-4" style={{ color: colors.primary }} /> Export Data (CSV)
          </h2>
          <div className="grid grid-cols-2 gap-2">
            {EXPORTABLE.map(e => (
              <a key={e.entity} href={api.exportCsvUrl(e.entity)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[11px] font-medium transition-colors hover:brightness-110"
                style={{ background: colors.canvas, color: colors.inkSubtle }}>
                <Download className="w-3 h-3" /> {e.label}
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* Saved views */}
      {segments.length > 0 && (
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h2 className="text-[13px] font-bold mb-3">Saved Views</h2>
          <div className="flex flex-wrap gap-2">
            {segments.map(s => (
              <div key={s.id} className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px]"
                style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                <span className="text-[9px] font-bold uppercase" style={{ color: colors.primary }}>{s.domain}</span>
                <span style={{ color: colors.ink }}>{s.name}</span>
                <button onClick={() => removeSegment(s.id)} style={{ color: colors.inkTertiary }}>
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default MyWork;
