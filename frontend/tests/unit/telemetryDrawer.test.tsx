/**
 * Right telemetry drawer tests (mocked fixtures only).
 * Run: cd frontend && npx vitest run tests/unit/telemetryDrawer.test.tsx
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { MathTrapScorecard } from "@/components/mission-control/MathTrapScorecard";
import { LCATriageTree } from "@/components/mission-control/LCATriageTree";
import {
  ArchitectCoderInspector,
  parseDiff,
} from "@/components/mission-control/ArchitectCoderInspector";
import {
  deriveBuild,
  getInspector,
  getScorecard,
  getTriage,
  trapState,
} from "@/lib/telemetryDrawer";
import { makeRun } from "./scrum28-helpers";
import type { PRRun, SelfHealingAttempt } from "@/types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function attempt(n: number, overrides: Partial<SelfHealingAttempt> = {}): SelfHealingAttempt {
  return {
    attempt_number: n,
    passed: false,
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function measuredAttempt(n: number, passed: boolean): SelfHealingAttempt {
  return attempt(n, {
    passed,
    verification_status: passed ? "verification_passed" : "verification_failed",
    viewport_metrics: {
      mobile: { v_r: passed ? 0.99 : 0.62, iou: passed ? 0 : 0.0, delta_x: passed ? 0.5 : 0, valid: true, passed },
      desktop: { v_r: passed ? 1.0 : 0.91, iou: 0, delta_x: 0, valid: true, passed },
    },
  });
}

describe("MathTrapScorecard thresholds", () => {
  it("evaluates traps on raw values with no pre-rounding", () => {
    expect(trapState("vr", 0.98, false)).toBe("pass");
    expect(trapState("vr", 0.9799, false)).toBe("warning");
    expect(trapState("vr", 0.85, false)).toBe("warning");
    expect(trapState("vr", 0.8499, false)).toBe("fail");
    expect(trapState("iou", 0, false)).toBe("pass");
    expect(trapState("iou", 0.03, false)).toBe("warning");
    expect(trapState("iou", 0.0500001, false)).toBe("fail");
    expect(trapState("deltaX", 2, false)).toBe("pass");
    expect(trapState("deltaX", 2.0001, false)).toBe("fail");
    expect(trapState("vr", null, true)).toBe("pending");
    expect(trapState("vr", null, false)).toBe("unavailable");
    expect(trapState("iou", Number.NaN, false)).toBe("unavailable");
  });

  it("renders pass, warning, and fail states with values and thresholds", () => {
    const run = makeRun({ attempts: [measuredAttempt(1, false)] });
    const data = getScorecard(run);
    render(<MathTrapScorecard current={data.current} best={data.best} runActive={false} />);
    // Mobile V_r 0.62 -> fail; desktop V_r 0.91 -> warning (never Pass).
    const traps = screen.getAllByTestId("trap-vr");
    expect(traps.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByTestId("trap-badge-vr").map((b) => b.textContent)).toContain("Fail");
    expect(screen.getAllByTestId("trap-badge-vr").map((b) => b.textContent)).toContain("Intermediate");
    expect(screen.getByTestId("math-trap-scorecard").textContent).toContain("0.620");
    expect(screen.getByTestId("math-trap-scorecard").textContent).toContain("0.910");
  });

  it("never shows Pass for IoU between 0.00 and 0.05", () => {
    const run = makeRun({
      attempts: [
        attempt(1, {
          verification_status: "verification_failed",
          viewport_metrics: {
            mobile: { v_r: 0.99, iou: 0.04, delta_x: 1, valid: true, passed: false },
            desktop: { v_r: 0.99, iou: 0.04, delta_x: 1, valid: true, passed: false },
          },
        }),
      ],
    });
    render(<MathTrapScorecard {...getScorecard(run)} runActive={false} />);
    const badges = screen.getAllByTestId("trap-badge-iou").map((b) => b.textContent);
    expect(badges).toEqual(["Intermediate", "Intermediate"]);
  });

  it("shows Pending while active and Unavailable when finished without measurements", () => {
    render(<MathTrapScorecard current={null} best={null} runActive />);
    expect(screen.getByTestId("scorecard-empty")).toBeTruthy();
    expect(screen.getAllByTestId("trap-badge-vr").map((b) => b.textContent)).toEqual(["Pending", "Pending"]);
    cleanup();
    render(<MathTrapScorecard current={null} best={null} runActive={false} />);
    expect(screen.getAllByTestId("trap-badge-vr").map((b) => b.textContent)).toEqual([
      "Unavailable",
      "Unavailable",
    ]);
  });

  it("uses the backend verdict verbatim and distinguishes current from best", () => {
    const run = makeRun({
      attempts: [measuredAttempt(1, true), measuredAttempt(2, false)],
    });
    const data = getScorecard(run);
    expect(data.current?.label).toContain("latest");
    expect(data.best?.label).toContain("best (passed)");
    render(<MathTrapScorecard {...data} runActive={false} />);
    const verdicts = screen.getAllByTestId("backend-verdict").map((v) => v.textContent);
    expect(verdicts[0]).toContain("verification_failed");
    expect(verdicts[0]).not.toContain("PASSED");
    expect(verdicts[1]).toContain("verification_passed");
    expect(screen.getByTestId("math-trap-scorecard").textContent).toContain("Attempt 1 · best (passed)");
  });

  it("does not duplicate legacy aggregate metrics onto both viewports", () => {
    const run = makeRun({
      attempts: [attempt(1, { verified_vr: 0.62, verified_iou: 0.0, verification_status: "verification_failed" })],
    });
    const data = getScorecard(run);
    expect(data.current?.mobile).toBeNull();
    expect(data.current?.desktop).toBeNull();
    render(<MathTrapScorecard {...data} runActive={false} />);
    expect(screen.getByTestId("math-trap-scorecard").textContent).not.toContain("0.620");
  });
});

describe("LCATriageTree", () => {
  function triageRun(): PRRun {
    return makeRun({
      repair_spec: {
        lca_element_id: "visor-el-04",
        triage_summary: "LCA is CheckoutForm: lowest common ancestor of visor-el-04 and visor-el-09.",
        triage_confidence: 0.87,
        triage_status: "resolved",
        target_files: ["src/components/CheckoutPage.tsx"],
        triage_rejected_targets: [
          { path: "src/components/ui/Button.tsx", reason: "protected_shared_ui" },
          { path: "../etc/passwd", reason: "path_traversal" },
        ],
        hierarchy: [
          {
            ancestor_chain: [
              { tag: "html" },
              { tag: "body" },
              { tag: "main" },
              { tag: "div", react_hint: "CheckoutPage" },
              { tag: "form", react_hint: "CheckoutForm", "data-visor-el-id": "visor-el-04" },
            ],
          },
        ],
      },
    });
  }

  it("renders the real ancestor chain with the LCA highlighted", () => {
    const triage = getTriage(triageRun());
    render(<LCATriageTree triage={triage} />);
    const nodes = screen.getAllByTestId("lca-node");
    expect(nodes.length).toBe(5);
    expect(screen.getByTestId("lca-triage-tree").textContent).toContain("CheckoutForm");
    const lca = nodes.find((n) => n.getAttribute("data-lca") === "true");
    expect(lca?.textContent).toContain("visor-el-04");
    expect(screen.getByTestId("lca-visor-id").textContent).toBe("visor-el-04");
    expect(screen.getByTestId("lca-reason").textContent).toContain("lowest common ancestor");
  });

  it("labels targets and BR-2 protected decisions distinctly", () => {
    render(<LCATriageTree triage={getTriage(triageRun())} />);
    const target = screen.getByTestId("lca-target");
    expect(target.textContent).toContain("[Target File]");
    expect(target.textContent).toContain("CheckoutPage.tsx");
    const rejected = screen.getAllByTestId("lca-rejected");
    expect(rejected[0].textContent).toContain("[Protected Shared UI]");
    expect(rejected[0].textContent).toContain("Protected shared UI (BR-2)");
    expect(rejected[1].textContent).toContain("Path traversal");
  });

  it("never labels a protected file as a repair target", () => {
    const run = makeRun({ repair_spec: { target_files: ["src/components/ui/Button.tsx"] } });
    render(<LCATriageTree triage={getTriage(run)} />);
    const row = screen.getByTestId("lca-target");
    expect(row.getAttribute("data-protected")).toBe("true");
    expect(row.textContent).toContain("[Protected Shared UI]");
    expect(row.textContent).not.toContain("[Target File]");
  });

  it("shows a clear empty state without fabricating ancestry", () => {
    render(<LCATriageTree triage={getTriage(makeRun())} />);
    expect(screen.getByTestId("lca-empty")).toBeTruthy();
    expect(screen.queryAllByTestId("lca-node")).toHaveLength(0);
  });
});

describe("ArchitectCoderInspector", () => {
  const DIFF = [
    "--- a/src/components/CheckoutPage.tsx",
    "+++ b/src/components/CheckoutPage.tsx",
    "@@ -10,3 +10,3 @@",
    " ctx line",
    "-position: fixed;",
    "+position: sticky;",
    " ctx tail",
  ].join("\n");

  const SPEC = {
    root_cause: "Fixed promo banner occludes checkout button",
    affected_selectors: [".promo-banner"],
    target_file: "src/components/CheckoutPage.tsx",
    css_strategy: "position: sticky",
    desktop_preservation_constraints: ["keep 1440px layout"],
    forbidden_hacks: ["!important"],
  };

  function inspectorRun(): PRRun {
    return makeRun({
      current_step: "5.VERIFY",
      attempts: [
        attempt(1, {
          repair_spec: SPEC,
          unified_diff: DIFF,
          passed: false,
          verification_status: "verification_failed",
        }),
      ],
      sandbox: { last_patch_phase: "hmr_observed", last_hmr_status: "observed", server_state: "running" },
    });
  }

  it("shows the actual RepairSpec JSON formatted, with copy support", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<ArchitectCoderInspector data={getInspector(inspectorRun())} runId="run-1" />);
    const json = screen.getByTestId("spec-json");
    expect(json.textContent).toContain('"root_cause": "Fixed promo banner occludes checkout button"');
    expect(json.textContent).toContain('"css_strategy": "position: sticky"');
    fireEvent.click(screen.getByTestId("copy-spec"));
    await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0][0]).toContain("root_cause");
    cleanup();
    render(<ArchitectCoderInspector data={getInspector(makeRun())} runId="run-2" />);
    expect(screen.getByTestId("spec-unavailable")).toBeTruthy();
  });

  it("renders the diff with added/removed lines and real line numbers", () => {
    render(<ArchitectCoderInspector data={getInspector(inspectorRun())} runId="run-1" />);
    fireEvent.click(screen.getByTestId("tab-diff"));
    const body = screen.getByTestId("diff-body");
    expect(body.textContent).toContain("position: sticky;");
    const added = screen.getAllByTestId("diff-line-add");
    const removed = screen.getAllByTestId("diff-line-del");
    expect(added).toHaveLength(1);
    expect(removed).toHaveLength(1);
    expect(added[0].className).toContain("bg-verified-emerald");
    expect(removed[0].className).toContain("bg-defect-crimson");
    // Hunk @@ -10,3 +10,3 @@: removed line is old 11, added line is new 11.
    expect(removed[0].textContent).toContain("11");
    expect(added[0].textContent).toContain("11");
    const lines = parseDiff(DIFF);
    expect(lines.find((l) => l.kind === "del")?.oldNo).toBe(11);
    expect(lines.find((l) => l.kind === "add")?.newNo).toBe(11);
    cleanup();
    render(<ArchitectCoderInspector data={getInspector(makeRun())} runId="run-2" />);
    fireEvent.click(screen.getByTestId("tab-diff"));
    expect(screen.getByTestId("diff-unavailable")).toBeTruthy();
  });

  it("distinguishes generated diffs from applied ones and never fakes build success", () => {
    // Patch exists, sandbox silent: no success claim, application unknown.
    const bare = getInspector(makeRun({ current_patch: DIFF }));
    expect(bare.build).toBe("unavailable");
    expect(bare.diffApplied).toBeNull();
    render(<ArchitectCoderInspector data={bare} runId="run-1" />);
    fireEvent.click(screen.getByTestId("tab-diff"));
    expect(screen.getByTestId("diff-applied").textContent).toBe("Generated · application unknown");
    expect(screen.getByTestId("build-status").textContent).toContain("unavailable");
    cleanup();

    // Sandbox reports HMR observed: applied + build success.
    render(<ArchitectCoderInspector data={getInspector(inspectorRun())} runId="run-1" />);
    fireEvent.click(screen.getByTestId("tab-diff"));
    expect(screen.getByTestId("diff-applied").textContent).toBe("Applied");
    expect(screen.getByTestId("build-status").getAttribute("data-state")).toBe("success");
  });

  it("maps sandbox build states from the existing contract", () => {
    expect(deriveBuild(makeRun({ sandbox: { last_hmr_status: "compile_failed" } })).build).toBe("failed");
    expect(deriveBuild(makeRun({ sandbox: { last_patch_phase: "hmr_observed" } })).build).toBe("success");
    expect(deriveBuild(makeRun({ sandbox: { last_patch_phase: "compilation_succeeded" } })).build).toBe("success");
    expect(deriveBuild(makeRun({ sandbox: { last_patch_phase: "patch_applied" } })).build).toBe("running");
    expect(deriveBuild(makeRun({ sandbox: { last_patch_phase: "none" } })).build).toBe("pending");
    expect(deriveBuild(makeRun()).build).toBe("unavailable");
  });

  it("links to the existing /runs/[runId] route only with a real run id", () => {
    render(<ArchitectCoderInspector data={getInspector(inspectorRun())} runId="run-99" />);
    const link = screen.getByTestId("run-permalink");
    expect(link.getAttribute("href")).toBe("/runs/run-99");
    cleanup();
    render(<ArchitectCoderInspector data={getInspector(makeRun())} runId={null} />);
    expect(screen.queryByTestId("run-permalink")).toBeNull();
    expect(screen.getByTestId("run-permalink-unavailable")).toBeTruthy();
  });
});
