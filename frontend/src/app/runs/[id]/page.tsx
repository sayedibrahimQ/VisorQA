"use client";

import React, { use } from "react";
import Link from "next/link";
import { 
  ArrowLeft, 
  GitPullRequest, 
  CheckCircle2, 
  Layers, 
  Code2, 
  ExternalLink 
} from "lucide-react";

import { MaskSlider } from "@/components/MaskSlider";
import { DiffViewer } from "@/components/DiffViewer";

export default function RunInspectorPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const runId = resolvedParams.id;

  return (
    <div className="flex flex-col min-h-screen bg-canvas text-text-primary">
      {/* Top Header */}
      <header className="h-14 border-b border-border-subtle bg-surface px-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary px-2.5 py-1 rounded bg-elevated border border-border-subtle transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Mission Control</span>
          </Link>
          <div className="h-4 w-px bg-border-subtle" />
          <div className="flex items-center gap-2 text-sm font-mono font-medium">
            <GitPullRequest className="w-4 h-4 text-cyan-400" />
            <span>Run Inspector: {runId}</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Autonomous Healed (Strike 1/3)</span>
          </span>
        </div>
      </header>

      {/* Inspector Body Content */}
      <div className="p-6 max-w-7xl mx-auto w-full flex flex-col gap-6">
        {/* Run Metadata Card */}
        <div className="grid grid-cols-4 gap-4 p-4 rounded-lg bg-surface border border-border-subtle text-xs font-mono">
          <div>
            <div className="text-text-muted mb-1">Target Repository</div>
            <div className="text-text-primary font-medium">sayedibrahimQ/VisorQA</div>
          </div>
          <div>
            <div className="text-text-muted mb-1">PR / Branch</div>
            <div className="text-text-primary font-medium">#42 (feat/checkout-banner)</div>
          </div>
          <div>
            <div className="text-text-muted mb-1">Commit SHA</div>
            <div className="text-text-primary font-medium">a1b2c3d4e5</div>
          </div>
          <div>
            <div className="text-text-muted mb-1">Verified Equation</div>
            <div className="text-emerald-400 font-medium">V_r = 1.00, IoU = 0.00</div>
          </div>
        </div>

        {/* 2-Column Inspector: Mask Overlays & Verified Unified Diff */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xs font-medium text-text-secondary uppercase">
              <Layers className="w-3.5 h-3.5 text-cyan-400" />
              <span>SAM 3.1 Pixel Mask Inspection</span>
            </div>
            <div className="h-[520px]">
              <MaskSlider vrScore={0.62} iouScore={0.0} />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xs font-medium text-text-secondary uppercase">
              <Code2 className="w-3.5 h-3.5 text-purple-400" />
              <span>Verified HMR Patch & Git Diff</span>
            </div>
            <div className="h-[520px]">
              <DiffViewer isVerified={true} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
