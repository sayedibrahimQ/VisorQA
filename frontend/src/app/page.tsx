"use client";

import React, { useState } from "react";
import Link from "next/link";
import { 
  ShieldCheck, 
  GitPullRequest, 
  Smartphone, 
  Monitor, 
  Radio, 
  Sparkles,
  ChevronRight,
  ExternalLink
} from "lucide-react";

import { MaskSlider } from "@/components/MaskSlider";
import { LiveTrace } from "@/components/LiveTrace";
import { DiffViewer } from "@/components/DiffViewer";
import { PRRun } from "@/types";

export default function LiveRunsPage() {
  const [selectedViewport, setSelectedViewport] = useState<"mobile" | "desktop">("mobile");
  const [activeRunId, setActiveRunId] = useState<string>("run-demo-42");

  const sampleRuns: PRRun[] = [
    {
      id: "run-demo-42",
      pr_number: 42,
      repo_name: "sayedibrahimQ/VisorQA",
      branch: "feat/checkout-banner",
      commit_sha: "a1b2c3d",
      status: "RUNNING",
      current_step: "1.SENSE",
      strikes: 1,
      anomalies_count: 1,
    },
    {
      id: "run-demo-41",
      pr_number: 41,
      repo_name: "sayedibrahimQ/VisorQA",
      branch: "fix/nav-dropdown",
      commit_sha: "f9e8d7c",
      status: "RESOLVED",
      current_step: "5.VERIFY",
      strikes: 1,
      anomalies_count: 0,
    },
  ];

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-canvas text-text-primary">
      {/* Top Bar Navigation */}
      <header className="h-14 border-b border-border-subtle bg-surface px-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 font-display font-semibold text-base tracking-tight">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
            <span>VisorQA</span>
          </div>
          <span className="text-text-muted text-xs">/</span>
          <div className="flex items-center gap-1.5 text-xs font-mono bg-elevated px-2.5 py-1 rounded border border-border-subtle">
            <GitPullRequest className="w-3.5 h-3.5 text-cyan-400" />
            <span>PR #42: feat/checkout-banner</span>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5 text-emerald-400 bg-emerald-950/40 border border-emerald-900/60 px-2.5 py-1 rounded">
            <Radio className="w-3 h-3 animate-pulse" />
            <span>WS: LIVE</span>
          </div>
          <div className="text-text-secondary">Latency: <span className="text-text-primary">8.4s</span></div>
          <div className="text-text-secondary">Cost: <span className="text-text-primary">$0.03</span></div>
        </div>
      </header>

      {/* Main Split-Pane Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Rail: PR Runs Stream */}
        <aside className="w-64 border-r border-border-subtle bg-surface/50 flex flex-col shrink-0">
          <div className="p-3 border-b border-border-subtle text-xs font-medium text-text-secondary uppercase tracking-wider flex items-center justify-between">
            <span>PR Runs Stream</span>
            <span className="text-[10px] font-mono bg-elevated px-1.5 py-0.5 rounded text-text-muted">Live</span>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {sampleRuns.map((run) => (
              <div
                key={run.id}
                onClick={() => setActiveRunId(run.id)}
                className={`p-2.5 rounded-md border text-xs cursor-pointer transition-colors ${
                  activeRunId === run.id
                    ? "bg-elevated border-border-focus text-text-primary"
                    : "bg-surface border-border-subtle text-text-secondary hover:bg-elevated/40"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-medium">#{run.pr_number} {run.branch}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                    run.status === "RUNNING"
                      ? "bg-cyan-950 text-cyan-400 border border-cyan-800"
                      : "bg-emerald-950 text-emerald-400 border border-emerald-800"
                  }`}>
                    {run.status}
                  </span>
                </div>
                <div className="text-[11px] text-text-muted flex items-center justify-between font-mono">
                  <span>Step: {run.current_step}</span>
                  <Link href={`/runs/${run.id}`} className="hover:text-text-primary flex items-center gap-0.5">
                    <span>Inspect</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* Center Canvas: Viewport Switcher & Mask Preview */}
        <main className="flex-1 flex flex-col min-w-0 p-4 gap-4 overflow-y-auto">
          {/* FSM Top Stepper */}
          <LiveTrace currentStep="1.SENSE" strikes={1} />

          {/* Viewport Selector */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 bg-surface p-1 rounded-md border border-border-subtle text-xs">
              <button
                onClick={() => setSelectedViewport("mobile")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded transition-colors ${
                  selectedViewport === "mobile"
                    ? "bg-elevated text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Smartphone className="w-3.5 h-3.5" />
                <span>Mobile 375px (1 Defect)</span>
              </button>
              <button
                onClick={() => setSelectedViewport("desktop")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded transition-colors ${
                  selectedViewport === "desktop"
                    ? "bg-elevated text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Monitor className="w-3.5 h-3.5" />
                <span>Desktop 1440px (Pass)</span>
              </button>
            </div>
            <div className="text-xs font-mono text-text-muted">
              Auto-Healing L4 Telemetry Mode
            </div>
          </div>

          {/* Viewport Canvas Mask Slider */}
          <div className="flex-1 min-h-[380px]">
            <MaskSlider vrScore={0.62} iouScore={0.0} />
          </div>
        </main>

        {/* Right Drawer: Telemetry & Code Diff */}
        <aside className="w-96 border-l border-border-subtle bg-surface/50 p-4 flex flex-col gap-4 overflow-y-auto shrink-0">
          <div className="flex items-center gap-2 pb-2 border-b border-border-subtle">
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span className="font-display font-semibold text-sm">Telemetry & Code Repair</span>
          </div>

          {/* Mathematical Equations Card */}
          <div className="p-3 bg-surface border border-border-subtle rounded-md text-xs space-y-2">
            <div className="font-mono text-text-secondary text-[11px] uppercase">Mathematical Verification</div>
            <div className="flex items-center justify-between font-mono">
              <span className="text-text-muted">Visibility Ratio (V_r):</span>
              <span className="text-rose-400 font-semibold">0.62 (&lt; 0.85 Threshold)</span>
            </div>
            <div className="flex items-center justify-between font-mono">
              <span className="text-text-muted">Collision IoU:</span>
              <span className="text-emerald-400 font-semibold">0.00 (Pass)</span>
            </div>
          </div>

          {/* Diff Viewer Component */}
          <div className="flex-1">
            <DiffViewer />
          </div>
        </aside>
      </div>
    </div>
  );
}
