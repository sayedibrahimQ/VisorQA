"use client";

import React, { use, useState, useEffect } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  GitPullRequest,
  CheckCircle2,
  Layers,
  Code2,
  ExternalLink,
  Activity,
  AlertTriangle,
  Cpu,
  FileCode,
  FolderTree,
  Lock,
  RefreshCw,
  Sliders,
  Sparkles,
  Terminal,
  Zap,
  Copy,
  Check,
  Smartphone,
  Monitor,
  ShieldCheck,
} from "lucide-react";

import { MaskSlider } from "@/components/MaskSlider";
import { DiffViewer } from "@/components/DiffViewer";
import { LiveTrace } from "@/components/LiveTrace";

interface RunData {
  id: string;
  prNumber: number;
  repo: string;
  branch: string;
  commitSha: string;
  status: "healed" | "verified" | "fallback";
  strikes: number;
  vrScore: number;
  iouScore: number;
  bleedScore: number;
  latency: string;
  cost: string;
  targetFile: string;
}

const RUNS_CATALOG: Record<string, RunData> = {
  "run-demo-42": {
    id: "run-demo-42",
    prNumber: 42,
    repo: "sayedibrahimQ/VisorQA",
    branch: "feat/checkout-banner",
    commitSha: "a1b2c3d4e5",
    status: "healed",
    strikes: 1,
    vrScore: 1.0,
    iouScore: 0.0,
    bleedScore: 0.0,
    latency: "14.2s",
    cost: "$0.03",
    targetFile: "src/components/PromoBanner.tsx",
  },
  "run-demo-41": {
    id: "run-demo-41",
    prNumber: 41,
    repo: "sayedibrahimQ/VisorQA",
    branch: "fix/mobile-nav-overlap",
    commitSha: "f8e7d6c5b4",
    status: "healed",
    strikes: 2,
    vrScore: 0.99,
    iouScore: 0.0,
    bleedScore: 0.0,
    latency: "18.6s",
    cost: "$0.05",
    targetFile: "src/components/Navigation.tsx",
  },
  "run-demo-39": {
    id: "run-demo-39",
    prNumber: 39,
    repo: "sayedibrahimQ/VisorQA",
    branch: "refactor/cart-drawer",
    commitSha: "3c4d5e6f7a",
    status: "verified",
    strikes: 0,
    vrScore: 1.0,
    iouScore: 0.0,
    bleedScore: 0.0,
    latency: "9.4s",
    cost: "$0.02",
    targetFile: "src/components/CartDrawer.tsx",
  },
  "run-demo-38": {
    id: "run-demo-38",
    prNumber: 38,
    repo: "sayedibrahimQ/VisorQA",
    branch: "feat/promo-modal-grid",
    commitSha: "9b8a7c6d5e",
    status: "fallback",
    strikes: 3,
    vrScore: 0.88,
    iouScore: 0.08,
    bleedScore: 12.0,
    latency: "28.1s",
    cost: "$0.09",
    targetFile: "src/components/PromoModal.tsx",
  },
};

const FSM_NODES = [
  { key: "1.SENSE", label: "1. SENSE", engine: "Playwright + SAM 3.1", latency: "0.45s" },
  { key: "2.TRIAGE", label: "2. TRIAGE", engine: "Muse Spark (LCA)", latency: "0.52s" },
  { key: "3.DIAGNOSE", label: "3. DIAGNOSE", engine: "Muse Wonder (Spec)", latency: "2.1s" },
  { key: "4.PATCH", label: "4. PATCH", engine: "Muse Code (Diff)", latency: "1.2s" },
  { key: "5.VERIFY", label: "5. VERIFY", engine: "Modal HMR (Dual Gate)", latency: "0.3s" },
];

