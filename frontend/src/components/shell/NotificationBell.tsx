import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { Bell, Activity, Shield } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { api, type PendingHITLItem, type AppNotification } from '../../api/client';
import { humanize } from '../../lib/format';
import { useVisiblePoll } from '../../hooks/useLiveRefresh';
import { focusMenuItem } from './menuNav';

/**
 * The header's notification bell: pending HITL approvals plus org
 * notifications, with the badge, dropdown panel, and 30s visibility-aware poll.
 *
 * Extracted from Shell (M7.3) so the poll's setState re-renders only this
 * component instead of the entire route tree. Takes no props at all, so
 * nothing Shell does can cascade a render into it except context changes.
 */
export default function NotificationBell() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<PendingHITLItem[]>([]);
  const [orgNotifs, setOrgNotifs] = useState<AppNotification[]>([]);
  const notifButtonRef = useRef<HTMLButtonElement>(null);

  // Notifications: real pending human-in-the-loop approvals (the actionable
  // queue), polled every 30s. The bell badge lights only when there are items.
  // The poll pauses while the tab is hidden and re-fires on return: the badge
  // and its panel are in-app DOM only (no title, favicon or OS notification),
  // so a hidden tab has nothing to show, and the user always sees a fresh count.
  const notifsAlive = useRef(true);
  // Set on mount as well as cleared on unmount: StrictMode (and Fast Refresh)
  // run setup/cleanup/setup on the same instance, so a cleanup-only effect
  // would latch the ref false forever and every setter below would be skipped.
  useEffect(() => { notifsAlive.current = true; return () => { notifsAlive.current = false; }; }, []);
  const loadNotifs = () => {
    api.getPendingHITL()
      .then(d => { if (notifsAlive.current) setNotifs(Array.isArray(d) ? d : []); })
      .catch(() => { if (notifsAlive.current) setNotifs([]); });
    // Org notifications (SLA escalations, @mentions, automation alerts).
    api.getNotifications(true, 10)
      .then(d => { if (notifsAlive.current) setOrgNotifs(d.items || []); })
      .catch(() => { if (notifsAlive.current) setOrgNotifs([]); });
  };
  useEffect(() => { loadNotifs(); }, []);
  useVisiblePoll(loadNotifs, 30000);

  // Escape closes the panel from anywhere (was part of Shell's global
  // keydown handler before the M7.3 extraction).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setNotifOpen(false); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const handleNotifKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusMenuItem(e.currentTarget, 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusMenuItem(e.currentTarget, -1); }
    else if (e.key === 'Escape') { setNotifOpen(false); notifButtonRef.current?.focus(); }
  };

  return (
    <div className="relative" onKeyDown={handleNotifKeyDown}>
      <button ref={notifButtonRef} aria-label="Notifications" aria-expanded={notifOpen} aria-haspopup="true"
        onClick={() => setNotifOpen(o => !o)}
        className="p-1.5 rounded hover:bg-surface2 transition-colors relative"
        style={{ color: notifOpen ? colors.primary : colors.inkSubtle }}>
        <Bell className="w-4 h-4" />
        {(notifs.length + orgNotifs.length) > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 rounded-full text-[11px] font-bold text-white flex items-center justify-center"
            style={{ background: colors.error }}>{(notifs.length + orgNotifs.length) > 9 ? '9+' : (notifs.length + orgNotifs.length)}</span>
        )}
      </button>
      {notifOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setNotifOpen(false)} />
          <div role="menu" aria-label="Notifications" className="absolute top-full right-0 mt-1 w-80 rounded-lg border shadow-xl z-50 overflow-hidden"
            style={{ background: colors.surface1, borderColor: colors.hairline }}>
            <div className="px-3 py-2.5 border-b flex items-center justify-between" style={{ borderColor: colors.hairline }}>
              <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>Notifications</span>
              <span className="text-[11px] px-1.5 py-0.5 rounded-full"
                style={{ background: notifs.length ? colors.error + '20' : colors.surface3, color: notifs.length ? colors.error : colors.inkSubtle }}>
                {notifs.length} pending
              </span>
            </div>
            <div className="max-h-[360px] overflow-y-auto">
              {/* Org notifications: SLA escalations, @mentions, automation alerts */}
              {orgNotifs.map(n => (
                <button key={n.id} type="button" role="menuitem" data-menuitem
                  onClick={() => { navigate('/pulse'); setNotifOpen(false); }}
                  className="w-full text-left px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b block focus:outline-none focus-visible:bg-surface2"
                  style={{ borderColor: colors.hairline }}>
                  <div className="flex items-start gap-2">
                    <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5"
                      style={{ background: (n.severity === 'critical' ? colors.error : colors.warning) + '20' }}>
                      <Activity className="w-3.5 h-3.5" style={{ color: n.severity === 'critical' ? colors.error : colors.warning }} />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.title}</div>
                      {n.description && <div className="text-[11px] mt-0.5 truncate" style={{ color: colors.inkSubtle }}>{n.description}</div>}
                    </div>
                  </div>
                </button>
              ))}
              {notifs.length === 0 && orgNotifs.length === 0 ? (
                <div className="px-3 py-8 text-center">
                  <Bell className="w-6 h-6 mx-auto mb-2" style={{ color: colors.inkTertiary }} />
                  <div className="text-[12px]" style={{ color: colors.inkSubtle }}>You're all caught up</div>
                  <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>No decisions or alerts awaiting you</div>
                </div>
              ) : notifs.map(n => (
                <button key={n.id} type="button" role="menuitem" data-menuitem
                  onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                  className="w-full text-left px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b block focus:outline-none focus-visible:bg-surface2"
                  style={{ borderColor: colors.hairline }}>
                  <div className="flex items-start gap-2">
                    <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5" style={{ background: colors.warning + '20' }}>
                      <Shield className="w-3.5 h-3.5" style={{ color: colors.warning }} />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.task_intent || n.skill_id_name}</div>
                      <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
                        Approval required{n.route_type ? ` · ${n.route_type === 'GATED_AGENT' ? 'Pipeline gate' : humanize(n.route_type)}` : ''}
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
            {notifs.length > 0 && (
              <button type="button" role="menuitem" data-menuitem
                onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                className="w-full px-3 py-2 text-center text-[12px] cursor-pointer hover:bg-surface2 transition-colors font-medium focus:outline-none focus-visible:bg-surface2"
                style={{ color: colors.primary }}>
                Review all in Decisions
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
