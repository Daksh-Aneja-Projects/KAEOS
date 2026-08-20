import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import GlobalSearch from './GlobalSearch';

// The entity-search effect hits the API on every query; stub it out so the
// module "Go to" results (pure client-side state) are what's under test.
vi.mock('../../api/client', () => ({
  api: { globalSearch: vi.fn().mockResolvedValue({ results: {} }) },
}));

const mount = (userDept: string | null = null) =>
  render(
    <MemoryRouter>
      <GlobalSearch userDept={userDept} />
    </MemoryRouter>
  );

afterEach(() => vi.restoreAllMocks());

// M7.3 extraction: search state lives HERE, not in Shell. These are mount
// tests (type -> dropdown appears); a Shell render-isolation probe is not
// practical in this harness because Shell is un-exported and needs the full
// Auth/Branding/api stack.
describe('GlobalSearch', () => {
  it('shows module results when typing, and clears on Escape', () => {
    mount();
    const input = screen.getByRole('combobox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'market' } });

    expect(screen.getByText('Marketplace')).toBeInTheDocument();
    expect(screen.getByText('Go to')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect((input as HTMLInputElement).value).toBe('');
    expect(screen.queryByText('Marketplace')).not.toBeInTheDocument();
  });

  it('shows the empty state for a query nothing matches', () => {
    mount();
    const input = screen.getByRole('combobox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'zzzz-no-such' } });
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument();
  });

  it('hides other departments from a scoped user', () => {
    mount('hr');
    const input = screen.getByRole('combobox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'department' } });
    expect(screen.getByText('HR Department')).toBeInTheDocument();
    expect(screen.queryByText('Lending Department')).not.toBeInTheDocument();
  });

  it('focuses the input on Ctrl+K', () => {
    mount();
    const input = screen.getByRole('combobox');
    expect(document.activeElement).not.toBe(input);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(document.activeElement).toBe(input);
  });
});
