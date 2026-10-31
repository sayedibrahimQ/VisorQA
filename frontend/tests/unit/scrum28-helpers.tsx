/**
 * Shared SCRUM-28 test helpers (mocked WebSocket + REST, no credentials).
 * Not a test file itself (does not match *.test.*).
 */
import React from "react";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { useMissionControlStream } from "@/hooks/useMissionControlStream";
import { getAttemptState } from "@/lib/fsmSelectors";
import type { PRRun } from "@/types";
import { PRRunSidebar } from "@/components/mission-control/PRRunSidebar";
import { FSMOrchestratorBar } from "@/components/mission-control/FSMOrchestratorBar";
import { ThreeStrikeLoop } from "@/components/mission-control/ThreeStrikeLoop";

// ---------------------------------------------------------------------------
// Mock WebSocket (mirrors tests/unit/missionControlStream.test.tsx)
// ---------------------------------------------------------------------------

export class MockWebSocket {
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
}

// ---------------------------------------------------------------------------
// Payload factories (real backend contract only — no invented event types)
// ---------------------------------------------------------------------------

let testSeq = 0;
export function nextApiBase(): string {
  testSeq += 1;
  return `http://scrum28-${testSeq}.local`;
}

const baseNow = Date.now();

/** Envelope with a strictly increasing timestamp (seq) for same-run updates. */
export function envelope(
  event: string,
  runId: string,
  state: object = {},
  seq = 0,
): string {
  return JSON.stringify({
    event,
    type: event,
    timestamp: new Date(baseNow + seq * 50).toISOString(),
    run_id: runId,
    state: {
      run_id: runId,
      repo_full_name: "org/repo",
      pr_number: 7,
      branch: "fix/x",
      commit_sha: "abc123",
      status: "RUNNING",
      current_step: "1.SENSE",
      attempt: 0,
      anomalies: [],
      ...state,
    },
  });
}

export function restRow(id: string, overrides: object = {}): object {
  return {
    id,
    pr_number: 7,
    repo_name: "org/repo",
    branch: "fix/x",
    commit_sha: "abc123",
    status: "RUNNING",
    current_step: "1.SENSE",
    strikes: 0,
    anomalies_count: 0,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeRun(overrides: Partial<PRRun> = {}): PRRun {
  return {
    id: "run-1",
    pr_number: 7,
    repo_name: "org/repo",
    branch: "fix/x",
    commit_sha: "abc123",
    status: "RUNNING",
    current_step: "1.SENSE",
    strikes: 0,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Stream harness: real hook + sync engine + SCRUM-28 components, one socket
// ---------------------------------------------------------------------------

export function StreamHarness({ apiBase }: { apiBase: string }) {
  const stream = useMissionControlStream({
    apiBase,
    baseBackoffMs: 5,
    maxBackoffMs: 20,
    heartbeatMs: 0,
  });
  return (
    <div>
      <PRRunSidebar
        runs={stream.runs}
        activeRunId={stream.activeRunId}
        loading={stream.loading}
        error={stream.error}
        connectionStatus={stream.status}
        onSelect={(id) => stream.selectRun(id)}
      />
      <FSMOrchestratorBar run={stream.activeRun} />
      <ThreeStrikeLoop attempt={getAttemptState(stream.activeRun)} />
    </div>
  );
}

export function renderStreamHarness() {
  const apiBase = nextApiBase();
  const rendered = render(<StreamHarness apiBase={apiBase} />);
  return { ...rendered, apiBase };
}

// ---------------------------------------------------------------------------
// matchMedia stub for reduced-motion tests
// ---------------------------------------------------------------------------

export function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}
