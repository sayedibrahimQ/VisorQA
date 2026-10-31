"use client";

import React from "react";
import { formatLatency } from "@/lib/fsmSelectors";
import { cn } from "@/lib/utils";

interface LatencyBadgeProps {
  /** Measured per-node latency in ms, or null when unavailable. */
  ms: number | null;
  /** Accessible context, e.g. the node name. */
  nodeName?: string;
  className?: string;
}

/**
 * Real per-node latency badge. Renders a neutral placeholder when no backend
 * measurement exists — never a fabricated value.
 */
export function LatencyBadge({ ms, nodeName, className }: LatencyBadgeProps) {
  const text = formatLatency(ms);
  if (text === null) {
    return (
      <span
        data-testid="latency-badge"
        data-state="unavailable"
        aria-label={nodeName ? `${nodeName} latency unavailable` : "Latency unavailable"}
        title="No timing data reported by backend"
        className={cn(
          "inline-flex items-center rounded-sm border border-border-subtle px-1.5 py-px font-mono text-[10px] leading-4 text-text-muted",
          className,
        )}
      >
        —
      </span>
    );
  }
  return (
    <span
      data-testid="latency-badge"
      data-state="measured"
      aria-label={nodeName ? `${nodeName} latency ${text}` : `Latency ${text}`}
      className={cn(
        "inline-flex items-center rounded-sm border border-border-subtle bg-canvas px-1.5 py-px font-mono text-[10px] leading-4 text-text-secondary",
        className,
      )}
    >
      {text}
    </span>
  );
}
