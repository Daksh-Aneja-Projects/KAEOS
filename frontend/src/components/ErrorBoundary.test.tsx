import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ErrorBoundary from './ErrorBoundary';

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
});
