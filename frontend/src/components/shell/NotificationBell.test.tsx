import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import NotificationBell from './NotificationBell';

const getPendingHITL = vi.fn();
const getNotifications = vi.fn();
vi.mock('../../api/client', () => ({
  api: {
    getPendingHITL: (...a: unknown[]) => getPendingHITL(...a),
    getNotifications: (...a: unknown[]) => getNotifications(...a),
  },
}));

const mount = () =>
  render(
    <MemoryRouter>
      <NotificationBell />
    </MemoryRouter>
  );

afterEach(() => vi.restoreAllMocks());

// M7.3 extraction: the HITL/org-notification poll state lives HERE, not in
// Shell. Mount tests (badge from the poll, panel on click) - see the note in
// GlobalSearch.test.tsx on why a Shell render-isolation probe is impractical.
describe('NotificationBell', () => {
  it('shows the badge count from pending HITL items and opens the panel', async () => {
    getPendingHITL.mockResolvedValue([
      { id: 1, task_intent: 'Approve vendor payment', skill_id_name: 'ap_pay', route_type: 'HITL' },
    ]);
    getNotifications.mockResolvedValue({ items: [] });
    mount();

    // Badge renders once the mount fetch lands.
    expect(await screen.findByText('1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Notifications' }));
    expect(screen.getByText('1 pending')).toBeInTheDocument();
    expect(screen.getByText('Approve vendor payment')).toBeInTheDocument();
    expect(screen.getByText('Review all in Decisions')).toBeInTheDocument();

    // Escape closes the panel (the pre-extraction global-shortcut behavior).
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByText('1 pending')).not.toBeInTheDocument();
  });

  it('shows the caught-up empty state when there is nothing pending', async () => {
    getPendingHITL.mockResolvedValue([]);
    getNotifications.mockResolvedValue({ items: [] });
    mount();

    const bell = screen.getByRole('button', { name: 'Notifications' });
    fireEvent.click(bell);
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument();
    // No badge without items.
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
});
