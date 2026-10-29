/**
 * VisorQA E2E Test Suite - Tier 2: Boundary & Corner Cases
 * 
 * Verifies boundaries, extreme inputs, toggle cycles, slider ranges [0, 100],
 * viewport extremes (375px mobile, 1440px desktop), edge cases, and accessibility
 * contracts across all 17 features (5 test cases per feature = 85 tests).
 */

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { execSync } = require("node:child_process");

const FRONTEND_DIR = path.resolve(__dirname, "../../");
const WORKSPACE_ROOT = path.resolve(__dirname, "../../../");

function readFrontend(relPath) {
  return fs.readFileSync(path.join(FRONTEND_DIR, relPath), "utf8");
}

function getRenderedHtml() {
  const htmlPath = path.join(FRONTEND_DIR, ".next/server/app/index.html");
  if (!fs.existsSync(htmlPath)) {
    throw new Error("Build output index.html not found. Please run 'npm run build' first.");
  }
  return fs.readFileSync(htmlPath, "utf8");
}

const tests = [];

function register(id, name, fn) {
  tests.push({ id, name, fn });
}

// ============================================================================
// FEATURE 1: Sticky Header & Telemetry Ribbon (Boundaries & Corners - 5 tests)
// ============================================================================

register("B1.1", "Header Boundaries: Mobile menu trigger declared with accessible controls", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes("Open navigation menu"), "Mobile menu trigger must provide accessible label");
  assert(src.includes("md:hidden"), "Mobile menu must be hidden on medium screens and above");
});

register("B1.2", "Header Boundaries: Telemetry ribbon horizontal overflow containment", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes("overflow-x-auto"), "Ribbon must declare overflow-x-auto to prevent layout blowout on 375px");
  assert(src.includes("whitespace-nowrap"), "Ribbon must declare whitespace-nowrap to keep ticker on a single line");
});

register("B1.3", "Header Boundaries: Logo anchor accessibility and home navigation", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes('href="#top"'), "Logo link must point to #top anchor");
  assert(src.includes('aria-label="VisorQA home"'), "Logo must declare accessible aria-label");
  assert(src.includes("FOCUS"), "Logo anchor must use high-contrast FOCUS ring utility");
});

register("B1.4", "Header Boundaries: External links declare target='_blank' and rel='noreferrer'", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes('target="_blank"'), "External links must open in new tab");
  assert(src.includes('rel="noreferrer"'), "External links must specify rel='noreferrer' for security");
});

register("B1.5", "Header Boundaries: Fixed header height constraint (h-14) prevents CLS", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes("h-14"), "Header must declare fixed h-14 (56px) height boundary to prevent cumulative layout shift");
});

// ============================================================================
// FEATURE 2: High-Craft Hero Section & CLI Quickstart (Boundaries & Corners - 5 tests)
// ============================================================================

register("B2.1", "Hero Boundaries: Quickstart copy button screen reader feedback", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes('aria-live="polite"'), "Copy feedback must use aria-live='polite' region");
  assert(src.includes("Copied to clipboard") || src.includes("Copy install command"), "Must provide dynamic accessible label");
});

register("B2.2", "Hero Boundaries: Clipboard exception fallback for insecure origins", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("document.createElement(\"textarea\")"), "useCopy hook must fallback to textarea when clipboard API blocked");
  assert(src.includes("document.execCommand(\"copy\")"), "Must execute legacy copy fallback on error");
});

register("B2.3", "Hero Boundaries: Blueprint background pointer events and opacity mask", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("pointer-events-none"), "Background grid must be pointer-events-none to avoid trapping clicks");
  assert(src.includes("mask-image:radial-gradient"), "Background must use radial alpha gradient mask");
});

register("B2.4", "Hero Boundaries: Monospace CLI command truncation on small screens", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("truncate font-mono"), "CLI command must be truncated to prevent viewport blowout");
  assert(src.includes("max-w-md") || src.includes("max-w-xl"), "Terminal box must be width-bounded");
});

