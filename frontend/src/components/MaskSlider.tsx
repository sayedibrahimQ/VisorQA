"use client";

import React, { useState } from "react";
import { Sliders, Eye, EyeOff, Smartphone, Monitor } from "lucide-react";

interface MaskSliderProps {
  domBoxLabel?: string;
  samMaskLabel?: string;
  vrScore?: number;
  iouScore?: number;
  viewport?: "mobile" | "desktop";
  onViewportChange?: (vp: "mobile" | "desktop") => void;
}

export function MaskSlider({
  domBoxLabel = "Expected B_DOM (Playwright)",
  samMaskLabel = "Actual M_SAM (Meta SAM 3.1)",
  vrScore = 0.62,
  iouScore = 0.0,
  viewport: controlledViewport,
  onViewportChange,
}: MaskSliderProps) {
  const [sliderPosition, setSliderPosition] = useState<number>(50);
  const [showMask, setShowMask] = useState<boolean>(true);
  const [internalViewport, setInternalViewport] = useState<"mobile" | "desktop">("mobile");

  const activeViewport = controlledViewport || internalViewport;
  const setViewport = (vp: "mobile" | "desktop") => {
    setInternalViewport(vp);
    if (onViewportChange) onViewportChange(vp);
  };

  const isDesktop = activeViewport === "desktop";

  return (
    <div className="flex flex-col h-full bg-surface border border-border-subtle rounded-lg overflow-hidden shadow-xl">
      {/* Top Controls Header */}
      <div className="flex flex-wrap items-center justify-between px-4 py-2.5 border-b border-border-subtle bg-elevated/70 text-xs gap-2">
        <div className="flex items-center gap-2">
          <Sliders className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-medium text-text-primary">SAM 3.1 Mask Inspector</span>
        </div>

        {/* Viewport Segmented Selector */}
        <div className="flex items-center gap-1 rounded border border-border-subtle bg-canvas p-0.5 font-mono text-[11px]">
          <button
            type="button"
            onClick={() => setViewport("mobile")}
            className={`flex items-center gap-1 px-2 py-0.5 rounded transition-colors ${
              !isDesktop ? "bg-elevated text-cyan-300 font-semibold" : "text-text-muted hover:text-text-primary"
            }`}
          >
            <Smartphone className="w-3 h-3" />
            <span>375px</span>
          </button>
          <button
            type="button"
            onClick={() => setViewport("desktop")}
            className={`flex items-center gap-1 px-2 py-0.5 rounded transition-colors ${
              isDesktop ? "bg-elevated text-cyan-300 font-semibold" : "text-text-muted hover:text-text-primary"
            }`}
          >
            <Monitor className="w-3 h-3" />
            <span>1440px</span>
          </button>
        </div>

        <div className="flex items-center gap-3 font-mono">
          <span className="text-text-secondary text-[11px]">
            V_r: <span className={vrScore >= 0.85 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>{vrScore.toFixed(2)}</span>
          </span>
          <span className="text-text-secondary text-[11px]">
            IoU: <span className={iouScore <= 0.05 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>{iouScore.toFixed(2)}</span>
          </span>
          <button
            type="button"
            onClick={() => setShowMask(!showMask)}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface border border-border-subtle text-text-secondary hover:text-text-primary hover:border-cyan-500/40 transition-colors"
          >
            {showMask ? <Eye className="w-3 h-3 text-cyan-400" /> : <EyeOff className="w-3 h-3" />}
            <span className="text-[11px]">{showMask ? "Overlay ON" : "Overlay OFF"}</span>
          </button>
        </div>
      </div>

      {/* Viewport Canvas Stage */}
      <div className="relative flex-1 flex items-center justify-center p-4 bg-canvas/90 overflow-hidden">
        {/* Optical blueprint background grid */}
        <div
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:24px_24px]"
          aria-hidden="true"
        />

        {/* Viewport Frame */}
        <div
          className={`bg-surface border border-border-subtle rounded-md relative overflow-hidden flex flex-col transition-all duration-300 shadow-2xl ${
            isDesktop ? "w-full max-w-2xl h-[420px]" : "w-full max-w-xs h-[420px]"
          }`}
        >
          {/* Active Photonic Laser Scanline */}
          <div
            className="pointer-events-none absolute inset-x-0 z-20 h-0.5 bg-gradient-to-r from-transparent via-cyan-400 to-transparent shadow-[0_0_12px_#00F2FE] animate-laser-sweep opacity-85"
            aria-hidden="true"
          />

          {/* Simulated App Header */}
          <div className="h-7 border-b border-border-subtle bg-elevated px-3 flex items-center justify-between text-[10px] font-mono text-text-muted">
            <span className="truncate">app preview · checkout (example)</span>
            <span>{isDesktop ? "1440x900" : "375x812"}</span>
          </div>

          {/* Simulated Content with Mask Overlays */}
          <div className="p-3 flex-1 relative flex flex-col gap-2 font-mono text-xs">
            {/* Promo Banner with Collision */}
            <div className="relative rounded border border-rose-500/50 bg-elevated p-2 text-rose-300 shadow-sm">
              <div className="flex items-center justify-between text-[9px]">
                <span className="font-semibold text-rose-400">visor-el-04 · PromoBanner</span>
                <span className="text-text-muted">position: fixed</span>
              </div>
              <p className="mt-0.5 text-[11px] text-text-primary truncate">
                Promotional banner (example layout)
              </p>
            </div>

            {/* Target Element / Checkout Button Card */}
            <div className="rounded border border-border-subtle bg-canvas/80 p-3 flex-1 flex flex-col justify-between">
              <div className="space-y-1.5 text-[11px] text-text-secondary">
                <div className="flex justify-between">
                  <span>Order Items (2)</span>
                  <span className="text-text-primary">$ —</span>
                </div>
                <div className="flex justify-between text-text-muted text-[10px]">
                  <span>Autonomous Agent Runner</span>
                  <span>Active</span>
                </div>
              </div>

              {/* Confirm Button */}
              <div className="mt-3 rounded bg-cyan-500/20 border border-cyan-400/40 p-2 text-center text-cyan-300 font-semibold text-[11px]">
                visor-el-09 · CONFIRM & PAY
              </div>
            </div>

            {/* SAM 3.1 & DOM Overlays based on slider and toggle */}
            {showMask && (
              <div
                className="pointer-events-none absolute inset-0 transition-opacity duration-200"
                style={{ opacity: sliderPosition / 100 }}
              >
                {/* Expected B_DOM (Playwright) - Dashed Cyan */}
                <div className="absolute top-10 left-3 right-3 h-14 border-2 border-dashed border-mask-dom-box bg-mask-defect-fill/20 rounded flex items-start justify-between p-1">
                  <span className="text-[9px] font-mono text-cyan-300 bg-canvas/90 px-1 rounded border border-border-subtle">
                    B_DOM (Playwright)
                  </span>
                  <span className="text-[9px] font-mono text-rose-400 bg-canvas/90 px-1 rounded border border-border-subtle">
                    V_r = {vrScore} FAIL
                  </span>
                </div>

                {/* Actual M_SAM (Meta SAM 3.1) - Crimson Defect Mask */}
                <div className="absolute top-12 left-5 right-5 h-10 border border-rose-500 bg-rose-500/30 rounded flex items-center justify-center shadow-lg">
                  <span className="text-[9px] font-mono text-rose-200 bg-rose-950/80 px-1.5 py-0.5 rounded border border-rose-500/50">
                    M_SAM Segmented Defect Mask
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Slider Control */}
      <div className="px-4 py-2.5 border-t border-border-subtle bg-surface/60 flex items-center gap-4 text-xs">
        <span className="text-text-muted font-mono text-[11px] truncate max-w-[160px]">{domBoxLabel}</span>
        <input
          type="range"
          min="0"
          max="100"
          value={sliderPosition}
          onChange={(e) => setSliderPosition(Number(e.target.value))}
          className="flex-1 accent-cyan-400 cursor-pointer h-1.5 bg-elevated rounded-lg"
          aria-label="SAM Mask Opacity Slider"
        />
        <span className="text-text-muted font-mono text-[11px] truncate max-w-[160px]">{samMaskLabel}</span>
      </div>
    </div>
  );
}
