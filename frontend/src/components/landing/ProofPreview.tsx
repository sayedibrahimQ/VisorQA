"use client";

import React, { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Code2,
  ExternalLink,
  GitCommit,
  GitPullRequest,
  Play,
  RotateCcw,
  ShieldCheck,
  Smartphone,
  XCircle,
  Zap,
} from "lucide-react";
import { FOCUS } from "./shared";
import { cn } from "@/lib/utils";

type ViewState = "before" | "after";

export function ProofPreview() {
  const [viewState, setViewState] = useState<ViewState>("before");
  const [isSimulating, setIsSimulating] = useState(false);
  const [activeFsmStep, setActiveFsmStep] = useState<number | null>(null);

  const isPatched = viewState === "after";

  const handleSimulate = () => {
    if (isSimulating) return;
    setIsSimulating(true);
    setViewState("before");

    const steps = [
      { step: 1, delay: 0 },    // SENSE
      { step: 2, delay: 350 },  // TRIAGE
      { step: 3, delay: 700 },  // DIAGNOSE
      { step: 4, delay: 1050 }, // PATCH
      { step: 5, delay: 1400 }, // VERIFY
    ];

    steps.forEach(({ step, delay }) => {
      setTimeout(() => {
        setActiveFsmStep(step);
      }, delay);
    });

    setTimeout(() => {
      setViewState("after");
      setActiveFsmStep(null);
      setIsSimulating(false);
    }, 1800);
  };

  const fsmSteps = [
    { num: "01", name: "Sense", desc: "SAM 3.1" },
    { num: "02", name: "Triage", desc: "Muse Spark" },
    { num: "03", name: "Diagnose", desc: "Muse Wonder" },
    { num: "04", name: "Patch", desc: "Muse Code" },
    { num: "05", name: "Verify", desc: "Dual Viewport" },
  ];

  return (
    <div
      id="demo"
      className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#0A0A0C] shadow-2xl shadow-black/80"
    >
      {/* 1. TOP TOOLBAR: WINDOW CONTROLS WITH VIBRANT MACOS DOTS & WHITE BRAND BUTTON */}
      <div className="flex h-12 items-center justify-between border-b border-white/[0.08] bg-[#111115] px-4">
        {/* Left: Colored Window Dots (Red, Yellow, Green) & Git PR Pill */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            <span
              className="h-3 w-3 rounded-full shadow-sm"
              style={{ backgroundColor: "#FF5F56", boxShadow: "0 0 6px rgba(255, 95, 86, 0.4)" }}
            />
            <span
              className="h-3 w-3 rounded-full shadow-sm"
              style={{ backgroundColor: "#FFBD2E", boxShadow: "0 0 6px rgba(255, 189, 46, 0.4)" }}
            />
            <span
              className="h-3 w-3 rounded-full shadow-sm"
              style={{ backgroundColor: "#27C93F", boxShadow: "0 0 6px rgba(39, 201, 63, 0.4)" }}
            />
          </div>
          <div className="h-3.5 w-px bg-white/10" />
          <div className="flex items-center gap-2 font-mono text-xs text-zinc-300">
            <GitPullRequest className="h-3.5 w-3.5 text-zinc-400 shrink-0" />
            <span className="font-semibold text-white">PR #3</span>
            <span className="text-zinc-600 hidden sm:inline">/</span>
            <span className="text-zinc-400 hidden sm:inline truncate max-w-[200px] md:max-w-none">
              feat/sticky-mobile-offer-banner
            </span>
          </div>
        </div>

        {/* Right: State Segmented Control & Solid White Action Button */}
        <div className="flex items-center gap-3 shrink-0">
          {/* Segmented Switch */}
          <div className="flex items-center rounded-lg border border-white/[0.08] bg-black/40 p-0.5 font-mono text-xs">
            <button
              type="button"
              onClick={() => setViewState("before")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors whitespace-nowrap",
                FOCUS,
                !isPatched
                  ? "bg-rose-500/15 font-medium text-rose-300 border border-rose-500/30"
                  : "text-zinc-400 hover:text-zinc-200"
              )}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
              <span>Before (Defect)</span>
            </button>
            <button
              type="button"
              onClick={() => setViewState("after")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors whitespace-nowrap",
                FOCUS,
                isPatched
                  ? "bg-cyan-500/15 font-medium text-cyan-300 border border-cyan-500/30"
                  : "text-zinc-400 hover:text-zinc-200"
              )}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
              <span>After (Fixed)</span>
            </button>
          </div>

          {/* Primary Action Button: Solid White Brand Identity */}
          <button
            type="button"
            onClick={isPatched ? () => setViewState("before") : handleSimulate}
            disabled={isSimulating}
            className={cn(
              "inline-flex items-center justify-center gap-2 px-4 py-2 min-h-[34px] rounded-lg font-mono text-xs font-semibold whitespace-nowrap shrink-0 select-none transition-all active:scale-[0.98]",
              FOCUS,
              isPatched
                ? "border border-white/20 bg-white/10 text-white hover:bg-white/20 shadow-sm"
                : "bg-white text-black hover:bg-zinc-100 shadow-sm shadow-white/10 disabled:opacity-75 disabled:cursor-wait"
            )}
          >
            {isSimulating ? (
              <>
                <Zap className="h-3.5 w-3.5 animate-spin text-black shrink-0" />
                <span className="leading-none text-black">Healing PR...</span>
              </>
            ) : isPatched ? (
              <>
                <RotateCcw className="h-3.5 w-3.5 text-white shrink-0" />
                <span className="leading-none text-white">Reset View</span>
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 fill-black text-black shrink-0" />
                <span className="leading-none text-black">Simulate Repair</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 2. FSM PROGRESS BAR (Clean & Subdued) */}
      <div className="flex h-9 items-center justify-between border-b border-white/[0.06] bg-[#0E0E12] px-4 font-mono text-xs text-zinc-500">
        <span className="flex items-center gap-2 text-zinc-400 text-[11px]">
          <Zap className="h-3.5 w-3.5 text-zinc-400" />
          <span>FSM Pipeline:</span>
        </span>
        <div className="flex items-center gap-4 sm:gap-6 overflow-x-auto">
          {fsmSteps.map((step, idx) => {
            const stepNum = idx + 1;
            const isActive = activeFsmStep === stepNum;
            const isCompleted = isPatched || (activeFsmStep !== null && activeFsmStep > stepNum);

            return (
              <div
                key={step.name}
                className={cn(
                  "flex items-center gap-1.5 transition-colors text-[11px]",
                  isActive
                    ? "text-indigo-400 font-medium"
                    : isCompleted
                    ? "text-cyan-400 font-medium"
                    : "text-zinc-600"
                )}
              >
                <span
                  className={cn(
                    "flex h-4 w-4 items-center justify-center rounded-full text-[10px] border",
                    isActive
                      ? "border-indigo-400 bg-indigo-500/20 text-indigo-300"
                      : isCompleted
                      ? "border-cyan-500/40 bg-cyan-500/20 text-cyan-300"
                      : "border-zinc-800 bg-zinc-900 text-zinc-600"
                  )}
                >
                  {isCompleted ? "✓" : step.num}
                </span>
                <span>{step.name}</span>
                {idx < fsmSteps.length - 1 && (
                  <ChevronRight className="h-3 w-3 text-zinc-800 hidden sm:inline" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. MAIN WORKBENCH: BALANCED DUAL-COLUMN LAYOUT WITH MATCHING HEIGHTS */}
      <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-white/[0.08]">
        {/* LEFT COLUMN: THE REALISTIC VIEWPORT INSPECTOR (FIXED HEIGHT, NO JUMPS) */}
        <div className="lg:col-span-7 p-4 sm:p-5 flex flex-col justify-between bg-[#08080A] h-[540px]">
          {/* Viewport Meta Info Bar */}
          <div className="flex h-6 items-center justify-between text-xs font-mono text-zinc-400 mb-2 shrink-0">
            <div className="flex items-center gap-2">
              <Smartphone className="h-3.5 w-3.5 text-zinc-400" />
              <span className="font-semibold text-zinc-200">Mobile Safari</span>
              <span className="text-zinc-600">·</span>
              <span className="text-zinc-500 text-[11px]">375 × 812 px · DPR 3.0</span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium border font-mono",
                  isPatched
                    ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-400"
                    : "border-rose-500/30 bg-rose-500/10 text-rose-400"
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    isPatched ? "bg-cyan-400" : "bg-rose-500"
                  )}
                />
                {isPatched ? "Resolved (Strike 1)" : "Defect: Occlusion (Strike 0)"}
              </span>
            </div>
          </div>

          {/* Device Stage Frame: Perfectly locked height, no cut-offs */}
          <div className="flex-1 rounded-lg border border-white/[0.08] bg-[#0E0E12] overflow-hidden shadow-inner flex flex-col justify-between">
            {/* Store Browser Bar */}
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-white/[0.06] bg-[#121217] px-4 font-mono text-xs">
              <div className="flex items-center gap-2 font-medium text-white">
                <span className="text-cyan-400 font-bold">Æ</span>
                <span>Aether Hardware Store</span>
              </div>
              <span className="text-zinc-400 text-[11px]">Cart: $189.00 (1 item)</span>
            </div>

            {/* Target App Content Body */}
            <div className="p-4 flex-1 flex flex-col justify-between overflow-hidden">
              {/* Product Summary Card */}
              <div className="rounded border border-white/[0.06] bg-[#15151B] p-3 text-xs">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-semibold text-white">Aether Cyberdeck v2</div>
                    <div className="text-[11px] text-zinc-400 mt-0.5 font-mono">
                      Neural Edition · 16-Core RISC-V
                    </div>
                  </div>
                  <div className="font-mono font-bold text-white">$189.00</div>
                </div>
                <div className="mt-2.5 pt-2 border-t border-white/[0.06] flex justify-between font-mono text-[11px] text-zinc-400">
                  <span>Order Total (Free 2-Day Shipping)</span>
                  <span className="text-zinc-200 font-semibold font-mono">$189.00</span>
                </div>
              </div>

              {/* ACTION AREA: COLLISION ZONE (FIXED 150PX HEIGHT, ZERO CUT-OFF) */}
              <div className="relative h-[150px] flex flex-col justify-end">
                {isPatched ? (
                  /* HEALED LAYOUT: Banner sits cleanly ABOVE the button */
                  <div className="space-y-2.5 w-full">
                    {/* Healed Banner in Normal Flow */}
                    <div className="rounded border border-cyan-500/40 bg-cyan-500/[0.08] p-2 text-xs font-mono">
                      <div className="flex justify-between items-center text-cyan-300">
                        <span className="font-medium text-[11px]">20% Flash Promo Applied</span>
                        <span className="text-[10px] bg-cyan-500/20 text-cyan-300 px-1.5 py-0.2 rounded border border-cyan-500/30">
                          AETHER20
                        </span>
                      </div>
                      <div className="text-[10px] text-cyan-400/80 mt-0.5 flex justify-between">
                        <span>position: relative (in document flow)</span>
                        <span className="text-zinc-400">#promo-banner [visor-el-04]</span>
                      </div>
                    </div>

                    {/* Unobstructed Primary CTA Button */}
                    <div className="w-full">
                      <div className="h-11 w-full rounded bg-cyan-500 text-black font-mono text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-cyan-500/20">
                        <Check className="h-4 w-4" />
                        <span>Confirm &amp; Pay $189.00</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  /* DEFECT LAYOUT: Fixed banner physically overlaps 45% of the button */
                  <div className="relative w-full h-full flex flex-col justify-end">
                    {/* Target Button (Sitting at bottom - subdued neutral so no clashing colors) */}
                    <div className="w-full h-11 rounded bg-zinc-800 border border-zinc-700/60 text-zinc-400 font-mono text-xs font-bold uppercase tracking-wider flex items-center justify-center opacity-70">
                      <span>Confirm &amp; Pay $189.00</span>
                    </div>

                    {/* Fixed Promo Banner (Positioned directly over the top of the button) */}
                    <div className="absolute inset-x-0 bottom-4 rounded border border-rose-500 bg-[#1A0A0E] p-2 text-xs font-mono shadow-2xl z-20">
                      <div className="flex justify-between items-center text-rose-300">
                        <span className="font-medium text-[11px]">20% Flash Promo Offer</span>
                        <span className="text-[10px] bg-rose-500/20 px-1.5 py-0.2 rounded border border-rose-500/30">
                          AETHER20
                        </span>
                      </div>
                      <div className="text-[10px] text-rose-400/80 mt-0.5 flex justify-between">
                        <span>position: fixed; bottom: 16px;</span>
                        <span className="text-zinc-400">#promo-banner [visor-el-04]</span>
                      </div>
                    </div>

                    {/* DevTools Optical Collision Box (Dashed red box over the intersection) */}
                    <div className="absolute inset-x-0 bottom-0 h-11 border-2 border-dashed border-rose-500 bg-rose-500/20 rounded z-30 pointer-events-none flex items-center justify-center">
                      <span className="bg-black/95 border border-rose-500 text-rose-300 font-mono text-[10px] px-2 py-0.5 rounded shadow-lg flex items-center gap-1 font-semibold">
                        <AlertTriangle className="h-3 w-3 text-rose-400" />
                        <span>Overlap: 45% of button is occluded (IoU = 0.450)</span>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Stage Footer Status Bar */}
            <div className="h-8 shrink-0 border-t border-white/[0.06] bg-[#121217] px-4 flex items-center justify-between font-mono text-[11px] text-zinc-400">
              <span>Target: <code className="text-zinc-200">#checkout-submit-btn</code></span>
              <span className={isPatched ? "text-cyan-400 font-medium" : "text-rose-400 font-medium"}>
                {isPatched ? "✓ Line of sight verified (Vr = 1.000)" : "✗ Blocked on mobile viewports (Vr = 0.550)"}
              </span>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: DEVELOPER TELEMETRY & PR CI INSPECTOR (MATCHING 540PX HEIGHT) */}
        <div className="lg:col-span-5 p-4 sm:p-5 flex flex-col justify-between bg-[#0B0B0E] h-[540px]">
          <div className="space-y-3 flex-1 flex flex-col justify-between">
            {/* 1. GITHUB PR CI CHECKS */}
            <div>
              <div className="flex items-center justify-between text-xs font-mono text-zinc-400 mb-1.5">
                <span className="font-semibold text-zinc-200">Pull Request CI Checks</span>
                <span className="text-zinc-500 text-[11px]">sayedibrahimQ/aether-hardware</span>
              </div>

              <div className="rounded-lg border border-white/[0.08] bg-[#111116] divide-y divide-white/[0.06] text-xs font-mono">
                {/* Traditional DOM Test Check */}
                <div className="p-2.5 flex items-start justify-between gap-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
                      <span className="font-medium text-white text-[11px]">Playwright DOM Check</span>
                    </div>
                    <p className="text-[10px] text-zinc-400">
                      HTML node <code className="text-zinc-300">#checkout-submit-btn</code> is attached in DOM.
                    </p>
                  </div>
                  <span className="rounded bg-cyan-500/15 px-2 py-0.5 text-[10px] font-medium text-cyan-300 shrink-0 border border-cyan-500/30">
                    Passed
                  </span>
                </div>

                {/* VisorQA Optical SAM 3.1 Check */}
                <div className="p-2.5 flex items-start justify-between gap-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      {isPatched ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                      )}
                      <span className="font-medium text-white text-[11px]">VisorQA Optical QA</span>
                    </div>
                    <p className="text-[10px] text-zinc-400">
                      {isPatched
                        ? "Zero pixel collisions detected on 375px and 1440px viewports."
                        : "SAM 3.1 detected 45% occlusion between #promo-banner and button."}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "rounded px-2 py-0.5 text-[10px] font-medium shrink-0 border",
                      isPatched
                        ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/30"
                        : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                    )}
                  >
                    {isPatched ? "Passed" : "Failed"}
                  </span>
                </div>
              </div>
            </div>

            {/* 2. DETERMINISTIC DISCREPANCY MATH TABLE */}
            <div>
              <div className="text-xs font-mono font-semibold text-zinc-200 mb-1.5">
                Deterministic Discrepancy Math
              </div>

              <div className="rounded-lg border border-white/[0.08] bg-[#111116] overflow-hidden text-xs font-mono">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06] bg-white/[0.02] text-zinc-400 text-[10px]">
                      <th className="py-1.5 px-3 font-medium">Metric</th>
                      <th className="py-1.5 px-3 font-medium">Target</th>
                      <th className="py-1.5 px-3 font-medium">Measured</th>
                      <th className="py-1.5 px-3 font-medium text-right">Verdict</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] text-[10px]">
                    <tr>
                      <td className="py-1.5 px-3 text-zinc-300">Visibility Ratio (Vr)</td>
                      <td className="py-1.5 px-3 text-zinc-500">≥ 0.98</td>
                      <td className="py-1.5 px-3 font-semibold text-white">
                        {isPatched ? "1.000" : "0.550"}
                      </td>
                      <td className="py-1.5 px-3 text-right">
                        <span
                          className={cn(
                            "px-1.5 py-0.5 rounded text-[9px] font-medium border",
                            isPatched
                              ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/30"
                              : "bg-rose-500/20 text-rose-300 border-rose-500/30"
                          )}
                        >
                          {isPatched ? "PASS" : "FAIL"}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <td className="py-1.5 px-3 text-zinc-300">Sibling Overlap (IoU)</td>
                      <td className="py-1.5 px-3 text-zinc-500">= 0.00</td>
                      <td className="py-1.5 px-3 font-semibold text-white">
                        {isPatched ? "0.000" : "0.450"}
                      </td>
                      <td className="py-1.5 px-3 text-right">
                        <span
                          className={cn(
                            "px-1.5 py-0.5 rounded text-[9px] font-medium border",
                            isPatched
                              ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/30"
                              : "bg-rose-500/20 text-rose-300 border-rose-500/30"
                          )}
                        >
                          {isPatched ? "PASS" : "FAIL"}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <td className="py-1.5 px-3 text-zinc-300">Viewport Bleed (Δx)</td>
                      <td className="py-1.5 px-3 text-zinc-500">≤ 2.0px</td>
                      <td className="py-1.5 px-3 font-semibold text-white">0.0px</td>
                      <td className="py-1.5 px-3 text-right">
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                          PASS
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 3. SYNTHESIZED GITHUB UNIFIED DIFF */}
            <div>
              <div className="flex items-center justify-between text-xs font-mono text-zinc-400 mb-1.5">
                <span className="font-semibold text-zinc-200">Muse Code Synthesized Patch</span>
                <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                  <GitCommit className="h-3 w-3 text-zinc-400" />
                  <span>visorqa[bot]</span>
                </span>
              </div>

              <div className="rounded-lg border border-white/[0.08] bg-[#0A0A0D] p-2.5 font-mono text-[10px] leading-relaxed overflow-x-auto">
                <div className="text-zinc-500">@@ -28,4 +28,4 @@ src/components/CheckoutPage.tsx</div>
                <div className="text-zinc-400">   id=&quot;promo-banner&quot;</div>
                <div
                  className={cn(
                    "px-1 rounded transition-colors",
                    isPatched ? "text-zinc-600 line-through" : "bg-rose-500/15 text-rose-300 font-medium"
                  )}
                >
                  -  className=&quot;fixed bottom-4 inset-x-4 z-50 ...&quot;
                </div>
                <div
                  className={cn(
                    "px-1 rounded transition-colors",
                    isPatched ? "bg-cyan-500/15 text-cyan-300 font-medium" : "text-zinc-600"
                  )}
                >
                  +  className=&quot;relative mb-3 inset-x-0 ...&quot;
                </div>
              </div>
            </div>
          </div>

          {/* BOTTOM FOOTER: COMMIT STATUS & GITHUB LINK */}
          <div className="h-8 shrink-0 border-t border-white/[0.06] flex items-center justify-between font-mono text-[11px] text-zinc-400 pt-2">
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5 text-cyan-400" />
              <span>Verified &amp; auto-committed by visorqa[bot]</span>
            </span>
            <a
              href="https://github.com/sayedibrahimQ/aether-hardware/pull/3"
              target="_blank"
              rel="noopener noreferrer"
              className="text-zinc-300 hover:text-white flex items-center gap-1 font-medium transition-colors"
            >
              <span>View PR #3</span>
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