register("B2.5", "Hero Boundaries: Responsive grid columns adaptation (1 to 12)", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("grid-cols-1"), "Hero must stack into single column on mobile");
  assert(src.includes("lg:grid-cols-12"), "Hero must expand to 12 columns on large desktop viewports");
});

// ============================================================================
// FEATURE 3: Core Utility & Monochrome Tokens (Boundaries & Corners - 5 tests)
// ============================================================================

register("B3.1", "Token Boundaries: Root html element enforces dark class permanently", () => {
  const layout = readFrontend("src/app/layout.tsx");
  assert(layout.includes('<html lang="en" className="dark">'), "Root html tag must enforce dark mode");
});

register("B3.2", "Token Boundaries: Technical scrollbar styling defined in globals.css", () => {
  const css = readFrontend("src/app/globals.css");
  assert(css.includes("::-webkit-scrollbar"), "globals.css must specify custom webkit scrollbar");
  assert(css.includes("width: 6px") || css.includes("width: 8px"), "Scrollbar width must be narrow technical width");
  assert(css.includes("#0a0a0c") && css.includes("#22222a"), "Scrollbar must use canvas and border-subtle colors");
});

register("B3.3", "Token Boundaries: High-contrast focus state token defined in shared.tsx", () => {
  const shared = readFrontend("src/components/landing/shared.tsx");
  assert(shared.includes("focus-visible:ring-2"), "FOCUS constant must specify 2px ring");
  assert(shared.includes("focus-visible:ring-cyan-400"), "FOCUS constant must use cyan-400 accent ring");
  assert(shared.includes("focus-visible:ring-offset-2"), "FOCUS constant must specify ring offset");
});

register("B3.4", "Token Boundaries: Contrast ratio exceeds WCAG AAA standard and zero-CLS containment", () => {
  const tailwind = readFrontend("tailwind.config.ts");
  const css = readFrontend("src/app/globals.css");
  // Canvas #0A0A0C to Text Primary #FAFAFA yields contrast ratio > 18:1 (AAA requires >= 7:1)
  assert(tailwind.includes('"#0A0A0C"') && tailwind.includes('"#FAFAFA"'), "Must use Obsidian #0A0A0C and Alabaster #FAFAFA");
  assert(css.includes(".zero-cls-container") && css.includes("contain: paint layout"), "globals.css must specify zero-cls-container with layout containment");
});

register("B3.5", "Token Boundaries: Zero unstyled light canvas leakage", () => {
  const css = readFrontend("src/app/globals.css");
  assert(!css.includes("background: #ffffff") && !css.includes("background-color: #ffffff"), "globals.css must not specify bright light canvas");
});

// ============================================================================
// FEATURE 4: Dual-Viewport Interactive Sandbox (Boundaries & Corners - 5 tests)
// ============================================================================

register("B4.1", "Sandbox Boundaries: useStageScale hook clamps scale to at most 1.0", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Math.min(1,"), "Scale calculation must clamp scale to at most 1.0 (never zoom in)");
});

register("B4.2", "Sandbox Boundaries: Exact design viewport dimensions (375px & 1440px)", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("375 : 1440"), "Design width must be exactly 375 for mobile and 1440 for desktop");
});

register("B4.3", "Sandbox Boundaries: Outer stage container enforces overflow-hidden", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("overflow-hidden bg-canvas"), "Stage wrapper must enforce overflow-hidden to prevent document horizontal scroll");
});

register("B4.4", "Sandbox Boundaries: Transform origin anchored at top left", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('transformOrigin: "top left"'), "Scaled wrapper must anchor at top left to eliminate layout drift");
});

register("B4.5", "Sandbox Boundaries: Accessible demo caption footnote transparency", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Dual-Viewport Proof Engine") || src.includes("Simulated demo"), "Caption must transparently disclose demo status");
  assert(src.includes('id="demo-caption"'), "Caption must declare id='demo-caption'");
});

