import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import LiveBadge from './LiveBadge';

/**
 * Rendered without providers on purpose: the default AuthContext has no user,
 * so useWebSocket never opens a socket (real behavior for a logged-out or
 * pre-hydration render) and the badge reports Offline. No network, no mocks.
 */
describe('LiveBadge', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-25T12:00:00.000Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows Offline when there is no live socket', () => {
    render(<LiveBadge lastSync={null} />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.queryByText(/synced/)).toBeNull();
  });

  it('exposes the reconnect state in the tooltip', () => {
    const { container } = render(<LiveBadge lastSync={null} />);
    expect((container.firstElementChild as HTMLElement).title)
      .toBe('Reconnecting to the live event stream');
  });

  it('renders "synced just now" for a sync under 2 seconds old', () => {
    render(<LiveBadge lastSync={Date.now()} />);
    expect(screen.getByText(/synced just now/)).toBeInTheDocument();
  });

  it('renders seconds, then minutes, then hours since the last sync', () => {
    const now = Date.now();
    const r1 = render(<LiveBadge lastSync={now - 30_000} />);
    expect(screen.getByText(/synced 30s ago/)).toBeInTheDocument();
    r1.unmount();

    const r2 = render(<LiveBadge lastSync={now - 5 * 60_000} />);
    expect(screen.getByText(/synced 5m ago/)).toBeInTheDocument();
    r2.unmount();

    render(<LiveBadge lastSync={now - 2 * 3_600_000} />);
    expect(screen.getByText(/synced 2h ago/)).toBeInTheDocument();
  });

  it('advances the "synced" ticker every second without parent re-renders', () => {
    render(<LiveBadge lastSync={Date.now()} />);
    expect(screen.getByText(/synced just now/)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.getByText(/synced 5s ago/)).toBeInTheDocument();
  });
});
