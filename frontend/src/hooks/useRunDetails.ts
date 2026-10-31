"use client";

/**
 * useRunDetails — hydrates `GET /api/runs/{id}` for the selected run.
 *
 * Stale-data guard: every fetch is generation-tagged and aborted on
 * supersede; a response is applied only when it still matches the current
 * run id + generation, so an older in-flight REST response can never
 * overwrite state derived from newer WebSocket events. Callers pass a
 * `liveKey` (WS status + last-event stamp); when it changes — notably on
 * terminal transitions (RESOLVED / FAILED / FALLBACK_*) — details refetch
 * immediately so freshly persisted artifact URLs hydrate without reload.
 * This hook opens no sockets; the mission-control stream stays sole owner.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { RunDetails } from "@/types";
import { resolveApiBase } from "@/hooks/useMissionControlStream";

export interface RunDetailsState {
  details: RunDetails | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function isRunDetailsPayload(value: unknown): value is RunDetails {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "string" && Array.isArray(v.attempts);
}

export function useRunDetails(
  runId: string | null,
  opts: { apiBase?: string; liveKey?: string } = {},
): RunDetailsState {
  const apiBase = resolveApiBase(opts.apiBase);
  const liveKey = opts.liveKey ?? "";
  const [details, setDetails] = useState<RunDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const generationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!runId) {
      setDetails(null);
      setLoading(false);
      setError(null);
      return;
    }
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);

    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`GET /api/runs/${runId} failed: ${res.status}`);
        const body: unknown = await res.json();
        // Stale guard: only the newest generation for the current run wins.
        if (generationRef.current !== generation || controller.signal.aborted) return;
        if (!isRunDetailsPayload(body) || body.id !== runId) {
          setDetails(null);
          setError(null);
          return;
        }
        setDetails(body);
        setError(null);
      } catch (err) {
        if (controller.signal.aborted || generationRef.current !== generation) return;
        setError(err instanceof Error ? err.message : "Run details hydration failed");
      } finally {
        if (generationRef.current === generation && !controller.signal.aborted) {
          setLoading(false);
        }
      }
    })();

    return () => {
      controller.abort();
    };
    // liveKey/nonce changes intentionally retrigger hydration (WS-driven).
  }, [apiBase, runId, liveKey, nonce]);

  return { details, loading, error, refetch };
}
