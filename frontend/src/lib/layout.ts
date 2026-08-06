/**
 * Canonical layout tokens.
 *
 * The app shell (App.tsx) and the tab-body containers in `views/` deliberately
 * carry NO padding, because the tab bars above them are full-bleed with an
 * edge-to-edge bottom border. That means the gutter has to be owned by the leaf
 * surface instead, and it has to be owned exactly once: a routed page and a
 * component rendered as a tab body are the same kind of thing and must look the
 * same. Before this existed every leaf invented its own value (p-8 down to p-1,
 * px-2 py-0, or nothing at all), so sibling tabs of one view disagreed and the
 * unpadded ones sat flush against the sidebar.
 *
 * Apply PAGE_PAD once at the root element of any leaf surface. Do not add it to
 * a tab-body wrapper in `views/`, or the two will stack.
 */

/** Standard page gutter: comfortable on a phone, roomier on a desktop. */
export const PAGE_PAD = 'px-5 sm:px-6 lg:px-8 py-6';

/**
 * Horizontal-only variant, for a full-bleed surface that manages its own
 * vertical rhythm (a tab bar, a sticky toolbar) but must still line its content
 * up with the PAGE_PAD gutter.
 */
export const PAGE_PAD_X = 'px-5 sm:px-6 lg:px-8';

/** Vertical rhythm between the major blocks of a page. */
export const PAGE_STACK = 'space-y-6';
