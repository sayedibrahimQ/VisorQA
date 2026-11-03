"use client";

import React from "react";
import { Check, Loader2, Minus, X } from "lucide-react";
import {
  getNodeStates,
  type FSMNodeState,
  type NodeStatus,
} from "@/lib/fsmSelectors";
import type { PRRun } from "@/types";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";
import { LatencyBadge } from "./LatencyBadge";

interface FSMOrchestratorBarProps {
  run: PRRun | null;
  className?: string;
}

const STATUS_LABEL: Record<NodeStatus, string> = {
  pending: "PENDING",
  active: "RUNNING...",
  completed: "DONE",
  failed: "FAILED",
  skipped: "SKIPPED",
};

function StatusIcon({ status }: { status: NodeStatus }) {
  switch (status) {
    case "active":
      return (
        <Loader2
          data-testid="node-status-icon"
          className="h-3.5 w-3.5 animate-spin text-laser-cyan motion-reduce:animate-none"
        />
      );
    case "completed":
      return (
        <Check
          data-testid="node-status-icon"
          className="h-3.5 w-3.5 text-verified-emerald"
          strokeWidth={2.5}
        />
      );
    case "failed":
      return (
        <X
          data-testid="node-status-icon"
          className="h-3.5 w-3.5 text-defect-crimson"
          strokeWidth={2.5}
        />
      );
    case "skipped":
      return (
        <Minus
          data-testid="node-status-icon"
          className="h-3.5 w-3.5 text-text-muted"
        />
      );
    default:
      return (
        <span
          data-testid="node-status-icon"
          className="h-1.5 w-1.5 rounded-full bg-text-muted/50"
        />
      );
  }
}

function nodeClasses(status: NodeStatus): string {
  switch (status) {
    case "active":
      return "harmony-glow border-laser-cyan/90 shadow-[0_0_14px_rgba(0,242,254,0.35)] animate-pulse ring-1 ring-triage-amber/60 bg-elevated";
    case "completed":
      return "border-verified-emerald/50 bg-surface shadow-[0_0_8px_rgba(16,185,129,0.15)] transition-colors duration-500";
    case "failed":
      return "border-defect-crimson/70 bg-defect-crimson/[0.07]";
    case "skipped":
      return "border-border-subtle/50 bg-transparent opacity-60";
    default:
      return "border-border-subtle bg-surface/60";
  }
}

function NodeCard({ node, reducedMotion }: { node: FSMNodeState; reducedMotion: boolean }) {
  const isActive = node.status === "active";
  return (
    <div
      data-testid={`fsm-node-${node.key}`}
      data-status={node.status}
      aria-current={isActive ? "step" : undefined}
      aria-label={`Step ${node.step}: ${node.name}, ${STATUS_LABEL[node.status]}`}
      className={cn(
        "relative min-w-[128px] flex-1 rounded-md border px-2.5 py-2 transition-all duration-300",
        nodeClasses(node.status),
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] text-text-muted">
          {String(node.step).padStart(2, "0")}
        </span>
        <StatusIcon status={node.status} />
      </div>
      <div className="mt-0.5 truncate font-display text-[13px] font-semibold leading-5 text-text-primary">
        {node.name}
      </div>
      <div className="truncate font-mono text-[10px] leading-4 text-text-muted">
        {node.model}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-1.5">
        <span
          className={cn(
            "font-mono text-[10px] uppercase tracking-wide",
            node.status === "active" && "text-laser-cyan font-bold animate-pulse",
            node.status === "completed" && "text-verified-emerald font-semibold",
            node.status === "failed" && "text-defect-crimson font-semibold",
            node.status === "skipped" && "text-text-muted",
            node.status === "pending" && "text-text-muted",
          )}
        >
          {STATUS_LABEL[node.status]}
        </span>
        <LatencyBadge ms={node.latencyMs} nodeName={node.name} />
      </div>
      {isActive && !reducedMotion ? (
        <span aria-hidden="true" className="harmony-beam pointer-events-none absolute inset-0 rounded-md" />
      ) : null}
    </div>
  );
}

/**
 * Top five-node deterministic FSM stepper.
 * Bound 1:1 to real backend stage execution (01 Sense .. 05 Verify & Commit).
 */
export function FSMOrchestratorBar({ run, className }: FSMOrchestratorBarProps) {
  const reducedMotion = usePrefersReducedMotion();
  const nodes = getNodeStates(run);

  return (
    <section
      aria-label="Pipeline progress"
      data-testid="fsm-orchestrator-bar"
      data-motion={reducedMotion ? "reduced" : "full"}
      className={cn("min-w-0", className)}
    >
      <div className="overflow-x-auto pb-1">
        <ol className="flex min-w-[680px] items-stretch gap-0">
          {nodes.map((node, i) => (
            <li key={node.key} className="flex min-w-0 flex-1 items-stretch">
              {i > 0 ? (
                <span
                  data-testid={`fsm-connector-${i}`}
                  data-filled={nodes[i - 1].status === "completed" ? "true" : "false"}
                  aria-hidden="true"
                  className={cn(
                    "block h-px w-5 shrink-0 self-center transition-colors duration-500",
                    nodes[i - 1].status === "completed"
                      ? "bg-verified-emerald/80 shadow-[0_0_6px_rgba(16,185,129,0.4)]"
                      : nodes[i - 1].status === "active"
                        ? "bg-laser-cyan/60 animate-pulse"
                        : nodes[i - 1].status === "failed"
                          ? "bg-defect-crimson/50"
                          : "bg-border-subtle",
                  )}
                />
              ) : null}
              <NodeCard node={node} reducedMotion={reducedMotion} />
            </li>
          ))}
        </ol>
      </div>
      {run === null ? (
        <p className="mt-1 font-mono text-[11px] text-text-muted">
          No run selected — pipeline idle.
        </p>
      ) : null}
    </section>
  );
}
