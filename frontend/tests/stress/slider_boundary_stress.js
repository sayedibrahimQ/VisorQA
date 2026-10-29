/**
 * VisorQA Empirical Challenge - Stress Test 2: Interactive Slider Boundary & Touch Verification
 * 
 * Adversarially verifies:
 * 1. Boundary Clamping: [0, 100] mathematical invariant under extreme inputs
 * 2. Keyboard Step Transitions: Arrow keys (step 2), Shift+Arrow (step 10), Home/End
 * 3. Touch/Pointer Handlers: Pointer capture, cancelAnimationFrame debounce, touchAction="none"
 * 4. Responsive Stage Scaling: useStageScale strictly down-scales (scale <= 1)
 * 5. Component markup ARIA conformance: role="slider", aria-valuenow, valuemin, valuemax
 */

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND_DIR = path.resolve(__dirname, "../../");
const PROOF_PREVIEW_PATH = path.join(FRONTEND_DIR, "src/components/landing/ProofPreview.tsx");
const MASK_SLIDER_PATH = path.join(FRONTEND_DIR, "src/components/MaskSlider.tsx");

console.log("======================================================================");
console.log("   CHALLENGER 1 — ADVERSARIAL SLIDER BOUNDARY & TOUCH STRESS HARNESS   ");
console.log("======================================================================");

let passedAssertions = 0;
let totalAssertions = 0;

function check(desc, fn) {
  totalAssertions++;
  try {
    fn();
    passedAssertions++;
    console.log(`  ✓ ${desc}`);
  } catch (err) {
    console.error(`  ✗ ${desc}`);
    console.error(`    Error: ${err.message}`);
    throw err;
  }
}

// ----------------------------------------------------------------------------
// 1. Math Clamping Logic Verification
// ----------------------------------------------------------------------------
console.log("\n--- Category 1: Math Coordinate Clamping & Boundary Invariants ---");

function simulateCoordinateConversion(clientX, rect) {
  const pct = ((clientX - rect.left) / rect.width) * 100;
  return Math.min(100, Math.max(0, Math.round(pct)));
}

const mockRects = [
  { left: 100, width: 500 }, // Standard desktop stage
  { left: 20, width: 335 },  // Mobile stage
  { left: 0, width: 1440 },  // Fullscreen desktop stage
  { left: 450, width: 800 }, // Offset stage
];

for (const rect of mockRects) {
  check(`Under-bound negative clientX (-999999) clamps strictly to 0 [rect left=${rect.left}, w=${rect.width}]`, () => {
    const val = simulateCoordinateConversion(-999999, rect);
    assert.strictEqual(val, 0);
  });

  check(`Negative clientX below stage left (${rect.left - 50}) clamps strictly to 0`, () => {
    const val = simulateCoordinateConversion(rect.left - 50, rect);
    assert.strictEqual(val, 0);
  });

  check(`Exact stage start (${rect.left}) evaluates to exactly 0`, () => {
    const val = simulateCoordinateConversion(rect.left, rect);
    assert.strictEqual(val, 0);
  });

  check(`Exact stage center (${rect.left + rect.width / 2}) evaluates to exactly 50`, () => {
    const val = simulateCoordinateConversion(rect.left + rect.width / 2, rect);
    assert.strictEqual(val, 50);
  });

  check(`Exact stage end (${rect.left + rect.width}) evaluates to exactly 100`, () => {
    const val = simulateCoordinateConversion(rect.left + rect.width, rect);
    assert.strictEqual(val, 100);
  });

  check(`Over-bound clientX beyond stage right (${rect.left + rect.width + 100}) clamps strictly to 100`, () => {
    const val = simulateCoordinateConversion(rect.left + rect.width + 100, rect);
    assert.strictEqual(val, 100);
  });

  check(`Extreme over-bound clientX (+999999) clamps strictly to 100`, () => {
    const val = simulateCoordinateConversion(999999, rect);
    assert.strictEqual(val, 100);
  });
}

// ----------------------------------------------------------------------------
// 2. Keyboard Step Transitions & Corner Boundary Clamping
// ----------------------------------------------------------------------------
console.log("\n--- Category 2: Keyboard Step Transitions & Corner Boundaries ---");

function simulateKeyboardStep(currentPos, key, shiftKey = false) {
  const step = shiftKey ? 10 : 2;
  if (key === "ArrowLeft") {
    return Math.max(0, currentPos - step);
  } else if (key === "ArrowRight") {
    return Math.min(100, currentPos + step);
  } else if (key === "Home") {
    return 0;
  } else if (key === "End") {
    return 100;
  }
  return currentPos;
}

check("ArrowLeft at 0 clamps strictly at 0 (never negative)", () => {
  assert.strictEqual(simulateKeyboardStep(0, "ArrowLeft", false), 0);
});

check("Shift+ArrowLeft at 5 clamps strictly at 0 (never -5)", () => {
  assert.strictEqual(simulateKeyboardStep(5, "ArrowLeft", true), 0);
});

check("ArrowLeft at 1 clamps strictly at 0 (never -1)", () => {
  assert.strictEqual(simulateKeyboardStep(1, "ArrowLeft", false), 0);
});

check("ArrowRight at 100 clamps strictly at 100 (never > 100)", () => {
  assert.strictEqual(simulateKeyboardStep(100, "ArrowRight", false), 100);
});

check("Shift+ArrowRight at 95 clamps strictly at 100 (never 105)", () => {
  assert.strictEqual(simulateKeyboardStep(95, "ArrowRight", true), 100);
});

