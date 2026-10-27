"use client";

import React from "react";
import { GitCommit, FileCode, Check } from "lucide-react";

interface DiffViewerProps {
  filePath?: string;
  diffContent?: string;
  isVerified?: boolean;
}

const DEFAULT_DIFF = `--- a/src/components/PromoBanner.tsx
+++ b/src/components/PromoBanner.tsx
@@ -14,3 +14,3 @@
- <div className="fixed top-0 inset-x-0 z-50 bg-rose-600 text-white">
+ <div className="sticky top-0 inset-x-0 z-10 bg-rose-600 text-white">
    <span>Free Worldwide Shipping on Orders Over $50</span>
  </div>`;

export function DiffViewer({
  filePath = "src/components/PromoBanner.tsx",
  diffContent = DEFAULT_DIFF,
  isVerified = true,
}: DiffViewerProps) {
  const lines = diffContent.split("\n");

  return (
    <div className="flex flex-col bg-surface border border-border-subtle rounded-lg overflow-hidden">
      {/* Diff Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-elevated border-b border-border-subtle text-xs">
        <div className="flex items-center gap-2">
          <FileCode className="w-4 h-4 text-text-secondary" />
          <span className="font-mono text-text-primary">{filePath}</span>
        </div>
        {isVerified && (
          <div className="flex items-center gap-1 text-emerald-400 font-mono text-[11px]">
            <Check className="w-3.5 h-3.5" />
            <span>Self-Healed & Verified (IoU = 0)</span>
          </div>
        )}
      </div>

      {/* Diff Content Lines */}
      <div className="p-3 bg-canvas/90 font-mono text-xs overflow-x-auto space-y-0.5">
        {lines.map((line, idx) => {
          let lineClass = "text-text-secondary";
          if (line.startsWith("+") && !line.startsWith("+++")) {
            lineClass = "text-emerald-400 bg-emerald-950/30 px-1 rounded-sm";
          } else if (line.startsWith("-") && !line.startsWith("---")) {
            lineClass = "text-rose-400 bg-rose-950/30 px-1 rounded-sm";
          } else if (line.startsWith("@@")) {
            lineClass = "text-cyan-400";
          }
          return (
            <div key={idx} className={`${lineClass} whitespace-pre`}>
              {line}
            </div>
          );
        })}
      </div>

      {/* Auto-Commit Footer */}
      <div className="px-4 py-2 border-t border-border-subtle bg-surface flex items-center justify-between text-xs text-text-muted">
        <div className="flex items-center gap-1.5 font-mono">
          <GitCommit className="w-3.5 h-3.5 text-text-secondary" />
          <span>Commit: fix(ui): autonomous visual repair by VisorQA</span>
        </div>
        <span className="text-[11px]">PyGithub Auto-Commit</span>
      </div>
    </div>
  );
}
