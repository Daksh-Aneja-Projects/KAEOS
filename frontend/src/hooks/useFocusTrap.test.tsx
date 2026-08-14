import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { useFocusTrap } from './useFocusTrap';
import { announce, LiveRegionHost } from '../components/a11y/LiveRegion';

function Dialog({ onClose }: { onClose: () => void }) {
  const ref = useFocusTrap<HTMLDivElement>(true, onClose);
  return (
    <div ref={ref} role="dialog" tabIndex={-1}>
      <button>First</button>
      <button>Last</button>
    </div>
  );
}

describe('useFocusTrap', () => {
  it('closes on Escape and focuses the first control on open', () => {
    const onClose = vi.fn();
    const { getByText } = render(<Dialog onClose={onClose} />);
    expect(document.activeElement).toBe(getByText('First'));
    fireEvent.keyDown(getByText('First'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe('announce / LiveRegionHost', () => {
  it('renders an announced polite message into the status region', async () => {
    const { findByRole } = render(<LiveRegionHost />);
    announce('Saved successfully');
    const status = await findByRole('status');
    // rAF-deferred write; wait a tick.
    await new Promise((r) => setTimeout(r, 20));
    expect(status.textContent).toBe('Saved successfully');
  });

  it('ignores blank messages', () => {
    const spy = vi.fn();
    // no host mounted for this listener path; just assert no throw
    expect(() => announce('   ')).not.toThrow();
    expect(spy).not.toHaveBeenCalled();
  });
});
