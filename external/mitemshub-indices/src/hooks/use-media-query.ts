"use client";

import { useEffect, useState } from "react";

/**
 * SSR-safe hook that returns `true` when the given CSS media query matches,
 * re-rendering on changes. Defaults to `false` during SSR / first render.
 *
 * @example
 * ```ts
 * const isDesktop = useMediaQuery("(min-width: 768px)");
 * ```
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(query);
    setMatches(mq.matches);

    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);

  return matches;
}
