"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Copy, Sparkles } from "lucide-react";
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
        /* fallback failed; feedback still shown */
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
    <div className="relative">
      {/* Photonic Laser ambient background glow and coordinate blueprint grid */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-20 left-1/2 -z-10 h-[560px] w-full max-w-6xl -translate-x-1/2 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(0,242,254,0.15),transparent_70%)] animate-ambient-pulse"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(to_right,#1a1a21_1px,transparent_1px),linear-gradient(to_bottom,#1a1a21_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_75%_70%_at_50%_0%,black,transparent)] opacity-80"
      />

      <div className="relative grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-8">
        {/* Left Column: Typography and CTAs */}
        <div className="lg:col-span-6 lg:pr-2">
          {/* Autonomy Badge with Radar Ping */}
          <div className="inline-flex items-center gap-2.5 rounded-full border border-border-subtle bg-surface/90 px-3.5 py-1.5 font-mono text-xs text-text-secondary backdrop-blur-md shadow-sm">
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
            <span className="tracking-wide">AUTONOMOUS VISUAL QA · L4 AGENT</span>
            <span className="text-border-strong">/</span>
            <span className="text-laser-cyan font-mono text-[11px]">SAM 3.1 + MUSE</span>
          </div>

          {/* Vercel-inspired Gradient Heading */}
          <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl lg:text-[3.25rem]">
            <span className="bg-gradient-to-b from-white via-white/95 to-white/60 bg-clip-text text-transparent">
              Ship UI that heals its own pixel regressions.
            </span>
          </h1>

          {/* High-Impact Subheading */}
          <p className="mt-5 text-base leading-relaxed text-text-secondary md:text-lg">
            VisorQA renders every pull request on mobile and desktop,
            segments components with Meta SAM 3.1, and scores visibility and
            collision math. Muse Spark triages the fault, Muse Wonder
            diagnoses the cause, and Muse Code proposes a minimal patch —
            verified before anything lands.
          </p>

          {/* Dual CTAs */}
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href={MISSION_CONTROL_URL}
              className={cn(
                "group relative flex items-center gap-2 rounded-md bg-text-primary px-5 py-2.5 text-sm font-semibold text-canvas shadow-lg shadow-white/5 transition-all hover:bg-white hover:shadow-cyan-500/20 active:scale-[0.99]",
                FOCUS
              )}
            >
              <span>Start Self-Healing</span>
              <ArrowRight
                className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            </Link>

            <Link
              href="#demo"
              className={cn(
                "flex items-center gap-2 rounded-md border border-border-subtle bg-surface px-5 py-2.5 text-sm font-medium text-text-secondary transition-all hover:border-text-secondary/40 hover:bg-elevated hover:text-text-primary",
                FOCUS
              )}
            >
              <span>View Live Demo</span>
            </Link>
          </div>

          {/* Interactive Quickstart CLI Terminal Snippet */}
          <div
            id="quickstart"
            className="mt-6 flex max-w-md items-center justify-between gap-3 rounded-md border border-border-subtle bg-surface/90 px-3.5 py-2.5 shadow-inner backdrop-blur-sm"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span aria-hidden="true" className="font-mono text-sm text-cyan-400 select-none">
                $
              </span>
              <code className="truncate font-mono text-xs sm:text-sm text-text-primary">
                {CLI_CMD}
              </code>
            </div>

            <button
              type="button"
              onClick={() => copy(CLI_CMD)}
              aria-label={
                copied ? "Copied to clipboard" : "Copy install command"
              }
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded border border-border-subtle bg-elevated px-2.5 py-1.5 font-mono text-xs text-text-secondary transition-colors hover:border-text-secondary/40 hover:text-text-primary",
                FOCUS
              )}
            >
              {copied ? (
                <Check
                  className="h-3.5 w-3.5 text-verified-emerald"
                  aria-hidden="true"
                />
              ) : (
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              <span aria-live="polite" className="text-[11px]">
                {copied ? "Copied" : "Copy"}
              </span>
            </button>
          </div>

          {/* Subtext Trust Markers */}
          <div className="mt-4 flex items-center gap-4 font-mono text-[11px] text-text-muted">
            <span className="flex items-center gap-1">
              <Sparkles className="h-3 w-3 text-cyan-400" aria-hidden="true" />
              Zero-Shot SAM 3.1
            </span>
            <span>·</span>
            <span>&lt;15s Cycle Time</span>
            <span>·</span>
            <span>$0.03 / PR</span>
          </div>
        </div>

        {/* Right Column: Embedded Interactive Proof Sandbox */}
        <div className="lg:col-span-6">
          <ProofPreview />
        </div>
      </div>
    </div>
  );
}
