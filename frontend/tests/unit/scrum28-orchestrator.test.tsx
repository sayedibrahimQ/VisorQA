/**
 * SCRUM-28 component + selector tests (mocked data only in tests).
 * Run: cd frontend && npx vitest run tests/unit/scrum28-orchestrator.test.tsx
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import {
  clampStrikes,
  formatLatency,
  getAttemptState,
  getNodeStates,
  getRunStatusMeta,
  partitionRuns,
} from "@/lib/fsmSelectors";
import { FSMOrchestratorBar } from "@/components/mission-control/FSMOrchestratorBar";
import { PRRunSidebar } from "@/components/mission-control/PRRunSidebar";
import { ThreeStrikeLoop } from "@/components/mission-control/ThreeStrikeLoop";
import { makeRun, stubMatchMedia } from "./scrum28-helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function sidebarProps(runs: ReturnType<typeof makeRun>[], extra = {}) {
  const onSelect = vi.fn();
  return {
    props: {
      runs,
      activeRunId: null as string | null,
      loading: false,
      error: null as string | null,
      connectionStatus: "open",
      onSelect,
      ...extra,
    },
    onSelect,
  };
}

describe("SCRUM-28 FSMOrchestratorBar", () => {
  it("1. renders all five FSM nodes in order with model labels", () => {
    render(<FSMOrchestratorBar run={makeRun()} />);
    expect(screen.getByTestId("fsm-orchestrator-bar")).toBeTruthy();
    const nodes = [
      ["fsm-node-1.SENSE", "Sense", "SAM 3.1"],
      ["fsm-node-2.TRIAGE", "Triage", "Muse Spark"],
      ["fsm-node-3.DIAGNOSE", "Diagnose", "Muse Wonder"],
      ["fsm-node-4.PATCH", "Patch", "Muse Code + HMR"],
      ["fsm-node-5.VERIFY", "Verify & Commit", "SAM 3.1 + GitHub"],
    ] as const;
    for (const [testId, name, model] of nodes) {
      const node = screen.getByTestId(testId);
      expect(node.textContent).toContain(name);
      expect(node.textContent).toContain(model);
    }
    // Step numbers present.
    const bar = screen.getByTestId("fsm-orchestrator-bar");
    expect(bar.textContent).toContain("01");
    expect(bar.textContent).toContain("05");
  });

  it("2. derives correct node status without implying unconfirmed completion", () => {
    // TRIAGE running: SENSE structurally complete, TRIAGE active, rest pending.
    render(<FSMOrchestratorBar run={makeRun({ current_step: "2.TRIAGE" })} />);
    expect(screen.getByTestId("fsm-node-1.SENSE").getAttribute("data-status")).toBe("completed");
    expect(screen.getByTestId("fsm-node-2.TRIAGE").getAttribute("data-status")).toBe("active");
    expect(screen.getByTestId("fsm-node-3.DIAGNOSE").getAttribute("data-status")).toBe("pending");
    expect(screen.getByTestId("fsm-node-4.PATCH").getAttribute("data-status")).toBe("pending");
    expect(screen.getByTestId("fsm-node-5.VERIFY").getAttribute("data-status")).toBe("pending");
    cleanup();

    // VERIFY observed with zero strikes proves nothing about D/P: neutral.
    const states = getNodeStates(makeRun({ current_step: "5.VERIFY", strikes: 0 }));
    expect(states.map((s) => s.status)).toEqual([
      "completed",
      "pending",
      "pending",
      "pending",
      "active",
    ]);

    // Resolved without loop entry: middle nodes skipped, never "completed".
    const early = getNodeStates(
      makeRun({ status: "RESOLVED", current_step: "5.VERIFY", strikes: 0 }),
    );
    expect(early.map((s) => s.status)).toEqual([
      "completed",
      "skipped",
      "skipped",
      "skipped",
      "completed",
    ]);
  });

  it("3. highlights the active node with aria-current and harmony glow", () => {
    render(<FSMOrchestratorBar run={makeRun({ current_step: "2.TRIAGE" })} />);
    const active = screen.getByTestId("fsm-node-2.TRIAGE");
    expect(active.getAttribute("aria-current")).toBe("step");
    expect(active.className).toContain("harmony-glow");
    for (const id of ["fsm-node-1.SENSE", "fsm-node-3.DIAGNOSE"]) {
      const other = screen.getByTestId(id);
      expect(other.getAttribute("aria-current")).toBeNull();
      expect(other.className).not.toContain("harmony-glow");
    }
  });

  it("4. renders latency badges with real measured values", () => {
    render(
      <FSMOrchestratorBar
        run={makeRun({ step_latency_ms: { "1.SENSE": 142, "2.TRIAGE": 87 } })}
      />,
    );
    const badges = screen.getAllByTestId("latency-badge");
    expect(badges).toHaveLength(5);
    const measured = badges.filter((b) => b.getAttribute("data-state") === "measured");
    expect(measured).toHaveLength(2);
    expect(measured.map((b) => b.textContent).sort()).toEqual(["142 ms", "87 ms"]);
    expect(formatLatency(142)).toBe("142 ms");
  });

  it("5. shows a neutral placeholder when latency data is missing", () => {
    render(<FSMOrchestratorBar run={makeRun()} />);
    const badges = screen.getAllByTestId("latency-badge");
    expect(badges).toHaveLength(5);
    for (const badge of badges) {
      expect(badge.getAttribute("data-state")).toBe("unavailable");
      expect(badge.textContent).toBe("—");
    }
    expect(formatLatency(undefined)).toBeNull();
    expect(formatLatency(Number.NaN)).toBeNull();
    expect(formatLatency(-5)).toBeNull();
  });
});

describe("SCRUM-28 PRRunSidebar", () => {
  it("6. separates active and historical runs without mixing status", () => {
    const runs = [
      makeRun({ id: "run-a", status: "RUNNING", pr_number: 1 }),
      makeRun({ id: "run-b", status: "PENDING", pr_number: 2 }),
      makeRun({ id: "run-c", status: "RESOLVED", current_step: "5.VERIFY", strikes: 1, pr_number: 3 }),
      makeRun({ id: "run-d", status: "FAILED", current_step: "5.VERIFY", strikes: 3, pr_number: 4 }),
    ];
    const { props } = sidebarProps(runs, { activeRunId: "run-a" });
    render(<PRRunSidebar {...props} />);
    const activeList = screen.getByTestId("active-run-list");
    const historyList = screen.getByTestId("historical-run-list");
    expect(activeList.querySelectorAll("li")).toHaveLength(2);
    expect(historyList.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByTestId("run-status-run-a").textContent).toContain("Running");
    expect(screen.getByTestId("run-status-run-b").textContent).toContain("Pending");
    expect(screen.getByTestId("run-status-run-c").textContent).toContain("Resolved");
    expect(screen.getByTestId("run-status-run-d").textContent).toContain("Failed");
    // Selected run highlighted.
    expect(screen.getByTestId("run-item-run-a").getAttribute("data-selected")).toBe("true");
    expect(screen.getByTestId("run-item-run-b").getAttribute("data-selected")).toBe("false");
    const { active, historical } = partitionRuns(runs);
    expect(active.map((r) => r.id)).toEqual(["run-a", "run-b"]);
    expect(historical.map((r) => r.id)).toEqual(["run-c", "run-d"]);
  });

  it("6b. renders loading, empty, and connection-error states", () => {
    const loading = sidebarProps([], { loading: true });
    render(<PRRunSidebar {...loading.props} />);
    expect(screen.getByTestId("sidebar-loading")).toBeTruthy();
    cleanup();

    const empty = sidebarProps([]);
    render(<PRRunSidebar {...empty.props} />);
    expect(screen.getByTestId("sidebar-empty")).toBeTruthy();
    cleanup();

    const failed = sidebarProps([], { error: "boom", connectionStatus: "reconnecting" });
    render(<PRRunSidebar {...failed.props} />);
    const alert = screen.getByTestId("sidebar-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toContain("boom");
  });

  it("6c. never fabricates a PR title", () => {
    const { props } = sidebarProps([makeRun({ id: "run-x" })]);
    render(<PRRunSidebar {...props} />);
    expect(screen.getByTestId("run-item-run-x").textContent).toContain("No title reported");
    cleanup();
    const titled = sidebarProps([makeRun({ id: "run-y", pr_title: "Fix banner" })]);
    render(<PRRunSidebar {...titled.props} />);
    expect(screen.getByTestId("run-item-run-y").textContent).toContain("Fix banner");
  });
});

describe("SCRUM-28 ThreeStrikeLoop", () => {
  it("10. visualizes attempts with failed/active/pending distinct", () => {
    render(<ThreeStrikeLoop attempt={getAttemptState(makeRun({ strikes: 2 }))} />);
    const loop = screen.getByTestId("three-strike-loop");
    expect(loop.getAttribute("data-phase")).toBe("in_progress");
    expect(screen.getByTestId("strike-segment-1").getAttribute("data-state")).toBe("failed");
    expect(screen.getByTestId("strike-segment-2").getAttribute("data-state")).toBe("active");
    expect(screen.getByTestId("strike-segment-3").getAttribute("data-state")).toBe("pending");
    expect(screen.getByTestId("strike-label").textContent).toBe("2/3");
    // Exactly three segments — never a fourth.
    expect(screen.getAllByTestId(/strike-segment-/)).toHaveLength(3);
    expect(screen.queryByTestId("strike-segment-4")).toBeNull();
  });

  it("11. shows successful resolution immediately", () => {
    render(
      <ThreeStrikeLoop
        attempt={getAttemptState(makeRun({ status: "RESOLVED", current_step: "5.VERIFY", strikes: 2 }))}
      />,
    );
    expect(screen.getByTestId("three-strike-loop").getAttribute("data-phase")).toBe("resolved");
    expect(screen.getByTestId("strike-segment-1").getAttribute("data-state")).toBe("failed");
    expect(screen.getByTestId("strike-segment-2").getAttribute("data-state")).toBe("passed");
    expect(screen.getByTestId("strike-segment-3").getAttribute("data-state")).toBe("skipped");
    const bar = getNodeStates(makeRun({ status: "RESOLVED", current_step: "5.VERIFY", strikes: 2 }));
    expect(bar.map((s) => s.status)).toEqual([
      "completed",
      "completed",
      "completed",
      "completed",
      "completed",
    ]);
  });

  it("12. shows terminal failure after three attempts", () => {
    render(
      <ThreeStrikeLoop
        attempt={getAttemptState(makeRun({ status: "FAILED", current_step: "5.VERIFY", strikes: 3 }))}
      />,
    );
    const loop = screen.getByTestId("three-strike-loop");
    expect(loop.getAttribute("data-phase")).toBe("terminal");
    for (const n of [1, 2, 3]) {
      expect(screen.getByTestId(`strike-segment-${n}`).getAttribute("data-state")).toBe("failed");
    }
    expect(screen.getByTestId("strike-label").textContent).toBe("3/3");
    expect(screen.getAllByTestId(/strike-segment-/)).toHaveLength(3);
    // Stepper attributes failure to the repair loop, not success.
    const bar = getNodeStates(makeRun({ status: "FAILED", current_step: "5.VERIFY", strikes: 3 }));
    expect(bar.map((s) => s.status)).toEqual([
      "completed",
      "completed",
      "failed",
      "failed",
      "failed",
    ]);
    expect(clampStrikes(99)).toBe(3);
  });
});

describe("SCRUM-28 status metadata", () => {
  it("maps backend statuses including WAITING without color-only signaling", () => {
    expect(getRunStatusMeta("QUEUED")).toEqual({ label: "Waiting", tone: "neutral", historical: false });
    expect(getRunStatusMeta("RUNNING").label).toBe("Running");
    expect(getRunStatusMeta("RESOLVED").historical).toBe(true);
    expect(getRunStatusMeta("FAILED").historical).toBe(true);
    expect(getRunStatusMeta("SOMETHING_NEW").label).toBe("SOMETHING_NEW");
  });
});

describe("SCRUM-28 responsive + reduced motion", () => {
  it("15. sidebar collapses on mobile and stepper scrolls without page overflow", () => {
    const { props } = sidebarProps([makeRun({ id: "run-a" })]);
    render(<PRRunSidebar {...props} />);
    const toggle = screen.getByTestId("sidebar-toggle");
    expect(toggle.className).toContain("md:hidden");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const aside = screen.getByTestId("pr-run-sidebar");
    expect(aside.getAttribute("data-open")).toBe("false");
    expect(aside.className).toContain("hidden");
    expect(aside.className).toContain("md:flex");
    fireEvent.click(toggle);
    expect(screen.getByTestId("sidebar-toggle").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("pr-run-sidebar").getAttribute("data-open")).toBe("true");
    cleanup();

    render(<FSMOrchestratorBar run={makeRun()} />);
    const scroller = screen.getByTestId("fsm-orchestrator-bar").querySelector(".overflow-x-auto");
    expect(scroller).not.toBeNull();
  });

  it("16. disables animated effects under reduced motion", () => {
    stubMatchMedia(true);
    render(
      <div>
        <FSMOrchestratorBar run={makeRun({ current_step: "2.TRIAGE" })} />
        <ThreeStrikeLoop attempt={getAttemptState(makeRun({ strikes: 1 }))} />
      </div>,
    );
    expect(screen.getByTestId("fsm-orchestrator-bar").getAttribute("data-motion")).toBe("reduced");
    expect(screen.getByTestId("three-strike-loop").getAttribute("data-motion")).toBe("reduced");
    expect(screen.queryByTestId("strike-loop-arc")).toBeNull();
    expect(document.querySelector(".harmony-beam")).toBeNull();
    // Status still communicated without animation.
    expect(screen.getByTestId("fsm-node-2.TRIAGE").getAttribute("data-status")).toBe("active");
    expect(screen.getByTestId("strike-segment-1").getAttribute("data-state")).toBe("active");
    cleanup();

    stubMatchMedia(false);
    render(<ThreeStrikeLoop attempt={getAttemptState(makeRun({ strikes: 1 }))} />);
    expect(screen.getByTestId("three-strike-loop").getAttribute("data-motion")).toBe("full");
    expect(screen.queryByTestId("strike-loop-arc")).not.toBeNull();
  });
});
