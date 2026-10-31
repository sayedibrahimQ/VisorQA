"use client";

import React from "react";
import { AlertTriangle, Check, Clock, Minus, X } from "lucide-react";
import {
  trapState,
  type AttemptTrapSnapshot,
  type TrapKind,
  type TrapState,
  type ViewportTrapMetrics,
} from "@/lib/telemetryDrawer";
import { cn } from "@/lib/utils";

interface MathTrapScorecardProps {
  current: AttemptTrapSnapshot | null;
  best: AttemptTrapSnapshot | null;
  /** True while the run may still produce measurements (Pending vs Unavailable). */
  runActive: boolean;
  /** Baseline (attempt_0, before) snapshot for delta comparison. */
  baseline?: AttemptTrapSnapshot | null;
}

const TRAPS: { kind: TrapKind; label: string; rule: string; digits: number; unit?: string }[] = [
  { kind: "vr", label: "V_r", rule: "fail < 0.85 · pass ≥ 0.98", digits: 3 },
  { kind: "iou", label: "IoU", rule: "defect > 0.05 · pass = 0.00", digits: 3 },
  { kind: "deltaX", label: "Delta_x", rule: "pass ≤ 2px · fail > 2px", digits: 1, unit: "px" },
];

const STATE_META: Record<TrapState, { label: string; classes: string; Icon: typeof Check }> = {
  pass: { label: "Pass", classes: "border-verified-emerald/60 text-verified-emerald", Icon: Check },
  fail: { label: "Fail", classes: "border-defect-crimson/60 text-defect-crimson", Icon: X },
  warning: { label: "Intermediate", classes: "border-triage-amber/60 text-triage-amber", Icon: AlertTriangle },
  pending: { label: "Pending", classes: "border-border-subtle text-text-muted", Icon: Clock },
  unavailable: { label: "Unavailable", classes: "border-border-subtle text-text-muted", Icon: Minus },
};

/** Display-only bar fill (0-100); status never derives from this value. */
function barFill(kind: TrapKind, value: number | null): number {
  if (value === null || !Number.isFinite(value)) return 0;
  if (kind === "vr") return Math.min(100, Math.max(0, value * 100));
  if (kind === "iou") return Math.min(100, Math.max(0, (1 - value / 0.1) * 100));
  return Math.min(100, Math.max(0, (1 - value / 20) * 100));
}

function TrapRow({ kind, label, rule, digits, unit, value, awaiting }: {
  kind: TrapKind;
  label: string;
  rule: string;
  digits: number;
  unit?: string;
  value: number | null;
  awaiting: boolean;
}) {
  const state = trapState(kind, value, awaiting);
  const meta = STATE_META[state];
  const Icon = meta.Icon;
  return (
    <div data-testid={`trap-${kind}`} data-state={state} className="py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-xs text-text-primary">
          {label}
          <span className="ml-1.5 text-[10px] text-text-muted">{rule}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="font-mono text-xs text-text-primary">
            {value === null ? "—" : `${value.toFixed(digits)}${unit ?? ""}`}
          </span>
          <span
            data-testid={`trap-badge-${kind}`}
            className={cn(
              "inline-flex items-center gap-0.5 rounded-sm border px-1 py-px font-mono text-[9px] uppercase tracking-wide",
              meta.classes,
            )}
          >
            <Icon className="h-2.5 w-2.5" strokeWidth={2.5} />
            {meta.label}
          </span>
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`${label} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(barFill(kind, value))}
        className="mt-1 h-1 overflow-hidden rounded-full bg-border-subtle"
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] motion-reduce:transition-none",
            state === "pass" && "bg-verified-emerald",
            state === "fail" && "bg-defect-crimson",
            state === "warning" && "bg-triage-amber",
            (state === "pending" || state === "unavailable") && "bg-text-muted/40",
          )}
          style={{ width: `${barFill(kind, value)}%` }}
        />
      </div>
    </div>
  );
}

function ViewportBlock({ title, metrics, awaiting }: {
  title: string;
  metrics: ViewportTrapMetrics | null;
  awaiting: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{title}</p>
      <div className="divide-y divide-border-subtle/60">
        {TRAPS.map((t) => (
          <TrapRow
            key={t.kind}
            kind={t.kind}
            label={t.label}
            rule={t.rule}
            digits={t.digits}
            unit={t.unit}
            value={metrics === null ? null : t.kind === "vr" ? metrics.vr : t.kind === "iou" ? metrics.iou : metrics.deltaX}
            awaiting={awaiting}
          />
        ))}
      </div>
      {metrics?.passed !== null && metrics?.passed !== undefined ? (
        <p className="mt-1 font-mono text-[10px] text-text-muted">
          Backend viewport verdict: {metrics.passed ? "passed" : "failed"}
        </p>
      ) : null}
      {metrics && metrics.failureReasons.length > 0 ? (
        <ul className="mt-1 space-y-0.5 font-mono text-[10px] text-text-muted">
          {metrics.failureReasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Snapshot({ snapshot, awaiting }: { snapshot: AttemptTrapSnapshot; awaiting: boolean }) {
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-mono text-[11px] font-semibold text-text-secondary">{snapshot.label}</h4>
        <span data-testid="backend-verdict" className="font-mono text-[10px] text-text-muted">
          {snapshot.backendVerdict
            ? `Backend verdict: ${snapshot.backendVerdict}${snapshot.backendPassed !== null ? ` (${snapshot.backendPassed ? "passed" : "failed"})` : ""}`
            : "Backend verdict unavailable"}
        </span>
      </div>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <ViewportBlock title="Mobile 375px" metrics={snapshot.mobile} awaiting={awaiting} />
        <ViewportBlock title="Desktop 1440px" metrics={snapshot.desktop} awaiting={awaiting} />
      </div>
    </div>
  );
}

/**
 * Math-trap scorecard: V_r / IoU / Delta_x against the exact backend
 * thresholds, evaluated on raw values. The overall verdict line is the
 * backend's own `verification_status`; no frontend verdict is computed.
 */
export function MathTrapScorecard({ current, best, runActive, baseline = null }: MathTrapScorecardProps) {
  return (
    <section aria-label="Math trap scorecard" data-testid="math-trap-scorecard" className="min-w-0">
      <h3 className="font-display text-sm font-semibold text-text-primary">Math Traps</h3>
      {current ? (
        <div className="mt-2 space-y-4">
          {baseline ? (
            <div data-testid="scorecard-baseline" className="border-b border-border-subtle pb-3 opacity-80">
              <Snapshot snapshot={baseline} awaiting={false} />
            </div>
          ) : null}
          <Snapshot snapshot={current} awaiting={runActive} />
          {best ? (
            <div className="border-t border-border-subtle pt-3">
              <Snapshot snapshot={best} awaiting={false} />
            </div>
          ) : null}
        </div>
      ) : (
        <div data-testid="scorecard-empty" className="mt-2">
          <p className="text-xs text-text-secondary">No verification measurements yet.</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            <ViewportBlock title="Mobile 375px" metrics={null} awaiting={runActive} />
            <ViewportBlock title="Desktop 1440px" metrics={null} awaiting={runActive} />
          </div>
          <p data-testid="backend-verdict" className="mt-2 font-mono text-[10px] text-text-muted">
            Backend verdict unavailable
          </p>
        </div>
      )}
    </section>
  );
}