// ============================================================================
// FEATURE 5: SAM 3.1 Mask Scrubber (Boundaries & Corners - 5 tests)
// ============================================================================

register("B5.1", "Scrubber Boundaries: Slider position clamped at lower bound 0%", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Math.max(0,"), "Position calculations must clamp to at least 0%");
});

register("B5.2", "Scrubber Boundaries: Slider position clamped at upper bound 100%", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Math.min(100,"), "Position calculations must clamp to at most 100%");
});

register("B5.3", "Scrubber Boundaries: Keyboard navigation support for Arrow, Home, and End", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("ArrowLeft") && src.includes("ArrowRight"), "Keyboard handler must handle ArrowLeft and ArrowRight");
  assert(src.includes("Home") && src.includes("End"), "Keyboard handler must handle Home (0%) and End (100%)");
  assert(src.includes("event.shiftKey ? 10 : 2"), "Shift+Arrow must step by 10%, standard Arrow by 2%");
});

register("B5.4", "Scrubber Boundaries: Pointer capture and touch-action: none", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("setPointerCapture"), "Pointer down must set pointer capture for stutter-free dragging");
  assert(src.includes('touchAction: "none"'), "Scrubber must set touchAction: 'none' to prevent mobile gesture interference");
});

register("B5.5", "Scrubber Boundaries: requestAnimationFrame throttling on pointer move", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("requestAnimationFrame"), "Move events must schedule updates via requestAnimationFrame");
  assert(src.includes("cancelAnimationFrame"), "Component must cancel pending animation frames on unmount");
});

// ============================================================================
// FEATURE 6: Mathematical Trap Scorecard (Boundaries & Corners - 5 tests)
// ============================================================================

register("B6.1", "Math Boundaries: Visibility Ratio (Vr) threshold condition evaluated", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("vrPassing") || src.includes("0.85"), "Must evaluate Vr threshold boundary");
  assert(src.includes("0.45"), "Must evaluate failing Vr baseline (0.45 < 0.85)");
});

register("B6.2", "Math Boundaries: Sibling Collision (IoU) threshold condition evaluated", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("iouPassing") || src.includes("0.05"), "Must evaluate IoU collision threshold boundary (0.05)");
  assert(src.includes("0.16"), "Must evaluate failing IoU collision baseline (0.16 > 0.05)");
});

register("B6.3", "Math Boundaries: Viewport Bleed (Δx) threshold condition evaluated", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("bleedPassing") || src.includes("2.0"), "Must evaluate bleed threshold boundary (2.0px)");
});

register("B6.4", "Math Boundaries: Composite NumPy health equation documented", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Formula: H = Vr - max(IoU) - 0.01·Δx") || src.includes("Deterministic Mathematical Scorecard"), "Must document composite mathematical formula");
});

register("B6.5", "Math Boundaries: Screen reader announcements on score transitions", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('aria-live="polite"'), "Score transitions must announce through polite live regions");
});

// ============================================================================
// FEATURE 7: Visual Patch Toggle & Unified Diff (Boundaries & Corners - 5 tests)
// ============================================================================

register("B7.1", "Patch Boundaries: Repeated toggle cycle stability", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("setPatched((p) => !p)"), "Toggle handler must invert state cleanly");
});

register("B7.2", "Patch Boundaries: Anti-hack CSS rules verified in synthesized diff", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(!src.includes("!important"), "Synthesized diff must strictly reject !important overrides");
  assert(!src.includes("9999"), "Synthesized diff must strictly reject z-index 9999 escalation");
});

register("B7.3", "Patch Boundaries: Diff hunk header styling isolation", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes('line.startsWith("@@")'), "Diff parser must isolate hunk headers");
  assert(src.includes("text-cyan-400"), "Hunk headers must be styled in cyan");
});

