"use client";

import React, { memo, useCallback, useId, useRef, useState } from "react";
import {
  Eye,
  EyeOff,
  GripVertical,
  Monitor,
  Smartphone,
  SplitSquareHorizontal,
  Square,
} from "lucide-react";
import {
  DOM_BOX_STROKE,
  SAM_MASK_FILL,
  SAM_MASK_OPACITY,
  VIEWPORT_SPECS,
  formatMetric,
  type HMRInfo,
  type StageBox,
  type StageElement,
  type StageMask,
  type ViewportName,
  type ViewportPanelData,
  type ViewportSpec,
  type ViewportVerification,
} from "@/lib/viewportArtifacts";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";

export interface DualViewportStageProps {
  runId: string | null;
  runLabel: string | null;
  mobile: ViewportPanelData;
  desktop: ViewportPanelData;
  hmr: HMRInfo | null;
  untaggedCount?: number;
  loading?: boolean;
  error?: string | null;
  initialViewport?: ViewportName;
  className?: string;
  /** Strike scrubber (Workstream 3): baseline + strike options. */
  attempts?: { attemptNumber: number; label: string }[];
  selectedAttempt?: number;
  onAttemptChange?: (attemptNumber: number) => void;
  /** Real sandbox provider + HMR latency for the selected attempt. */
  sandboxProvider?: string | null;
  hmrLatencyMs?: number | null;
}

interface HoverTarget {
  viewport: ViewportName;
  id: string;
}

function sameTarget(a: HoverTarget | null, viewport: ViewportName, id: string): boolean {
  return a !== null && a.viewport === viewport && a.id === id;
}

function clampPosition(p: number): number {
  return Math.min(100, Math.max(0, Math.round(p * 10) / 10));
}

// ---------------------------------------------------------------------------
// SVG overlays (memoized: scrubber drags must not rebuild this tree)
// ---------------------------------------------------------------------------

interface OverlaySvgProps {
  spec: ViewportSpec;
  elements: StageElement[];
  showBoxes: boolean;
  showMasks: boolean;
  showLabels: boolean;
  hoveredId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  idPrefix: string;
}

function MaskShape({ mask, spec, idPrefix, index, linked, dimmed }: {
  mask: StageMask;
  spec: ViewportSpec;
  idPrefix: string;
  index: number;
  linked: boolean;
  dimmed: boolean;
}) {
  const opacity = dimmed ? SAM_MASK_OPACITY * 0.45 : linked ? Math.min(0.6, SAM_MASK_OPACITY + 0.2) : SAM_MASK_OPACITY;
  if (mask.kind === "polygon") {
    return (
      <polygon
        points={mask.points.map((p) => `${p.x},${p.y}`).join(" ")}
        fill={SAM_MASK_FILL}
        opacity={opacity}
        stroke={linked ? SAM_MASK_FILL : "none"}
        strokeWidth={linked ? 1.5 : 0}
      />
    );
  }
  if (mask.kind === "contour") {
    return (
      <polyline
        points={mask.points.map((p) => `${p.x},${p.y}`).join(" ")}
        fill={SAM_MASK_FILL}
        opacity={opacity}
        stroke={SAM_MASK_FILL}
        strokeWidth={1.5}
      />
    );
  }
  // Raster binary mask: exact-viewport PNG applied as a luminance mask over a
  // crimson rect, so source colors never leak and no geometry is invented.
  const maskId = `${idPrefix}-m-${index}`;
  return (
    <>
      <mask id={maskId}>
        <image
          href={mask.url}
          x={0}
          y={0}
          width={spec.width}
          height={spec.height}
          preserveAspectRatio="none"
        />
      </mask>
      <rect
        x={0}
        y={0}
        width={spec.width}
        height={spec.height}
        fill={SAM_MASK_FILL}
        opacity={opacity}
        mask={`url(#${maskId})`}
      />
    </>
  );
}

