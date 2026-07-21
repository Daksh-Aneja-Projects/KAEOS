import React, { useEffect, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTheme } from '../context/ThemeContext';

/**
 * A compact "this data is live" indicator: a heartbeat dot reflecting the
 * tenant WebSocket connection, plus a "synced Ns ago" ticker that counts up
 * from the last successful load. No glow — just an honest pulse + a clock so
 * the dashboard visibly feels connected to the backend.
 *
 * Parents pass `lastSync` (Date.now() at their last successful fetch); the
 * badge owns the per-second re-render so callers don't need a timer.
 */
const LiveBadge: React.FC<{ lastSync: number | null; label?: string }> = ({ lastSync, label = 'Live' }) => {
  const { colors } = useTheme();
  const { status } = useWebSocket();
  const [, tick] = useState(0);

  // Re-render every second so "synced Ns ago" advances.
  useEffect(() => {
    const t = setInterval(() => tick(n => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const connected = status === 'connected';
  const dot = connected ? '#22c55e' : status === 'connecting' ? '#f59e0b' : '#94a3b8';

  const ago = (() => {
    if (!lastSync) return null;
    const s = Math.max(0, Math.floor((Date.now() - lastSync) / 1000));
    if (s < 2) return 'just now';
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
  })();

  return (
    <div className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}
      title={connected ? 'Connected to the live event stream' : 'Reconnecting to the live event stream'}>
      <span className="relative flex h-2 w-2">
        {connected && (
          <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
            style={{ background: dot }} />
        )}
        <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: dot }} />
      </span>
      <span className="font-medium" style={{ color: connected ? colors.ink : colors.inkSubtle }}>
        {connected ? label : status === 'connecting' ? 'Connecting…' : 'Offline'}
      </span>
      {ago && <span style={{ color: colors.inkTertiary }}>· synced {ago}</span>}
    </div>
  );
};

export default LiveBadge;
