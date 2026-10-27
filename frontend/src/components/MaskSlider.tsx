"use client";

import React, { useState } from "react";
import { Sliders, Eye, EyeOff } from "lucide-react";

interface MaskSliderProps {
  domBoxLabel?: string;
  samMaskLabel?: string;
  vrScore?: number;
  iouScore?: number;
}

export function MaskSlider({
  domBoxLabel = "Expected B_DOM (Playwright)",
  samMaskLabel = "Actual M_SAM (Meta SAM 3.1)",
  vrScore = 0.62,
  iouScore = 0.0,
}: MaskSliderProps) {
  const [sliderPosition, setSliderPosition] = useState<number>(50);
  const [showMask, setShowMask] = useState<boolean>(true);

  return (
    <div className="flex flex-col h-full bg-surface border border-border-subtle rounded-lg overflow-hidden">
      {/* Top Controls Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-subtle bg-elevated/50 text-xs">
        <div className="flex items-center gap-2">
          <Sliders className="w-3.5 h-3.5 text-text-secondary" />
          <span className="font-medium text-text-primary">SAM 3.1 Mask Inspector</span>
        </div>
        <div className="flex items-center gap-3 font-mono">
          <span className="text-text-secondary">V_r: <span className="text-rose-400 font-semibold">{vrScore}</span></span>
          <span className="text-text-secondary">IoU: <span className="text-emerald-400 font-semibold">{iouScore}</span></span>
          <button
            onClick={() => setShowMask(!showMask)}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface border border-border-subtle text-text-secondary hover:text-text-primary"
          >
            {showMask ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            <span>{showMask ? "Overlay ON" : "Overlay OFF"}</span>
          </button>
        </div>
      </div>

      {/* Viewport Canvas Placeholder */}
      <div className="relative flex-1 flex items-center justify-center p-6 bg-canvas/60">
        <div className="w-full max-w-sm aspect-[9/16] max-h-[480px] bg-surface border border-border-subtle rounded-md relative overflow-hidden flex flex-col items-center justify-center">
          <div className="text-xs text-text-muted text-center px-4 font-mono">
            [Viewport Canvas Preview: 375x812]
            <div className="mt-2 text-text-secondary">
              DOM Bounding Box vs. SAM 3.1 Segmented Mask
            </div>
          </div>

          {/* Mask Overlay simulation box */}
          {showMask && (
            <div className="absolute top-20 w-4/5 h-16 border-2 border-dashed border-mask-dom-box bg-mask-defect-fill/30 rounded flex items-center justify-center">
              <span className="text-[10px] font-mono text-cyan-300">visor-el-04 (V_r = {vrScore})</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Slider Control */}
      <div className="p-3 border-t border-border-subtle bg-surface/50 flex items-center gap-4 text-xs">
        <span className="text-text-muted font-mono">{domBoxLabel}</span>
        <input
          type="range"
          min="0"
          max="100"
          value={sliderPosition}
          onChange={(e) => setSliderPosition(Number(e.target.value))}
          className="flex-1 accent-indigo-500 cursor-pointer"
        />
        <span className="text-text-muted font-mono">{samMaskLabel}</span>
      </div>
    </div>
  );
}
