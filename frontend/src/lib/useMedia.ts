import { useEffect, useState } from "react";

/**
 * Returns whether the given media query currently matches. Defaults to false
 * when `window.matchMedia` is unavailable (jsdom), so tests render the
 * compact/mobile shell and don't have duplicate nav buttons.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mq = window.matchMedia(query);
    const handler = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(mq.matches);
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }, [query]);

  return matches;
}

export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 1024px)");
}
