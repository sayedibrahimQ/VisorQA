"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  GitPullRequest,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { CLI_CMD, FOCUS, MISSION_CONTROL_URL } from "./shared";
import { ProofPreview } from "./ProofPreview";
import { cn } from "@/lib/utils";

function useCopy() {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    []
  );

  const copy = useCallback(async (text: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error("clipboard unavailable");
      }
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
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
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  }, []);

  return { copied, copy };
}

export function Hero() {
  const { copied, copy } = useCopy();

  return (
    <section aria-label="Hero" className="relative pt-2 pb-8 sm:pb-12">
      {/* Ambient Directional Lighting & Architectural Mesh Grid */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 left-1/2 -z-10 h-[640px] w-full max-w-7xl -translate-x-1/2 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(0,242,254,0.12),rgba(99,102,241,0.05)_50%,transparent_80%)] animate-ambient-pulse"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(to_right,rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:36px_36px] [mask-image:radial-gradient(ellipse_70%_60%_at_50%_15%,black_40%,transparent_100%)] opacity-70"
      />

      {/* Top Value Prop & Heading Area */}
      <div className="mx-auto max-w-4xl text-center">
        {/* Status Capsule */}
        <div className="inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-surface/90 px-3.5 py-1.5 font-mono text-xs text-text-secondary backdrop-blur-md shadow-sm transition-all hover:border-cyan-500/40">
          <span className="relative flex h-2 w-2">
            <span
              aria-hidden="true"
              className="absolute inline-flex h-full w-full rounded-full bg-verified-emerald opacity-75 animate-ping"
            />
            <span
              aria-hidden="true"
              className="relative inline-flex h-2 w-2 rounded-full bg-verified-emerald motion-safe:animate-pulse"
            />
          </span>
          <span className="font-semibold tracking-wide text-text-primary">
            L4 AUTONOMOUS AGENT
          </span>
          <span className="text-border-strong select-none">/</span>
          <span className="text-cyan-400 font-mono text-[11px] tracking-tight">
            META SAM 3.1 + MUSE
          </span>
          <span className="hidden sm:inline text-border-strong select-none">/</span>
          <span className="hidden sm:inline font-mono text-[11px] text-text-muted">
            PR-FIRST HEALING
          </span>
        </div>

        {/* Display Headline */}
        <h1 className="mt-6 font-display text-4xl font-semibold tracking-tight sm:text-5xl lg:text-6xl lg:leading-[1.12]">
          <span className="bg-gradient-to-b from-white via-white/95 to-zinc-400 bg-clip-text text-transparent">
            Ship UI that catches its own visual regressions.
          </span>
        </h1>

        {/* Cognitive Clarity Subheading */}
        <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg">
          DOM tests pass because the HTML node is attached. But on mobile, a sticky promo banner blocks the buy button. VisorQA pairs Playwright DOM geometry with <span className="text-zinc-200 font-medium">Meta SAM 3.1 pixel segmentation</span> to detect occlusions mathematically and auto-commit verified CSS patches before merge.
        </p>

        {/* Action Group */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            href={MISSION_CONTROL_URL}
            className={cn(
              "group relative flex items-center gap-2 rounded-lg bg-white px-6 py-3 text-sm font-semibold text-black shadow-lg shadow-cyan-500/10 transition-all hover:bg-zinc-100 hover:shadow-cyan-400/25 active:scale-[0.99]",
              FOCUS
            )}
          >
            <span>Launch Mission Control</span>
            <ArrowRight
              className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </Link>

          <a
            href="https://github.com/sayedibrahimQ/aether-hardware/pull/3"
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "flex items-center gap-2 rounded-lg border border-white/10 bg-surface/80 px-5 py-3 text-sm font-medium text-text-secondary backdrop-blur-sm transition-all hover:border-white/25 hover:bg-elevated hover:text-text-primary active:scale-[0.99]",
              FOCUS
            )}
          >
            <GitPullRequest className="h-4 w-4 text-cyan-400" aria-hidden="true" />
            <span>Inspect Live PR #3</span>
            <ExternalLink className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
          </a>

          {/* Quick CLI snippet */}
          <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-surface/60 px-3 py-2 backdrop-blur-sm font-mono text-xs">
            <span className="text-cyan-400 select-none">$</span>
            <span className="text-text-secondary select-all">{CLI_CMD}</span>
            <button
              type="button"
              onClick={() => copy(CLI_CMD)}
              title={copied ? "Copied!" : "Copy command"}
              className="ml-1 p-1 rounded hover:bg-elevated text-text-muted hover:text-text-primary transition-colors"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-verified-emerald" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>

        {/* Trust Signals & Architecture Pillars */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-6 font-mono text-xs text-text-muted">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5 text-verified-emerald" />
            <span>Dual-Viewport (375px & 1440px)</span>
          </div>
          <span className="text-border-strong select-none">·</span>
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
            <span>Zero Spatial Hallucinations (SAM 3.1)</span>
          </div>
          <span className="text-border-strong select-none">·</span>
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-verified-emerald" />
            <span>Deterministic Math Guardrails</span>
          </div>
        </div>
      </div>

      {/* The Hero Centerpiece: State-of-the-Art Optical Telemetry Workbench */}
      <div className="mt-10 sm:mt-12">
        <ProofPreview />
      </div>
    </section>
  );
}
