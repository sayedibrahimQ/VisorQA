"use client";

import React, { useId, useState } from "react";
import { AlertTriangle, ChevronDown, Inbox, Loader2 } from "lucide-react";
import {
  clampStrikes,
  getRunStatusMeta,
  MAX_STRIKES,
  partitionRuns,
  stageLabel,
  type RunTone,
} from "@/lib/fsmSelectors";
import type { PRRun } from "@/types";
import { cn } from "@/lib/utils";

interface PRRunSidebarProps {
  runs: PRRun[];
  activeRunId: string | null;
  loading: boolean;
  error: string | null;
  connectionStatus: string;
  onSelect: (runId: string) => void;
  className?: string;
}

const TONE_CLASSES: Record<RunTone, string> = {
  neutral: "border-border-subtle text-text-secondary",
  info: "border-neural-pulse/50 text-neural-pulse",
  success: "border-verified-emerald/50 text-verified-emerald",
  danger: "border-defect-crimson/60 text-defect-crimson",
  warning: "border-triage-amber/50 text-triage-amber",
};

const TONE_DOT: Record<RunTone, string> = {
  neutral: "bg-text-muted",
  info: "bg-neural-pulse",
  success: "bg-verified-emerald",
  danger: "bg-defect-crimson",
  warning: "bg-triage-amber",
};

function formatTimestamp(value: string | undefined): string | null {
  if (!value) return null;
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toLocaleString();
}

function RunRow({
  run,
  selected,
  onSelect,
}: {
  run: PRRun;
  selected: boolean;
  onSelect: (runId: string) => void;
}) {
  const meta = getRunStatusMeta(run.status);
  const ts = formatTimestamp(run.updated_at ?? run.created_at);
  const strikes = clampStrikes(run.strikes);
  return (
    <li>
      <button
        type="button"
        data-testid={`run-item-${run.id}`}
        data-selected={selected ? "true" : "false"}
        aria-current={selected ? "true" : undefined}
        aria-label={`PR ${run.pr_number}, ${run.repo_name}, ${meta.label}, stage ${stageLabel(run.current_step)}`}
        onClick={() => onSelect(run.id)}
        className={cn(
          "w-full rounded-md border px-3 py-2 text-left transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
          selected
            ? "border-neural-pulse/60 bg-elevated"
            : "border-border-subtle bg-surface hover:border-border-strong",
        )}
      >
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-[13px] font-medium text-text-primary">
            PR #{run.pr_number}
          </span>
          <span
            data-testid={`run-status-${run.id}`}
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 py-px font-mono text-[10px]",
              TONE_CLASSES[meta.tone],
            )}
          >
            <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", TONE_DOT[meta.tone])} />
            {meta.label}
          </span>
        </span>
        {typeof run.pr_title === "string" && run.pr_title ? (
          <span className="mt-0.5 block truncate text-xs text-text-secondary">
            {run.pr_title}
          </span>
        ) : (
          <span className="mt-0.5 block truncate text-xs italic text-text-muted">
            No title reported
          </span>
        )}
        <span className="mt-0.5 block truncate font-mono text-[11px] text-text-muted">
          {run.repo_name || "—"} · {run.branch || "—"}
        </span>
        <span className="mt-1 flex items-center justify-between gap-2 font-mono text-[10px] text-text-muted">
          <span data-testid={`run-stage-${run.id}`}>{stageLabel(run.current_step)}</span>
          <span data-testid={`run-attempt-${run.id}`} title="Repair attempts used">
            {strikes}/{MAX_STRIKES}
          </span>
        </span>
        <span className="mt-0.5 block font-mono text-[10px] text-text-muted">
          {ts ?? "No activity recorded"}
        </span>
      </button>
    </li>
  );
}

/**
 * Persistent left PR Runs Stream sidebar. Pure view over the shared
 * `useMissionControlStream` snapshot — selection flows through `selectRun`,
 * auto-focus and dedup stay owned by the sync engine.
 */
export function PRRunSidebar({
  runs,
  activeRunId,
  loading,
  error,
  connectionStatus,
  onSelect,
  className,
}: PRRunSidebarProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const { active, historical } = partitionRuns(runs);
  const showLoading = loading && runs.length === 0;
  const showEmpty = !loading && runs.length === 0 && !error;

  const body = (
    <div className="flex min-h-0 flex-1 flex-col">
      {error ? (
        <p
          data-testid="sidebar-error"
          role="alert"
          className="mx-3 mt-3 flex items-start gap-2 rounded-md border border-defect-crimson/50 bg-defect-crimson/[0.07] px-2.5 py-2 text-xs text-defect-crimson"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Stream error: {error}
            <span className="mt-0.5 block font-mono text-[10px] opacity-80">
              state: {connectionStatus}
            </span>
          </span>
        </p>
      ) : null}

      {showLoading ? (
        <p data-testid="sidebar-loading" className="flex items-center gap-2 px-3 py-6 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
          Loading runs…
        </p>
      ) : null}

      {showEmpty ? (
        <div data-testid="sidebar-empty" className="px-3 py-6 text-sm text-text-secondary">
          <Inbox className="h-5 w-5 text-text-muted" />
          <p className="mt-2 font-medium text-text-primary">No PR runs yet</p>
          <p className="mt-0.5 text-xs text-text-muted">
            New webhook runs appear here automatically.
          </p>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {active.length > 0 ? (
          <section aria-label="Active runs">
            <h3 className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
              Active ({active.length})
            </h3>
            <ul data-testid="active-run-list" className="mt-2 space-y-2">
              {active.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  selected={run.id === activeRunId}
                  onSelect={(id) => {
                    onSelect(id);
                    setOpen(false);
                  }}
                />
              ))}
            </ul>
          </section>
        ) : null}

        {historical.length > 0 ? (
          <section aria-label="Run history" className={active.length > 0 ? "mt-5" : undefined}>
            <h3 className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
              History ({historical.length})
            </h3>
            <ul data-testid="historical-run-list" className="mt-2 space-y-2">
              {historical.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  selected={run.id === activeRunId}
                  onSelect={(id) => {
                    onSelect(id);
                    setOpen(false);
                  }}
                />
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  );

  return (
    <div className={cn("min-h-0", className)}>
      <button
        type="button"
        data-testid="sidebar-toggle"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus md:hidden"
      >
        <span>
          PR Runs ({runs.length})
        </span>
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
      </button>
      {/* Mobile: collapsible panel. md+: persistent sidebar. */}
      <aside
        id={listId}
        aria-label="PR runs stream"
        data-testid="pr-run-sidebar"
        data-open={open ? "true" : "false"}
        className={cn(
          "min-h-0 flex-col rounded-md border border-border-subtle bg-surface-subtle md:flex md:h-full",
          open ? "mt-2 flex max-h-[60vh]" : "hidden",
        )}
      >
        <div className="hidden items-baseline justify-between border-b border-border-subtle px-3 py-2.5 md:flex">
          <h2 className="font-display text-sm font-semibold text-text-primary">
            PR Runs
          </h2>
          <span data-testid="sidebar-count" className="font-mono text-[11px] text-text-muted">
            {runs.length} total
          </span>
        </div>
        {body}
      </aside>
    </div>
  );
}
