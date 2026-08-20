import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import { CountUp } from './CountUp';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

  it('animates a value change by writing textContent from the rAF loop', () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => {
      frames.push(cb);
      return frames.length;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});

    const t0 = performance.now();
    const { container, rerender } = render(<CountUp value={0} duration={10000} />);
    expect(frames.length).toBe(0); // mount shows the value directly, no animation

    rerender(<CountUp value={100} duration={10000} />);
    // The layout effect rewinds the DOM to the old number before first paint.
    expect(container.textContent).toBe('0');
    expect(frames.length).toBe(1);

    // Mid-flight frame: an intermediate number, written without a re-render.
    frames.shift()!(t0 + 5000);
    const mid = parseFloat(container.textContent!);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(100);

    // Final frame lands exactly on the target and stops scheduling.
    frames.shift()!(t0 + 30000);
    expect(container.textContent).toBe('100');
    expect(frames.length).toBe(0);
  });

  it('jumps straight to the final value under prefers-reduced-motion', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
    const raf = vi.spyOn(window, 'requestAnimationFrame');

    const { container, rerender } = render(<CountUp value={5} suffix="%" />);
    rerender(<CountUp value={80} suffix="%" />);

    expect(container.textContent).toBe('80%');
    expect(raf).not.toHaveBeenCalled();
  });
});
