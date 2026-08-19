import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import { useVisiblePoll } from './useLiveRefresh';

/** jsdom leaves `document.hidden` read-only, so redefine it before the event. */
function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

function Poller({ onTick }: { onTick: () => void }) {
  useVisiblePoll(onTick, 1000);
  return null;
}

describe('useVisiblePoll', () => {
  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
  });

  it('polls while visible, pauses while hidden, and refetches on return', () => {
    vi.useFakeTimers();
    const onTick = vi.fn();
    render(<Poller onTick={onTick} />);

    // The hook owns the timer only - the mount fetch stays the caller's effect.
    vi.advanceTimersByTime(2000);
    expect(onTick).toHaveBeenCalledTimes(2);

    // A backgrounded tab burns no queries.
    setHidden(true);
    vi.advanceTimersByTime(5000);
    expect(onTick).toHaveBeenCalledTimes(2);

    // Coming back refetches at once, so the user never reads a stale screen...
    setHidden(false);
    expect(onTick).toHaveBeenCalledTimes(3);

    // ...and the timer resumes from there.
    vi.advanceTimersByTime(1000);
    expect(onTick).toHaveBeenCalledTimes(4);
  });

  it('stops polling once the caller unmounts', () => {
    vi.useFakeTimers();
    const onTick = vi.fn();
    const { unmount } = render(<Poller onTick={onTick} />);
    vi.advanceTimersByTime(1000);
    expect(onTick).toHaveBeenCalledTimes(1);

    unmount();
    vi.advanceTimersByTime(5000);
    expect(onTick).toHaveBeenCalledTimes(1);
  });
});
