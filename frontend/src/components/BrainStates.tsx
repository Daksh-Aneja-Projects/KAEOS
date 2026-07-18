/**
 * KAEOS - Brain State Components
 * 
 * These aren't generic loading/error/empty states.
 * They reflect the Enterprise Brain's cognitive states:
 * 
 * - BrainLoading  → The Brain is reasoning
 * - BrainEmpty    → The Brain hasn't learned this domain yet
 * - BrainError    → A cognitive pathway is interrupted
 * - LiveIndicator → Shows a stream is connected to the Brain
 */

import React from 'react';
import { Brain, Loader2, AlertTriangle, Inbox, RefreshCw, Wifi, WifiOff } from 'lucide-react';

interface BrainLoadingProps {
  message?: string;
  /** Compact = inline spinner, full = centered with Brain icon */
  variant?: 'compact' | 'full';
}

export const BrainLoading: React.FC<BrainLoadingProps> = ({
  message = 'Querying Enterprise Brain…',
  variant = 'full'
}) => {
  if (variant === 'compact') {
    return (
      <div className="flex items-center gap-2 py-4 text-sm" style={{ color: 'var(--ink-subtle, #8A8F98)' }}>
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>{message}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-20 gap-4">
      <div className="relative">
        <Brain className="w-12 h-12" style={{ color: 'var(--primary, #5E6AD2)', opacity: 0.3 }} />
        <Loader2 className="w-6 h-6 animate-spin absolute -bottom-1 -right-1" style={{ color: 'var(--primary, #5E6AD2)' }} />
      </div>
      <p className="text-sm font-medium" style={{ color: 'var(--ink-subtle, #8A8F98)' }}>{message}</p>
    </div>
  );
};


interface BrainEmptyProps {
  /** What the Brain hasn't learned yet */
  title: string;
  /** What the user should do to teach the Brain */
  action?: string;
  /** Custom icon (default: Inbox) */
  icon?: React.ElementType;
}

export const BrainEmpty: React.FC<BrainEmptyProps> = ({
  title,
  action,
  icon: Icon = Inbox,
}) => (
  <div className="flex flex-col items-center justify-center py-16 gap-3">
    <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
      style={{ background: 'var(--surface-2, #F0F0F3)' }}>
      <Icon className="w-7 h-7" style={{ color: 'var(--ink-tertiary, #B0B3B8)' }} />
    </div>
    <p className="text-[14px] font-medium" style={{ color: 'var(--ink-subtle, #8A8F98)' }}>
      {title}
    </p>
    {action && (
      <p className="text-[12px]" style={{ color: 'var(--ink-tertiary, #B0B3B8)' }}>
        {action}
      </p>
    )}
  </div>
);


interface BrainErrorProps {
  message: string;
  onRetry?: () => void;
}

export const BrainError: React.FC<BrainErrorProps> = ({ message, onRetry }) => (
  <div className="flex flex-col items-center justify-center py-16 gap-3">
    <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
      style={{ background: 'rgba(229, 83, 75, 0.08)' }}>
      <AlertTriangle className="w-7 h-7" style={{ color: '#E5534B' }} />
    </div>
    <p className="text-[14px] font-medium" style={{ color: '#E5534B' }}>
      Neural pathway interrupted
    </p>
    <p className="text-[12px] max-w-md text-center" style={{ color: 'var(--ink-subtle, #8A8F98)' }}>
      {message}
    </p>
    {onRetry && (
      <button onClick={onRetry}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all hover:opacity-80"
        style={{ background: 'rgba(229, 83, 75, 0.08)', color: '#E5534B' }}>
        <RefreshCw className="w-3 h-3" /> Retry
      </button>
    )}
  </div>
);


interface LiveIndicatorProps {
  isLive: boolean;
  staleness?: number;
  /** Show staleness in seconds when > this threshold */
  staleThreshold?: number;
}

export const LiveIndicator: React.FC<LiveIndicatorProps> = ({
  isLive,
  staleness = 0,
  staleThreshold = 60,
}) => {
  const isStale = staleness > staleThreshold;

  if (!isLive) {
    return (
      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold"
        style={{ background: 'rgba(229, 83, 75, 0.08)', color: '#E5534B' }}>
        <WifiOff className="w-3 h-3" /> DISCONNECTED
      </span>
    );
  }

  if (isStale) {
    return (
      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold"
        style={{ background: 'rgba(245, 166, 35, 0.08)', color: '#F5A623' }}>
        <Wifi className="w-3 h-3" /> STALE ({staleness}s)
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold"
      style={{ background: 'rgba(39, 166, 68, 0.08)', color: '#27A644' }}>
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: '#27A644' }}></span>
        <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: '#27A644' }}></span>
      </span>
      LIVE
    </span>
  );
};
