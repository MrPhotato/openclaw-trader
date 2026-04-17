import { useCallback, useEffect, useRef } from "react";

type ScrollAttachers = {
  /** Attach to the balance chart's scroll viewport. */
  balanceRef: (node: HTMLDivElement | null) => void;
  /** Attach to the K-line chart's scroll viewport. */
  klineRef: (node: HTMLDivElement | null) => void;
};

/**
 * Keeps two chart scroll viewports in lockstep:
 *
 *   1. Scrolling viewport A mirrors its scrollLeft to viewport B (and
 *      vice versa), so panning either chart moves the other.
 *   2. Wheel input on either viewport is hijacked into horizontal
 *      scroll (same behavior the balance chart always had).
 *   3. Both viewports pin to their right edge whenever any of
 *      `pinDeps` changes (granularity flip, data refresh, width change).
 *
 * Callbacks are exposed as ref-setter callbacks so the parent can pass
 * them straight to `<div ref={...}>` without plumbing refs through.
 */
export function useSyncedScrollPinnedCharts(options: {
  pinDeps: ReadonlyArray<unknown>;
  wheelHijack?: { active: boolean; deps: ReadonlyArray<unknown> };
}): ScrollAttachers {
  const balanceNodeRef = useRef<HTMLDivElement | null>(null);
  const klineNodeRef = useRef<HTMLDivElement | null>(null);

  // Flag used to guard the scroll-mirror so we don't recurse: when we
  // programmatically set scrollLeft on the "follower", its own scroll
  // handler fires and would try to set the leader — we detect that and
  // bail.
  const isSyncing = useRef(false);

  const attachScrollMirror = useCallback(() => {
    const a = balanceNodeRef.current;
    const b = klineNodeRef.current;
    if (!a || !b) return undefined;
    const mirror = (source: HTMLDivElement, target: HTMLDivElement) => () => {
      if (isSyncing.current) return;
      isSyncing.current = true;
      target.scrollLeft = source.scrollLeft;
      requestAnimationFrame(() => {
        isSyncing.current = false;
      });
    };
    const onA = mirror(a, b);
    const onB = mirror(b, a);
    a.addEventListener("scroll", onA, { passive: true });
    b.addEventListener("scroll", onB, { passive: true });
    return () => {
      a.removeEventListener("scroll", onA);
      b.removeEventListener("scroll", onB);
    };
  }, []);

  const balanceRef = useCallback(
    (node: HTMLDivElement | null) => {
      balanceNodeRef.current = node;
      // Re-attach whenever either ref changes.
      if (node && klineNodeRef.current) attachScrollMirror();
    },
    [attachScrollMirror],
  );

  const klineRef = useCallback(
    (node: HTMLDivElement | null) => {
      klineNodeRef.current = node;
      if (node && balanceNodeRef.current) attachScrollMirror();
    },
    [attachScrollMirror],
  );

  // Scroll mirror (stable across mounts — lives as long as both refs exist).
  useEffect(() => {
    return attachScrollMirror();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Wheel hijack on both viewports: vertical wheel → horizontal scroll.
  // Syncing takes care of mirroring so we only need to handle one of them
  // (the mirror will drag the other along), but we attach to both so the
  // user can wheel over either chart and get the same behavior.
  const wheelActive = options.wheelHijack?.active ?? false;
  const wheelDeps = options.wheelHijack?.deps ?? [];
  useEffect(() => {
    const a = balanceNodeRef.current;
    const b = klineNodeRef.current;
    if (!a && !b) return;
    const handle = (target: HTMLDivElement) => (event: WheelEvent) => {
      if (!wheelActive) return;
      event.preventDefault();
      event.stopPropagation();
      const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
      target.scrollLeft += delta;
    };
    const handlers: Array<[HTMLDivElement, (event: WheelEvent) => void]> = [];
    if (a) {
      const onA = handle(a);
      a.addEventListener("wheel", onA, { passive: false });
      handlers.push([a, onA]);
    }
    if (b) {
      const onB = handle(b);
      b.addEventListener("wheel", onB, { passive: false });
      handlers.push([b, onB]);
    }
    return () => {
      for (const [node, fn] of handlers) node.removeEventListener("wheel", fn);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wheelActive, ...wheelDeps]);

  // Pin to right edge on any pin-dep change.
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      const a = balanceNodeRef.current;
      const b = klineNodeRef.current;
      if (a) a.scrollLeft = a.scrollWidth;
      if (b) b.scrollLeft = b.scrollWidth;
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, options.pinDeps);

  return { balanceRef, klineRef };
}
