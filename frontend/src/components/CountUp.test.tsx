import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { CountUp } from './CountUp';

describe('CountUp', () => {
  it('renders the final value with prefix, suffix, and decimals', () => {
    const { container } = render(
      <CountUp value={42.5} decimals={1} prefix="$" suffix="%" />
    );
    expect(container.textContent).toBe('$42.5%');
  });

  it('renders an integer value with no decimals by default', () => {
    const { container } = render(<CountUp value={128} />);
    expect(container.textContent).toBe('128');
  });
});
