// Roving keyboard nav for the header dropdowns (search results, notifications):
// ArrowDown/Up move between [data-menuitem] buttons, wrapping at the ends.
// Shared by GlobalSearch and NotificationBell.
export const focusMenuItem = (container: HTMLElement, dir: 1 | -1) => {
  const items = Array.from(container.querySelectorAll<HTMLButtonElement>('[data-menuitem]'));
  if (!items.length) return;
  const idx = items.indexOf(document.activeElement as HTMLButtonElement);
  const nextIdx = idx === -1 ? (dir === 1 ? 0 : items.length - 1) : (idx + dir + items.length) % items.length;
  items[nextIdx].focus();
};
