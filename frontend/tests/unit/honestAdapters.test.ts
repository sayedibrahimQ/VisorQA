/**
 * Honest adapters: no fabricated elements, metrics, HMR latency, or
 * guardrail verdicts when the backend measured nothing.
 * Run: cd frontend && npx vitest run tests/unit/honestAdapters.test.ts
 */
import { describe, expect, it } from "vitest";

import { inspectorForAttempt, stageForAttempt } from "@/lib/runDetails";
import type { RunDetails } from "@/types";

function emptyDetails(): RunDetails {
  return {
    id: "run-honest",
    pr_number: 1,
    repo_name: "sayedibrahimQ/aether-hardware",
    repo_full_name: "sayedibrahimQ/aether-hardware",
    branch: "feat/mobile-promo-banner",
    commit_sha: "abc123",
    status: "RUNNING",
    current_step: "1.SENSE",
    strikes: 0,
    max_attempts: 3,
    anomalies_count: 0,
    anomalies: [],
    target_files: [],
    verification_status: "",
    is_resolved: false,
    best_score: null,
    triage_metadata: null,
    attempts: [
      {
        attempt_number: 0,
        kind: "baseline",
        screenshots: {
          mobile: { before_url: null, after_url: null },
          desktop: { before_url: null, after_url: null },
        },
        sam_masks: {
          mobile: { mask_url: null, overlay_url: null },
          desktop: { mask_url: null, overlay_url: null },
        },
        b_dom_boxes: {},
        element_metrics: [],
        viewport_summary: {
          mobile: {
            viewport: "mobile", width: 375, height: 812, v_r: null, iou: null,
            delta_x: null, health_score: null, valid: false, passed: null,
            failure_reasons: ["mobile: missing viewport metrics"], screenshot_ref: null,
          },
          desktop: {
            viewport: "desktop", width: 1440, height: 900, v_r: null, iou: null,
            delta_x: null, health_score: null, valid: false, passed: null,
            failure_reasons: ["desktop: missing viewport metrics"], screenshot_ref: null,
          },
        },
        triage_metadata: null,
        repair_spec: null,
        patch_telemetry: null,
        verification_feedback: {
          dual_viewport_passed: null, verification_status: null,
          strike_decision: null, failure_reasons: [],
          github: {
            publication_status: "not_attempted", commit_pushed: false,
            commit_sha: null, review_comment_posted: false,
          },
        },
        unified_diff: null,
        passed: null,
      },
    ],
    artifacts: [],
    created_at: null,
    updated_at: null,
  } as unknown as RunDetails;
}

describe("honest run-details adapters", () => {
  it("invents no element when the attempt measured nothing", () => {
    const stage = stageForAttempt(emptyDetails(), 0, "");
    expect(stage.mobile.elements).toEqual([]);
    expect(stage.desktop.elements).toEqual([]);
    expect(stage.mobile.beforeUrl).toBeNull();
    expect(stage.mobile.verification?.vr ?? null).toBeNull();
  });

  it("invents no HMR latency, provider, or guardrails", () => {
    const stage = stageForAttempt(emptyDetails(), 0, "");
    expect(stage.hmrLatencyMs).toBeNull();
    expect(stage.sandboxProvider).toBeNull();

    const inspector = inspectorForAttempt(emptyDetails(), 0);
    expect(inspector.build).toBe("unavailable");
    expect(inspector.buildDetail).toBeNull();
    expect(inspector.guardrails).toBeNull();
    expect(inspector.decision).toBeNull();
    expect(inspector.diffApplied).toBeNull();
  });
});
