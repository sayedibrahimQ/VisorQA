/**
 * useMissionControlStream tests (mocked WebSocket + REST, no credentials).
 * Run: cd frontend && npx vitest run tests/unit/missionControlStream.test.tsx
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import React, { StrictMode } from "react";

import {
  __resetMissionControlHubsForTests,
  resolveWsUrl,
  useMissionControlStream,
} from "@/hooks/useMissionControlStream";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: ((e: object) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: object) => void) | null = null;
  onerror: ((e: object) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    queueMicrotask(() => {
      if (this.readyState === MockWebSocket.CONNECTING) {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.({});
      }
    });
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSED;
    queueMicrotask(() => this.onclose?.({}));
  }

  serverSend(data: string): void {
    this.onmessage?.({ data });
  }

  serverCloseUnexpectedly(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }
}

let testId = 0;
let fetchImpl: (url: string) => Promise<unknown>;
const fetchCalls: string[] = [];

function envelope(event: string, runId: string, state: object = {}) {
  return JSON.stringify({
    event,
    type: event,
    timestamp: new Date().toISOString(),
    run_id: runId,
    state: {
      run_id: runId,
      repo_full_name: "org/repo",
      pr_number: 7,
      branch: "fix/x",
      commit_sha: "abc",
      status: "RUNNING",
      current_step: "1.SENSE",
      attempt: 0,
      anomalies: [],
      ...state,
    },
  });
}

function restRow(id: string, overrides: object = {}) {
  return {
    id,
    pr_number: 7,
    repo_name: "org/repo",
    branch: "fix/x",
    commit_sha: "abc",
    status: "RUNNING",
    current_step: "1.SENSE",
    strikes: 0,
    anomalies_count: 0,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderStream(opts: object = {}) {
  testId += 1;
  return renderHook(() =>
    useMissionControlStream({
      apiBase: `http://test-${testId}.local`,
      baseBackoffMs: 5,
      maxBackoffMs: 20,
      heartbeatMs: 0,
      ...opts,
    }),
  );
}

beforeEach(() => {
  MockWebSocket.instances = [];
  fetchCalls.length = 0;
  fetchImpl = async () => [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      fetchCalls.push(url);
      const body = await fetchImpl(url);
      return { ok: true, json: async () => body };
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  __resetMissionControlHubsForTests();
});

async function waitForOpenSockets(n: number) {
  await waitFor(
    () => {
      const open = MockWebSocket.instances.filter(
        (s) => s.readyState === MockWebSocket.OPEN,
      );
      expect(open.length).toBe(n);
    },
    { timeout: 10000 },
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useMissionControlStream", () => {
  it("1. hydrates initial runs from GET /api/runs", async () => {
    fetchImpl = async () => [restRow("run-1"), restRow("run-2")];
    const { result } = renderStream();
    await waitFor(() => expect(result.current.runs).toHaveLength(2), {
      timeout: 10000,
    });
    expect(fetchCalls[0]).toContain("/api/runs");
    expect(result.current.loading).toBe(false);
  });

  it("2. connects WS and picks wss:// for https pages", async () => {
    expect(resolveWsUrl("", "/ws/mission-control")).toContain("ws://");
    expect(resolveWsUrl("https://api.example", "/ws/mission-control")).toBe(
      "wss://api.example/ws/mission-control",
    );
    expect(resolveWsUrl("http://api.example", "/ws/mission-control")).toBe(
      "ws://api.example/ws/mission-control",
    );
    const { result } = renderStream();
    await waitForOpenSockets(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/mission-control");
    expect(result.current.status).toBe("open");
  });

  it("3. applies incoming run updates", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(
        envelope("SENSE_COMPLETE", "run-9", { current_step: "2.TRIAGE" }),
      );
    });
    await waitFor(() =>
      expect(result.current.runs.find((r) => r.id === "run-9")).toBeTruthy(),
    );
  });

  it("4+5. auto-focuses a new PR run with no manual interaction", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    expect(result.current.activeRunId).toBeNull();
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-pr"));
    });
    await waitFor(() => expect(result.current.activeRunId).toBe("run-pr"));
    expect(result.current.activeRun?.pr_number).toBe(7);
  });

  it("6. ignores duplicate webhook deliveries", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    const frame = envelope("SENSE_STARTED", "run-dup");
    act(() => {
      MockWebSocket.instances[0].serverSend(frame);
      MockWebSocket.instances[0].serverSend(frame);
    });
    await waitFor(() => expect(result.current.activeRunId).toBe("run-dup"));
    expect(result.current.runs.filter((r) => r.id === "run-dup")).toHaveLength(1);
  });

  it("7. ignores malformed messages safely", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend("not-json{{{");
      MockWebSocket.instances[0].serverSend("[1,2,3]");
      MockWebSocket.instances[0].serverSend("{}");
    });
    await act(async () => {});
    expect(result.current.runs).toHaveLength(0);
    expect(result.current.activeRunId).toBeNull();
  });

  it("8+9. reconnects automatically after unexpected close", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverCloseUnexpectedly();
    });
    await waitFor(() =>
      expect(["reconnecting", "open"]).toContain(result.current.status),
    );
    await waitForOpenSockets(1);
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    await waitFor(() => expect(result.current.status).toBe("open"));
  });

  it("10. rehydrates REST after reconnect to recover missed events", async () => {
    let calls = 0;
    fetchImpl = async () => {
      calls += 1;
      return calls === 1 ? [] : [restRow("run-missed")];
    };
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverCloseUnexpectedly();
    });
    await waitFor(() =>
      expect(result.current.runs.find((r) => r.id === "run-missed")).toBeTruthy(),
    );
    expect(fetchCalls.length).toBeGreaterThanOrEqual(2);
  });

  it("11. older REST response never overwrites newer WS state", async () => {
    let release!: (rows: unknown) => void;
    const gate = new Promise<unknown>((resolve) => {
      release = resolve;
    });
    fetchImpl = () => gate;
    const { result } = renderStream();
    await waitForOpenSockets(1);
    // WS update lands while REST is still pending.
    act(() => {
      MockWebSocket.instances[0].serverSend(
        envelope("TRIAGE_COMPLETE", "run-race", { current_step: "5.VERIFY" }),
      );
    });
    await waitFor(() =>
      expect(
        result.current.runs.find((r) => r.id === "run-race")?.current_step,
      ).toBe("5.VERIFY"),
    );
    // Stale older REST snapshot resolves afterwards.
    await act(async () => {
      release([restRow("run-race", { current_step: "1.SENSE" })]);
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(
      result.current.runs.find((r) => r.id === "run-race")?.current_step,
    ).toBe("5.VERIFY");
  });

  it("12. cleans up socket and listeners on unmount", async () => {
    const { unmount } = renderStream();
    await waitForOpenSockets(1);
    const sock = MockWebSocket.instances[0];
    unmount();
    expect(sock.readyState).toBe(MockWebSocket.CLOSED);
    expect(sock.onmessage).toBeNull();
  });

  it("13. StrictMode leaves exactly one active connection", async () => {
    testId += 1;
    const apiBase = `http://strict-${testId}.local`;
    const { unmount } = renderHook(
      () =>
        useMissionControlStream({
          apiBase,
          baseBackoffMs: 5,
          maxBackoffMs: 20,
          heartbeatMs: 0,
        }),
      { wrapper: ({ children }) => <StrictMode>{children}</StrictMode> },
    );
    await waitForOpenSockets(1);
    const open = MockWebSocket.instances.filter(
      (s) => s.readyState === MockWebSocket.OPEN,
    );
    expect(open).toHaveLength(1);
    unmount();
  });

  it("14. unrelated telemetry never steals workspace focus", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-keep"));
    });
    await waitFor(() => expect(result.current.activeRunId).toBe("run-keep"));
    act(() => {
      MockWebSocket.instances[0].serverSend(
        JSON.stringify({ type: "PONG", payload: "x" }),
      );
      MockWebSocket.instances[0].serverSend(
        envelope("TELEMETRY_PULSE", "global"),
      );
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_1_FEEDBACK", "run-keep", { attempt: 1 }),
      );
    });
    await act(async () => {});
    expect(result.current.activeRunId).toBe("run-keep");
  });

  it("15. handles multiple incoming PR events safely", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-a"));
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-b"));
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-c"));
    });
    await waitFor(() => expect(result.current.runs).toHaveLength(3));
    expect(result.current.activeRunId).toBe("run-c");
  });

  it("16. focus latency is under 1.2s", async () => {
    const { result } = renderStream();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-lat"));
    });
    await waitFor(() => expect(result.current.activeRunId).toBe("run-lat"));
    // eslint-disable-next-line no-console
    console.log(`FOCUS_LATENCY_MS=${result.current.focusLatencyMs}`);
    expect(result.current.focusLatencyMs).not.toBeNull();
    expect(result.current.focusLatencyMs as number).toBeLessThan(1200);
  });
});
