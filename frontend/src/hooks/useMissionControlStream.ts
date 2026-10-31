"use client";

/**
 * useMissionControlStream — real-time Mission Control telemetry.
 *
 * Hydrates from `GET /api/runs`, streams `/ws/mission-control`, and
 * auto-focuses the workspace when a GitHub webhook PR run arrives
 * (`SENSE_STARTED` for a new run id). One shared socket per URL across
 * consumers (refcounted), StrictMode-safe, with backoff+jitter reconnect
 * and REST rehydration after every reconnect.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PRRun } from "@/types";
import {
  ConnectionStatus,
  HydratedSnapshot,
  MissionControlSync,
} from "@/lib/missionControlSync";

export interface MissionControlStream {
  runs: PRRun[];
  activeRun: PRRun | null;
  activeRunId: string | null;
  status: ConnectionStatus;
  loading: boolean;
  error: string | null;
  reconnectAttempt: number;
  focusLatencyMs: number | null;
  lastEventAt: string | null;
  selectRun: (runId: string | null) => void;
}

export interface StreamOptions {
  apiBase?: string;
  wsPath?: string;
  maxBackoffMs?: number;
  baseBackoffMs?: number;
  heartbeatMs?: number;
}

const DEFAULT_WS_PATH = "/ws/mission-control";

export function resolveApiBase(explicit?: string): string {
  if (explicit !== undefined) return explicit.replace(/\/$/, "");
  const env =
    typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_API_URL
      : undefined;
  return (env ?? "").replace(/\/$/, "");
}

export function resolveWsUrl(apiBase: string, wsPath: string): string {
  if (/^wss?:\/\//i.test(apiBase)) {
    return `${apiBase.replace(/\/$/, "")}${wsPath}`;
  }
  if (/^https?:\/\//i.test(apiBase)) {
    return `${apiBase.replace(/^http/i, "ws").replace(/\/$/, "")}${wsPath}`;
  }
  if (typeof window !== "undefined") {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.host}${wsPath}`;
  }
  return wsPath;
}

interface HubListener {
  onSnapshot: (snap: HydratedSnapshot) => void;
  onMeta: (meta: {
    status: ConnectionStatus;
    loading: boolean;
    error: string | null;
    reconnectAttempt: number;
  }) => void;
}

class StreamHub {
  readonly key: string;
  private sync = new MissionControlSync();
  private listeners = new Set<HubListener>();
  private refs = 0;
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private hydrateController: AbortController | null = null;
  private status: ConnectionStatus = "connecting";
  private loading = true;
  private error: string | null = null;
  private reconnectAttempt = 0;
  private closed = false;
  private connectEpoch = 0;

  constructor(
    key: string,
    private apiBase: string,
    private wsUrl: string,
    private opts: Required<
      Pick<StreamOptions, "maxBackoffMs" | "baseBackoffMs" | "heartbeatMs">
    >,
  ) {
    this.key = key;
  }

  attach(listener: HubListener): () => void {
    this.listeners.add(listener);
    this.refs += 1;
    if (this.refs === 1) {
      this.closed = false;
      this.start();
    } else {
      listener.onSnapshot(this.sync.snapshot());
      listener.onMeta(this.meta());
    }
    return () => {
      this.listeners.delete(listener);
      this.refs -= 1;
      if (this.refs <= 0) {
        this.refs = 0;
        this.shutdown();
      }
    };
  }

  selectRun(runId: string | null): void {
    this.sync.selectRun(runId);
    this.emitSnapshot();
  }

  private meta() {
    return {
      status: this.status,
      loading: this.loading,
      error: this.error,
      reconnectAttempt: this.reconnectAttempt,
    };
  }

  private emitSnapshot(): void {
    const snap = this.sync.snapshot();
    for (const l of this.listeners) l.onSnapshot(snap);
  }

  private emitMeta(): void {
    const meta = this.meta();
    for (const l of this.listeners) l.onMeta(meta);
  }

  private setStatus(status: ConnectionStatus): void {
    this.status = status;
    this.emitMeta();
  }

  private start(): void {
    this.hydrate();
    this.connectSocket();
  }

  private shutdown(): void {
    this.closed = true;
    this.connectEpoch += 1;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.hydrateController?.abort();
    this.hydrateController = null;
    this.closeSocket();
    this.setStatus("closed");
  }

  private closeSocket(): void {
    const ws = this.socket;
    this.socket = null;
    if (ws) {
      ws.onopen = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
    }
  }

  private async hydrate(): Promise<void> {
    const generation = this.sync.beginHydration();
    this.hydrateController?.abort();
    const controller = new AbortController();
    this.hydrateController = controller;
    this.loading = true;
    this.emitMeta();
    try {
      const res = await fetch(`${this.apiBase}/api/runs`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`GET /api/runs failed: ${res.status}`);
      const rows: unknown = await res.json();
      // Stale slower response vs a newer round is dropped inside the engine.
      if (this.sync.applyHydration(rows, generation)) this.emitSnapshot();
      if (generation === this.sync.currentGeneration) {
        this.error = null;
      }
    } catch (err) {
      if (controller.signal.aborted || this.closed) return;
      this.error =
        err instanceof Error ? err.message : "REST hydration failed";
    } finally {
      if (!controller.signal.aborted) {
        this.loading = false;
        this.emitMeta();
      }
    }
  }

  private connectSocket(): void {
    if (this.closed || typeof WebSocket === "undefined") return;
    const epoch = this.connectEpoch;
    this.closeSocket(); // never two live sockets per hub
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.wsUrl);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = ws;

    ws.onopen = () => {
      if (this.closed || epoch !== this.connectEpoch) return;
      this.reconnectAttempt = 0;
      this.setStatus("open");
      this.startHeartbeat();
    };
    ws.onmessage = (event: MessageEvent) => {
      if (this.closed || epoch !== this.connectEpoch) return;
      const data = typeof event.data === "string" ? event.data : "";
      if (!data) return;
      const receiptTs = Date.now();
      const { changed } = this.sync.applyMessage(data, receiptTs);
      if (changed) this.emitSnapshot();
    };
    const onDown = () => {
      if (this.closed || epoch !== this.connectEpoch) return;
      this.closeSocket();
      this.scheduleReconnect();
    };
    ws.onclose = onDown;
    ws.onerror = () => {
      // onerror is followed by onclose; only reconnect if the socket died
      // without a close event (defensive; browsers normally send both).
      if (this.closed || epoch !== this.connectEpoch) return;
      if (this.socket === ws && ws.readyState === WebSocket.CLOSED) onDown();
    };
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.opts.heartbeatMs <= 0) return;
    this.heartbeatTimer = setInterval(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        try {
          this.socket.send(JSON.stringify({ type: "PING" }));
        } catch {
          /* send failure surfaces via onclose */
        }
      }
    }, this.opts.heartbeatMs);
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
    this.setStatus("reconnecting");
    const attempt = this.reconnectAttempt;
    const capped = Math.min(
      this.opts.maxBackoffMs,
      this.opts.baseBackoffMs * 2 ** attempt,
    );
    const delay = Math.min(
      this.opts.maxBackoffMs,
      Math.floor(capped / 2 + Math.random() * (capped / 2)),
    );
    this.reconnectAttempt += 1;
    this.emitMeta();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      if (this.closed) return;
      this.hydrate(); // recover events missed during the outage
      this.connectSocket();
    }, delay);
  }
}