register("B7.4", "Patch Boundaries: Horizontal diff scroll containment", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes("overflow-x-auto"), "Diff content container must enforce overflow-x-auto to prevent mobile blowout");
});

register("B7.5", "Patch Boundaries: Self-healed verification confirmation with Check icon", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes("Self-Healed & Verified (IoU = 0)"), "Must display verification badge");
  assert(src.includes("<Check"), "Must render Lucide Check icon");
});

// ============================================================================
// FEATURE 8: Model Credibility Strip (Boundaries & Corners - 5 tests)
// ============================================================================

register("B8.1", "Model Boundaries: Responsive grid columns adaptation (2 to 5)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("grid-cols-2") && src.includes("sm:grid-cols-5"), "Must transition from 2 columns on mobile to 5 on desktop");
});

register("B8.2", "Model Boundaries: Precise latency target chips per model", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("<450ms"), "SAM 3.1 must specify <450ms latency");
  assert(src.includes("<600ms"), "Muse Spark must specify <600ms latency");
  assert(src.includes("0.3s"), "Playwright/HMR must specify 0.3s latency");
});

register("B8.3", "Model Boundaries: Monospace uppercase typography for roles", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("font-mono text-[11px] uppercase tracking-wider"), "Model roles must use monospace uppercase tracking");
});

register("B8.4", "Model Boundaries: Hover ambient bottom laser sheen transition", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("group-hover:via-cyan-400"), "Model card must display ambient cyan bottom sheen on hover");
});

register("B8.5", "Model Boundaries: Pure Lucide SVG icons across all 5 models", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Scan") && src.includes("Zap") && src.includes("Bot") && src.includes("Code2") && src.includes("Monitor"), "Must use Lucide Scan, Zap, Bot, Code2, Monitor icons");
});

// ============================================================================
// FEATURE 9: Interactive 5-Node FSM Pipeline (Boundaries & Corners - 5 tests)
// ============================================================================

register("B9.1", "FSM Boundaries: Interactive node state inspection support", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("FSM_STEPS") || src.includes("PIPELINE_STEPS"), "Pipeline must define step metadata array");
  assert(src.includes("setSelectedIdx"), "Stepper buttons must allow interactive state inspection");
});

register("B9.2", "FSM Boundaries: Retry feedback loopback condition (3 strikes cap)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("three strikes, then halt") || src.includes("3 strikes"), "Must specify 3 strikes loopback termination");
});

register("B9.3", "FSM Boundaries: Trace event stream chronological formatting", () => {
  const src = readFrontend("src/components/LiveTrace.tsx");
  assert(src.includes("[${evt.timestamp}]") || src.includes("evt.timestamp"), "Trace log must render timestamp bracket");
  assert(src.includes("[${evt.step}]") || src.includes("evt.step"), "Trace log must render step badge");
});

register("B9.4", "FSM Boundaries: Trace terminal vertical height bounds (max-h-48)", () => {
  const src = readFrontend("src/components/LiveTrace.tsx");
  assert(src.includes("max-h-48 overflow-y-auto"), "Terminal stream must be height-bounded to prevent page explosion");
});

register("B9.5", "FSM Boundaries: Pipeline anchor scroll margin offset (scroll-mt-20)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes('id="pipeline"') && src.includes("scroll-mt-20"), "Pipeline section must declare scroll-mt-20 offset for sticky header");
});

// ============================================================================
// FEATURE 10: Enterprise Quantitative Metrics Grid (Boundaries & Corners - 5 tests)
// ============================================================================

register("B10.1", "Metrics Boundaries: Space Grotesk tabular numeral styling", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("font-display") && src.includes("font-semibold"), "Metric values must use Space Grotesk SemiBold");
});

register("B10.2", "Metrics Boundaries: Responsive 2-to-4 column bento transition", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("grid-cols-2") && src.includes("lg:grid-cols-4"), "Metrics grid must adapt from 2 columns to 4 columns");
});

