import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import Sparkline from './Sparkline';

// Geometry checks use the component defaults: width 120, height 28, pad 2.
// For points [0, 10]: x spans 2..118, y spans 26 (min) .. 2 (max).

describe('Sparkline', () => {
  it('renders nothing with fewer than 2 usable points', () => {
    expect(render(<Sparkline points={[]} />).container.firstChild).toBeNull();
    expect(render(<Sparkline points={[5]} />).container.firstChild).toBeNull();
    expect(render(<Sparkline points={[null, null]} />).container.firstChild).toBeNull();
    expect(render(<Sparkline points={[null, 7]} />).container.firstChild).toBeNull();
  });

  it('draws the line through correctly scaled coordinates', () => {
    const { container } = render(<Sparkline points={[0, 10]} />);
    const paths = container.querySelectorAll('path');
    // First path is the area fill, second is the stroked line.
    expect(paths).toHaveLength(2);
    expect(paths[1].getAttribute('d')).toBe('M 2.0 26.0 L 118.0 2.0');
    expect(paths[1].getAttribute('fill')).toBe('none');
  });

  it('closes the area fill down to the baseline', () => {
    const { container } = render(<Sparkline points={[0, 10]} />);
    const area = container.querySelectorAll('path')[0];
    expect(area.getAttribute('d')).toBe('M 2.0 26.0 L 118.0 2.0 L 118.0 28 L 2.0 28 Z');
  });

  it('ignores null gaps in the series', () => {
    const withNulls = render(<Sparkline points={[null, 0, null, 10, null]} />);
    const clean = render(<Sparkline points={[0, 10]} />);
    expect(withNulls.container.querySelectorAll('path')[1].getAttribute('d'))
      .toBe(clean.container.querySelectorAll('path')[1].getAttribute('d'));
  });

  it('renders a flat series as a horizontal line (span fallback, no NaN)', () => {
    const { container } = render(<Sparkline points={[5, 5, 5]} />);
    const d = container.querySelectorAll('path')[1].getAttribute('d')!;
    expect(d).toBe('M 2.0 26.0 L 60.0 26.0 L 118.0 26.0');
    expect(d).not.toContain('NaN');
  });

  it('marks the present moment with a dot at the last coordinate', () => {
    const { container } = render(<Sparkline points={[0, 10]} />);
    const dot = container.querySelector('circle')!;
    expect(dot.getAttribute('cx')).toBe('118');
    expect(dot.getAttribute('cy')).toBe('2');
  });

  it('applies the stroke color and derives the gradient id from it', () => {
    const { container } = render(<Sparkline points={[1, 2]} color="#5e6ad2" />);
    expect(container.querySelectorAll('path')[1].getAttribute('stroke')).toBe('#5e6ad2');
    expect(container.querySelector('linearGradient')!.getAttribute('id')).toBe('spark-5e6ad2');
  });

  it('shows the nearest value on hover and clears it on leave', () => {
    const { container } = render(<Sparkline points={[0, 10]} />);
    const svg = container.querySelector('svg')!;
    // jsdom has no layout; supply the box the hover math reads.
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 120, height: 28, right: 120, bottom: 28, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.mouseMove(svg, { clientX: 118, clientY: 10 });
    expect(svg.querySelector('text')?.textContent).toBe('10');

    fireEvent.mouseMove(svg, { clientX: 2, clientY: 10 });
    expect(svg.querySelector('text')?.textContent).toBe('0');

    fireEvent.mouseLeave(svg);
    expect(svg.querySelector('text')).toBeNull();
  });

  it('formats non-integer hover values to 2 decimals', () => {
    const { container } = render(<Sparkline points={[0.125, 9.875]} />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 120, height: 28, right: 120, bottom: 28, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.mouseMove(svg, { clientX: 118, clientY: 10 });
    expect(svg.querySelector('text')?.textContent).toBe('9.88');
  });
});