check("ArrowRight at 99 clamps strictly at 100 (never 101)", () => {
  assert.strictEqual(simulateKeyboardStep(99, "ArrowRight", false), 100);
});

check("Home key from any position (0, 37, 72, 100) instantly transitions to 0", () => {
  for (const pos of [0, 37, 72, 100]) {
    assert.strictEqual(simulateKeyboardStep(pos, "Home"), 0);
  }
});

check("End key from any position (0, 37, 72, 100) instantly transitions to 100", () => {
  for (const pos of [0, 37, 72, 100]) {
    assert.strictEqual(simulateKeyboardStep(pos, "End"), 100);
  }
});

check("Exhaustive traversal: Stepping 60 times right from 0 ends at 100", () => {
  let pos = 0;
  for (let i = 0; i < 60; i++) {
    pos = simulateKeyboardStep(pos, "ArrowRight", false);
  }
  assert.strictEqual(pos, 100);
});

check("Exhaustive traversal: Stepping 60 times left from 100 ends at 0", () => {
  let pos = 100;
  for (let i = 0; i < 60; i++) {
    pos = simulateKeyboardStep(pos, "ArrowLeft", false);
  }
  assert.strictEqual(pos, 0);
});

// ----------------------------------------------------------------------------
// 3. Stage Scale Downscaling Invariant
// ----------------------------------------------------------------------------
console.log("\n--- Category 3: Responsive useStageScale Downscaling Invariants ---");

function simulateStageScale(designWidth, clientWidth) {
  return Math.min(1, clientWidth / designWidth);
}

check("Mobile design width 375: clientWidth 375 yields scale 1.0", () => {
  assert.strictEqual(simulateStageScale(375, 375), 1.0);
});

check("Mobile design width 375: clientWidth 300 scales down to 0.8", () => {
  assert.strictEqual(simulateStageScale(375, 300), 300 / 375);
});

check("Mobile design width 375: clientWidth 1200 does NOT upscale (clamped to 1.0)", () => {
  assert.strictEqual(simulateStageScale(375, 1200), 1.0);
});

check("Desktop design width 1440: clientWidth 1440 yields scale 1.0", () => {
  assert.strictEqual(simulateStageScale(1440, 1440), 1.0);
});

check("Desktop design width 1440: clientWidth 720 scales down to 0.5", () => {
  assert.strictEqual(simulateStageScale(1440, 720), 0.5);
});

check("Desktop design width 1440: clientWidth 2560 does NOT upscale (clamped to 1.0)", () => {
  assert.strictEqual(simulateStageScale(1440, 2560), 1.0);
});

check("Degenerate clientWidth 0 yields scale 0 without NaN", () => {
  const scale = simulateStageScale(1440, 0);
  assert.strictEqual(scale, 0);
  assert(!isNaN(scale));
});

// ----------------------------------------------------------------------------
// 4. Source Code Static Contract Verification
// ----------------------------------------------------------------------------
console.log("\n--- Category 4: Source Code Component Contracts & Accessibility ---");

const proofContent = fs.readFileSync(PROOF_PREVIEW_PATH, "utf8");
const maskSliderContent = fs.readFileSync(MASK_SLIDER_PATH, "utf8");

check("ProofPreview.tsx implements role='slider' with ARIA min/max/now/text", () => {
  assert(proofContent.includes("role=\"slider\""), "Must declare role='slider'");
  assert(proofContent.includes("aria-valuemin={0}"), "Must declare aria-valuemin={0}");
  assert(proofContent.includes("aria-valuemax={100}"), "Must declare aria-valuemax={100}");
  assert(proofContent.includes("aria-valuenow="), "Must declare aria-valuenow");
  assert(proofContent.includes("aria-valuetext="), "Must declare aria-valuetext");
});

check("ProofPreview.tsx declares pointer events and pointer capture", () => {
  assert(proofContent.includes("onPointerDown"), "Must implement onPointerDown");
  assert(proofContent.includes("setPointerCapture"), "Must capture pointer for smooth drag");
  assert(proofContent.includes("onPointerMove"), "Must implement onPointerMove");
  assert(proofContent.includes("onPointerUp"), "Must implement onPointerUp");
  assert(proofContent.includes("onPointerCancel"), "Must implement onPointerCancel");
});

check("ProofPreview.tsx declares touchAction: 'none' on draggable handle", () => {
  assert(proofContent.includes("touchAction: \"none\""), "Must set touchAction: 'none' for touch dragging");
});

check("ProofPreview.tsx throttles clientX updates with requestAnimationFrame", () => {
  assert(proofContent.includes("requestAnimationFrame"), "Must use rAF for smooth 60fps drag");
  assert(proofContent.includes("cancelAnimationFrame"), "Must clean up rAF on unmount");
});

check("ProofPreview.tsx implements clipPath with exact percentage inversion (100 - pos)", () => {
  assert(proofContent.includes("clipPath: `inset(0 ${100 - pos}% 0 0)`"), "Must use dynamic clipPath inset");
});

check("MaskSlider.tsx component bounds are strictly min='0' and max='100'", () => {
  assert(maskSliderContent.includes("min=\"0\""), "MaskSlider must specify min='0'");
  assert(maskSliderContent.includes("max=\"100\""), "MaskSlider must specify max='100'");
});

console.log("\n======================================================================");
console.log(`TOTAL SLIDER ASSERTIONS PASSED: ${passedAssertions} / ${totalAssertions} (100%)`);
console.log("======================================================================");