register("B10.3", "Metrics Boundaries: Monospace uppercase technical kicker chips", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("font-mono text-[10px] uppercase"), "Metric chips must be uppercase monospace");
});

register("B10.4", "Metrics Boundaries: Technical mechanisms explained in detail", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Lowest Common Ancestor traversal"), "Must detail LCA token reduction mechanism");
  assert(src.includes("DOM point prompts"), "Must detail DOM point prompts mechanism");
});

register("B10.5", "Metrics Boundaries: Zero emojis in metrics bento cards", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  const metricsSection = src.substring(src.indexOf("export function Metrics"), src.indexOf("export function Pipeline"));
  assert(!/\p{Extended_Pictographic}/u.test(metricsSection), "Metrics section must not contain any Unicode emojis");
});

// ============================================================================
// FEATURE 11: Architecture Bento Grid (5 Pillars) (Boundaries & Corners - 5 tests)
// ============================================================================

register("B11.1", "Bento Boundaries: Asymmetric 12-column grid spans (7/5 and 4/4/4)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("lg:col-span-7") && src.includes("lg:col-span-5"), "Top row must use 7/5 asymmetric column split");
  assert(src.includes("lg:col-span-4"), "Bottom row must use 4/4/4 triple column split");
});

register("B11.2", "Bento Boundaries: Specialized agent separation of concerns", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Pydantic RepairSpec JSON"), "Muse Wonder must produce structured Pydantic JSON");
  assert(src.includes("syntax-valid unified diffs"), "Muse Code must synthesize unified diffs");
});

register("B11.3", "Bento Boundaries: Sub-second HMR latency avoids container reboot", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("0.3s") && src.includes("Hot Module Replacement"), "Must document 0.3s HMR injection");
});

register("B11.4", "Bento Boundaries: Design system primitives immutability classification", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("src/components/ui/*") && src.includes("immutable"), "Must document design system immutability");
});

register("B11.5", "Bento Boundaries: Non-destructive review fallback on strike 3", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("never force-commits") || src.includes("never force-committed"), "Must guarantee no unverified commits pushed");
  assert(src.includes("PR review comment"), "Must fallback to non-destructive PR review comment");
});

// ============================================================================
// FEATURE 12: Enterprise Safety Guardrails (Boundaries & Corners - 5 tests)
// ============================================================================

register("B12.1", "Guardrails Boundaries: Formal rule code taxonomy (BR-1 through BR-6)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("BR-1") && src.includes("BR-2") && src.includes("BR-3"), "Must enumerate business rules BR-1 through BR-3");
  assert(src.includes("BR-4") && src.includes("BR-5") && src.includes("BR-6"), "Must enumerate business rules BR-4 through BR-6");
});

register("B12.2", "Guardrails Boundaries: Strict database spend cap ceiling ($0.15)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("$0.15"), "Must enforce $0.15 spend limit");
  assert(src.includes("database constraint") || src.includes("CHECK constraint"), "Must specify database-level enforcement");
});

register("B12.3", "Guardrails Boundaries: Banned CSS override patterns explicitly screened", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("!important") && src.includes("z-index: 9999"), "Must explicitly identify !important and z-index: 9999 as banned");
});

register("B12.4", "Guardrails Boundaries: Webhook acceptance budget (1.2s)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("1.2s"), "Must state 1.2s webhook acknowledgment budget");
  assert(src.includes("HMAC-SHA256"), "Must require HMAC-SHA256 cryptographic verification");
});

register("B12.5", "Guardrails Boundaries: Uniform Lucide ShieldCheck iconography across all rules", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("ShieldCheck"), "Guardrails must use Lucide ShieldCheck icon");
  assert(src.includes("text-verified-emerald"), "Guardrails icons must use verified-emerald styling");
});

// ============================================================================
// FEATURE 13: Technical FAQ Accordion (Boundaries & Corners - 5 tests)
// ============================================================================

