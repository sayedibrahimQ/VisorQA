/**
 * DualViewportStage tests (mocked fixtures only — never production data).
 * Run: cd frontend && npx vitest run tests/unit/dualViewportStage.test.tsx
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { DualViewportStage } from "@/components/mission-control/DualViewportStage";
import {
  VIEWPORT_SPECS,
  adaptRunToStage,
  formatMetric,
  toStageBox,
  toStageMask,
  viewportFromTag,
  type HMRInfo,
  type ViewportPanelData,
} from "@/lib/viewportArtifacts";
import { makeRun, stubMatchMedia } from "./scrum28-helpers";

// ---------------------------------------------------------------------------
// Fixtures (test-only)
// ---------------------------------------------------------------------------

const MOBILE_IMG = "/static/artifacts/run-1/mobile.png";
const MOBILE_HEALED = "/static/artifacts/run-1/mobile_healed.png";
const DESKTOP_IMG = "/static/artifacts/run-1/desktop.png";
const DESKTOP_HEALED = "/static/artifacts/run-1/desktop_healed.png";

function mobilePanel(overrides: Partial<ViewportPanelData> = {}): ViewportPanelData {
  return {
    viewport: "mobile",
    beforeUrl: MOBILE_IMG,
    afterUrl: MOBILE_HEALED,
    elements: [
      {
        id: "visor-el-04",
        box: { x: 12, y: 80, width: 350, height: 60 },
        defectType: "OCCLUSION",
        vr: 0.62,
        iou: 0.0,
        deltaX: 0,
        status: "DETECTED",
        masks: [
          { kind: "polygon", points: [{ x: 12, y: 80 }, { x: 362, y: 80 }, { x: 362, y: 140 }, { x: 12, y: 140 }] },
        ],
        maskState: "available",
      },
      {
        id: "visor-el-09",
        box: { x: 20, y: 400, width: 335, height: 52 },
        defectType: "COLLISION",
        vr: null,
        iou: 0.12,
        deltaX: null,
        status: null,
        masks: [],
        maskState: "unavailable",
      },
    ],
    verification: { vr: 0.62, iou: 0.0, deltaX: 0, passed: false, status: "verification_failed" },
    ...overrides,
  };
}

function desktopPanel(overrides: Partial<ViewportPanelData> = {}): ViewportPanelData {
  return {
    viewport: "desktop",
    beforeUrl: DESKTOP_IMG,
    afterUrl: DESKTOP_HEALED,
    elements: [
      {
        id: "visor-el-04",
        box: { x: 100, y: 200, width: 640, height: 90 },
        defectType: "OCCLUSION",
        vr: 0.91,
        iou: 0.0,
        deltaX: 0,
        status: "DETECTED",
        masks: [
          { kind: "contour", points: [{ x: 100, y: 200 }, { x: 740, y: 200 }, { x: 740, y: 290 }] },
        ],
        maskState: "available",
      },
    ],
    verification: { vr: 0.91, iou: 0.0, deltaX: 0, passed: false, status: "verification_failed" },
    ...overrides,
  };
}

const HMR_OBSERVED: HMRInfo = { observed: true, phase: "hmr_observed", status: "observed", latencyMs: 812 };
const HMR_PENDING: HMRInfo = { observed: false, phase: "patch_applied", status: "timeout", latencyMs: null };

function renderStage(props: {
  mobile?: ViewportPanelData;
  desktop?: ViewportPanelData;
  hmr?: HMRInfo | null;
  runId?: string | null;
  runLabel?: string | null;
} = {}) {
  return render(
    <DualViewportStage
      runId={props.runId === undefined ? "run-1" : props.runId}
      runLabel={props.runLabel === undefined ? "org/repo PR #7" : props.runLabel}
      mobile={props.mobile ?? mobilePanel()}
      desktop={props.desktop ?? desktopPanel()}
      hmr={props.hmr === undefined ? HMR_PENDING : props.hmr}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("DualViewportStage viewport switching", () => {
  it("1. selects the mobile viewport at 375px", () => {
    renderStage();
    expect(screen.getByTestId("dual-viewport-stage").getAttribute("data-viewport")).toBe("mobile");
    expect(screen.getByTestId("viewport-switch-mobile").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("stage-panel-mobile")).toBeTruthy();
    expect(screen.queryByTestId("stage-panel-desktop")).toBeNull();
  });

  it("2. switches to the desktop viewport immediately", () => {
    renderStage();
    fireEvent.click(screen.getByTestId("viewport-switch-desktop"));
    expect(screen.getByTestId("dual-viewport-stage").getAttribute("data-viewport")).toBe("desktop");
    expect(screen.getByTestId("stage-panel-desktop")).toBeTruthy();
    expect(screen.queryByTestId("stage-panel-mobile")).toBeNull();
    expect(screen.getByTestId("viewport-dims-desktop").textContent).toContain("1440×900");
    fireEvent.click(screen.getByTestId("viewport-switch-mobile"));
    expect(screen.getByTestId("stage-panel-mobile")).toBeTruthy();
  });

  it("3. renders synchronized side-by-side mode with the active viewport clear", () => {
    renderStage();
    fireEvent.click(screen.getByTestId("viewport-mode-side"));
    expect(screen.getByTestId("dual-viewport-stage").getAttribute("data-mode")).toBe("side-by-side");
    expect(screen.getByTestId("side-by-side-grid")).toBeTruthy();
    expect(screen.getByTestId("stage-panel-mobile")).toBeTruthy();
    expect(screen.getByTestId("stage-panel-desktop")).toBeTruthy();
    // Mobile was selected: it stays the active panel.
    expect(screen.getByTestId("stage-panel-mobile").getAttribute("data-active")).toBe("true");
    expect(screen.getByTestId("stage-panel-desktop").getAttribute("data-active")).toBe("false");
    // Stacked on narrow screens, two columns when wide.
    expect(screen.getByTestId("side-by-side-grid").className).toContain("grid-cols-1");
    expect(screen.getByTestId("side-by-side-grid").className).toContain("xl:grid-cols-2");
  });

  it("4. keeps correct logical viewport dimensions in every mode", () => {
    expect(VIEWPORT_SPECS.mobile.width).toBe(375);
    expect(VIEWPORT_SPECS.desktop.width).toBe(1440);
    renderStage();
    const panel = screen.getByTestId("stage-panel-mobile");
    expect(panel.getAttribute("data-logical-width")).toBe("375");
    expect(panel.getAttribute("data-logical-height")).toBe("812");
    fireEvent.click(screen.getByTestId("viewport-mode-side"));
    const desk = screen.getByTestId("stage-panel-desktop");
    expect(desk.getAttribute("data-logical-width")).toBe("1440");
    expect(desk.getAttribute("data-logical-height")).toBe("900");
  });

  it("5. scales screenshots while SVG coordinates stay aligned to logical pixels", () => {
    renderStage();
    const svg = screen.getByTestId("overlay-svg-mobile");
    expect(svg.getAttribute("viewBox")).toBe("0 0 375 812");
    const box = screen.getByTestId("dom-box-mobile-visor-el-04");
    expect(box.getAttribute("x")).toBe("12");
    expect(box.getAttribute("y")).toBe("80");
    expect(box.getAttribute("width")).toBe("350");
    expect(box.getAttribute("height")).toBe("60");
    const img = screen.getByTestId("screenshot-before-mobile");
    expect(img.getAttribute("src")).toBe(MOBILE_IMG);
    // Aspect ratio locked to logical dimensions; no stretch.
    const track = screen.getByTestId("compare-track-mobile");
    expect(track.style.aspectRatio).toBe("375 / 812");
  });
});

describe("DualViewportStage overlays", () => {
  it("6. renders DOM bounding boxes as dashed cyan with transparent fill", () => {
    renderStage();
    const box = screen.getByTestId("dom-box-mobile-visor-el-04");
    expect(box.getAttribute("stroke")).toBe("#00F0FF");
    expect(box.getAttribute("fill")).toBe("transparent");
    expect(box.getAttribute("stroke-dasharray")).toContain("7");
    // Selected element renders solid to distinguish from hovered.
    fireEvent.click(box);
    expect(screen.getByTestId("dom-box-mobile-visor-el-04").getAttribute("stroke-dasharray")).toBe("none");
  });

  it("7. renders SAM polygon, contour, and raster masks in crimson at 35%", () => {
    renderStage();
    const poly = screen.getByTestId("sam-mask-mobile-visor-el-04");
    expect(poly.getAttribute("data-kind")).toBe("polygon");
    const polyShape = poly.querySelector("polygon");
    expect(polyShape?.getAttribute("fill")).toBe("#F43F5E");
    expect(polyShape?.getAttribute("opacity")).toBe("0.35");
    cleanup();

    renderStage();
    fireEvent.click(screen.getByTestId("viewport-switch-desktop"));
    const contour = screen.getByTestId("sam-mask-desktop-visor-el-04");
    expect(contour.getAttribute("data-kind")).toBe("contour");
    cleanup();

    // Raster binary mask: exact-viewport PNG behind a crimson luminance mask.
    const raster = mobilePanel({
      elements: [
        {
          id: "visor-el-11",
          box: { x: 0, y: 0, width: 100, height: 100 },
          defectType: "OCCLUSION",
          vr: 0.5,
          iou: 0,
          deltaX: 0,
          status: "DETECTED",
          masks: [{ kind: "image", url: "/m/mask.png", width: 375, height: 812 }],
          maskState: "available",
        },
      ],
    });
    renderStage({ mobile: raster });
    const rasterMask = screen.getByTestId("sam-mask-mobile-visor-el-11");
    expect(rasterMask.getAttribute("data-kind")).toBe("image");
    expect(rasterMask.querySelector("mask")).not.toBeNull();
    const tinted = rasterMask.querySelector("rect");
    expect(tinted?.getAttribute("fill")).toBe("#F43F5E");
    expect(tinted?.getAttribute("mask")).toContain("url(#");
  });

  it("8. toggles boxes and masks independently; slider works with overlays off", () => {
    renderStage();
    fireEvent.click(screen.getByTestId("toggle-boxes"));
    expect(screen.queryByTestId("dom-box-mobile-visor-el-04")).toBeNull();
    expect(screen.getByTestId("sam-mask-mobile-visor-el-04")).toBeTruthy();
    fireEvent.click(screen.getByTestId("toggle-boxes"));
    fireEvent.click(screen.getByTestId("toggle-masks"));
    expect(screen.getByTestId("dom-box-mobile-visor-el-04")).toBeTruthy();
    expect(screen.queryByTestId("sam-mask-mobile-visor-el-04")).toBeNull();
    // Comparison stays usable with overlays disabled.
    fireEvent.click(screen.getByTestId("toggle-boxes"));
    expect(screen.getByTestId("compare-slider-mobile")).toBeTruthy();
    expect(screen.getByTestId("after-clip-mobile")).toBeTruthy();
  });
});

describe("DualViewportStage tooltips", () => {
  it("9. shows an element tooltip on hover and keyboard focus", () => {
    renderStage();
    const box = screen.getByTestId("dom-box-mobile-visor-el-04");
    fireEvent.mouseOver(box);
    const tip = screen.getByTestId("element-tooltip");
    expect(tip.getAttribute("data-element-id")).toBe("visor-el-04");
    expect(tip.textContent).toContain("visor-el-04");
    fireEvent.mouseOut(box);
    expect(screen.queryByTestId("element-tooltip")).toBeNull();
    fireEvent.focus(box);
    expect(screen.getByTestId("element-tooltip")).toBeTruthy();
    fireEvent.blur(box);
    expect(screen.queryByTestId("element-tooltip")).toBeNull();
  });

  it("10. associates metrics with the correct element id", () => {
    renderStage();
    fireEvent.mouseOver(screen.getByTestId("dom-box-mobile-visor-el-04"));
    expect(screen.getByTestId("element-tooltip").textContent).toContain("0.62");
    fireEvent.mouseOut(screen.getByTestId("dom-box-mobile-visor-el-04"));
    fireEvent.mouseOver(screen.getByTestId("dom-box-mobile-visor-el-09"));
    const tip = screen.getByTestId("element-tooltip");
    expect(tip.getAttribute("data-element-id")).toBe("visor-el-09");
    expect(tip.textContent).toContain("0.12");
    expect(tip.textContent).not.toContain("0.62");
  });

  it("11. marks missing metrics unavailable instead of inventing values", () => {
    renderStage();
    fireEvent.mouseOver(screen.getByTestId("dom-box-mobile-visor-el-09"));
    const tip = screen.getByTestId("element-tooltip");
    expect(tip.textContent).toContain("—");
    expect(formatMetric(null)).toBeNull();
    cleanup();
    renderStage({ mobile: mobilePanel({ verification: null }) });
    expect(screen.getByTestId("verification-verdict-mobile").textContent).toBe("Unverified");
  });
});

describe("DualViewportStage comparison scrubber", () => {
  function mockTrackWidth(viewport: string, width: number) {
    const track = screen.getByTestId(`compare-track-${viewport}`);
    vi.spyOn(track, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width,
      height: width,
      right: width,
      bottom: width,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    return track;
  }

  it("12. clips the after layer at the scrubber position with before/after labels", () => {
    renderStage();
    const clip = screen.getByTestId("after-clip-mobile");
    expect(clip.style.clipPath).toBe("inset(0 0 0 50%)");
    const slider = screen.getByTestId("compare-slider-mobile");
    expect(slider.getAttribute("role")).toBe("slider");
    expect(slider.getAttribute("aria-valuenow")).toBe("50");
    const track = screen.getByTestId("compare-track-mobile");
    expect(track.textContent).toContain("Before · Defect");
    expect(track.textContent).toContain("After · HMR");
  });

  it("13. drags with the mouse to reposition the divider", () => {
    renderStage();
    const track = mockTrackWidth("mobile", 400);
    // jsdom lacks PointerEvent, so drive the pointer handlers with
    // coordinate-carrying mouse events typed as pointer events.
    act(() => {
      track.dispatchEvent(new MouseEvent("pointerdown", { clientX: 100, bubbles: true }));
      track.dispatchEvent(new MouseEvent("pointermove", { clientX: 300, bubbles: true }));
      track.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    });
    expect(screen.getByTestId("compare-slider-mobile").getAttribute("aria-valuenow")).toBe("75");
    expect(screen.getByTestId("after-clip-mobile").style.clipPath).toBe("inset(0 0 0 75%)");
  });

  it("14. supports touch dragging without hijacking vertical scroll", () => {
    renderStage();
    const track = mockTrackWidth("mobile", 400);
    expect(track.style.touchAction).toBe("pan-y");
    const slider = screen.getByTestId("compare-slider-mobile");
    expect(slider.style.touchAction).toBe("none");
    act(() => {
      track.dispatchEvent(new MouseEvent("pointerdown", { clientX: 40, bubbles: true }));
      track.dispatchEvent(new MouseEvent("pointermove", { clientX: 120, bubbles: true }));
      track.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    });
    expect(screen.getByTestId("compare-slider-mobile").getAttribute("aria-valuenow")).toBe("30");
  });

  it("15. operates the slider from the keyboard", () => {
    renderStage();
    const slider = screen.getByTestId("compare-slider-mobile");
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(screen.getByTestId("compare-slider-mobile").getAttribute("aria-valuenow")).toBe("52");
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    fireEvent.keyDown(slider, { key: "Home" });
    expect(screen.getByTestId("compare-slider-mobile").getAttribute("aria-valuenow")).toBe("0");
    fireEvent.keyDown(slider, { key: "End" });
    expect(screen.getByTestId("compare-slider-mobile").getAttribute("aria-valuenow")).toBe("100");
  });

  it("15b. preserves scrubber position when switching viewports", () => {
    renderStage();
    const slider = screen.getByTestId("compare-slider-mobile");
    fireEvent.keyDown(slider, { key: "End" });
    fireEvent.click(screen.getByTestId("viewport-switch-desktop"));
    expect(screen.getByTestId("compare-slider-desktop").getAttribute("aria-valuenow")).toBe("100");
  });

  it("16. respects reduced motion", () => {
    stubMatchMedia(true);
    renderStage();
    expect(screen.getByTestId("dual-viewport-stage").getAttribute("data-motion")).toBe("reduced");
    cleanup();
    stubMatchMedia(false);
    renderStage();
    expect(screen.getByTestId("dual-viewport-stage").getAttribute("data-motion")).toBe("full");
  });
});

describe("DualViewportStage data correctness", () => {
  it("17. explains missing screenshot artifacts with placeholders", () => {
    renderStage({ mobile: mobilePanel({ beforeUrl: null }) });
    const placeholder = screen.getByTestId("placeholder-before-mobile");
    expect(placeholder.textContent).toContain("before screenshot unavailable");
    expect(placeholder.textContent).toContain("375×812");
    expect(screen.queryByTestId("screenshot-before-mobile")).toBeNull();
    cleanup();
    renderStage({
      mobile: mobilePanel({ afterUrl: null }),
      desktop: desktopPanel({ afterUrl: null }),
    });
    const compare = screen.getByTestId("toggle-compare");
    expect((compare as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("compare-track-mobile").textContent).toContain("after unavailable");
    expect(screen.queryByTestId("compare-slider-mobile")).toBeNull();
  });

  it("18. keeps mobile and desktop metrics separate", () => {
    renderStage();
    expect(screen.getByTestId("verification-mobile").textContent).toContain("0.62");
    expect(screen.getByTestId("verification-desktop").textContent).toContain("0.91");
    fireEvent.click(screen.getByTestId("viewport-mode-side"));
    fireEvent.mouseOver(screen.getByTestId("dom-box-desktop-visor-el-04"));
    const tip = screen.getByTestId("element-tooltip");
    expect(tip.getAttribute("data-element-id")).toBe("visor-el-04");
    expect(tip.textContent).toContain("0.91");
    expect(tip.textContent).not.toContain("0.62");
  });

  it("19. reports HMR status only from sandbox data", () => {
    renderStage({ hmr: HMR_OBSERVED });
    const ok = screen.getByTestId("hmr-status");
    expect(ok.getAttribute("data-observed")).toBe("true");
    expect(ok.textContent).toContain("HMR observed");
    cleanup();
    renderStage({ hmr: HMR_PENDING });
    const pending = screen.getByTestId("hmr-status");
    expect(pending.getAttribute("data-observed")).toBe("false");
    expect(pending.textContent).toContain("HMR not confirmed");
    expect(pending.textContent).not.toContain("HMR observed");
    cleanup();
    renderStage({ hmr: null });
    expect(screen.getByTestId("hmr-status").textContent).toContain("HMR status unavailable");
  });

  it("20. fabricates no production metrics from an empty run", () => {
    const stage = adaptRunToStage(makeRun());
    expect(stage.mobile.beforeUrl).toBeNull();
    expect(stage.desktop.beforeUrl).toBeNull();
    expect(stage.mobile.elements).toEqual([]);
    expect(stage.mobile.verification).toBeNull();
    expect(stage.hmr).toBeNull();
    const { container } = render(
      <DualViewportStage
        runId={stage.runId}
        runLabel={stage.runLabel}
        mobile={stage.mobile}
        desktop={stage.desktop}
        hmr={stage.hmr}
        untaggedCount={stage.untaggedCount}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toContain("1.00");
    expect(text).not.toContain("RESOLVED");
    expect(text).not.toContain("HMR observed");
    expect(screen.getByTestId("placeholder-before-mobile")).toBeTruthy();
  });

  it("20b. withholds untagged elements instead of mixing viewports", () => {
    const stage = adaptRunToStage(
      makeRun({
        anomalies: [
          {
            id: "a1",
            element_id: "visor-el-04",
            defect_type: "OCCLUSION",
            bounding_box: { x: 1, y: 2, width: 3, height: 4 },
            visibility_ratio: 0.5,
            status: "DETECTED",
          },
        ],
      }),
    );
    expect(stage.untaggedCount).toBe(1);
    expect(stage.mobile.elements).toEqual([]);
    expect(stage.desktop.elements).toEqual([]);
  });
});

describe("viewportArtifacts validators", () => {
  it("rejects invalid boxes, masks, and viewport tags without guessing", () => {
    expect(toStageBox(null)).toBeNull();
    expect(toStageBox({ x: 0, y: 0, width: -1, height: 5 })).toBeNull();
    expect(toStageBox({ x: 0, y: 0, width: 1, height: 1 })).toEqual({ x: 0, y: 0, width: 1, height: 1 });
    expect(viewportFromTag("375px")).toBe("mobile");
    expect(viewportFromTag("1440px")).toBe("desktop");
    expect(viewportFromTag("nope")).toBeNull();
    const spec = VIEWPORT_SPECS.mobile;
    expect(toStageMask({ kind: "polygon", points: [{ x: 0, y: 0 }] }, spec).mask).toBeNull();
    const mismatch = toStageMask({ kind: "image", url: "/m.png", width: 100, height: 100 }, spec);
    expect(mismatch).toEqual({ mask: null, mismatch: true });
    const ok = toStageMask({ kind: "image", url: "/m.png", width: 375, height: 812 }, spec);
    expect(ok.mismatch).toBe(false);
    expect(ok.mask).not.toBeNull();
  });
});
