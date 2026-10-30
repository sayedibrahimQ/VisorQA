"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowRight, Menu, Star, X } from "lucide-react";
import { FOCUS, MISSION_CONTROL_URL, REPO_URL } from "./shared";
import { cn } from "@/lib/utils";

export const NAV_LINKS = [
  { label: "Product", href: "#product" },
  { label: "Pipeline", href: "#pipeline" },
  { label: "Architecture", href: "#architecture" },
  { label: "Guardrails", href: "#guardrails" },
  { label: "FAQ", href: "#faq" },
  { label: "Docs", href: REPO_URL, external: true },
];

export function Logo() {
  return (
    <span className="flex items-center gap-2.5" aria-hidden="true">
      <svg
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="shrink-0 transition-transform duration-200 group-hover:scale-105"
      >
        <rect
          x="1.5"
          y="1.5"
          width="25"
          height="25"
          rx="6"
          fill="#111115"
          stroke="#22222A"
          strokeWidth="1.5"
        />
        <rect
          x="2.5"
          y="2.5"
          width="23"
          height="23"
          rx="5"
          stroke="#FAFAFA"
          strokeWidth="1"
          strokeOpacity="0.2"
        />
        {/* Visor horizontal laser scanline */}
        <path
          d="M6 14h16"
          stroke="#00F0FF"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        {/* Central sensor aperture */}
        <circle
          cx="14"
          cy="14"
          r="2.5"
          fill="#0A0A0C"
          stroke="#00F0FF"
          strokeWidth="1.5"
        />
        <circle cx="14" cy="14" r="1" fill="#FAFAFA" />
      </svg>
      <span className="font-display text-lg font-semibold tracking-tight text-text-primary">
        Visor<span className="text-cyan-400">QA</span>
      </span>
    </span>
  );
}

export function Ribbon() {
  return (
    <div
      id="telemetry"
      aria-label="System telemetry"
      className="flex h-8 items-center justify-center gap-2 sm:gap-3 overflow-x-auto whitespace-nowrap border-b border-border-subtle bg-surface/80 px-4 font-mono text-[11px] text-text-secondary backdrop-blur-sm"
    >
      <span className="flex items-center gap-1.5 font-medium text-text-primary">
        <span
          aria-hidden="true"
          className="h-2 w-2 rounded-full bg-verified-emerald motion-safe:animate-pulse"
        />
        L4 AUTONOMOUS
      </span>
      <span aria-hidden="true" className="text-text-muted">
        ·
      </span>
      <span className="hidden sm:inline">SAM 3.1 + MUSE SPARK / WONDER / CODE</span>
      <span aria-hidden="true" className="hidden sm:inline text-text-muted">
        ·
      </span>
      <span className="text-text-secondary">
        COST <span className="font-semibold text-text-primary">$0.03</span> / PR
      </span>
      <span aria-hidden="true" className="text-text-muted">
        ·
      </span>
      <span>
        WEBHOOK <span className="font-semibold text-text-primary">&lt;1.2S</span>
      </span>
      <span aria-hidden="true" className="hidden md:inline text-text-muted">
        ·
      </span>
      <span className="hidden md:inline text-text-muted">
        HMR <span className="text-cyan-400">0.3S</span>
      </span>
    </div>
  );
}

export function SiteHeader() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 h-14 border-b border-border-subtle bg-canvas/85 backdrop-blur-md">
      <div className="mx-auto flex h-full max-w-6xl items-center justify-between gap-4 px-4">
        <Link
          href="#top"
          aria-label="VisorQA home"
          className={cn("group rounded focus:outline-none", FOCUS)}
        >
          <Logo />
        </Link>

        {/* Desktop Navigation */}
        <nav aria-label="Primary" className="hidden items-center gap-6 md:flex">
          {NAV_LINKS.map((item) =>
            item.external ? (
              <a
                key={item.label}
                href={item.href}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "rounded text-sm text-text-secondary transition-colors hover:text-text-primary",
                  FOCUS
                )}
              >
                {item.label}
              </a>
            ) : (
              <Link
                key={item.label}
                href={item.href}
                className={cn(
                  "rounded text-sm text-text-secondary transition-colors hover:text-text-primary",
                  FOCUS
                )}
              >
                {item.label}
              </Link>
            )
          )}
        </nav>

        {/* Desktop CTA actions */}
        <div className="hidden items-center gap-3 md:flex">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Star VisorQA on GitHub"
            className={cn(
              "flex items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 py-1.5 font-mono text-xs text-text-secondary transition-all hover:border-text-secondary/40 hover:bg-elevated hover:text-text-primary",
              FOCUS
            )}
          >
            <Star className="h-3.5 w-3.5 text-triage-amber" aria-hidden="true" />
            <span>Star</span>
          </a>
          <Link
            href={MISSION_CONTROL_URL}
            className={cn(
              "group relative flex items-center gap-1.5 overflow-hidden rounded-md bg-text-primary px-3.5 py-1.5 text-sm font-medium text-canvas shadow-sm transition-all hover:bg-white hover:shadow-cyan-500/10",
              FOCUS
            )}
          >
            <span>Open Mission Control</span>
            <ArrowRight
              className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </Link>
        </div>

        {/* Mobile Hamburger Toggle */}
        <div className="flex items-center gap-2 md:hidden">
          <Link
            href={MISSION_CONTROL_URL}
            className={cn(
              "rounded-md bg-text-primary px-2.5 py-1 text-xs font-medium text-canvas",
              FOCUS
            )}
          >
            Launch
          </Link>
          <button
            type="button"
            aria-expanded={mobileMenuOpen}
            aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            onClick={() => setMobileMenuOpen((open) => !open)}
            className={cn(
              "flex items-center justify-center rounded-md border border-border-subtle bg-surface p-1.5 text-text-secondary hover:text-text-primary",
              FOCUS
            )}
          >
            {mobileMenuOpen ? (
              <X className="h-5 w-5" aria-hidden="true" />
            ) : (
              <Menu className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      {/* Mobile Drawer Menu */}
      {mobileMenuOpen && (
        <div className="absolute inset-x-0 top-14 z-50 border-b border-border-subtle bg-canvas/95 p-4 shadow-2xl backdrop-blur-xl md:hidden">
          <nav className="flex flex-col gap-2">
            {NAV_LINKS.map((item) =>
              item.external ? (
                <a
                  key={item.label}
                  href={item.href}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => setMobileMenuOpen(false)}
                  className="rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-surface hover:text-text-primary"
                >
                  {item.label}
                </a>
              ) : (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setMobileMenuOpen(false)}
                  className="rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-surface hover:text-text-primary"
                >
                  {item.label}
                </Link>
              )
            )}
            <div className="mt-3 flex flex-col gap-2 pt-3 border-t border-border-subtle">
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-center gap-1.5 rounded-md border border-border-subtle bg-surface py-2 font-mono text-xs text-text-secondary"
              >
                <Star className="h-3.5 w-3.5 text-triage-amber" aria-hidden="true" />
                <span>Star on GitHub</span>
              </a>
              <Link
                href={MISSION_CONTROL_URL}
                onClick={() => setMobileMenuOpen(false)}
                className="flex items-center justify-center gap-1.5 rounded-md bg-text-primary py-2 text-sm font-medium text-canvas"
              >
                <span>Open Mission Control</span>
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