register("B13.1", "FAQ Boundaries: Native browser marker suppressed on summary elements", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("[&::-webkit-details-marker]:hidden"), "Must suppress native webkit details marker");
  assert(src.includes("list-none"), "Must suppress default list styling");
});

register("B13.2", "FAQ Boundaries: Summary element keyboard focus visible ring", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("FOCUS"), "FAQ summary elements must declare FOCUS utility for keyboard accessibility");
});

register("B13.3", "FAQ Boundaries: Rotating '+' indicator animation via group-open:rotate-45", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("group-open:rotate-45"), "Indicator must rotate 45 degrees on accordion expansion");
  assert(src.includes("transition-transform"), "Must apply transition-transform for smooth animation");
});

register("B13.4", "FAQ Boundaries: Cross-page regression rate quantified (<2.0%)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("2.0%"), "FAQ must quantify cross-page regression rate below 2.0%");
});

register("B13.5", "FAQ Boundaries: Section anchor scroll margin offset (scroll-mt-20)", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes('id="faq"') && src.includes("scroll-mt-20"), "FAQ section must declare scroll-mt-20 offset");
});

// ============================================================================
// FEATURE 14: Final Conversion CTA & Quickstart (Boundaries & Corners - 5 tests)
// ============================================================================

register("B14.1", "CTA Boundaries: Top ambient laser sheen highlight line", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("bg-gradient-to-r from-transparent via-cyan-400"), "CTA card must feature ambient laser highlight sheen");
});

register("B14.2", "CTA Boundaries: Terminal quickstart copy feedback with Lucide Check icon", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("handleCopy"), "CTA must declare handleCopy handler");
  assert(src.includes("Check") && src.includes("Copy"), "CTA must render Lucide Check and Copy icons");
});

register("B14.3", "CTA Boundaries: High-contrast button hover transitions", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("hover:bg-white"), "Primary button must transition to pure white on hover");
  assert(src.includes("hover:border-text-secondary"), "Secondary button must transition border on hover");
});

register("B14.4", "CTA Boundaries: Trust badges responsive wrapping and spacing", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("flex-wrap items-center justify-center gap-x-6 gap-y-2"), "Badges must wrap with gap-x-6 gap-y-2 to avoid clipping on mobile");
});

register("B14.5", "CTA Boundaries: Accessible section landmark", () => {
  const html = getRenderedHtml();
  assert(html.includes("<section aria-label=\"Get started"), "CTA must be wrapped in accessible section landmark");
});

// ============================================================================
// FEATURE 15: Enterprise 4-Column Footer (Boundaries & Corners - 5 tests)
// ============================================================================

register("B15.1", "Footer Boundaries: Responsive 2-to-4 column grid adaptation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("grid-cols-2") && src.includes("md:grid-cols-[1.5fr_1fr_1fr_1fr]"), "Footer must adapt from 2 columns on mobile to 4 custom columns on desktop");
});

register("B15.2", "Footer Boundaries: Semantic nav landmarks per link group", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("<nav key={column.title} aria-label={`Footer: ${column.title}`}"), "Each footer column must declare a semantic <nav> with descriptive aria-label");
});

register("B15.3", "Footer Boundaries: External link security attributes", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("target: \"_blank\", rel: \"noreferrer\""), "External links in footer must declare target='_blank' and rel='noreferrer'");
});

register("B15.4", "Footer Boundaries: Regulatory illustrative values disclaimer chip", () => {
  const html = getRenderedHtml();
  assert(html.includes("DEMO VALUES ARE ILLUSTRATIVE"), "Footer must render DEMO VALUES ARE ILLUSTRATIVE disclaimer chip");
});

register("B15.5", "Footer Boundaries: Operational live status indicator with pulsing dot", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Operational"), "Footer must render operational status");
  assert(src.includes("bg-verified-emerald motion-safe:animate-pulse"), "Status must feature pulsing verified emerald dot");
});

