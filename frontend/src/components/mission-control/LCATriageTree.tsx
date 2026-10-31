"use client";

import React from "react";
import { FileCode2, GitBranch, Shield, Target } from "lucide-react";
import { isProtectedUiPath, type LCATreeNode, type TriageData } from "@/lib/telemetryDrawer";
import { cn } from "@/lib/utils";

const REASON_LABELS: Record<string, string> = {
  protected_shared_ui: "Protected shared UI (BR-2)",
  not_in_repository_tree: "Not in repository tree",
  malformed_path: "Malformed path",
  path_traversal: "Path traversal",
  low_confidence: "Low confidence",
  insufficient_evidence: "Insufficient evidence",
  intentional_overlap_filtered: "Intentional overlap filtered",
};

function TreeNodes({ nodes, depth = 0 }: { nodes: LCATreeNode[]; depth?: number }) {
  return (
    <ul className={cn(depth > 0 && "ml-3 border-l border-border-subtle pl-3")}>
      {nodes.map((node) => (
        <li key={node.key} data-testid="lca-node" data-lca={node.isLCA ? "true" : undefined} className="py-0.5">
          <div
            className={cn(
              "flex flex-wrap items-center gap-1.5 rounded-sm px-1.5 py-1 font-mono text-xs",
              node.isLCA
                ? "border border-neural-pulse/50 bg-elevated text-text-primary"
                : "text-text-secondary",
            )}
          >
            <GitBranch className="h-3 w-3 shrink-0 text-text-muted" aria-hidden="true" />
            <span className="break-all">{node.label}</span>
            {node.visorElId ? (
              <span
                data-testid="lca-visor-id"
                className="rounded-sm border border-border-subtle px-1 py-px text-[10px] text-text-muted"
              >
                {node.visorElId}
              </span>
            ) : null}
            {node.isLCA ? (
              <span className="rounded-sm border border-neural-pulse/50 px-1 py-px text-[9px] uppercase tracking-wide text-neural-pulse">
                LCA
              </span>
            ) : null}
          </div>
          {node.children.length > 0 ? <TreeNodes nodes={node.children} depth={depth + 1} /> : null}
        </li>
      ))}
    </ul>
  );
}

/**
 * Node 2 LCA triage tree. Renders only backend-reported ancestor chains,
 * authorized targets, and BR-2 decisions — protected files are labeled as
 * protected, never as repair targets.
 */
export function LCATriageTree({ triage }: { triage: TriageData }) {
  const hasTriage = triage.lcaElementId !== null || triage.lcaChain.length > 0 || triage.targets.length > 0;
  return (
    <section aria-label="LCA triage tree" data-testid="lca-triage-tree" className="min-w-0">
      <h3 className="font-display text-sm font-semibold text-text-primary">LCA Triage</h3>

      {!hasTriage ? (
        <p data-testid="lca-empty" className="mt-2 text-xs text-text-secondary">
          No triage hierarchy reported for this run yet.
        </p>
      ) : (
        <div className="mt-2">
          {triage.lcaChain.length > 0 ? (
            <TreeNodes nodes={triage.lcaChain} />
          ) : (
            <p className="text-xs text-text-secondary">
              LCA element {triage.lcaElementId ?? "—"} reported without an ancestor chain.
            </p>
          )}
          {triage.lcaElementId && triage.lcaChain.length > 0 ? (
            <p className="mt-2 font-mono text-[11px] text-text-secondary">
              LCA: <span className="text-text-primary">{triage.lcaElementId}</span>
              {triage.confidence !== null ? ` · confidence ${triage.confidence.toFixed(2)}` : ""}
              {triage.triageStatus ? ` · ${triage.triageStatus}` : ""}
            </p>
          ) : null}
          {triage.lcaReason ? (
            <p data-testid="lca-reason" className="mt-1 text-xs leading-5 text-text-muted">
              {triage.lcaReason}
            </p>
          ) : null}
        </div>
      )}

      {triage.targets.length > 0 ? (
        <div className="mt-3">
          <h4 className="font-mono text-[10px] uppercase tracking-wider text-text-muted">Repair targets</h4>
          <ul className="mt-1.5 space-y-1">
            {triage.targets.map((path) => {
              const protectedPath = isProtectedUiPath(path);
              return (
                <li
                  key={path}
                  data-testid="lca-target"
                  data-protected={protectedPath ? "true" : "false"}
                  className="flex flex-wrap items-center gap-1.5 rounded-sm border border-border-subtle bg-surface px-2 py-1 font-mono text-[11px]"
                >
                  <FileCode2 className="h-3 w-3 shrink-0 text-text-muted" aria-hidden="true" />
                  <span className="break-all text-text-primary">{path}</span>
                  {protectedPath ? (
                    <span className="inline-flex items-center gap-1 rounded-sm border border-triage-amber/60 px-1 py-px text-[9px] uppercase tracking-wide text-triage-amber">
                      <Shield className="h-2.5 w-2.5" /> [Protected Shared UI]
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-sm border border-verified-emerald/60 px-1 py-px text-[9px] uppercase tracking-wide text-verified-emerald">
                      <Target className="h-2.5 w-2.5" /> [Target File]
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {triage.rejected.length > 0 ? (
        <div className="mt-3">
          <h4 className="font-mono text-[10px] uppercase tracking-wider text-text-muted">BR-2 decisions</h4>
          <ul className="mt-1.5 space-y-1">
            {triage.rejected.map((r, i) => (
              <li
                key={`${r.path}-${i}`}
                data-testid="lca-rejected"
                className="flex flex-wrap items-center gap-1.5 rounded-sm border border-border-subtle px-2 py-1 font-mono text-[11px]"
              >
                <Shield className="h-3 w-3 shrink-0 text-triage-amber" aria-hidden="true" />
                <span className="break-all text-text-secondary">{r.path}</span>
                <span className="text-[10px] text-text-muted">
                  {isProtectedUiPath(r.path) ? "[Protected Shared UI] · " : ""}
                  {REASON_LABELS[r.reason] ?? r.reason}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {triage.filteredIntentional.length > 0 ? (
        <p className="mt-2 font-mono text-[10px] text-text-muted">
          Filtered as intentional overlap: {triage.filteredIntentional.join(", ")}
        </p>
      ) : null}

      {triage.tokenReductionRatio !== null && triage.tokenReductionRatio !== undefined ? (
        <p data-testid="lca-token-ratio" className="mt-2 font-mono text-[10px] text-text-muted">
          Token reduction {(triage.tokenReductionRatio * 100).toFixed(1)}%
          {triage.candidateFiles && triage.candidateFiles.length > 0
            ? ` · ${triage.candidateFiles.length} candidate files`
            : ""}
        </p>
      ) : null}
    </section>
  );
}