export default function RunInspectorPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const runId = resolvedParams.id;

  const currentRun: RunData = RUNS_CATALOG[runId] || {
    id: runId,
    prNumber: 42,
    repo: "sayedibrahimQ/VisorQA",
    branch: "feat/checkout-banner",
    commitSha: "a1b2c3d4e5",
    status: "healed",
    strikes: 1,
    vrScore: 1.0,
    iouScore: 0.0,
    bleedScore: 0.0,
    latency: "14.2s",
    cost: "$0.03",
    targetFile: "src/components/PromoBanner.tsx",
  };

  const [activeTab, setActiveTab] = useState<"math" | "lca" | "spec" | "diff" | "trace">("math");
  const [activeNode, setActiveNode] = useState<string>("5.VERIFY");
  const [copiedLink, setCopiedLink] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const handleCopyLink = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard?.writeText(window.location.href);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    }
  };

  const compositeHealthScore = (
    currentRun.vrScore -
    currentRun.iouScore -
    0.01 * currentRun.bleedScore
  ).toFixed(2);

  const museWonderSpec = {
    defect_id: `DEF-2026-${currentRun.prNumber}`,
    defect_type: "Z_INDEX_OCCLUSION",
    visibility_ratio: 0.45,
    collision_iou: 0.16,
    target_file: currentRun.targetFile,
    root_cause: "Sticky PromoBanner absolute positioning occludes checkout primary CTA",
    repair_strategy: "Convert position: fixed to position: sticky with top-0 z-10 and bottom padding",
    css_constraints: {
      banned_properties: ["!important", "z-index: 9999"],
      viewport_isolation: ["375px", "1440px"],
      cross_viewport_zero_regression: true,
    },
    verified_attempt: currentRun.strikes,
  };

  return (
    <div className="flex flex-col min-h-screen bg-canvas text-text-primary">
      {/* Top Header & Telemetry Bar */}
      <header className="h-14 border-b border-border-subtle bg-surface px-4 sm:px-6 flex items-center justify-between sticky top-0 z-50 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary px-2.5 py-1 rounded bg-elevated border border-border-subtle hover:border-cyan-500/40 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Mission Control</span>
            <span className="sm:hidden">Home</span>
          </Link>
          <div className="h-4 w-px bg-border-subtle" />
          <div className="flex items-center gap-2 text-xs sm:text-sm font-mono font-medium truncate">
            <GitPullRequest className="w-4 h-4 text-cyan-400 shrink-0" />
            <span className="truncate">Run Inspector: {runId}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          {/* WebSocket Status Indicator */}
          <div className="hidden md:flex items-center gap-1.5 rounded bg-surface border border-border-subtle px-2 py-0.5 font-mono text-[11px] text-text-secondary">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-verified-emerald opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-verified-emerald" />
            </span>
            <span className="text-text-muted">WS:</span>
            <span className="text-verified-emerald font-semibold">CONNECTED</span>
          </div>

          {/* Deep link copy button */}
          <button
            type="button"
            onClick={handleCopyLink}
            className="flex items-center gap-1 text-xs font-mono px-2 py-1 rounded bg-elevated border border-border-subtle text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-colors"
            title="Copy Deep Link"
          >
            {copiedLink ? <Check className="w-3.5 h-3.5 text-verified-emerald" /> : <Copy className="w-3.5 h-3.5" />}
            <span className="hidden sm:inline">{copiedLink ? "Copied" : "Share"}</span>
          </button>

          {/* Status Badge */}
          {currentRun.status === "healed" && (
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1.5 shadow-sm">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Autonomous Healed (Strike {currentRun.strikes}/3)</span>
            </span>
          )}
          {currentRun.status === "verified" && (
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-cyan-950/60 border border-cyan-800 text-cyan-400 flex items-center gap-1.5 shadow-sm">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Zero Regressions (Pass)</span>
            </span>
          )}
          {currentRun.status === "fallback" && (
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-amber-950/60 border border-amber-800 text-amber-400 flex items-center gap-1.5 shadow-sm">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>3-Strike Halt (PR Review Fallback)</span>
            </span>
          )}
        </div>
      </header>

      {/* Main Mission Control Body */}
      <div className="flex-1 flex flex-col p-4 sm:p-6 max-w-[1600px] mx-auto w-full gap-5">
        {/* Run Metadata HUD Card */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 p-4 rounded-lg bg-surface border border-border-subtle text-xs font-mono shadow-sm">
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">Target Repository</div>
            <div className="text-text-primary font-medium truncate">{currentRun.repo}</div>
          </div>
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">PR / Branch</div>
            <div className="text-text-primary font-medium truncate">
              #{currentRun.prNumber} ({currentRun.branch})
            </div>
          </div>
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">Commit SHA</div>
            <div className="text-text-primary font-medium">{currentRun.commitSha}</div>
          </div>
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">Verified Equation</div>
            <div className="text-emerald-400 font-medium">V_r = 1.00, IoU = 0.00</div>
          </div>
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">Cycle Latency</div>
            <div className="text-cyan-400 font-medium">{currentRun.latency} (HMR 0.3s)</div>
          </div>
          <div>
            <div className="text-text-muted mb-1 text-[10px] uppercase tracking-wider">Cost / Spend Cap</div>
            <div className="text-text-primary font-medium">{currentRun.cost} / $0.15 max</div>
          </div>
        </div>

        {/* 5-Node Interactive FSM Orchestrator Stepper */}
        <div className="rounded-lg border border-border-subtle bg-surface p-3.5 shadow-sm">
          <div className="flex items-center justify-between pb-2.5 mb-2.5 border-b border-border-subtle">
            <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
              <Activity className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
              <span>Level 4 Autonomous FSM Execution Pipeline</span>
            </div>
            <div className="flex items-center gap-2 font-mono text-[11px] text-text-muted">
              <span>Strike Counter:</span>
              <span className="text-triage-amber font-semibold">{currentRun.strikes}/3</span>
              <span>·</span>
              <span className="text-verified-emerald">Auto-Commit Pushed</span>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {FSM_NODES.map((node, idx) => {
              const isSelected = activeNode === node.key;
              const isPassed = idx < 4;
              return (
                <button
                  key={node.key}
                  type="button"
                  onClick={() => setActiveNode(node.key)}
                  className={`p-2.5 rounded-md border text-left transition-all ${
                    isSelected
                      ? "bg-elevated border-cyan-400 shadow-[0_0_12px_rgba(0,242,254,0.2)]"
                      : "bg-canvas/60 border-border-subtle hover:border-border-strong hover:bg-elevated/40"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-xs font-semibold text-text-primary">{node.label}</span>
                    <span className="font-mono text-[9px] text-cyan-400">{node.latency}</span>
                  </div>
                  <div className="font-mono text-[10px] text-text-muted truncate">{node.engine}</div>
                  <div className="mt-1 flex items-center gap-1 font-mono text-[9px] text-emerald-400">
                    <CheckCircle2 className="w-2.5 h-2.5" />
                    <span>Verified</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* 3-Column Command Center Workspace */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1 items-start">
          {/* Left Rail: PR Runs Stream Switcher */}
          <div className="lg:col-span-3 rounded-lg border border-border-subtle bg-surface p-4 flex flex-col gap-3 shadow-sm">
            <div className="flex items-center justify-between pb-2 border-b border-border-subtle">
              <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
                <GitPullRequest className="w-3.5 h-3.5 text-cyan-400" />
                <span>PR Runs Stream</span>
              </div>
              <span className="font-mono text-[10px] text-text-muted">4 Active Runs</span>
            </div>

            <div className="space-y-2">
              {Object.values(RUNS_CATALOG).map((r) => {
                const isActive = r.id === runId;
                return (
                  <Link
                    key={r.id}
                    href={`/runs/${r.id}`}
                    className={`block p-2.5 rounded-md border transition-all text-xs font-mono ${
                      isActive
                        ? "bg-elevated border-cyan-400/80 shadow-[0_0_10px_rgba(0,242,254,0.15)]"
                        : "bg-canvas/50 border-border-subtle hover:bg-elevated/40 hover:border-text-secondary/40"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold text-text-primary">PR #{r.prNumber}</span>
                      <span
                        className={`text-[9px] px-1.5 py-0.2 rounded font-semibold ${
                          r.status === "healed"
                            ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800"
                            : r.status === "verified"
                            ? "bg-cyan-950/80 text-cyan-400 border border-cyan-800"
                            : "bg-amber-950/80 text-amber-400 border border-amber-800"
                        }`}
                      >
                        {r.status === "healed" ? "Healed" : r.status === "verified" ? "Verified" : "Halted"}
                      </span>
                    </div>
                    <div className="text-[11px] text-text-secondary truncate">{r.branch}</div>
                    <div className="mt-1 flex items-center justify-between text-[10px] text-text-muted">
                      <span>V_r: {r.vrScore.toFixed(2)}</span>
                      <span>Strike {r.strikes}/3</span>
                      <span>{r.latency}</span>
                    </div>
                  </Link>
                );
              })}
            </div>

            {/* Quick Agent Policy Guardrails Summary */}
            <div className="mt-2 pt-3 border-t border-border-subtle text-[11px] font-mono text-text-muted space-y-1.5">
              <div className="flex items-center gap-1.5 text-text-secondary">
                <Lock className="w-3 h-3 text-amber-400" />
                <span>BR-2: src/components/ui/* Locked</span>
              </div>
              <div className="flex items-center gap-1.5 text-text-secondary">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                <span>BR-3: Cross-Viewport Verified</span>
              </div>
              <div className="flex items-center gap-1.5 text-text-secondary">
                <RefreshCw className="w-3 h-3 text-cyan-400" />
                <span>BR-1: 3-Strike Hard Cap</span>
              </div>
            </div>
          </div>

          {/* Center Column: Dual-Viewport Canvas with Mask Overlays */}
          <div className="lg:col-span-5 flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs font-medium text-text-secondary uppercase px-1">
              <div className="flex items-center gap-2">
                <Layers className="w-3.5 h-3.5 text-cyan-400" />
                <span>Dual-Viewport Canvas & SAM Mask</span>
              </div>
              <span className="font-mono text-[10px] text-text-muted">Modal Sandbox v2.4</span>
            </div>
            <div className="h-[520px]">
              <MaskSlider vrScore={0.62} iouScore={0.0} />
            </div>
          </div>

          {/* Right Column: Multi-Tab Inspector Drawer */}
          <div className="lg:col-span-4 flex flex-col gap-2">
            {/* Tab Switcher */}
            <div className="flex items-center gap-1 rounded-lg border border-border-subtle bg-surface p-1 text-xs font-mono overflow-x-auto">
              <button
                type="button"
                onClick={() => setActiveTab("math")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                  activeTab === "math" ? "bg-elevated font-semibold text-cyan-300 shadow-sm" : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Cpu className="w-3 h-3" />
                <span>Math Trap</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("lca")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                  activeTab === "lca" ? "bg-elevated font-semibold text-cyan-300 shadow-sm" : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <FolderTree className="w-3 h-3" />
                <span>LCA Tree</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("spec")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                  activeTab === "spec" ? "bg-elevated font-semibold text-cyan-300 shadow-sm" : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <FileCode className="w-3 h-3" />
                <span>Spec JSON</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("diff")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                  activeTab === "diff" ? "bg-elevated font-semibold text-cyan-300 shadow-sm" : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Code2 className="w-3 h-3" />
                <span>Diff</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("trace")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                  activeTab === "trace" ? "bg-elevated font-semibold text-cyan-300 shadow-sm" : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Terminal className="w-3 h-3" />
                <span>Trace</span>
              </button>
            </div>

            {/* Tab Panels Container */}
            <div className="h-[520px]">
              {/* Tab 1: Mathematical Trap Scorecard */}
              {activeTab === "math" && (
                <div className="h-full rounded-lg border border-border-subtle bg-surface p-4 flex flex-col justify-between font-mono text-xs shadow-sm overflow-y-auto">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between border-b border-border-subtle pb-2">
                      <span className="font-semibold text-text-primary text-sm flex items-center gap-1.5">
                        <Cpu className="w-4 h-4 text-cyan-400" />
                        NumPy Discrepancy Matrix
                      </span>
                      <span className="text-[10px] text-text-muted">Zero VLM Guessing</span>
                    </div>

                    {/* Formula 1: Visibility Ratio */}
                    <div className="p-2.5 rounded bg-canvas/70 border border-border-subtle">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-text-muted text-[11px]">1. Visibility Ratio (V_r)</span>
                        <span className="text-emerald-400 font-semibold px-1.5 py-0.2 rounded bg-emerald-950/60 border border-emerald-800 text-[10px]">
                          PASS
                        </span>
                      </div>
                      <div className="text-sm font-semibold text-text-primary">
                        V_r = {currentRun.vrScore.toFixed(2)}{" "}
                        <span className="text-[10px] font-normal text-text-muted">(threshold: &ge; 0.98)</span>
                      </div>
                      <p className="mt-1 text-[10px] text-text-muted">Formula: Area(M_SAM &cap; B_DOM) / Area(B_DOM)</p>
                    </div>

                    {/* Formula 2: Sibling Collision IoU */}
                    <div className="p-2.5 rounded bg-canvas/70 border border-border-subtle">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-text-muted text-[11px]">2. Sibling Collision (IoU)</span>
                        <span className="text-emerald-400 font-semibold px-1.5 py-0.2 rounded bg-emerald-950/60 border border-emerald-800 text-[10px]">
                          PASS
                        </span>
                      </div>
                      <div className="text-sm font-semibold text-text-primary">
                        IoU = {currentRun.iouScore.toFixed(2)}{" "}
                        <span className="text-[10px] font-normal text-text-muted">(threshold: &le; 0.05)</span>
                      </div>
                      <p className="mt-1 text-[10px] text-text-muted">Formula: Area(Mi &cap; Mj) / Area(Mi &cup; Mj)</p>
                    </div>

                    {/* Formula 3: Viewport Bleed */}
                    <div className="p-2.5 rounded bg-canvas/70 border border-border-subtle">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-text-muted text-[11px]">3. Viewport Bleed (&Delta;_x)</span>
                        <span className="text-emerald-400 font-semibold px-1.5 py-0.2 rounded bg-emerald-950/60 border border-emerald-800 text-[10px]">
                          PASS
                        </span>
                      </div>
                      <div className="text-sm font-semibold text-text-primary">
                        &Delta;_x = {currentRun.bleedScore.toFixed(1)}px{" "}
                        <span className="text-[10px] font-normal text-text-muted">(threshold: &le; 2.0px)</span>
                      </div>
                      <p className="mt-1 text-[10px] text-text-muted">Formula: max(0, X_max(B_DOM) - W_viewport)</p>
                    </div>
                  </div>

                  {/* Composite Health Score Banner */}
                  <div className="mt-3 p-3 rounded bg-elevated border border-cyan-500/30">
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-text-secondary">Composite Health Score</span>
                      <span className="text-base font-bold text-cyan-300">H = {compositeHealthScore}</span>
                    </div>
                    <div className="text-[10px] text-text-muted mt-1">
                      H = mean(V_r) - max(IoU) - 0.01·&Delta;x (Autonomous Commit Gate)
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 2: LCA DOM Hierarchy Tree */}
              {activeTab === "lca" && (
                <div className="h-full rounded-lg border border-border-subtle bg-surface p-4 flex flex-col justify-between font-mono text-xs shadow-sm overflow-y-auto">
                  <div>
                    <div className="flex items-center justify-between border-b border-border-subtle pb-2 mb-3">
                      <span className="font-semibold text-text-primary text-sm flex items-center gap-1.5">
                        <FolderTree className="w-4 h-4 text-indigo-400" />
                        LCA DOM Fault Localization
                      </span>
                      <span className="text-[10px] text-text-muted">Muse Spark (0.52s)</span>
                    </div>

                    <div className="p-2.5 rounded bg-canvas/80 border border-border-subtle space-y-2 text-[11px]">
                      <div className="text-text-muted">HTML Root &lt;html lang=&quot;en&quot;&gt;</div>
                      <div className="pl-3 text-text-muted">&boxur;&boxh; &lt;body className=&quot;min-h-screen&quot;&gt;</div>
                      <div className="pl-6 text-text-muted">&boxur;&boxh; &lt;main className=&quot;checkout-page&quot;&gt;</div>
                      <div className="pl-9 text-indigo-300 font-semibold bg-indigo-950/40 p-1 rounded border border-indigo-500/30">
                        &boxur;&boxh; [LCA Container] &lt;div className=&quot;relative min-h-screen&quot;&gt;
                      </div>
                      <div className="pl-12 text-rose-300">
                        &boxur;&boxh; [Colliding Sibling] &lt;PromoBanner /&gt; (visor-el-04)
                      </div>
                      <div className="pl-12 text-amber-300 flex items-center gap-1">
                        &boxur;&boxh; <Lock className="w-2.5 h-2.5 text-amber-400" />
                        <span>[Protected UI] src/components/ui/Button.tsx (IMMUTABLE)</span>
                      </div>
                      <div className="pl-12 text-emerald-300">
                        &boxur;&boxh; [TARGET FILE] src/components/PromoBanner.tsx (MUTATED)
                      </div>
                    </div>

                    <div className="mt-3 p-2.5 rounded bg-canvas/60 border border-border-subtle text-[11px] text-text-secondary leading-relaxed">
                      <span className="text-cyan-400 font-semibold">Token Pruning:</span> Walked DOM tree upward to Lowest Common Ancestor. Extracted 3,200 tokens instead of 28,000 full-repo tokens (88.5% reduction). Protected shared design system primitives under <code className="text-text-primary">src/components/ui/*</code>.
                    </div>
                  </div>

                  <div className="mt-2 text-[10px] text-text-muted border-t border-border-subtle pt-2">
                    Verified in ADR-002: DOM Ancestor Hierarchy & Muse Spark Triage
                  </div>
                </div>
              )}

              {/* Tab 3: Muse Wonder Spec JSON */}
              {activeTab === "spec" && (
                <div className="h-full rounded-lg border border-border-subtle bg-surface p-4 flex flex-col font-mono text-xs shadow-sm overflow-hidden">
                  <div className="flex items-center justify-between border-b border-border-subtle pb-2 mb-2">
                    <span className="font-semibold text-text-primary text-sm flex items-center gap-1.5">
                      <FileCode className="w-4 h-4 text-purple-400" />
                      Pydantic RepairSpec JSON
                    </span>
                    <span className="text-[10px] text-text-muted">Meta Muse Wonder</span>
                  </div>
                  <pre className="flex-1 p-3 bg-canvas/90 rounded border border-border-subtle text-[11px] overflow-auto text-cyan-300 leading-relaxed font-mono">
                    {JSON.stringify(museWonderSpec, null, 2)}
                  </pre>
                  <div className="mt-2 text-[10px] text-text-muted flex items-center justify-between">
                    <span>Schema: pydantic.BaseModel (Validated)</span>
                    <span className="text-verified-emerald">Zero Syntax Errors</span>
                  </div>
                </div>
              )}

              {/* Tab 4: Unified Diff */}
              {activeTab === "diff" && (
                <div className="h-full">
                  <DiffViewer filePath={currentRun.targetFile} isVerified={true} />
                </div>
              )}

              {/* Tab 5: Live Trace Log */}
              {activeTab === "trace" && (
                <div className="h-full">
                  <LiveTrace
                    currentStep="5.VERIFY"
                    strikes={currentRun.strikes}
                    events={[
                      { timestamp: "00:01.2", step: "SENSE", message: `Playwright extracted DOM coordinates for PR #${currentRun.prNumber}` },
                      { timestamp: "00:02.4", step: "SENSE", message: "SAM 3.1 segmented M_SAM mask (Vr = 0.45 < 0.85, IoU = 0.16)" },
                      { timestamp: "00:03.1", step: "TRIAGE", message: `Muse Spark LCA located ${currentRun.targetFile} in 0.52s` },
                      { timestamp: "00:05.4", step: "DIAGNOSE", message: "Muse Wonder issued Pydantic RepairSpec: convert fixed to sticky" },
                      { timestamp: "00:07.1", step: "PATCH", message: "Muse Code synthesized unified diff; Modal HMR applied in 0.3s" },
                      { timestamp: "00:09.2", step: "VERIFY", message: "Dual-viewport gate passed: Vr = 1.00, IoU = 0.00. Auto-commit created." },
                    ]}
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
