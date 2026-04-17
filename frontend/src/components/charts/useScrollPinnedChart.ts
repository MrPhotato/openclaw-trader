import { useEffect, useRef } from "react";

/**
 * Keeps a scrollable chart viewport pinned to its right edge whenever the
 * inputs in `pinDeps` change, and optionally hijacks the mouse wheel so that
 * vertical scroll is converted to horizontal scroll (used for the balance
 * chart). The K-line chart opts out of the wheel hijack by omitting
 * `wheelHijackActive`.
 */
export function useScrollPinnedChart<T extends HTMLElement = HTMLDivElement>(options: {
  pinDeps: ReadonlyArray<unknown>;
  wheelHijack?: {
    active: boolean;
    deps: ReadonlyArray<unknown>;
  };
}) {
  const ref = useRef<T | null>(null);

  const wheelActive = options.wheelHijack?.active ?? false;
  const wheelDeps = options.wheelHijack?.deps ?? [];

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      if (!wheelActive) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
      node.scrollLeft += delta;
    };

    node.addEventListener("wheel", handleWheel, { passive: false });

    return () => {
      node.removeEventListener("wheel", handleWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wheelActive, ...wheelDeps]);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }
    const raf = requestAnimationFrame(() => {
      node.scrollLeft = node.scrollWidth;
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, options.pinDeps);

  return ref;
}
