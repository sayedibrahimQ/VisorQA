"use client";

import React from "react";
import { Check, X } from "lucide-react";
import { MAX_STRIKES, type AttemptState } from "@/lib/fsmSelectors";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";

interface ThreeStrikeLoopProps {
  attempt: AttemptState;
  className?: string;
}

type SegmentState = "failed" | "active" | "passed" | "pending" | "skipped";

function segmentsFor(attempt: AttemptState): SegmentState[] {
  const segs: SegmentState[] = [];
  for (let n = 1; n <= MAX_STRIKES; n += 1) {
    if (attempt.phase === "resolved") {
      if (n < attempt.current) segs.push("failed");
      else if (n === attempt.current) segs.push("passed");
      else segs.push("skipped");
    } else if (attempt.phase === "terminal") {
      segs.push(n <= Math.max(attempt.current, 1) ? "failed" : "skipped");
    } else if (attempt.phase === "in_progress") {
      if (n < attempt.current) segs.push("failed");
      else if (n === attempt.current) segs.push("active");
      else segs.push("pending");
    } else {
      segs.push("pending");
    }
  }
  return segs;
}

function phaseLabel(attempt: AttemptState): string {
  switch (attempt.phase) {
    case "resolved":
      return `Resolved on attempt ${Math.max(attempt.current, 1)} of ${attempt.max}`;
    case "terminal":
      return `Repair failed after ${attempt.max} of ${attempt.max} attempts`;
    case "in_progress":
      return `Attempt ${attempt.current} of ${attempt.max} in progress`;
    default:
      return `Repair loop ready · 0 of ${attempt.max} attempts used`;
  }
}

const SEGMENT_TEXT: Record<SegmentState, string> = {
  failed: "failed",
  active: "active",
  passed: "passed",
  pending: "pending",
  skipped: "not needed",
};

/**
 * Animated three-strike repair loop indicator. Driven only by real FSM
 * attempt data (`strikes` / `attempts` / terminal status). Exactly three
 * segments are ever rendered.
 */
export function ThreeStrikeLoop({ attempt, className }: ThreeStrikeLoopProps) {
  const reducedMotion = usePrefersReducedMotion();
  const segments = segmentsFor(attempt);

  return (
    <div
      data-testid="three-strike-loop"
      data-phase={attempt.phase}
      data-motion={reducedMotion ? "reduced" : "full"}
      role="img"
      aria-label={`Repair loop: ${phaseLabel(attempt)}`}
      className={cn("flex items-center gap-2", className)}
    >
      <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
        Repair
      </span>
      <div className="flex items-center gap-1" aria-hidden="true">
        {segments.map((state, i) => {
          const n = i + 1;
          return (
            <div key={n} className="flex items-center gap-1">
              {i > 0 ? (
                <span
                  className={cn(
                    "h-px w-3",
                    state === "pending" || state === "skipped"
                      ? "bg-border-subtle"
                      : state === "passed"
                        ? "bg-verified-emerald/60"
                        : "bg-defect-crimson/60",
                  )}
                />
              ) : null}
              <span
                data-testid={`strike-segment-${n}`}
                data-state={state}
                title={`Attempt ${n}/3 · ${SEGMENT_TEXT[state]}`}
                className={cn(
                  "relative flex h-6 w-6 items-center justify-center rounded-full border font-mono text-[10px]",
                  state === "failed" &&
                    "border-defect-crimson/70 bg-defect-crimson/10 text-defect-crimson",
                  state === "passed" &&
                    "border-verified-emerald/70 bg-verified-emerald/10 text-verified-emerald",
                  state === "pending" &&
                    "border-border-subtle bg-canvas text-text-muted",
                  state === "skipped" &&
                    "border-border-subtle/60 bg-transparent text-text-muted/50",
                  state === "active" &&
                    "border-triage-amber/80 bg-triage-amber/10 text-triage-amber",
                )}
              >
                {state === "failed" ? (
                  <X className="h-3 w-3" strokeWidth={2.5} />
                ) : state === "passed" ? (
                  <Check className="h-3 w-3" strokeWidth={2.5} />
                ) : (
                  <span>{n}</span>
                )}
                {state === "active" && !reducedMotion ? (
                  <span
                    key={`arc-${attempt.current}`}
                    data-testid="strike-loop-arc"
                    className="strike-loop-arc pointer-events-none absolute inset-[-3px] rounded-full"
                  />
                ) : null}
              </span>
            </div>
          );
        })}
      </div>
      <span
        data-testid="strike-label"
        className="font-mono text-[10px] text-text-secondary"
      >
        {attempt.phase === "idle"
          ? `0/${attempt.max}`
          : `${Math.max(attempt.current, 1)}/${attempt.max}`}
      </span>
      <span className="sr-only">{phaseLabel(attempt)}</span>
    </div>
  );
}
