import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ErrorBoundary, { isChunkLoadError } from './ErrorBoundary';

// Proves the React Testing Library + jsdom path works, not just pure-util tests.
describe('ErrorBoundary', () => {
  it('renders its children when there is no error', () => {
    render(
      <ErrorBoundary>
        <div>copilot dock</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('copilot dock')).toBeInTheDocument();
  });

  it('offers a plain Reload for a stale lazy chunk and never shows the raw URL', () => {
    const Boom = () => { throw new Error('Failed to fetch dynamically imported module: https://x.test/assets/Page-abc.js'); };
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Boom /></ErrorBoundary>);
    spy.mockRestore();
    expect(screen.getByText('A newer version of KAEOS is available. Reload to continue.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(screen.queryByText(/x\.test/)).toBeNull();
  });

  it('recognises the chunk-load failure messages', () => {
    for (const m of ['Failed to fetch dynamically imported module: /a.js', 'Importing a module script failed.', 'Loading chunk 12 failed.']) {
      expect(isChunkLoadError(new Error(m))).toBe(true);
    }
    expect(isChunkLoadError(new Error('x is undefined'))).toBe(false);
  });
});