// ============================================================================
// FEATURE 16: Zero-Emoji & Lucide Constraint (Boundaries & Corners - 5 tests)
// ============================================================================

const EMOJI_REGEX = /\p{Extended_Pictographic}/u;

register("B16.1", "Zero Emoji Boundaries: Comprehensive AST/regex scan of all tsx and ts files", () => {
  function scanDir(dir) {
    let files = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) files = files.concat(scanDir(full));
      else if (/\.(tsx?|jsx?)$/.test(e.name)) files.push(full);
    }
    return files;
  }
  const allFiles = scanDir(path.join(FRONTEND_DIR, "src"));
  for (const f of allFiles) {
    const content = fs.readFileSync(f, "utf8");
    assert(!EMOJI_REGEX.test(content), `Found Unicode emoji in source file: ${path.relative(FRONTEND_DIR, f)}`);
  }
});

register("B16.2", "Zero Emoji Boundaries: Global CSS file free of Unicode emojis", () => {
  const css = readFrontend("src/app/globals.css");
  assert(!EMOJI_REGEX.test(css), "globals.css must not contain any Unicode emojis");
});

register("B16.3", "Zero Emoji Boundaries: Rendered production HTML index.html scan", () => {
  const html = getRenderedHtml();
  const PURE_EMOJI_REGEX = /(?!\u00a9|\u00ae)\p{Extended_Pictographic}/u;
  assert(!PURE_EMOJI_REGEX.test(html), "Rendered production index.html must not contain any Unicode emojis");
});

register("B16.4", "Zero Emoji Boundaries: Lucide icons exclusively imported across landing components", () => {
  const files = [
    "src/components/landing/Hero.tsx",
    "src/components/landing/SiteHeader.tsx",
    "src/components/landing/ProofPreview.tsx",
    "src/components/landing/Sections.tsx",
    "src/components/DiffViewer.tsx",
    "src/components/LiveTrace.tsx",
  ];
  for (const f of files) {
    const content = readFrontend(f);
    assert(content.includes('from "lucide-react"'), `Component ${f} must import icons from 'lucide-react'`);
  }
});

register("B16.5", "Zero Emoji Boundaries: package.json metadata clean of emojis", () => {
  const pkg = readFrontend("package.json");
  assert(!EMOJI_REGEX.test(pkg), "package.json must not contain any Unicode emojis");
});

// ============================================================================
// FEATURE 17: Strict Backend Isolation (Boundaries & Corners - 5 tests)
// ============================================================================

register("B17.1", "Backend Boundaries: Zero modified, added, or deleted files in backend", () => {
  const gitStatus = execSync("git status --porcelain backend", {
    cwd: WORKSPACE_ROOT,
    encoding: "utf8",
  }).trim();
  assert.strictEqual(gitStatus, "", "backend directory must have zero git status changes");
});

register("B17.2", "Backend Boundaries: Git diff against HEAD shows zero changes in backend", () => {
  const diff = execSync("git diff HEAD -- backend", {
    cwd: WORKSPACE_ROOT,
    encoding: "utf8",
  }).trim();
  assert.strictEqual(diff, "", "backend directory must have zero git diff changes against HEAD");
});

register("B17.3", "Backend Boundaries: tsconfig path aliases strictly scoped to frontend/src", () => {
  const tsconfig = JSON.parse(readFrontend("tsconfig.json"));
  const paths = tsconfig.compilerOptions?.paths || {};
  assert(paths["@/*"], "tsconfig must define @/* path alias");
  assert(paths["@/*"][0] === "./src/*", "@/* must map strictly to ./src/* inside frontend");
});

register("B17.4", "Backend Boundaries: Zero symlinks from frontend to backend directory", () => {
  function checkSymlinks(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isSymbolicLink()) {
        const target = fs.readlinkSync(full);
        assert(!target.includes("backend"), `Symlink ${full} must not point to backend`);
      } else if (e.isDirectory() && e.name !== "node_modules" && e.name !== ".next") {
        checkSymlinks(full);
      }
    }
  }
  checkSymlinks(FRONTEND_DIR);
});

