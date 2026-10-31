/**
 * SCRUM-28 real-time integration tests: the real `useMissionControlStream`
 * hook + sync engine driving the new sidebar/stepper/loop (one socket).
 * Run: cd frontend && npx vitest run tests/unit/scrum28-stream.test.tsx
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

import {
  __resetMissionControlHubsForTests,
  useMissionControlStream,
} from "@/hooks/useMissionControlStream";
import MissionControlPage from "@/app/mission-control/page";
import {
  MockWebSocket,
  envelope,
  renderStreamHarness,
  restRow,
} from "./scrum28-helpers";

let fetchImpl: (url: string) => Promise<unknown>;

beforeEach(() => {
  MockWebSocket.instances = [];
  fetchImpl = async () => [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = await fetchImpl(url);
      return { ok: true, json: async () => body };
    }),
  );
});

afterEach(() => {
  cleanup();
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

describe("SCRUM-28 real-time integration", () => {
  it("7. selecting a PR updates the workspace selection", async () => {
    fetchImpl = async () => [
      restRow("run-a", { pr_number: 1, current_step: "1.SENSE" }),
      restRow("run-b", { pr_number: 2, current_step: "2.TRIAGE" }),
    ];
    renderStreamHarness();
    await waitFor(() => expect(screen.getByTestId("run-item-run-a")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("run-item-run-b")).toBeTruthy());

    fireEvent.click(screen.getByTestId("run-item-run-b"));
    await waitFor(() =>
      expect(screen.getByTestId("run-item-run-b").getAttribute("data-selected")).toBe("true"),
    );
    // Workspace stepper follows the selected run's step.
    expect(screen.getByTestId("fsm-node-2.TRIAGE").getAttribute("data-status")).toBe("active");

    fireEvent.click(screen.getByTestId("run-item-run-a"));
    await waitFor(() =>
      expect(screen.getByTestId("run-item-run-a").getAttribute("data-selected")).toBe("true"),
    );
    expect(screen.getByTestId("fsm-node-1.SENSE").getAttribute("data-status")).toBe("active");
  });

  it("8. incoming PR event updates the sidebar automatically", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    expect(screen.getByTestId("sidebar-empty")).toBeTruthy();
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-pr", {}, 1));
    });
    await waitFor(() => expect(screen.getByTestId("run-item-run-pr")).toBeTruthy());
    // Auto-focused without manual interaction.
    expect(screen.getByTestId("run-item-run-pr").getAttribute("data-selected")).toBe("true");
    expect(screen.queryByTestId("sidebar-empty")).toBeNull();
  });

  it("9. FSM events advance the active step and strike count", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-fsm", {}, 1));
    });
    await waitFor(() => expect(screen.getByTestId("run-item-run-fsm")).toBeTruthy());
    expect(screen.getByTestId("fsm-node-1.SENSE").getAttribute("data-status")).toBe("active");

    act(() => {
      MockWebSocket.instances[0].serverSend(
        envelope("TRIAGE_COMPLETE", "run-fsm", { current_step: "2.TRIAGE" }, 2),
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("fsm-node-2.TRIAGE").getAttribute("data-status")).toBe("active"),
    );
    expect(screen.getByTestId("fsm-node-1.SENSE").getAttribute("data-status")).toBe("completed");
    // TRIAGE completion does not fabricate DIAGNOSE/PATCH completion.
    expect(screen.getByTestId("fsm-node-3.DIAGNOSE").getAttribute("data-status")).toBe("pending");

    act(() => {
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_1_FEEDBACK", "run-fsm", { current_step: "5.VERIFY", attempt: 1 }, 3),
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("fsm-node-5.VERIFY").getAttribute("data-status")).toBe("active"),
    );
    expect(screen.getByTestId("strike-label").textContent).toBe("1/3");
  });

  it("11b. RUN_RESOLVED resolves the workspace through the live stream", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-ok", {}, 1));
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_1_FEEDBACK", "run-ok", { current_step: "5.VERIFY", attempt: 1 }, 2),
      );
      MockWebSocket.instances[0].serverSend(
        envelope(
          "RUN_RESOLVED",
          "run-ok",
          { current_step: "5.VERIFY", status: "RESOLVED", attempt: 1 },
          3,
        ),
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("three-strike-loop").getAttribute("data-phase")).toBe("resolved"),
    );
    expect(screen.getByTestId("run-status-run-ok").textContent).toContain("Resolved");
    // Resolved run moves to history without mixing into active.
    expect(screen.getByTestId("historical-run-list").textContent).toContain("PR #7");
    expect(screen.queryByTestId("active-run-list")).toBeNull();
  });

  it("12b. three failures then RUN_HALTED shows terminal failure", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-bad", {}, 1));
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_1_FEEDBACK", "run-bad", { current_step: "5.VERIFY", attempt: 1 }, 2),
      );
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_2_FEEDBACK", "run-bad", { current_step: "5.VERIFY", attempt: 2 }, 3),
      );
      MockWebSocket.instances[0].serverSend(
        envelope("ATTEMPT_3_FEEDBACK", "run-bad", { current_step: "5.VERIFY", attempt: 3 }, 4),
      );
    });
    await waitFor(() => expect(screen.getByTestId("strike-label").textContent).toBe("3/3"));
    act(() => {
      MockWebSocket.instances[0].serverSend(
        envelope(
          "RUN_HALTED",
          "run-bad",
          { current_step: "5.VERIFY", status: "FAILED", attempt: 3 },
          5,
        ),
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("three-strike-loop").getAttribute("data-phase")).toBe("terminal"),
    );
    expect(screen.getByTestId("fsm-node-5.VERIFY").getAttribute("data-status")).toBe("failed");
    expect(screen.queryByTestId("strike-segment-4")).toBeNull();
  });

  it("13. duplicate events neither duplicate rows nor disturb selection", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    const frame = envelope("SENSE_STARTED", "run-dup", {}, 1);
    act(() => {
      MockWebSocket.instances[0].serverSend(frame);
      MockWebSocket.instances[0].serverSend(frame);
      MockWebSocket.instances[0].serverSend(frame);
    });
    await waitFor(() => expect(screen.getByTestId("run-item-run-dup")).toBeTruthy());
    await act(async () => {});
    expect(screen.getAllByTestId("run-item-run-dup")).toHaveLength(1);
    expect(screen.getByTestId("run-item-run-dup").getAttribute("data-selected")).toBe("true");
  });

  it("13b. preserves selection when unrelated telemetry arrives", async () => {
    fetchImpl = async () => [restRow("run-keep", { updated_at: "2026-06-01T00:00:00Z" })];
    renderStreamHarness();
    await waitForOpenSockets(1);
    await waitFor(() => expect(screen.getByTestId("run-item-run-keep")).toBeTruthy());
    fireEvent.click(screen.getByTestId("run-item-run-keep"));
    await waitFor(() =>
      expect(screen.getByTestId("run-item-run-keep").getAttribute("data-selected")).toBe("true"),
    );
    act(() => {
      MockWebSocket.instances[0].serverSend(JSON.stringify({ type: "PONG" }));
      MockWebSocket.instances[0].serverSend(envelope("TELEMETRY_PULSE", "global", {}, 50));
    });
    await act(async () => {});
    expect(screen.getByTestId("run-item-run-keep").getAttribute("data-selected")).toBe("true");
  });

  it("14. missing or malformed telemetry never breaks the UI", async () => {
    renderStreamHarness();
    await waitForOpenSockets(1);
    act(() => {
      MockWebSocket.instances[0].serverSend("not-json{{{");
      MockWebSocket.instances[0].serverSend("[1,2,3]");
      MockWebSocket.instances[0].serverSend("{}");
      MockWebSocket.instances[0].serverSend(JSON.stringify({ event: "SENSE_STARTED" }));
      MockWebSocket.instances[0].serverSend(
        JSON.stringify({ event: "SENSE_STARTED", run_id: "global", state: {} }),
      );
    });
    await act(async () => {});
    expect(screen.getByTestId("sidebar-empty")).toBeTruthy();
    expect(screen.getByTestId("fsm-node-1.SENSE").getAttribute("data-status")).toBe("pending");
  });

  it("page integration uses a single shared socket for sidebar + stepper", async () => {
    fetchImpl = async () => [restRow("run-page")];
    render(<MissionControlPage />);
    await waitForOpenSockets(1);
    await waitFor(() => expect(screen.getByTestId("run-item-run-page")).toBeTruthy());
    expect(screen.getByTestId("fsm-orchestrator-bar")).toBeTruthy();
    // A live webhook arrival focuses the workspace (REST alone does not).
    act(() => {
      MockWebSocket.instances[0].serverSend(envelope("SENSE_STARTED", "run-live", {}, 1));
    });
    await waitFor(() =>
      expect(screen.getByTestId("run-item-run-live").getAttribute("data-selected")).toBe("true"),
    );
    expect(screen.getByTestId("three-strike-loop")).toBeTruthy();
    expect(screen.getByTestId("connection-status").textContent).toContain("open");
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("hook contract exposes the stream surface the UI consumes", async () => {
    const { useMissionControlStream: hook } = await import("@/hooks/useMissionControlStream");
    expect(typeof hook).toBe("function");
    expect(useMissionControlStream).toBe(hook);
  });
});