const hubs = new Map<string, StreamHub>();

/** Test-only: drop all shared hubs (sockets are closed via detach). */
export function __resetMissionControlHubsForTests(): void {
  hubs.clear();
}

function getHub(
  apiBase: string,
  wsPath: string,
  opts: StreamOptions,
): { hub: StreamHub; wsUrl: string } {
  const wsUrl = resolveWsUrl(apiBase, wsPath);
  const key = `${apiBase}::${wsUrl}`;
  let hub = hubs.get(key);
  if (!hub) {
    hub = new StreamHub(key, apiBase, wsUrl, {
      maxBackoffMs: opts.maxBackoffMs ?? 30000,
      baseBackoffMs: opts.baseBackoffMs ?? 1000,
      heartbeatMs: opts.heartbeatMs ?? 30000,
    });
    hubs.set(key, hub);
  }
  return { hub, wsUrl };
}

const INITIAL_SNAPSHOT: HydratedSnapshot = {
  runs: [],
  activeRunId: null,
  focusLatencyMs: null,
  lastEventAt: null,
};

export function useMissionControlStream(
  opts: StreamOptions = {},
): MissionControlStream {
  const apiBase = resolveApiBase(opts.apiBase);
  const wsPath = opts.wsPath ?? DEFAULT_WS_PATH;
  const [snapshot, setSnapshot] =
    useState<HydratedSnapshot>(INITIAL_SNAPSHOT);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const hubRef = useRef<StreamHub | null>(null);

  useEffect(() => {
    const { hub } = getHub(apiBase, wsPath, opts);
    hubRef.current = hub;
    const detach = hub.attach({
      onSnapshot: (snap) => setSnapshot({ ...snap, runs: [...snap.runs] }),
      onMeta: (meta) => {
        setStatus(meta.status);
        setLoading(meta.loading);
        setError(meta.error);
        setReconnectAttempt(meta.reconnectAttempt);
      },
    });
    return () => {
      hubRef.current = null;
      detach();
    };
    // apiBase/wsPath identity drives the hub key; options are hub-scoped.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, wsPath]);

  const selectRun = useCallback((runId: string | null) => {
    hubRef.current?.selectRun(runId);
  }, []);

  const activeRun =
    snapshot.activeRunId === null
      ? null
      : (snapshot.runs.find((r) => r.id === snapshot.activeRunId) ?? null);

  return {
    runs: snapshot.runs,
    activeRun,
    activeRunId: snapshot.activeRunId,
    status,
    loading,
    error,
    reconnectAttempt,
    focusLatencyMs: snapshot.focusLatencyMs,
    lastEventAt: snapshot.lastEventAt,
    selectRun,
  };
}
