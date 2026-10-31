"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { Check, Copy, ExternalLink } from "lucide-react";
import type { InspectorData, BuildState } from "@/lib/telemetryDrawer";
import { cn } from "@/lib/utils";

type TabId = "spec" | "diff";

interface ArchitectCoderInspectorProps {
  data: InspectorData;
  /** Real run id for the permalink; never link without one. */
  runId: string | null;
}

const BUILD_META: Record<BuildState, { label: string; classes: string }> = {
  pending: { label: "Build pending", classes: "border-border-subtle text-text-muted" },
  running: { label: "Build running", classes: "border-neural-pulse/50 text-neural-pulse" },
  success: { label: "Build succeeded", classes: "border-verified-emerald/60 text-verified-emerald" },
  failed: { label: "Build failed", classes: "border-defect-crimson/60 text-defect-crimson" },
  unavailable: { label: "Build status unavailable", classes: "border-border-subtle text-text-muted" },
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      data-testid={`copy-${label === "RepairSpec JSON" ? "spec" : "diff"}`}
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
            throw new Error("clipboard unavailable");
          }
          await navigator.clipboard.writeText(text);
          setState("copied");
        } catch {
          setState("failed");
        }
        window.setTimeout(() => setState("idle"), 1500);
      }}
      className="flex items-center gap-1 rounded-sm border border-border-subtle px-1.5 py-1 font-mono text-[10px] text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
    >
      {state === "copied" ? <Check className="h-3 w-3 text-verified-emerald" /> : <Copy className="h-3 w-3" />}
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Unified diff parsing (line numbers from @@ hunks; formatting preserved)
// ---------------------------------------------------------------------------

interface DiffLine {
  kind: "header" | "hunk" | "add" | "del" | "ctx";
  oldNo: number | null;
  newNo: number | null;
  text: string;
}

export function parseDiff(diff: string): DiffLine[] {
  const out: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("---") || raw.startsWith("+++") || raw.startsWith("diff --git") || raw.startsWith("index ")) {
      out.push({ kind: "header", oldNo: null, newNo: null, text: raw });
      continue;
    }
    const hunk = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldNo = Number.parseInt(hunk[1], 10);
      newNo = Number.parseInt(hunk[2], 10);
      out.push({ kind: "hunk", oldNo: null, newNo: null, text: raw });
      continue;
    }
    if (raw.startsWith("+")) {
      out.push({ kind: "add", oldNo: null, newNo, text: raw });
      newNo += 1;
    } else if (raw.startsWith("-")) {
      out.push({ kind: "del", oldNo, newNo: null, text: raw });
      oldNo += 1;
    } else if (raw.startsWith("\\")) {
      out.push({ kind: "header", oldNo: null, newNo: null, text: raw });
    } else {
      out.push({ kind: "ctx", oldNo, newNo, text: raw });
      oldNo += 1;
      newNo += 1;
    }
  }
  return out;
}

const DIFF_LINE_CLASSES: Record<DiffLine["kind"], string> = {
  header: "text-text-muted",
  hunk: "text-neural-pulse bg-surface",
  add: "text-verified-emerald bg-verified-emerald/[0.08]",
  del: "text-defect-crimson bg-defect-crimson/[0.08]",
  ctx: "text-text-secondary",
};

/**
 * Tabbed Architect (Muse Wonder RepairSpec) / Coder (Muse Code diff)
 * inspector. Renders only backend-reported specs, diffs, and build state;
 * a generated diff is never presented as applied or built without the
 * sandbox saying so.
 */