const OverlaySvg = memo(function OverlaySvg({
  spec,
  elements,
  showBoxes,
  showMasks,
  showLabels,
  hoveredId,
  selectedId,
  onHover,
  onSelect,
  idPrefix,
}: OverlaySvgProps) {
  return (
    <svg
      data-testid={`overlay-svg-${spec.name}`}
      viewBox={`0 0 ${spec.width} ${spec.height}`}
      className="absolute inset-0 h-full w-full"
      role="group"
      aria-label={`${spec.name} defect overlays`}
      preserveAspectRatio="none"
    >
      {elements.map((el, elIndex) => {
        const linked = hoveredId === el.id || selectedId === el.id;
        const dimmed = (hoveredId !== null && hoveredId !== el.id) || (selectedId !== null && selectedId !== el.id && hoveredId === null);
        return (
          <g key={el.id}>
            {showMasks
              ? el.masks.map((mask, i) => (
                  <g
                    key={i}
                    data-testid={`sam-mask-${spec.name}-${el.id}`}
                    data-kind={mask.kind}
                    opacity={dimmed ? 0.5 : 1}
                  >
                    <MaskShape
                      mask={mask}
                      spec={spec}
                      idPrefix={`${idPrefix}-${elIndex}`}
                      index={i}
                      linked={linked}
                      dimmed={dimmed}
                    />
                  </g>
                ))
              : null}
            {showBoxes && el.box ? (
              <g>
                <rect
                  data-testid={`dom-box-${spec.name}-${el.id}`}
                  x={el.box.x}
                  y={el.box.y}
                  width={el.box.width}
                  height={el.box.height}
                  fill="transparent"
                  stroke={DOM_BOX_STROKE}
                  strokeWidth={selectedId === el.id ? 2.5 : hoveredId === el.id ? 2.5 : 1.5}
                  strokeDasharray={selectedId === el.id ? "none" : "7 4"}
                  opacity={dimmed ? 0.45 : 1}
                  tabIndex={0}
                  role="button"
                  aria-label={`${el.id}, ${el.defectType ?? "defect status unknown"}${selectedId === el.id ? ", selected" : ""}`}
                  style={{ cursor: "pointer", outline: "none" }}
                  onMouseEnter={() => onHover(el.id)}
                  onMouseLeave={() => onHover(null)}
                  onFocus={() => onHover(el.id)}
                  onBlur={() => onHover(null)}
                  onClick={() => onSelect(el.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(el.id);
                    }
                  }}
                />
                {showLabels ? (
                  <text
                    data-testid={`dom-label-${spec.name}-${el.id}`}
                    x={Math.min(el.box.x + 3, spec.width - 4)}
                    y={Math.max(el.box.y - 5, 11)}
                    fill={DOM_BOX_STROKE}
                    fontSize={11}
                    fontFamily="monospace"
                    opacity={dimmed ? 0.5 : 0.95}
                    style={{ pointerEvents: "none" }}
                  >
                    {el.id}
                  </text>
                ) : null}
              </g>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
});

// ---------------------------------------------------------------------------
// Tooltip readout (follows the hovered element, clamped inside the stage)
// ---------------------------------------------------------------------------

function MetricRow({ label, value, suffix }: { label: string; value: string | null; suffix?: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-text-muted">{label}</dt>
      <dd className={value === null ? "text-text-muted" : "text-text-primary"}>
        {value === null ? "—" : `${value}${suffix ?? ""}`}
      </dd>
    </div>
  );
}

const ElementTooltip = memo(function ElementTooltip({
  element,
  spec,
  verificationStatus,
}: {
  element: StageElement;
  spec: ViewportSpec;
  verificationStatus: string | null;
}) {
  const box: StageBox = element.box ?? { x: spec.width / 2 - 40, y: spec.height / 2 - 20, width: 80, height: 40 };
  const leftPct = Math.min(92, Math.max(8, ((box.x + box.width / 2) / spec.width) * 100));
  const above = box.y / spec.height > 0.28;
  const topPct = above ? (box.y / spec.height) * 100 : ((box.y + box.height) / spec.height) * 100;
  return (
    <div
      data-testid="element-tooltip"
      data-element-id={element.id}
      role="status"
      aria-label={`Details for ${element.id}`}
      className="pointer-events-none absolute z-30 w-52 rounded-md border border-border-strong bg-elevated px-2.5 py-2 font-mono text-[11px] leading-5 shadow-xl"
      style={{
        left: `${leftPct}%`,
        top: `${topPct}%`,
        transform: above ? "translate(-50%, calc(-100% - 8px))" : "translate(-50%, 8px)",
      }}
    >
      <p className="truncate font-semibold text-text-primary">{element.id}</p>
      <dl className="mt-1">
        <MetricRow label="V_r" value={formatMetric(element.vr)} />
        <MetricRow label="IoU" value={formatMetric(element.iou)} />
        <MetricRow label="Δx" value={element.deltaX === null ? null : element.deltaX.toFixed(1)} suffix="px" />
        <MetricRow label="Defect" value={element.defectType} />
        <MetricRow label="Verify" value={verificationStatus} />
      </dl>
      {element.maskState !== "available" ? (
        <p className="mt-1 text-text-muted">
          {element.maskState === "mismatch" ? "Mask dimensions mismatch — not rendered" : "Mask unavailable"}
        </p>
      ) : null}
    </div>
  );
});

// ---------------------------------------------------------------------------
// One viewport panel
// ---------------------------------------------------------------------------

interface ViewportPanelProps {
  data: ViewportPanelData;
  active: boolean;
  compareEnabled: boolean;
  position: number;
  onPosition: (p: number) => void;
  showBoxes: boolean;
  showMasks: boolean;
  showLabels: boolean;
  hovered: HoverTarget | null;
  selected: HoverTarget | null;
  onHover: (t: HoverTarget | null) => void;
  onSelect: (t: HoverTarget) => void;
}

function ViewportPanel({
  data,
  active,
  compareEnabled,
  position,
  onPosition,
  showBoxes,
  showMasks,
  showLabels,
  hovered,
  selected,
  onHover,
  onSelect,
}: ViewportPanelProps) {
  const spec = VIEWPORT_SPECS[data.viewport];
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const rawId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const compared = compareEnabled && data.beforeUrl !== null && data.afterUrl !== null;
  const hoveredEl = hovered && hovered.viewport === data.viewport
    ? (data.elements.find((e) => e.id === hovered.id) ?? null)
    : null;

  const updateFromClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track || !Number.isFinite(clientX)) return;
      const rect = track.getBoundingClientRect();
      if (rect.width <= 0) return;
      onPosition(clampPosition(((clientX - rect.left) / rect.width) * 100));
    },
    [onPosition],
  );

  if (data.beforeUrl === null) {
    return (
      <div
        data-testid={`placeholder-before-${data.viewport}`}
        className={cn(
          "flex min-h-48 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border-strong bg-surface px-4 py-10 text-center",
          active && "border-neural-pulse/50",
        )}
      >
        <p className="font-mono text-xs text-text-secondary">
          {spec.label} · before screenshot unavailable
        </p>
        <p className="max-w-sm text-xs text-text-muted">
          The backend does not expose a {data.viewport} defect screenshot for this run yet. No
          placeholder image is rendered in its place.
        </p>
      </div>
    );
  }

  return (
    <div
      data-testid={`stage-panel-${data.viewport}`}
      data-active={active ? "true" : "false"}
      data-logical-width={spec.width}
      data-logical-height={spec.height}
      className={cn(
        "min-w-0 rounded-md border bg-surface-subtle p-2",
        active ? "border-neural-pulse/50" : "border-border-subtle",
      )}
    >
      <div className="flex items-center justify-between gap-2 px-1 pb-2">
        <span className="font-mono text-[11px] text-text-secondary">
          {data.viewport === "mobile" ? "Mobile" : "Desktop"} ·{" "}
          <span data-testid={`viewport-dims-${data.viewport}`}>{spec.label} logical</span>
        </span>
        <span className="font-mono text-[10px] text-text-muted">
          {data.elements.length} element{data.elements.length === 1 ? "" : "s"}
        </span>
      </div>

      <div
        ref={trackRef}
        data-testid={`compare-track-${data.viewport}`}
        className="relative w-full select-none overflow-hidden rounded-sm bg-canvas"
        style={{ aspectRatio: `${spec.width} / ${spec.height}`, touchAction: compared ? "pan-y" : "auto" }}
        onPointerDown={(e) => {
          if (!compared) return;
          if (e.pointerType === "mouse" && e.button !== 0) return;
          draggingRef.current = true;
          updateFromClientX(e.clientX);
        }}
        onPointerMove={(e) => {
          if (!compared || !draggingRef.current) return;
          updateFromClientX(e.clientX);
        }}
        onPointerUp={() => {
          draggingRef.current = false;
        }}
        onPointerCancel={() => {
          draggingRef.current = false;
        }}
      >
        {/* Before layer (defect) */}
        <img
          data-testid={`screenshot-before-${data.viewport}`}
          src={data.beforeUrl}
          alt={`${data.viewport} defect screenshot at ${spec.label}`}
          draggable={false}
          loading="lazy"
          className="absolute inset-0 h-full w-full"
        />
        <OverlaySvg
          spec={spec}
          elements={data.elements}
          showBoxes={showBoxes}
          showMasks={showMasks}
          showLabels={showLabels}
          hoveredId={hovered && hovered.viewport === data.viewport ? hovered.id : null}
          selectedId={selected && selected.viewport === data.viewport ? selected.id : null}
          onHover={(id) => onHover(id ? { viewport: data.viewport, id } : null)}
          onSelect={(id) => onSelect({ viewport: data.viewport, id })}
          idPrefix={`ov-${rawId}`}
        />

        {/* After layer (HMR healed), clipped by the scrubber */}
        {compared && data.afterUrl ? (
          <div
            data-testid={`after-clip-${data.viewport}`}
            className="absolute inset-0"
            style={{ clipPath: `inset(0 0 0 ${position}%)` }}
          >
            <img
              data-testid={`screenshot-after-${data.viewport}`}
              src={data.afterUrl}
              alt={`${data.viewport} healed screenshot at ${spec.label}`}
              draggable={false}
              loading="lazy"
              className="absolute inset-0 h-full w-full"
            />
          </div>
        ) : null}

        {compared ? (
          <>
            <span className="pointer-events-none absolute left-2 top-2 z-20 rounded-sm border border-border-subtle bg-canvas/90 px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
              Before · Defect
            </span>
            <span className="pointer-events-none absolute right-2 top-2 z-20 rounded-sm border border-verified-emerald/50 bg-canvas/90 px-1.5 py-0.5 font-mono text-[10px] text-verified-emerald">
              After · HMR
            </span>
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 z-20 w-px bg-text-primary/80"
              style={{ left: `${position}%` }}
            />
            <div
              data-testid={`compare-slider-${data.viewport}`}
              role="slider"
              tabIndex={0}
              aria-label={`${data.viewport} before after comparison position`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(position)}
              aria-valuetext={`${Math.round(position)} percent before, ${100 - Math.round(position)} percent after`}
              className="absolute top-1/2 z-30 flex h-9 w-7 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize items-center justify-center rounded-md border border-border-strong bg-elevated text-text-secondary shadow-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus motion-reduce:transition-none"
              style={{ left: `${position}%`, touchAction: "none" }}
              onKeyDown={(e) => {
                const step = e.shiftKey ? 10 : 2;
                if (e.key === "ArrowLeft") {
                  e.preventDefault();
                  onPosition(clampPosition(position - step));
                } else if (e.key === "ArrowRight") {
                  e.preventDefault();
                  onPosition(clampPosition(position + step));
                } else if (e.key === "Home") {
                  e.preventDefault();
                  onPosition(0);
                } else if (e.key === "End") {
                  e.preventDefault();
                  onPosition(100);
                }
              }}
            >
              <GripVertical className="h-4 w-4" />
            </div>
          </>
        ) : (
          <span className="pointer-events-none absolute left-2 top-2 z-20 rounded-sm border border-border-subtle bg-canvas/90 px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
            {data.afterUrl === null ? "Before · Defect (after unavailable)" : "Before · Defect"}
          </span>
        )}

        {showLabels && hoveredEl ? (
          <ElementTooltip
            element={hoveredEl}
            spec={spec}
            verificationStatus={hoveredEl.status}
          />
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Verification + HMR strips (backend values only, never computed here)
// ---------------------------------------------------------------------------

function VerificationStrip({ data }: { data: ViewportPanelData }) {
  const v: ViewportVerification | null = data.verification;
  const verdict = v === null || v.passed === null ? "Unverified" : v.passed ? "Verified" : "Failed";
  return (
    <div
      data-testid={`verification-${data.viewport}`}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-text-secondary"
    >
      <span className="text-text-muted">{data.viewport === "mobile" ? "Mobile" : "Desktop"} verify:</span>
      <span>V_r {formatMetric(v?.vr ?? null) ?? "—"}</span>
      <span>IoU {formatMetric(v?.iou ?? null) ?? "—"}</span>
      <span>Δx {(v?.deltaX === null || v?.deltaX === undefined) ? "—" : `${v.deltaX.toFixed(1)}px`}</span>
      <span
        data-testid={`verification-verdict-${data.viewport}`}
        className={cn(
          v?.passed === true && "text-verified-emerald",
          v?.passed === false && "text-defect-crimson",
          (v === null || v.passed === null) && "text-text-muted",
        )}
      >
        {v?.status ?? verdict}
      </span>
    </div>
  );
}

function HmrStrip({ hmr }: { hmr: HMRInfo | null }) {
  if (hmr === null) {
    return (
      <p data-testid="hmr-status" data-observed="unknown" className="font-mono text-[11px] text-text-muted">
        HMR status unavailable — sandbox did not report
      </p>
    );
  }
  return (
    <p
      data-testid="hmr-status"
      data-observed={hmr.observed ? "true" : "false"}
      className={cn(
        "font-mono text-[11px]",
        hmr.observed ? "text-verified-emerald" : "text-triage-amber",
      )}
    >
      {hmr.observed ? "HMR observed" : "HMR not confirmed"}
      {hmr.phase ? ` · phase ${hmr.phase}` : ""}
      {hmr.status && !hmr.observed ? ` · ${hmr.status}` : ""}
      {hmr.latencyMs !== null ? ` · ${Math.round(hmr.latencyMs)} ms` : ""}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Stage
// ---------------------------------------------------------------------------

export function DualViewportStage({
  runId,
  runLabel,
  mobile,
  desktop,
  hmr,
  untaggedCount = 0,
  loading = false,
  error = null,
  initialViewport = "mobile",
  className,
  attempts,
  selectedAttempt,
  onAttemptChange,
  sandboxProvider = null,
  hmrLatencyMs = null,
}: DualViewportStageProps) {
  const [viewport, setViewport] = useState<ViewportName>(initialViewport);
  const [sideBySide, setSideBySide] = useState(false);
  const [position, setPosition] = useState(50);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showMasks, setShowMasks] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [compare, setCompare] = useState(true);
  const [hovered, setHovered] = useState<HoverTarget | null>(null);
  const [selected, setSelected] = useState<HoverTarget | null>(null);
  const reducedMotion = usePrefersReducedMotion();

  const activeData = viewport === "mobile" ? mobile : desktop;
  const masksAvailable =
    mobile.elements.some((e) => e.masks.length > 0) ||
    desktop.elements.some((e) => e.masks.length > 0);
  const afterAvailable = mobile.afterUrl !== null || desktop.afterUrl !== null;

  const toggleButton = (
    testId: string,
    label: string,
    pressed: boolean,
    onToggle: () => void,
    disabled: boolean,
    disabledReason: string,
  ) => (
    <button
      key={testId}
      type="button"
      data-testid={testId}
      aria-pressed={pressed}
      aria-label={label}
      title={disabled ? disabledReason : label}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex items-center gap-1 rounded-sm border px-1.5 py-1 font-mono text-[10px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
        disabled
          ? "cursor-not-allowed border-border-subtle text-text-muted/60"
          : pressed
            ? "border-neural-pulse/50 text-text-primary"
            : "border-border-subtle text-text-muted hover:text-text-primary",
      )}
    >
      {pressed && !disabled ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
      {label}
    </button>
  );

  return (
    <section
      aria-label="Dual viewport inspection stage"
      data-testid="dual-viewport-stage"
      data-viewport={viewport}
      data-mode={sideBySide ? "side-by-side" : "single"}
      data-motion={reducedMotion ? "reduced" : "full"}
      data-run-id={runId ?? undefined}
      className={cn("min-w-0 rounded-md border border-border-subtle bg-surface", className)}
    >
      {/* Controls header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate font-display text-sm font-semibold text-text-primary">
            Inspection Canvas
          </h2>
          {runLabel ? (
            <span data-testid="stage-run-label" className="truncate font-mono text-[11px] text-text-muted">
              {runLabel}
            </span>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <div role="group" aria-label="Viewport selection" className="flex items-center gap-1 rounded-sm border border-border-subtle bg-canvas p-0.5">
            <button
              type="button"
              data-testid="viewport-switch-mobile"
              aria-pressed={viewport === "mobile"}
              onClick={() => setViewport("mobile")}
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
                viewport === "mobile" ? "bg-elevated font-semibold text-text-primary" : "text-text-muted hover:text-text-primary",
              )}
            >
              <Smartphone className="h-3 w-3" /> 375px
            </button>
            <button
              type="button"
              data-testid="viewport-switch-desktop"
              aria-pressed={viewport === "desktop"}
              onClick={() => setViewport("desktop")}
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
                viewport === "desktop" ? "bg-elevated font-semibold text-text-primary" : "text-text-muted hover:text-text-primary",
              )}
            >
              <Monitor className="h-3 w-3" /> 1440px
            </button>
          </div>

          <div role="group" aria-label="Comparison mode" className="flex items-center gap-1 rounded-sm border border-border-subtle bg-canvas p-0.5">
            <button
              type="button"
              data-testid="viewport-mode-single"
              aria-pressed={!sideBySide}
              aria-label="Single viewport mode"
              title="Single viewport mode"
              onClick={() => setSideBySide(false)}
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
                !sideBySide ? "bg-elevated text-text-primary" : "text-text-muted hover:text-text-primary",
              )}
            >
              <Square className="h-3 w-3" />
            </button>
            <button
              type="button"
              data-testid="viewport-mode-side"
              aria-pressed={sideBySide}
              aria-label="Side by side viewport mode"
              title="Side by side viewport mode"
              onClick={() => setSideBySide(true)}
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
                sideBySide ? "bg-elevated text-text-primary" : "text-text-muted hover:text-text-primary",
              )}
            >
              <SplitSquareHorizontal className="h-3 w-3" />
            </button>
          </div>

          {toggleButton("toggle-boxes", "Boxes", showBoxes, () => setShowBoxes((v) => !v), false, "")}
          {toggleButton(
            "toggle-masks",
            "Masks",
            showMasks,
            () => setShowMasks((v) => !v),
            !masksAvailable,
            "No SAM masks available for this run",
          )}
          {toggleButton("toggle-labels", "Labels", showLabels, () => setShowLabels((v) => !v), false, "")}
          {toggleButton(
            "toggle-compare",
            "Compare",
            compare,
            () => setCompare((v) => !v),
            !afterAvailable,
            "No healed after-screenshot available for this run",
          )}
        </div>
      </div>

      {/* Status strips */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-3 py-1.5">
        <HmrStrip hmr={hmr} />
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <VerificationStrip data={mobile} />
          <VerificationStrip data={desktop} />
        </div>
      </div>

      {/* Strike timeline scrubber (Workstream 3) */}
      {attempts && attempts.length > 0 && onAttemptChange ? (
        <div
          data-testid="attempt-scrubber"
          className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-3 py-1.5"
        >
          <div role="group" aria-label="Strike attempt timeline" className="flex flex-wrap items-center gap-1">
            <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-text-muted">
              Timeline
            </span>
            {attempts.map((a) => (
              <button
                key={a.attemptNumber}
                type="button"
                data-testid={`attempt-btn-${a.attemptNumber}`}
                aria-pressed={selectedAttempt === a.attemptNumber}
                onClick={() => onAttemptChange(a.attemptNumber)}
                className={cn(
                  "rounded-sm border px-2 py-1 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus",
                  selectedAttempt === a.attemptNumber
                    ? "border-neural-pulse/60 bg-elevated font-semibold text-text-primary"
                    : "border-border-subtle text-text-muted hover:text-text-primary",
                )}
              >
                {a.label}
              </button>
            ))}
          </div>
          <span data-testid="stage-sandbox" className="font-mono text-[10px] text-text-muted">
            sandbox {sandboxProvider ?? "—"}
            {hmrLatencyMs !== null ? ` · HMR ${Math.round(hmrLatencyMs)} ms` : ""}
          </span>
        </div>
      ) : null}

      {/* Canvas */}
      <div className="min-w-0 p-3">
        {loading ? (
          <p data-testid="stage-loading" className="py-8 text-center text-sm text-text-secondary">
            Loading inspection artifacts…
          </p>
        ) : null}
        {error ? (
          <p
            data-testid="stage-error"
            role="alert"
            className="rounded-md border border-defect-crimson/50 bg-defect-crimson/[0.07] px-3 py-2 text-xs text-defect-crimson"
          >
            Stage error: {error}
          </p>
        ) : null}
        {!loading && !error && runId === null ? (
          <p data-testid="stage-no-run" className="py-8 text-center text-sm text-text-secondary">
            Select a PR run to inspect its viewports.
          </p>
        ) : null}
        {!loading && !error && runId !== null ? (
          sideBySide ? (
            <div data-testid="side-by-side-grid" className="grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2">
              <ViewportPanel
                data={mobile}
                active={viewport === "mobile"}
                compareEnabled={compare}
                position={position}
                onPosition={setPosition}
                showBoxes={showBoxes}
                showMasks={showMasks}
                showLabels={showLabels}
                hovered={hovered}
                selected={selected}
                onHover={setHovered}
                onSelect={(t) => setSelected((prev) => (prev && prev.viewport === t.viewport && prev.id === t.id ? null : t))}
              />
              <ViewportPanel
                data={desktop}
                active={viewport === "desktop"}
                compareEnabled={compare}
                position={position}
                onPosition={setPosition}
                showBoxes={showBoxes}
                showMasks={showMasks}
                showLabels={showLabels}
                hovered={hovered}
                selected={selected}
                onHover={setHovered}
                onSelect={(t) => setSelected((prev) => (prev && prev.viewport === t.viewport && prev.id === t.id ? null : t))}
              />
            </div>
          ) : (
            <div className={cn("min-w-0", viewport === "mobile" && "mx-auto w-full max-w-[375px]")}>
              <ViewportPanel
                data={activeData}
                active
                compareEnabled={compare}
                position={position}
                onPosition={setPosition}
                showBoxes={showBoxes}
                showMasks={showMasks}
                showLabels={showLabels}
                hovered={hovered}
                selected={selected}
                onHover={setHovered}
                onSelect={(t) => setSelected((prev) => (prev && prev.viewport === t.viewport && prev.id === t.id ? null : t))}
              />
            </div>
          )
        ) : null}
        {untaggedCount > 0 ? (
          <p data-testid="stage-untagged" className="mt-2 font-mono text-[10px] text-text-muted">
            {untaggedCount} element{untaggedCount === 1 ? "" : "s"} without viewport tagging are
            withheld (metrics are never mixed across viewports).
          </p>
        ) : null}
      </div>
    </section>
  );
}
