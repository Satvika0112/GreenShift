import { useState, useEffect } from 'react';

// Tracks a CSS media query in React state so layout (e.g. collapsing the
// sidebar to an off-canvas panel on narrow viewports) can react to it —
// this app has no CSS-module/media-query build step, so breakpoint-driven
// inline-style decisions are made here instead.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const listener = () => setMatches(mql.matches);
    listener();
    mql.addEventListener('change', listener);
    return () => mql.removeEventListener('change', listener);
  }, [query]);

  return matches;
}
