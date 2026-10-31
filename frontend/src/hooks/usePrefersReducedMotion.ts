"use client";

import { useEffect, useState } from "react";

/** True when the OS requests reduced motion. SSR-safe (defaults to false). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(query.matches);
    sync();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", sync);
      return () => query.removeEventListener("change", sync);
    }
    // Legacy browsers.
    query.addListener(sync);
    return () => query.removeListener(sync);
  }, []);

  return reduced;
}
