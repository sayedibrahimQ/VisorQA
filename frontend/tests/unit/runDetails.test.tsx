/**
 * Workstreams 2-4 live hydration tests (mocked fetch only).
 * Run: cd frontend && npx vitest run tests/unit/runDetails.test.tsx
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import {
  attemptOptions,
  inspectorForAttempt,
  resolveArtifactUrl,
  scorecardForAttempt,
  stageForAttempt,
  triageForRun,
} from "@/lib/runDetails";
import { useRunDetails } from "@/hooks/useRunDetails";
import type { RunDetails } from "@/types";

function fixtureDetails(): RunDetails {
  const viewportSummary = (vr: number, passed: boolean | null) => ({
    viewport: "mobile",
    width: 375,
    height: 812,
    v_r: vr,
    iou: 0,
    delta_x: 0,
    health_score: null,
    valid: true,
    passed,
    failure_reasons: [],
  });
  const triage = {
    lca_element_id: "visor-el-04",
    lca_dom: {},
    hierarchy: [
      {
        ancestor_chain: [
          { tag: "main" },
          { tag: "form", react_hint: "CheckoutForm", "data-visor-el-id": "visor-el-04" },
        ],
      },
    ],
    candidate_files: ["a.tsx", "b.tsx", "c.tsx", "d.tsx"],
    target_files: ["src/components/CheckoutPage.tsx"],
    target_file: "src/components/CheckoutPage.tsx",
    locked_shared_ui_globs: ["src/components/ui/*"],
    triage_status: "resolved",
    triage_confidence: 0.87,
    triage_summary: "LCA CheckoutForm",
    rejected_targets: [{ path: "src/components/ui/Button.tsx", reason: "protected_shared_ui" }],
    token_reduction_ratio: 0.75,
  };
  const patch = {
    unified_diff: "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
    diff_sha256: "d".repeat(64),
    target_file: "src/components/CheckoutPage.tsx",
    target_pre_sha256: "a".repeat(64),
    target_post_sha256: "b".repeat(64),
    guardrails: { br2_ui_locked: true, br3_desktop_preserved: true, br4_no_hacks: true },
    sandbox_provider: "local",
    sandbox_phase: "hmr_observed",
    hmr_status: "observed",
    hmr_latency_ms: 812,
    build_status: "success",
    applied_cleanly: true,
  };
  const attempt = (n: number, vr: number, passed: boolean | null, decision: string | null) => ({
    attempt_number: n,
    kind: n === 0 ? "baseline" : "strike",
    screenshots: {
      mobile: { before_url: "/api/artifacts/run-1/attempt_0/375x812/screenshot_before.png", after_url: n > 0 ? `/api/artifacts/run-1/attempt_${n}/375x812/screenshot_after.png` : null },
      desktop: { before_url: "/api/artifacts/run-1/attempt_0/1440x900/screenshot_before.png", after_url: null },
    },
    sam_masks: {
      mobile: { mask_url: "/api/artifacts/run-1/attempt_0/375x812/sam_mask.png", overlay_url: null },
      desktop: { mask_url: null, overlay_url: null },
    },
    b_dom_boxes: {
      "visor-el-04": { x: 12, y: 80, width: 350, height: 60, cx: 187, cy: 110 },
    },
    element_metrics: [
      { visor_el_id: "visor-el-04", v_r: vr, iou: 0, delta_x: 0, defect_type: "OCCLUSION", viewport: "375px", trap_fired: vr < 0.85 ? "vr_below_0.85" : null },
    ],
    viewport_summary: { mobile: viewportSummary(vr, passed), desktop: { ...viewportSummary(vr, passed), viewport: "desktop", width: 1440, height: 900 } },
    triage_metadata: triage,
    repair_spec: { root_cause: "banner overlap", target_file: "src/components/CheckoutPage.tsx" },
    patch_telemetry: patch,
    verification_feedback: {
      dual_viewport_passed: passed,
      verification_status: passed ? "verification_passed" : "verification_failed",
      strike_decision: decision,
      failure_reasons: [],
    },
    unified_diff: patch.unified_diff,
    passed,
  });
  return {
    id: "run-1",
    pr_number: 101,
    repo_name: "org/repo",
    branch: "fix/x",
    commit_sha: "abc",
    status: "RESOLVED",
    current_step: "5.VERIFY",
    strikes: 1,
    attempts: [attempt(0, 0.62, null, null), attempt(1, 0.99, true, "RESOLVED")],
    triage_metadata: triage,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("runDetails adapters (Workstreams 3-4)", () => {
  it("resolves artifact URLs against the API base", () => {
    expect(resolveArtifactUrl("/api/artifacts/x.png", "http://localhost:8000")).toBe(
      "http://localhost:8000/api/artifacts/x.png",
    );
    expect(resolveArtifactUrl("https://cdn.example/x.png", "http://localhost:8000")).toBe(
      "https://cdn.example/x.png",
    );
    expect(resolveArtifactUrl(null, "http://localhost:8000")).toBeNull();
  });

  it("binds stage panels to the selected attempt with boxes, metrics, masks", () => {
    const stage = stageForAttempt(fixtureDetails(), 1, "http://localhost:8000");
    expect(stage.mobile.beforeUrl).toContain("/api/artifacts/run-1/attempt_0/375x812/screenshot_before.png");
    expect(stage.mobile.afterUrl).toContain("attempt_1");
    const el = stage.mobile.elements.find((e) => e.id === "visor-el-04");
    expect(el?.box).toEqual({ x: 12, y: 80, width: 350, height: 60 });
    expect(el?.vr).toBe(0.99);
    expect(el?.masks[0]?.kind).toBe("image");
    expect(stage.sandboxProvider).toBe("local");
    expect(stage.hmrLatencyMs).toBe(812);
    expect(attemptOptions(fixtureDetails()).map((a) => a.label)).toEqual(["Baseline", "Strike 1"]);
  });

  it("binds scorecard baseline vs selected strike without recomputing verdicts", () => {
    const { current, baseline } = scorecardForAttempt(fixtureDetails(), 1);
    expect(baseline?.mobile?.vr).toBe(0.62);
    expect(current.mobile?.vr).toBe(0.99);
    expect(current.backendVerdict).toBe("verification_passed");
  });

  it("binds triage tree and inspector decision, guardrails, hashes", () => {
    const triage = triageForRun(fixtureDetails());
    expect(triage.lcaElementId).toBe("visor-el-04");
    expect(triage.tokenReductionRatio).toBe(0.75);
    expect(triage.lcaChain.length).toBe(1);
    expect(triage.rejected[0].reason).toBe("protected_shared_ui");

    const inspector = inspectorForAttempt(fixtureDetails(), 1);
    expect(inspector.decision).toBe("RESOLVED");
    expect(inspector.guardrails?.br2UiLocked).toBe(true);
    expect(inspector.integrity?.preSha256).toBe("a".repeat(64));
    expect(inspector.build).toBe("success");
    expect(inspector.diffApplied).toBe(true);
  });
});

describe("useRunDetails stale guard (Workstream 2)", () => {
  it("never lets an older in-flight response overwrite newer run state", async () => {
    let resolveSlow!: (v: unknown) => void;
    const slow = new Promise((res) => {
      resolveSlow = res as (v: unknown) => void;
    });
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("run-slow")) {
        return slow.then(() => ({ ok: true, json: async () => ({ ...fixtureDetails(), id: "run-slow" }) }));
      }
      return Promise.resolve({ ok: true, json: async () => ({ ...fixtureDetails(), id: "run-fast" }) });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => useRunDetails(id, { apiBase: "http://api.test" }),
      { initialProps: { id: "run-slow" } },
    );
    rerender({ id: "run-fast" });
    await waitFor(() => expect(result.current.details?.id).toBe("run-fast"));
    resolveSlow(null);
    await waitFor(() => expect(result.current.details?.id).toBe("run-fast"));
    expect(result.current.details?.id).toBe("run-fast");
  });

  it("refetches when the live key changes (terminal WS transition)", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => fixtureDetails() }));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = renderHook(
      ({ liveKey }: { liveKey: string }) =>
        useRunDetails("run-1", { apiBase: "http://api.test", liveKey }),
      { initialProps: { liveKey: "RUNNING:0" } },
    );
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(1));
    rerender({ liveKey: "RESOLVED:1" });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));
  });
});