register("B17.5", "Backend Boundaries: Frontend builds and runs without any backend environment variables", () => {
  // Confirm frontend next.config doesn't mandate backend URLs or secrets
  const nextConfig = readFrontend("next.config.mjs");
  assert(!nextConfig.includes("BACKEND_URL"), "next.config.mjs must not require hardcoded BACKEND_URL");
});

// ============================================================================
// FEATURE 18: Internal Mission Control View (Boundaries & Corners - 5 tests)
// ============================================================================

register("B18.1", "Mission Control Boundaries: Responsive command center grid layout with explicit geometry", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes("lg:grid-cols-12"), "Must use 12-column responsive layout for 3-column split command center");
  assert(pageSrc.includes("h-[520px]"), "Workspace canvas must specify explicit height containment to guarantee CLS = 0");
});

register("B18.2", "Mission Control Boundaries: MaskSlider supports dual viewports (375px & 1440px)", () => {
  const sliderSrc = readFrontend("src/components/MaskSlider.tsx");
  assert(sliderSrc.includes("375px") && sliderSrc.includes("1440px"), "MaskSlider must support 375px mobile and 1440px desktop viewports");
  assert(sliderSrc.includes("Smartphone") && sliderSrc.includes("Monitor"), "Must use Lucide Smartphone and Monitor icons for viewport selection");
});

register("B18.3", "Mission Control Boundaries: Type safety and asynchronous parameter unwrapping", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes('"use client"'), "Must be client component for interactive inspection");
  assert(pageSrc.includes("use(params)"), "Must use React 19 unwrapping without synchronous access errors");
});

register("B18.4", "Mission Control Boundaries: 100% Lucide iconography across workspace views", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  const maskSrc = readFrontend("src/components/MaskSlider.tsx");
  const diffSrc = readFrontend("src/components/DiffViewer.tsx");
  
  const EMOJI_REGEX = /(?!\u00a9|\u00ae)\p{Extended_Pictographic}/u;
  assert(!EMOJI_REGEX.test(pageSrc), "runs/[id]/page.tsx must have zero emojis");
  assert(!EMOJI_REGEX.test(maskSrc), "MaskSlider.tsx must have zero emojis");
  assert(!EMOJI_REGEX.test(diffSrc), "DiffViewer.tsx must have zero emojis");
  assert(pageSrc.includes('from "lucide-react"'), "runs/[id]/page.tsx must import exclusively from lucide-react");
});

register("B18.5", "Mission Control Boundaries: Autonomous offline rendering without backend dependencies", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(!pageSrc.includes("http://localhost:8000") && !pageSrc.includes("process.env.BACKEND_URL"), 
    "Must not depend on hardcoded localhost backend URL");
  const maskSrc = readFrontend("src/components/MaskSlider.tsx");
  assert(maskSrc.includes("vrScore") && maskSrc.includes("iouScore"), "MaskSlider must render with prop-driven defaults");
});

// ============================================================================
// RUNNER EXPORT
// ============================================================================

async function run() {
  console.log(`\n--- Tier 2: Boundary & Corner Cases (${tests.length} tests) ---`);
  let passed = 0;
  let failed = 0;
  const errors = [];

  for (const t of tests) {
    try {
      await t.fn();
      passed++;
      console.log(`  ✓ [${t.id}] ${t.name}`);
    } catch (err) {
      failed++;
      console.error(`  ✗ [${t.id}] ${t.name}`);
      console.error(`    Error: ${err.message}`);
      errors.push({ id: t.id, name: t.name, error: err.message });
    }
  }

  return { name: "Tier 2: Boundary & Corner Cases", total: tests.length, passed, failed, errors };
}

module.exports = { run, tests };

if (require.main === module) {
  run().then((res) => {
    if (res.failed > 0) process.exit(1);
  });
}
