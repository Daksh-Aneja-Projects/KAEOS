import { useEffect, useRef } from 'react';

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'textarea:not([disabled])',
  'input:not([disabled])', 'select:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Make a dialog keyboard-accessible: trap Tab focus inside it, close on Esc,
 * move focus in on open and restore it to the opener on close.
 *
 * Usage: attach the returned ref to the dialog's outermost element (the one
 * with role="dialog" aria-modal="true"), and pass the close handler.
 */
export function useFocusTrap<T extends HTMLElement = HTMLDivElement>(
  active: boolean,
  onClose: () => void,
) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!active) return;
    const node = ref.current;
    const opener = document.activeElement as HTMLElement | null;

    // Focus the first focusable control (or the container itself). We rely on
    // the FOCUSABLE selector (which excludes [disabled] and tabindex="-1"); we
    // deliberately don't filter on offsetParent because it is null for
    // position:fixed dialogs (which is exactly how these modals are laid out).
    const focusables = () =>
      Array.from(node?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
        .filter((el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true');
    const first = focusables()[0];
    (first ?? node)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) { e.preventDefault(); return; }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const activeEl = document.activeElement;
      if (e.shiftKey && activeEl === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && activeEl === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    node?.addEventListener('keydown', onKey);
    return () => {
      node?.removeEventListener('keydown', onKey);
      opener?.focus?.();
    };
  }, [active, onClose]);

  return ref;
}
