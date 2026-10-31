"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  Code2,
  Copy,
  Cpu,
  FileCode,
  FolderTree,
  GitCommit,
  GitPullRequest,
  Layers,
  Lock,
  Monitor,
  RefreshCw,
  Scan,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Terminal,
  Zap,
} from "lucide-react";
import { DiffViewer } from "@/components/DiffViewer";
import { LiveTrace } from "@/components/LiveTrace";
import {
  CLI_CMD,
  FOCUS,
  MISSION_CONTROL_URL,
  REPO_URL,
  SectionHeading,
} from "./shared";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------
 * 1. MODEL STRIP
 * ----------------------------------------------------------------------- */
export function ModelStrip() {
  const models = [
    {
      name: "Meta SAM 3.1",
      role: "Pixel Segmentation",
      desc: "Zero-shot DOM point-prompts",
      latency: "<450ms",
      icon: Scan,
    },
    {
      name: "Meta Muse Spark",
      role: "Fault Localization",
      desc: "LCA DOM tree triage (2M TPM)",
      latency: "<600ms",
      icon: Zap,
    },
    {
      name: "Meta Muse Wonder",
      role: "Layout Architect",
      desc: "Pydantic RepairSpec JSON",
      latency: "2.1s",
      icon: Bot,
    },
    {
      name: "Meta Muse Code",
      role: "Diff Synthesis",
      desc: "Surgical unified diffs",
      latency: "1.2s",
      icon: Code2,
    },
    {
      name: "Modal + Playwright",
      role: "Sandbox & HMR",
      desc: "Dual-viewport hot reload",
      latency: "0.3s",
      icon: Monitor,
    },
  ];

  return (
    <section aria-label="Meta AI Models and Execution Engine" className="mt-16 border-y border-border-subtle bg-surface/30">
      <div className="grid grid-cols-2 divide-y divide-border-subtle sm:grid-cols-5 sm:divide-x sm:divide-y-0">
        {models.map((model) => {
          const Icon = model.icon;
          return (
            <div
              key={model.name}
              className="group relative px-4 py-4 transition-all duration-200 hover:bg-surface/80"
            >
              <div className="flex items-center justify-between">
                <span className="font-display text-sm font-semibold text-text-primary">
                  {model.name}
                </span>
                <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[9px] text-cyan-400">
                  {model.latency}
                </span>
              </div>
              <p className="mt-1 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-text-muted">
                <Icon className="h-3 w-3 text-text-secondary" aria-hidden="true" />
                <span>{model.role}</span>
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                {model.desc}
              </p>
              <div className="absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-400/0 to-transparent transition-all group-hover:via-cyan-400/50" />
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 2. QUANTITATIVE METRICS GRID
 * ----------------------------------------------------------------------- */
export function Metrics() {
  const stats = [
    {
      value: "<15.0s",
      chip: "END-TO-END CYCLE",
      label: "Cycle Latency",
      detail:
        "Webhook trigger to verified PR commit across mobile (375px) and desktop (1440px) sandboxes.",
    },
    {
      value: "99.2%",
      chip: "NUMPY PIXEL MATH",
      label: "Detection Precision",
      detail:
        "DOM point prompts (cx, cy) fed directly to SAM 3.1 eliminates VLM spatial hallucinations.",
    },
    {
      value: "88.5%",
      chip: "LCA DOM HIERARCHY",
      label: "Context Token Pruning",
      detail:
        "Lowest Common Ancestor traversal prunes context from ~28,000 to ~3,200 tokens per run.",
    },
    {
      value: "Max 3x / $0.03",
      chip: "DETERMINISTIC GUARDRAIL",
      label: "Bounded Self-Healing",
      detail:
        "Hard-capped 3-strike retry loop with $0.03 average PR spend ($0.15 database-enforced ceiling).",
    },
  ];

  return (
    <section aria-label="Engineering targets and performance metrics" className="mt-20">
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border-subtle bg-border-subtle sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, idx) => (
          <div
            key={stat.label}
            className="group relative flex flex-col justify-between bg-surface p-6 transition-colors hover:bg-elevated/60"
          >
            <div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-cyan-400">
                {stat.chip}
              </span>
              <p className="mt-3 font-display text-3xl font-semibold tracking-tight text-text-primary md:text-4xl">
                {stat.value}
              </p>
              <p className="mt-1 font-medium text-sm text-text-primary">
                {stat.label}
              </p>
              <p className="mt-2 text-xs leading-relaxed text-text-secondary">
                {stat.detail}
              </p>

              {/* Micro-visualizer indicator */}
              <div className="mt-3 font-mono text-[10px] text-text-muted">
                {idx === 0 && (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 rounded-full bg-cyan-950 border border-cyan-800/40 overflow-hidden">
                      <div className="h-full w-[80%] bg-gradient-to-r from-cyan-500 to-cyan-300 rounded-full" />
                    </div>
                    <span className="text-cyan-400 text-[9px] shrink-0">14.2s avg</span>
                  </div>
                )}
                {idx === 1 && (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 rounded-full bg-emerald-950 border border-emerald-800/40 overflow-hidden">
                      <div className="h-full w-[99.2%] bg-gradient-to-r from-emerald-500 to-emerald-300 rounded-full" />
                    </div>
                    <span className="text-emerald-400 text-[9px] shrink-0">0.8% bound</span>
                  </div>
                )}
                {idx === 2 && (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 rounded-full bg-indigo-950 border border-indigo-800/40 overflow-hidden">
                      <div className="h-full w-[88.5%] bg-gradient-to-r from-indigo-500 to-indigo-300 rounded-full" />
                    </div>
                    <span className="text-indigo-400 text-[9px] shrink-0">3.2K / 28K</span>
                  </div>
                )}
                {idx === 3 && (
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-emerald-950/60 px-1.5 py-0.5 text-[9px] text-emerald-400 border border-emerald-800/50">Strike 1: 82%</span>
                    <span className="rounded bg-amber-950/60 px-1.5 py-0.5 text-[9px] text-amber-400 border border-amber-800/50">Strike 2: 15%</span>
                    <span className="rounded bg-surface px-1.5 py-0.5 text-[9px] text-text-muted border border-border-subtle">Halt: 3%</span>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-4 flex items-center gap-1 font-mono text-[10px] text-text-muted">
              <CheckCircle2 className="h-3 w-3 text-verified-emerald" aria-hidden="true" />
              <span>Specification Verified</span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 font-mono text-[11px] text-text-muted">
        Specifications derived from VisorQA Software Requirements Specification (VQA-SRS-2026-V1) and ADR benchmarks.
      </p>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 3. INTERACTIVE 5-NODE FSM PIPELINE
 * ----------------------------------------------------------------------- */
interface FSMStepData {
  id: string;
  key: string;
  name: string;
  model: string;
  latency: string;
  inputs: string;
  outputs: string;
  telemetry: string;
  summary: string;
}

const FSM_STEPS: FSMStepData[] = [
  {
    id: "01",
    key: "SENSE",
    name: "Sense",
    model: "Playwright + Meta SAM 3.1",
    latency: "<450ms / viewport",
    inputs: "PR Branch, Dual viewports (375x812, 1440x900), DOM coordinates (cx, cy)",
    outputs: "Binary pixel mask M_SAM, Discrepancy math (Vr = 0.45, IoU = 0.16, Δx = 37px)",
    telemetry: "[00:01.8] SAM 3.1 segmented component visor-el-04: Vr = 0.45 < 0.85 (DEFECT DETECTED)",
    summary:
      "Boots ephemeral Modal container, extracts DOM geometry B_DOM, and prompts SAM 3.1 with center coordinates to compute exact pixel overlap.",
  },
  {
    id: "02",
    key: "TRIAGE",
    name: "Triage",
    model: "DOM LCA + Meta Muse Spark",
    latency: "<600ms",
    inputs: "Defect coordinates, Computed CSS (position, z-index), Repository file tree",
    outputs: "Target file: CheckoutPage.tsx, Protected globs locked: src/components/ui/*",
    telemetry: "[00:03.1] Muse Spark isolated DOM LCA container in 0.52s. Pruned 88.5% context tokens.",
    summary:
      "Walks DOM tree upward to Lowest Common Ancestor. Isolates container layout while strictly protecting shared atomic UI from breaking mutations.",
  },
  {
    id: "03",
    key: "DIAGNOSE",
    name: "Diagnose",
    model: "Meta Muse Wonder",
    latency: "~2.1s",
    inputs: "Red SAM mask overlay, Discrepancy scorecard, Container JSX snapshot",
    outputs: "Pydantic RepairSpec JSON (defect: OCCLUSION, strategy: sticky + padding-bottom)",
    telemetry: "[00:05.4] Muse Wonder issued RepairSpec: fixed banner lacks stacking context relative to Buy CTA",
    summary:
      "Multimodal layout architect analyzes visual overlay and computed styles. Emits structured JSON constraints without writing unguided raw code.",
  },
  {
    id: "04",
    key: "PATCH",
    name: "Patch",
    model: "Meta Muse Code + Modal HMR",
    latency: "~1.2s synth + 0.3s HMR",
    inputs: "RepairSpec JSON, Target file bytes, Anti-hack policy rules (no !important)",
    outputs: "Surgical Unified Diff applied via Hot Module Replacement in 0.3s",
    telemetry: "[00:07.1] Muse Code synthesized 4-line patch. Modal HMR applied in 284ms.",
    summary:
      "Synthesizes minimal unified diff, passes anti-hack CSS screening, and injects patch directly into running Next.js container via HMR.",
  },
  {
    id: "05",
    key: "VERIFY",
    name: "Verify",
    model: "Dual-Viewport Strike Gate",
    latency: "~1.4s re-check",
    inputs: "Running patched app at 375px & 1440px simultaneously, Attempt counter (1/3)",
    outputs: "Vr = 1.00 >= 0.98, IoU = 0.00, Δx = 0px -> PyGithub Verified Commit a8f92d1",
    telemetry: "[00:09.2] Verification PASSED on both viewports. Auto-commit pushed to PR branch.",
    summary:
      "Re-segments both mobile and desktop viewports simultaneously. Verified fixes are auto-committed; unverified attempts loop back up to 3 strikes.",
  },
];

export function Pipeline() {
  const [selectedIdx, setSelectedIdx] = useState<number>(0);
  const activeStep = FSM_STEPS[selectedIdx];

  return (
    <section id="pipeline" aria-label="Pipeline" className="mt-24 scroll-mt-20">
      <SectionHeading
        kicker="01 — DETERMINISTIC FSM PIPELINE"
        title="From webhook to verified fix with zero human clicks."
        body="One pure Python state machine drives five async nodes. Every transition is logged, every metric is recomputed, and loopbacks are strictly bounded."
      />

      {/* 5-Node Interactive Stepper */}
      <div className="mt-8 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {FSM_STEPS.map((step, idx) => {
          const isSelected = idx === selectedIdx;
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setSelectedIdx(idx)}
              className={cn(
                "group relative flex flex-col rounded-md border p-3 text-left transition-all",
                FOCUS,
                isSelected
                  ? "border-text-primary bg-elevated shadow-[0_0_16px_rgba(56,189,248,0.25)]"
                  : "border-border-subtle bg-surface/60 hover:border-text-secondary/40 hover:bg-elevated/40"
              )}
            >
              <div className="flex items-center justify-between font-mono text-xs">
                <span className={cn(isSelected ? "text-cyan-400 font-semibold" : "text-text-muted")}>
                  {step.id}
                </span>
                <span className="text-[10px] text-text-muted">{step.latency}</span>
              </div>
              <p className="mt-1 font-display text-base font-semibold text-text-primary">
                {step.name}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-text-secondary">
                {step.model}
              </p>
              {isSelected && (
                <div className="absolute inset-x-0 -bottom-px h-0.5 bg-gradient-to-r from-cyan-400 via-indigo-400 to-purple-400" />
              )}
            </button>
          );
        })}
      </div>

      {/* Node Inspector Card */}
      <div className="mt-4 rounded-lg border border-border-subtle bg-surface p-5 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-4">
          <div className="flex items-center gap-2">
            <span className="rounded bg-cyan-400/10 px-2 py-0.5 font-mono text-xs font-semibold text-cyan-300 border border-cyan-400/20">
              NODE {activeStep.id} · {activeStep.key}
            </span>
            <span className="font-display font-semibold text-text-primary text-base">
              {activeStep.name} ({activeStep.model})
            </span>
          </div>

          <div className="flex items-center gap-3 font-mono text-xs">
            <span className="text-text-muted">Target Latency:</span>
            <span className="text-text-primary font-semibold">{activeStep.latency}</span>
            <span className="text-text-muted">·</span>
            <span className="inline-flex items-center gap-1 rounded bg-triage-amber/10 px-2 py-0.5 text-triage-amber border border-triage-amber/30 text-[10px] font-semibold">
              <RefreshCw className="h-3 w-3" />
              Strike Loop: Max 3x
            </span>
          </div>
        </div>

        <p className="mt-3 text-sm text-text-secondary leading-relaxed">
          {activeStep.summary}
        </p>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {/* Inputs Box */}
          <div className="rounded border border-border-subtle bg-canvas/60 p-3 font-mono text-xs">
            <span className="text-text-muted block text-[10px] uppercase tracking-wider mb-1">
              Node Inputs & Spatial Constraints
            </span>
            <p className="text-text-secondary leading-relaxed">
              {activeStep.inputs}
            </p>
          </div>

          {/* Outputs Box */}
          <div className="rounded border border-border-subtle bg-canvas/60 p-3 font-mono text-xs">
            <span className="text-cyan-400 block text-[10px] uppercase tracking-wider mb-1">
              Node Outputs & Verified Telemetry
            </span>
            <p className="text-text-primary leading-relaxed font-medium">
              {activeStep.outputs}
            </p>
          </div>
        </div>

        {/* Live Trace Event Simulation */}
        <div className="mt-3 rounded border border-border-subtle bg-canvas/90 px-3.5 py-2.5 font-mono text-xs text-text-secondary flex items-center justify-between">
          <div className="flex items-center gap-2 truncate">
            <Terminal className="h-3.5 w-3.5 text-cyan-400 shrink-0" aria-hidden="true" />
            <span className="truncate text-text-primary">{activeStep.telemetry}</span>
          </div>
          <span className="shrink-0 text-[10px] text-verified-emerald flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />
            Active Trace
          </span>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 4. PRODUCT PROOF (LIVE TRACE + UNIFIED DIFF VIEWER)
 * ----------------------------------------------------------------------- */
const TRACE_EVENTS = [
  {
    timestamp: "00:01.2",
    step: "SENSE",
    message: "DOM bounding boxes extracted (Playwright 375x812 + 1440x900)",
  },
  {
    timestamp: "00:02.4",
    step: "SENSE",
    message: "SAM 3.1 segmented M_SAM for visor-el-04 (Vr = 0.45 < 0.85, IoU = 0.16)",
  },
  {
    timestamp: "00:03.1",
    step: "TRIAGE",
    message: "Muse Spark localized fault to CheckoutPage.tsx (src/ui/ locked)",
  },
  {
    timestamp: "00:05.8",
    step: "DIAGNOSE",
    message: "Muse Wonder issued RepairSpec: fixed banner lacks stacking context",
  },
  {
    timestamp: "00:07.2",
    step: "PATCH",
    message: "Muse Code diff synthesized & applied via Modal HMR in 0.3s",
  },
  {
    timestamp: "00:09.1",
    step: "VERIFY",
    message: "Re-segmented both viewports. Fix committed to the PR branch.",
  },
];

export function ProductProof() {
  return (
    <section id="product" aria-label="Product Proof" className="mt-24 scroll-mt-20">
      <SectionHeading
        kicker="02 — PRODUCT PROOF"
        title="Built for engineers who read diffs, not dashboards."
        body="Mission Control streams the live state machine, the NumPy discrepancy math behind every verdict, and the exact syntax-valid unified diff that fixed it."
      />

      <div className="mt-8 grid grid-cols-1 items-start gap-8 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <h3 className="font-display text-xl font-semibold text-text-primary">
            Watch every strike as it happens
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            The FSM stepper and trace log show which node is computing, what
            the models concluded, and how many strikes remain — streamed over
            native WebSocket the moment a pull request webhook lands.
          </p>
          <div className="mt-4 flex flex-col gap-2 font-mono text-xs text-text-muted">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-verified-emerald" />
              <span>Real-time WebSocket event envelope</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-verified-emerald" />
              <span>Timestamped millisecond latency tracing</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-verified-emerald" />
              <span>Automatic rollback if compile error caught</span>
            </div>
          </div>
          <Link
            href={MISSION_CONTROL_URL}
            className={cn(
              "mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-cyan-400 hover:text-cyan-300",
              FOCUS
            )}
          >
            Open live run inspector
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>

        <div className="lg:col-span-7">
          <LiveTrace
            currentStep="5.VERIFY"
            strikes={1}
            events={TRACE_EVENTS}
          />
        </div>
      </div>

      <div className="mt-12 grid grid-cols-1 items-start gap-8 lg:grid-cols-12">
        <div className="lg:order-2 lg:col-span-5">
          <h3 className="font-display text-xl font-semibold text-text-primary">
            Minimal diffs, verified twice
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            Every repair is a small unified diff against the diagnosed file —
            screened against anti-hack CSS rules, re-verified simultaneously on
            both 375px mobile and 1440px desktop, and auto-committed only when
            both viewports pass.
          </p>
          <div className="mt-4 flex flex-col gap-2 font-mono text-xs text-text-muted">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-verified-emerald" />
              <span>Anti-Hack CSS Policy: Zero !important / z-9999</span>
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-verified-emerald" />
              <span>Dual-Viewport Gate: Zero cross-device regression</span>
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-verified-emerald" />
              <span>PyGithub auto-commit with Markdown diff summary</span>
            </div>
          </div>
        </div>

        <div className="lg:order-1 lg:col-span-7">
          <DiffViewer
            filePath="src/components/PromoBanner.tsx"
            isVerified={true}
          />
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 5. ARCHITECTURE BENTO GRID (5 TECHNICAL PILLARS)
 * ----------------------------------------------------------------------- */
export function ArchitectureBento() {
  const pillars = [
    {
      title: "DOM-Guided SAM 3.1 Prompts",
      kicker: "PILLAR 01 · VISION SENSOR",
      detail:
        "Bypasses blind 4,096-point SAM grid mode by extracting 25–40 interactive DOM bounding boxes and center coordinates (cx, cy) from Playwright, achieving 10.6x faster inference (<450ms) with zero spatial hallucinations.",
      badge: "<450ms Latency",
      span: "lg:col-span-7",
      icon: Scan,
    },
    {
      title: "LCA DOM Hierarchy & Token Pruning",
      kicker: "PILLAR 02 · FAULT LOCALIZATION",
      detail:
        "Algorithms traverse upward to find the Lowest Common Ancestor. Automatically classifies atomic primitives (src/components/ui/*) as immutable and localizes repairs to parent layouts, cutting LLM context by 88.5%.",
      badge: "88.5% Fewer Tokens",
      span: "lg:col-span-5",
      icon: FolderTree,
    },
    {
      title: "Architect-Coder Separation",
      kicker: "PILLAR 03 · SPECIALIZED AGENTS",
      detail:
        "Muse Wonder serves strictly as the visual architect, emitting structured Pydantic RepairSpec JSON. Muse Code strictly synthesizes syntax-valid unified diffs. Unconstrained single-shot LLM code rewriting is prohibited.",
      badge: "Pydantic Schema",
      span: "lg:col-span-4",
      icon: Cpu,
    },
    {
      title: "Sandboxed Runners & Fast HMR",
      kicker: "PILLAR 04 · EXECUTION ENVIRONMENT",
      detail:
        "PR branches boot in isolated Modal cloud containers. Verified patches are injected directly into running Next.js processes via Hot Module Replacement in 0.3s, avoiding 15-second server reboot delays.",
      badge: "0.3s Hot Reload",
      span: "lg:col-span-4",
      icon: Zap,
    },
    {
      title: "Non-Destructive PR Review Fallback",
      kicker: "PILLAR 05 · ENTERPRISE SAFETY",
      detail:
        "If verification fails to reach Vr >= 0.98 after 3 strikes, VisorQA never force-commits to the PR branch. It cleanly halts and posts the highest-scoring candidate patch as a suggested GitHub PR review comment.",
      badge: "3-Strike Cap",
      span: "lg:col-span-4",
      icon: GitPullRequest,
    },
  ];

  return (
    <section id="architecture" aria-label="Architecture Bento Grid" className="mt-24 scroll-mt-20">
      <SectionHeading
        kicker="03 — ARCHITECTURAL PILLARS"
        title="Engineered from first principles for Level 4 autonomy."
        body="Five technical breakthroughs separate VisorQA from generic LLM chat wrappers, ensuring deterministic execution, design-system safety, and reproducible patches."
      />

      <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-12">
        {pillars.map((pillar) => {
          const Icon = pillar.icon;
          return (
            <div
              key={pillar.title}
              className={cn(
                "group relative flex flex-col justify-between rounded-lg border border-border-subtle bg-surface p-6 transition-all duration-200 hover:border-text-secondary/40 hover:bg-elevated/70",
                pillar.span
              )}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-cyan-400">
                    {pillar.kicker}
                  </span>
                  <span className="rounded bg-elevated px-2 py-0.5 font-mono text-[10px] text-text-muted border border-border-subtle">
                    {pillar.badge}
                  </span>
                </div>
                <h3 className="mt-3 font-display text-xl font-semibold text-text-primary group-hover:text-white">
                  {pillar.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  {pillar.detail}
                </p>
              </div>

              <div className="mt-5 flex items-center gap-2 border-t border-border-subtle/80 pt-3 font-mono text-xs text-text-muted">
                <Icon className="h-4 w-4 text-cyan-400" aria-hidden="true" />
                <span>Verified in VQA-ADR-2026-V1</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* ADR Master Trade-Off Matrix */}
      <div className="mt-6 rounded-lg border border-border-subtle bg-surface/70 p-5 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle pb-3">
          <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
            <Cpu className="h-4 w-4 text-cyan-400" />
            <span>ADR Master Trade-Off Matrix (VisorQA vs Conventional Approaches)</span>
          </div>
          <span className="font-mono text-[10px] text-text-muted">ISO 29148 / IEEE 830 Architecture</span>
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 text-xs font-mono">
          <div className="p-3.5 rounded bg-canvas/80 border border-border-subtle hover:border-cyan-500/30 transition-colors">
            <span className="text-cyan-400 font-semibold block mb-1">ADR-001: Webhook Closed-Loop</span>
            <p className="text-text-secondary text-[11px] leading-relaxed">
              Rejected manual browser extensions and chat bots; chosen automated webhook pipeline with &lt;1.2s ingress latency and zero human clicks.
            </p>
          </div>
          <div className="p-3.5 rounded bg-canvas/80 border border-border-subtle hover:border-indigo-500/30 transition-colors">
            <span className="text-indigo-400 font-semibold block mb-1">ADR-002: DOM LCA Triage</span>
            <p className="text-text-secondary text-[11px] leading-relaxed">
              Rejected full-repo Vector DB RAG (28K tokens, 40s cold-start); chosen LCA DOM tree triage with 88.5% context token reduction in 0.6s.
            </p>
          </div>
          <div className="p-3.5 rounded bg-canvas/80 border border-border-subtle hover:border-cyan-500/30 transition-colors">
            <span className="text-cyan-400 font-semibold block mb-1">ADR-003: DOM-Guided SAM 3.1</span>
            <p className="text-text-secondary text-[11px] leading-relaxed">
              Rejected blind 64x64 grid mode (4.8s); chosen DOM point prompts achieving 10.6x speedup (&lt;450ms) and zero spatial hallucinations.
            </p>
          </div>
          <div className="p-3.5 rounded bg-canvas/80 border border-border-subtle hover:border-emerald-500/30 transition-colors">
            <span className="text-emerald-400 font-semibold block mb-1">ADR-004: Architect-Coder + HMR</span>
            <p className="text-text-secondary text-[11px] leading-relaxed">
              Rejected monolithic LLM rewriting and 15s server restarts; chosen Muse Wonder JSON spec + Muse Code diffs with 0.3s Modal HMR.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// Export alias for backward-compatibility
export const Architecture = ArchitectureBento;

/* -------------------------------------------------------------------------
 * 6. ENTERPRISE SAFETY GUARDRAILS
 * ----------------------------------------------------------------------- */
const GUARDRAILS = [
  {
    title: "Three strikes, then halt",
    rule: "BR-1",
    body: "Failed verifications loop back with feedback at most three times. After strike three the run halts and the highest-scoring patch is attached as a GitHub review comment — never force-committed.",
  },
  {
    title: "Untouchable shared UI primitives",
    rule: "BR-2",
    body: "Files under src/components/ui/* (buttons, inputs, radix primitives) are strictly read-only. Faults inside primitives are localized upward to the consuming layout container.",
  },
  {
    title: "Dual-viewport gate",
    rule: "BR-3",
    body: "A fix must simultaneously achieve Vr ≥ 0.98, IoU = 0.00, and Δx ≤ 2px on both 375px mobile and 1440px desktop viewports, preventing cross-viewport regressions.",
  },
  {
    title: "Anti-hack CSS policy",
    rule: "BR-4",
    body: "Synthesized patches containing !important, z-index: 9999 escalations, or content-hiding shortcuts are screened out and rejected by database CHECK constraints.",
  },
  {
    title: "Hard cost ceiling ($0.15/run)",
    rule: "BR-5",
    body: "Each run is hard-capped at $0.15 of model spend, enforced as a database constraint. Typical runs complete for ~$0.03, eliminating runaway spend risks.",
  },
  {
    title: "Signed, verified webhooks",
    rule: "BR-6",
    body: "GitHub webhook payloads are HMAC-SHA256 verified, deduplicated by delivery ID, and acknowledged within the 1.2s acceptance budget.",
  },
];

export function Guardrails() {
  return (
    <section
      id="guardrails"
      aria-label="Enterprise Safety Guardrails"
      className="mt-24 scroll-mt-20"
    >
      <SectionHeading
        kicker="04 — ENTERPRISE GUARDRAILS"
        title="Autonomous, but never unsupervised in effect."
        body="Six hard constraints bound what the agent may attempt, spend, and ship. Safety policy lives in code and database constraints — not in wishful prompting."
      />
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {GUARDRAILS.map((item) => (
          <div
            key={item.title}
            className="rounded-lg border border-border-subtle bg-surface p-5 transition-colors hover:border-text-secondary/30"
          >
            <div className="flex items-center justify-between">
              <span className="rounded bg-verified-emerald/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-verified-emerald border border-verified-emerald/20">
                {item.rule}
              </span>
              <ShieldCheck
                className="h-4 w-4 text-verified-emerald"
                aria-hidden="true"
              />
            </div>
            <p className="mt-3 font-display text-base font-semibold text-text-primary">
              {item.title}
            </p>
            <p className="mt-2 text-xs leading-relaxed text-text-secondary">
              {item.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 7. TECHNICAL FAQ ACCORDION
 * ----------------------------------------------------------------------- */
const FAQS = [
  {
    q: "How does VisorQA detect layout bugs that Playwright and Cypress completely miss?",
    a: "Playwright and Cypress assert against DOM properties: they pass if an element exists in HTML, has CSS attributes, and isn't marked display: none. They cannot tell if a checkout button is covered by a sticky banner or obscured by an overlay. VisorQA pairs Playwright DOM bounding boxes (B_DOM) with Meta SAM 3.1 zero-shot segmentation masks (M_SAM) and evaluates deterministic NumPy math: Visibility Ratio (Vr < 0.85), Sibling Collision (IoU > 0.05), and Viewport Bleed (Δx > 2px).",
  },
  {
    q: "How does VisorQA prevent regressions on other viewports?",
    a: "Every PR branch is rendered simultaneously at 375px (Mobile) and 1440px (Desktop) inside isolated Modal sandboxes. Under Business Rule BR-3, a patch is accepted if and only if Vr >= 0.98, IoU = 0.00, and Δx <= 2px on both viewports simultaneously. If a mobile banner fix breaks a desktop multi-column grid, the dual-viewport gate fails and feeds cross-viewport error coordinates to Strike 2.",
  },
  {
    q: "What happens if the agent cannot resolve a defect within 3 attempts?",
    a: "The 3-Strike safety guardrail immediately terminates the loop. The agent snapshots the highest-scoring candidate patch (best_patch with best_score) and attaches it as a non-destructive GitHub Pull Request review comment with the SAM 3.1 visual overlays. VisorQA never force-commits unverified code to the PR branch.",
  },
  {
    q: "Can VisorQA break our global design system or shared UI components?",
    a: "No. Under Business Rule BR-2, shared UI components (src/components/ui/*, such as atomic buttons and inputs) are strictly read-only during triage. When a button is clipped or occluded, the DOM Lowest Common Ancestor algorithm isolates the parent layout container (CheckoutPage.tsx) or colliding sibling (PromoBanner.tsx), keeping cross-page regression rates below 2.0%.",
  },
  {
    q: "What prevents the AI from using dangerous CSS hacks like !important or z-index: 9999?",
    a: "VisorQA enforces an Anti-Hack CSS Policy (BR-4) at two independent layers: First, the orchestrator parser screens all generated diffs against banned patterns (!important, z-index: 9999, z-[9999]) and rejects unsafe patches before application. Second, the PostgreSQL database enforces a strict CHECK constraint on repair_attempts.unified_diff, making it impossible to persist brittle global overrides.",
  },
  {
    q: "What are the compute and API costs per pull request?",
    a: "Because VisorQA prompts SAM 3.1 with 25–40 DOM center coordinates rather than 4,096 blind grid points, and Muse Spark prunes context tokens by 88.5%, a typical PR run consumes ~3,200 tokens and costs an average of $0.03 in compute and model spend. Furthermore, each run has a hard PostgreSQL CHECK constraint capping total spend at $0.15 USD.",
  },
];

export function Faq() {
  return (
    <section id="faq" aria-label="Frequently Asked Questions" className="mt-24 scroll-mt-20">
      <SectionHeading
        kicker="05 — TECHNICAL FAQ"
        title="Frequently asked engineering questions."
        body="Deep architectural and security answers for engineering leaders and frontend specialists."
      />
      <div className="mt-8 divide-y divide-border-subtle border-y border-border-subtle">
        {FAQS.map((item) => (
          <details key={item.q} className="group py-5">
            <summary
              className={cn(
                "flex cursor-pointer list-none items-center justify-between gap-4 rounded text-left font-display text-base font-semibold text-text-primary [&::-webkit-details-marker]:hidden",
                FOCUS
              )}
            >
              <span>{item.q}</span>
              <span
                aria-hidden="true"
                className="font-mono text-xl leading-none text-cyan-400 transition-transform duration-200 group-open:rotate-45"
              >
                +
              </span>
            </summary>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-text-secondary">
              {item.a}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 8. FINAL CONVERSION CTA
 * ----------------------------------------------------------------------- */
export function FinalCta() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(CLI_CMD);
      } else {
        throw new Error("clipboard unavailable");
      }
    } catch {
      const area = document.createElement("textarea");
      area.value = CLI_CMD;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
      } catch {
        /* fallback */
      }
      document.body.removeChild(area);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section aria-label="Get started with VisorQA" className="mt-24">
      <div className="relative overflow-hidden rounded-lg border border-border-subtle bg-surface px-6 py-12 text-center md:py-16 shadow-2xl">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-400/40 to-transparent"
        />

        <span className="font-mono text-xs uppercase tracking-wider text-cyan-400">
          AUTONOMOUS SELF-HEALING FRONTEND AGENT
        </span>

        <h2 className="mx-auto mt-3 max-w-2xl font-display text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Stop reviewing pixels by hand.
        </h2>

        <p className="mx-auto mt-3 max-w-lg text-base text-text-secondary">
          Connect your repository and let VisorQA catch visual regressions and push verified fixes before your reviewers even notice.
        </p>

        {/* Terminal quickstart snippet */}
        <div className="mx-auto mt-6 flex max-w-md items-center justify-between gap-3 rounded-md border border-border-subtle bg-canvas/90 px-4 py-2.5 font-mono text-xs shadow-inner">
          <div className="flex items-center gap-2 truncate">
            <span className="text-cyan-400 select-none">$</span>
            <span className="truncate text-text-primary">{CLI_CMD}</span>
          </div>
          <button
            type="button"
            onClick={handleCopy}
            aria-label={copied ? "Copied to clipboard" : "Copy command"}
            className={cn(
              "flex items-center gap-1.5 rounded border border-border-subtle bg-elevated px-2 py-1 text-text-secondary hover:text-text-primary",
              FOCUS
            )}
          >
            {copied ? (
              <Check className="h-3 w-3 text-verified-emerald" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
            <span className="text-[10px]">{copied ? "Copied" : "Copy"}</span>
          </button>
        </div>

        {/* Dual Actions */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Link
            href={MISSION_CONTROL_URL}
            className={cn(
              "flex items-center gap-1.5 rounded-md bg-text-primary px-5 py-2.5 text-sm font-semibold text-canvas transition-colors hover:bg-white",
              FOCUS
            )}
          >
            Open Mission Control
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "rounded-md border border-border-subtle bg-surface px-5 py-2.5 text-sm font-medium text-text-secondary transition-colors hover:border-text-secondary/40 hover:text-text-primary",
              FOCUS
            )}
          >
            Read Architecture Spec
          </a>
        </div>

        {/* Trust Badges with Lucide CheckCircle2 */}
        <ul className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 font-mono text-[11px] text-text-muted">
          {[
            "HMAC-SHA256 Webhook",
            "Webhook in <1.2s",
            "$0.03 Typical Run",
            "Max 3x Strike Cap",
            "Zero Hallucination Math",
          ].map((item) => (
            <li key={item} className="flex items-center gap-1.5">
              <CheckCircle2
                className="h-3.5 w-3.5 text-verified-emerald"
                aria-hidden="true"
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------
 * 9. ENTERPRISE FOOTER
 * ----------------------------------------------------------------------- */
export function Footer() {
  const columns = [
    {
      title: "Product",
      links: [
        { label: "Live Mission Control", href: MISSION_CONTROL_URL },
        { label: "Interactive Proof", href: "#demo" },
        { label: "Pipeline Stepper", href: "#pipeline" },
        { label: "Architecture Bento", href: "#architecture" },
        { label: "Safety Guardrails", href: "#guardrails" },
      ],
    },
    {
      title: "Architecture",
      links: [
        { label: "ADR Blueprint", href: REPO_URL },
        { label: "SRS Specification", href: REPO_URL },
        { label: "Technical Design", href: REPO_URL },
        { label: "GitHub Repository", href: REPO_URL },
      ],
    },
    {
      title: "Meta AI Engines",
      links: [
        { label: "Meta SAM 3.1", href: "https://dev.meta.ai" },
        { label: "Meta Muse Spark", href: "https://dev.meta.ai" },
        { label: "Meta Muse Wonder", href: "https://dev.meta.ai" },
        { label: "Meta Muse Code", href: "https://dev.meta.ai" },
      ],
    },
  ];

  return (
    <footer className="mt-24 border-t border-border-subtle bg-canvas">
      <div className="grid grid-cols-2 gap-8 py-12 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-display text-lg font-semibold text-text-primary">
              Visor<span className="text-cyan-400">QA</span>
            </span>
            <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[9px] text-text-muted border border-border-subtle">
              L4 AGENT
            </span>
          </div>
          <p className="mt-3 max-w-xs text-sm leading-relaxed text-text-secondary">
            Autonomous visual QA and closed-loop self-healing agent for frontend pull requests.
          </p>
          <div className="mt-4 flex items-center gap-2 font-mono text-xs text-text-muted">
            <span className="h-2 w-2 rounded-full bg-verified-emerald motion-safe:animate-pulse" />
            <span>Operational · Sub-15s PR verification</span>
          </div>
        </div>

        {columns.map((column) => (
          <nav key={column.title} aria-label={`Footer: ${column.title}`}>
            <p className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
              {column.title}
            </p>
            <ul className="mt-3 space-y-2">
              {column.links.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    {...(link.href.startsWith("http")
                      ? { target: "_blank", rel: "noreferrer" }
                      : {})}
                    className={cn(
                      "rounded text-sm text-text-secondary transition-colors hover:text-text-primary",
                      FOCUS
                    )}
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>

      <div className="flex flex-col gap-3 border-t border-border-subtle py-6 font-mono text-[11px] text-text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>&copy; 2026 VisorQA. Built for the Meta Global AI Developer Hackathon.</p>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-verified-emerald">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            <span>All Systems Operational</span>
          </span>
          <span className="border border-border-subtle bg-surface px-1.5 py-0.5 text-[10px]">
            DEMO VALUES ARE ILLUSTRATIVE
          </span>
        </div>
      </div>
    </footer>
  );
}
