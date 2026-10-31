"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Layers,
  Monitor,
  ShieldCheck,
  Sliders,
  Smartphone,
  Zap,
} from "lucide-react";
import { FOCUS } from "./shared";
import { cn } from "@/lib/utils";

/** Scale a fixed-width stage down to fit its container (never up). */
function useStageScale(designWidth: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setScale(Math.min(1, el.clientWidth / designWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [designWidth]);

  return { ref, scale };
}

type Viewport = "mobile" | "desktop";

function CheckoutMock({
  viewport,
  patched,
}: {
  viewport: Viewport;
  patched: boolean;
}) {
  const wide = viewport === "desktop";

  return (
    <div className="absolute inset-0 bg-surface text-left" aria-hidden="true">
      {/* Browser Chrome / Header Bar */}
      <div className="flex h-8 items-center gap-1.5 border-b border-border-subtle bg-elevated px-3">
        <span className="h-2 w-2 rounded-full bg-rose-500/70" />
        <span className="h-2 w-2 rounded-full bg-amber-500/70" />
        <span className="h-2 w-2 rounded-full bg-emerald-500/70" />
        <span className="ml-2 h-4 flex-1 truncate rounded bg-canvas px-2 font-mono text-[9px] leading-4 text-text-muted">
          Live repository preview (example layout)
        </span>
        <span className="font-mono text-[9px] text-text-muted">
          {wide ? "1440x900" : "375x812"}
        </span>
      </div>

      <div className={wide ? "flex gap-4 p-4" : "p-4"}>
        {wide && (
          <div className="w-56 shrink-0 space-y-2">
            <div className="font-mono text-[10px] text-text-muted uppercase tracking-wider mb-2">
              Navigation
            </div>
            {["Catalog", "Cart (2 items)", "Payment Methods", "Order History"].map((item, idx) => (
              <div
                key={item}
                className={cn(
                  "rounded border border-border-subtle px-2.5 py-1.5 font-mono text-[10px]",
                  idx === 1
                    ? "bg-elevated font-medium text-text-primary border-cyan-500/30"
                    : "bg-surface text-text-secondary"
                )}
              >
                {item}
              </div>
            ))}
          </div>
        )}

        <div className="relative flex-1">
          {/* Promo Banner: absolute/fixed defect mode vs sticky in-flow mode */}
          <div
            className={cn(
              "rounded border px-3 py-2 transition-all duration-300",
              patched
                ? "relative border-verified-emerald/60 bg-verified-emerald/10 text-verified-emerald"
                : "absolute left-0 right-0 top-5 z-20 border-rose-500/60 bg-elevated text-rose-300 shadow-xl shadow-black/80"
            )}
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-semibold tracking-wide">
                visor-el-04 · STICKY PROMO BANNER
              </span>
              <span className="font-mono text-[9px] opacity-80">
                {patched ? "position: sticky" : "position: fixed (z-50)"}
              </span>
            </div>
            <p className="mt-0.5 text-xs font-medium text-text-primary">
              Promotional banner (example layout)
            </p>
          </div>

          {/* Checkout Order Card */}
          <div
            className={cn(
              "rounded border border-border-subtle bg-canvas p-4 transition-all duration-300",
              patched ? "mt-3" : "mt-2"
            )}
          >
            <div className="flex items-center justify-between border-b border-border-subtle pb-2">
              <span className="font-mono text-[10px] text-text-muted">
                visor-el-09 · ORDER SUMMARY
              </span>
              <span className="font-mono text-[10px] text-emerald-400">$ —</span>
            </div>

            <div className="mt-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <span>Enterprise Autonomous Agent License</span>
                <span className="font-mono text-text-primary">$150.00</span>
              </div>
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <span>Sandboxed Runners (x2)</span>
                <span className="font-mono text-text-primary">$39.00</span>
              </div>
              <div className="h-px bg-border-subtle my-1" />
              <div className="h-2 w-3/4 rounded bg-elevated" />
              <div className="h-2 w-1/2 rounded bg-elevated" />
            </div>

            {/* Pay Now Button */}
            <div className="mt-4 rounded bg-cyan-400 px-3 py-2.5 text-center font-mono text-xs font-semibold text-canvas shadow-sm">
              visor-el-12 · CONFIRM & PAY
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ProofPreview() {
  const [viewport, setViewport] = useState<Viewport>("mobile");
  const [patched, setPatched] = useState(false);
  const [pos, setPos] = useState(55);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const raf = useRef(0);

  const designWidth = viewport === "mobile" ? 375 : 1440;
  const designHeight = viewport === "mobile" ? 440 : 480;
  const { ref: scaleRef, scale } = useStageScale(designWidth);

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const setFromClientX = useCallback((clientX: number) => {
    const el = stageRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pct = ((clientX - rect.left) / rect.width) * 100;
    setPos(Math.min(100, Math.max(0, Math.round(pct))));
  }, []);

  const scheduleFromClientX = useCallback(
    (clientX: number) => {
      cancelAnimationFrame(raf.current);
      raf.current = requestAnimationFrame(() => setFromClientX(clientX));
    },
    [setFromClientX]
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 10 : 2;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setPos((p) => Math.max(0, p - step));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setPos((p) => Math.min(100, p + step));
    } else if (event.key === "Home") {
      event.preventDefault();
      setPos(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setPos(100);
    }
  };

  // Mathematical Trap Scorecard calculated values
  const vrValue = patched ? 1.0 : 0.45;
  const vrPassing = vrValue >= 0.85;

  const iouValue = patched ? 0.0 : 0.16;
  const iouPassing = iouValue <= 0.05;

  const bleedValue = patched ? 0.0 : viewport === "mobile" ? 37.0 : 0.0;
  const bleedPassing = bleedValue <= 2.0;

  return (
    <figure
      id="demo"
      aria-labelledby="demo-caption"
      className="overflow-hidden rounded-lg border border-border-subtle bg-surface shadow-2xl"
    >
      {/* Top Interactive Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle bg-surface/90 px-3 py-2.5">
        {/* Dual Viewport Selector */}
        <div
          role="group"
          aria-label="Preview viewport"
          className="flex items-center gap-1 rounded-md border border-border-subtle bg-canvas p-0.5 text-xs"
        >
          <button
            type="button"
            aria-pressed={viewport === "mobile"}
            onClick={() => setViewport("mobile")}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition-colors",
              FOCUS,
              viewport === "mobile"
                ? "bg-elevated font-medium text-text-primary shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            )}
          >
            <Smartphone className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
            <span>375px Mobile</span>
          </button>
          <button
            type="button"
            aria-pressed={viewport === "desktop"}
            onClick={() => setViewport("desktop")}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition-colors",
              FOCUS,
              viewport === "desktop"
                ? "bg-elevated font-medium text-text-primary shadow-sm"
                : "text-text-secondary hover:text-text-primary"
            )}
          >
            <Monitor className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
            <span>1440px Desktop</span>
          </button>
        </div>

        {/* Patch Switcher Toggle */}
        <div className="flex items-center gap-2.5">
          <span
            id="patch-toggle-label"
            className="font-mono text-xs text-text-secondary"
          >
            Apply Muse Code Patch:
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={patched}
            aria-labelledby="patch-toggle-label"
            onClick={() => setPatched((p) => !p)}
            className={cn(
              "relative h-6 w-11 shrink-0 rounded-full border transition-colors focus:outline-none",
              FOCUS,
              patched
                ? "border-verified-emerald bg-verified-emerald/30 shadow-[0_0_10px_rgba(16,185,129,0.3)]"
                : "border-border-subtle bg-elevated"
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "absolute top-0.5 rounded-full bg-text-primary shadow-md transition-all motion-safe:duration-200",
                patched ? "left-[22px] bg-verified-emerald" : "left-0.5"
              )}
              style={{ height: 16, width: 16 }}
            />
          </button>
          <span
            className={cn(
              "font-mono text-[10px] font-semibold uppercase",
              patched ? "text-verified-emerald" : "text-text-muted"
            )}
          >
            {patched ? "PATCHED" : "BROKEN PR"}
          </span>
        </div>
      </div>

      {/* Main Interactive Stage with Scrubber */}
      <div
        ref={scaleRef}
        className="w-full overflow-hidden bg-canvas relative"
        style={{ height: designHeight * scale }}
      >
        <div
          style={{
            width: designWidth,
            height: designHeight,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
        >
          <div ref={stageRef} className="relative h-full w-full select-none">
            {/* Active Sweeping Photonic Laser Scanline */}
            <div
              className="pointer-events-none absolute inset-x-0 z-20 h-0.5 bg-gradient-to-r from-transparent via-cyan-400 to-transparent shadow-[0_0_12px_#00F2FE] animate-laser-sweep opacity-80"
              aria-hidden="true"
            />

            <CheckoutMock viewport={viewport} patched={patched} />

            {/* SAM 3.1 Mask Layer revealed left of the scrubber */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
              aria-hidden="true"
            >
              {/* Expected DOM Bounding Box (B_DOM) - Dashed Cyan */}
              <div
                className={cn(
                  "absolute left-[6%] right-[6%] rounded border-2 border-dashed transition-colors duration-200",
                  viewport === "desktop" ? "top-[18%] h-[38%]" : "top-[26%] h-[38%]",
                  patched
                    ? "border-verified-emerald/80 bg-verified-emerald/10"
                    : "border-mask-dom-box bg-mask-defect-fill"
                )}
              >
                <div className="absolute -top-3 left-2 bg-canvas px-1.5 font-mono text-[9px] text-cyan-300 border border-border-subtle rounded">
                  B_DOM (Playwright)
                </div>
              </div>

              {/* Defect True Pixel Mask (M_SAM) - Crimson Translucent Fill */}
              {!patched && (
                <div
                  className={cn(
                    "absolute left-[6%] right-[6%] rounded border border-rose-500 bg-rose-500/25",
                    viewport === "desktop" ? "top-[22%] h-[24%]" : "top-[28%] h-[28%]"
                  )}
                >
                  <div className="absolute top-1 right-2 bg-rose-950/90 text-rose-300 px-1.5 py-0.5 rounded font-mono text-[9px] border border-rose-500/40">
                    M_SAM Collision Mask (IoU = 0.16)
                  </div>
                </div>
              )}
            </div>

            {/* Draggable Scrubber Divider Line */}
            <div
              className="absolute inset-y-0 w-0.5 bg-gradient-to-b from-cyan-400 via-white to-cyan-400 shadow-[0_0_8px_rgba(56,189,248,0.5)]"
              style={{ left: `${pos}%` }}
              aria-hidden="true"
            />

            {/* Draggable Scrubber Handle */}
            <div
              role="slider"
              tabIndex={0}
              aria-label="Reveal simulated SAM mask over DOM geometry"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(pos)}
              aria-valuetext={`${Math.round(pos)} percent mask revealed`}
              onKeyDown={onKeyDown}
              onPointerDown={(e) => {
                dragging.current = true;
                e.currentTarget.setPointerCapture(e.pointerId);
                setFromClientX(e.clientX);
              }}
              onPointerMove={(e) => {
                if (dragging.current) scheduleFromClientX(e.clientX);
              }}
              onPointerUp={() => {
                dragging.current = false;
              }}
              onPointerCancel={() => {
                dragging.current = false;
              }}
              className={cn(
                "absolute top-1/2 z-30 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize select-none rounded-full border border-border-focus bg-canvas px-2.5 py-1 font-mono text-[10px] font-semibold text-text-primary shadow-xl backdrop-blur-md",
                FOCUS
              )}
              style={{ left: `${pos}%`, touchAction: "none" }}
            >
              <span className="flex items-center gap-1">
                <Sliders className="h-3 w-3 text-cyan-400" />
                <span>{Math.round(pos)}%</span>
              </span>
            </div>

            {/* Live Verdict Pill Badges */}
            <div className="absolute left-3 top-10 z-20 flex flex-col gap-1.5">
              <span className="rounded border border-verified-emerald/60 bg-canvas/90 px-2 py-0.5 font-mono text-[10px] text-verified-emerald shadow-sm">
                Playwright DOM: PASS (HTML Exists)
              </span>
              <span
                aria-live="polite"
                className={cn(
                  "rounded border px-2 py-0.5 font-mono text-[10px] shadow-sm backdrop-blur-sm",
                  patched
                    ? "border-verified-emerald/80 bg-canvas/90 text-verified-emerald"
                    : "border-rose-500/80 bg-canvas/90 text-rose-400"
                )}
              >
                {patched
                  ? "SAM 3.1: V_r = 1.00 RESOLVED"
                  : "SAM 3.1: V_r = 0.45 FAIL (Occlusion)"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Live Mathematical Trap Scorecard */}
      <div className="border-t border-border-subtle bg-surface/95 p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5 font-mono text-xs font-medium text-text-primary">
            <Layers className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
            <span>Deterministic Mathematical Scorecard (NumPy)</span>
          </div>
          <span className="font-mono text-[10px] text-text-muted">
            Formula: H = Vr - max(IoU) - 0.01·Δx
          </span>
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {/* Card 1: Visibility Ratio Vr */}
          <div className="rounded border border-border-subtle bg-canvas/70 p-2.5 font-mono text-xs">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">1. Occlusion Trap</span>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                  vrPassing
                    ? "border border-verified-emerald/40 bg-verified-emerald/10 text-verified-emerald"
                    : "border border-rose-500/40 bg-rose-500/10 text-rose-400"
                )}
              >
                {vrPassing ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : (
                  <AlertTriangle className="h-3 w-3" />
                )}
                {vrPassing ? "PASS" : "FAIL (Vr < 0.85)"}
              </span>
            </div>
            <p className="mt-1 font-semibold text-text-primary">
              V_r = {vrValue.toFixed(2)}{" "}
              <span className="text-[11px] font-normal text-text-muted">
                (target: &ge; 0.98)
              </span>
            </p>
            <p className="text-[10px] text-text-muted">
              Area(M_SAM &cap; B_DOM) / Area(B_DOM)
            </p>
          </div>

          {/* Card 2: Sibling Collision IoU */}
          <div className="rounded border border-border-subtle bg-canvas/70 p-2.5 font-mono text-xs">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">2. Collision Trap</span>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                  iouPassing
                    ? "border border-verified-emerald/40 bg-verified-emerald/10 text-verified-emerald"
                    : "border border-rose-500/40 bg-rose-500/10 text-rose-400"
                )}
              >
                {iouPassing ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : (
                  <AlertTriangle className="h-3 w-3" />
                )}
                {iouPassing ? "PASS" : "FAIL (IoU > 0.05)"}
              </span>
            </div>
            <p className="mt-1 font-semibold text-text-primary">
              IoU = {iouValue.toFixed(2)}{" "}
              <span className="text-[11px] font-normal text-text-muted">
                (target: 0.00)
              </span>
            </p>
            <p className="text-[10px] text-text-muted">
              Area(Mi &cap; Mj) / Area(Mi &cup; Mj)
            </p>
          </div>

          {/* Card 3: Viewport Bleed Delta X */}
          <div className="rounded border border-border-subtle bg-canvas/70 p-2.5 font-mono text-xs">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">3. Viewport Bleed</span>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                  bleedPassing
                    ? "border border-verified-emerald/40 bg-verified-emerald/10 text-verified-emerald"
                    : "border border-rose-500/40 bg-rose-500/10 text-rose-400"
                )}
              >
                {bleedPassing ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : (
                  <AlertTriangle className="h-3 w-3" />
                )}
                {bleedPassing ? "PASS" : "FAIL (&Delta;x > 2px)"}
              </span>
            </div>
            <p className="mt-1 font-semibold text-text-primary">
              &Delta;_x = {bleedValue.toFixed(1)}px{" "}
              <span className="text-[11px] font-normal text-text-muted">
                (target: &le; 2.0px)
              </span>
            </p>
            <p className="text-[10px] text-text-muted">
              max(0, X_max(B_DOM) - W_viewport)
            </p>
          </div>
        </div>
      </div>

      <figcaption
        id="demo-caption"
        className="flex items-center justify-between border-t border-border-subtle px-3 py-2 font-mono text-[11px] text-text-muted bg-surface"
      >
        <span className="flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-verified-emerald" aria-hidden="true" />
          <span>Dual-Viewport Proof Engine (BR-3 verified)</span>
        </span>
        <span>Drag scrubber to inspect pixel mask discrepancy</span>
      </figcaption>
    </figure>
  );
}