export function ArchitectCoderInspector({ data, runId }: ArchitectCoderInspectorProps) {
  const [tab, setTab] = useState<TabId>("spec");
  const buildMeta = BUILD_META[data.build];
  const specText = useMemo(
    () => (data.repairSpec ? JSON.stringify(data.repairSpec, null, 2) : null),
    [data.repairSpec],
  );
  const diffLines = useMemo(() => (data.diff ? parseDiff(data.diff) : []), [data.diff]);

  return (
    <section aria-label="Architect and coder inspector" data-testid="architect-coder-inspector" className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-text-primary">Architect / Coder</h3>
        {runId ? (
          <Link
            data-testid="run-permalink"
            href={`/runs/${runId}`}
            className="flex items-center gap-1 font-mono text-[11px] text-neural-pulse hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
          >
            /runs/{runId}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </Link>
        ) : (
          <span data-testid="run-permalink-unavailable" className="font-mono text-[11px] text-text-muted">
            Permalink unavailable (no run ID)
          </span>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          data-testid="build-status"
          data-state={data.build}
          className={cn(
            "inline-flex items-center rounded-sm border px-1.5 py-0.5 font-mono text-[10px]",
            buildMeta.classes,
          )}
        >
          {buildMeta.label}
        </span>
        {data.buildDetail ? (
          <span className="font-mono text-[10px] text-text-muted">{data.buildDetail}</span>
        ) : null}
        {data.decision ? (
          <span data-testid="strike-decision" className="font-mono text-[10px] text-text-secondary">
            Decision: {data.decision}
          </span>
        ) : null}
      </div>

      {data.guardrails ? (
        <div data-testid="guardrails" className="mt-2 flex flex-wrap gap-1.5 font-mono text-[10px]">
          {(
            [
              ["BR-2 UI locked", data.guardrails.br2UiLocked],
              ["BR-3 desktop preserved", data.guardrails.br3DesktopPreserved],
              ["BR-4 no hacks", data.guardrails.br4NoHacks],
            ] as const
          ).map(([label, value]) => (
            <span
              key={label}
              className={cn(
                "rounded-sm border px-1.5 py-0.5",
                value === true && "border-verified-emerald/60 text-verified-emerald",
                value === false && "border-defect-crimson/60 text-defect-crimson",
                value === null && "border-border-subtle text-text-muted",
              )}
            >
              {label}: {value === null ? "—" : value ? "pass" : "fail"}
            </span>
          ))}
        </div>
      ) : null}

      {data.integrity ? (
        <dl data-testid="integrity-hashes" className="mt-2 space-y-0.5 font-mono text-[10px] text-text-muted">
          <div className="flex justify-between gap-2">
            <dt>diff sha256</dt>
            <dd className="truncate text-text-secondary">{data.integrity.diffSha256?.slice(0, 16) ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt>target pre</dt>
            <dd className="truncate text-text-secondary">{data.integrity.preSha256?.slice(0, 16) ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt>target post</dt>
            <dd className="truncate text-text-secondary">{data.integrity.postSha256?.slice(0, 16) ?? "—"}</dd>
          </div>
        </dl>
      ) : null}

      <div role="tablist" aria-label="Inspector tabs" className="mt-3 flex gap-1 rounded-sm border border-border-subtle bg-canvas p-0.5">
        <button
          type="button"
          role="tab"
          id="inspector-tab-spec"
          aria-selected={tab === "spec"}
          aria-controls="inspector-panel-spec"
          data-testid="tab-spec"
          onClick={() => setTab("spec")}
          className={cn(
            "flex-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
            tab === "spec" ? "bg-elevated font-semibold text-text-primary" : "text-text-muted hover:text-text-primary",
          )}
        >
          RepairSpec · Wonder
        </button>
        <button
          type="button"
          role="tab"
          id="inspector-tab-diff"
          aria-selected={tab === "diff"}
          aria-controls="inspector-panel-diff"
          data-testid="tab-diff"
          onClick={() => setTab("diff")}
          className={cn(
            "flex-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
            tab === "diff" ? "bg-elevated font-semibold text-text-primary" : "text-text-muted hover:text-text-primary",
          )}
        >
          Diff · Code
        </button>
      </div>

      {tab === "spec" ? (
        <div role="tabpanel" id="inspector-panel-spec" aria-labelledby="inspector-tab-spec" data-testid="panel-spec" className="mt-2">
          {specText ? (
            <div>
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="font-mono text-[10px] text-text-muted">
                  {data.repairSpecSource ?? "RepairSpec"}
                </span>
                <CopyButton text={specText} label="RepairSpec JSON" />
              </div>
              <pre
                data-testid="spec-json"
                className="max-h-80 overflow-auto rounded-md border border-border-subtle bg-canvas p-2.5 font-mono text-[11px] leading-5 text-text-secondary"
              >
                {specText}
              </pre>
            </div>
          ) : (
            <p data-testid="spec-unavailable" className="rounded-md border border-dashed border-border-strong px-3 py-4 text-xs text-text-secondary">
              No RepairSpec reported for this run yet. Node 3 (Muse Wonder) has not stored a
              diagnosis, or the stream has not delivered it.
            </p>
          )}
        </div>
      ) : (
        <div role="tabpanel" id="inspector-panel-diff" aria-labelledby="inspector-tab-diff" data-testid="panel-diff" className="mt-2">
          {data.diff ? (
            <div>
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 font-mono text-[10px] text-text-muted">
                  {data.diffSource ?? "Unified diff"}
                  <span
                    data-testid="diff-applied"
                    className={cn(
                      "rounded-sm border px-1 py-px text-[9px] uppercase tracking-wide",
                      data.diffApplied === true
                        ? "border-verified-emerald/60 text-verified-emerald"
                        : data.diffApplied === false
                          ? "border-triage-amber/60 text-triage-amber"
                          : "border-border-subtle text-text-muted",
                    )}
                  >
                    {data.diffApplied === true
                      ? "Applied"
                      : data.diffApplied === false
                        ? "Generated · not applied"
                        : "Generated · application unknown"}
                  </span>
                </span>
                <CopyButton text={data.diff} label="Unified diff" />
              </div>
              <div
                data-testid="diff-body"
                className="max-h-80 overflow-auto rounded-md border border-border-subtle bg-canvas font-mono text-[11px] leading-5"
              >
                {diffLines.map((line, i) => (
                  <div key={i} data-testid={`diff-line-${line.kind}`} className={cn("flex min-w-max", DIFF_LINE_CLASSES[line.kind])}>
                    <span aria-hidden="true" className="w-10 shrink-0 select-none pr-1 text-right text-text-muted/70">
                      {line.oldNo ?? ""}
                    </span>
                    <span aria-hidden="true" className="w-10 shrink-0 select-none pr-1 text-right text-text-muted/70">
                      {line.newNo ?? ""}
                    </span>
                    <span className="whitespace-pre pr-3">{line.text}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p data-testid="diff-unavailable" className="rounded-md border border-dashed border-border-strong px-3 py-4 text-xs text-text-secondary">
              No unified diff reported for this run yet. Node 4 (Muse Code) has not produced a
              patch, or the stream has not delivered it.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
