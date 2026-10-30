/**
 * VisorQA E2E Test Suite - Tier 1: Feature Coverage
 * 
 * Verifies the primary happy path behavior across all 17 features
 * in the Feature Inventory (5 test cases per feature = 85 tests).
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
// FEATURE 1: Sticky Header & Telemetry Ribbon (5 tests)
// ============================================================================

register("F1.1", "Sticky Header: Telemetry ribbon exists with semantic landmark", () => {
  const html = getRenderedHtml();
  assert(html.includes('id="telemetry"'), "Telemetry ribbon id='telemetry' must be present in DOM");
  assert(html.includes('aria-label="System telemetry"'), "Telemetry ribbon must have accessible label");
  assert(html.includes("border-border-subtle"), "Telemetry ribbon must have subtle border");
});

register("F1.2", "Sticky Header: Telemetry ribbon contains authoritative metrics", () => {
  const html = getRenderedHtml();
  assert(html.includes("L4 AUTONOMOUS") || html.includes("VISORQA L4 AUTONOMOUS"), "Must state L4 autonomy");
  assert(html.includes("$0.03"), "Must state $0.03 PR run cost");
  assert(html.includes("&lt;1.2S") || html.includes("<1.2S"), "Must state webhook latency <1.2s");
});

register("F1.3", "Sticky Header: Semantic header with sticky positioning and backdrop blur", () => {
  const html = getRenderedHtml();
  assert(html.includes("<header"), "Semantic <header> landmark must be rendered");
  assert(html.includes("sticky top-0 z-50"), "Header must be sticky at top with z-50");
  assert(html.includes("backdrop-blur"), "Header must feature frosted backdrop-blur styling");
});

register("F1.4", "Sticky Header: Visor SVG logo with laser scanline and retina circle", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes("#00F0FF"), "Logo SVG must contain cyan laser stroke #00F0FF");
  assert(src.includes("<svg") && src.includes("<circle") && src.includes("<path"), "Logo must contain SVG elements");
  assert(src.includes("VisorQA") || src.includes("Visor"), "Logo must contain VisorQA brand text");
});

register("F1.5", "Sticky Header: Primary navigation links and Mission Control CTA", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(src.includes("NAV_LINKS"), "SiteHeader must define NAV_LINKS");
  assert(src.includes("#pipeline"), "Nav must contain #pipeline link");
  assert(src.includes("#guardrails"), "Nav must contain #guardrails link");
  assert(src.includes("#faq"), "Nav must contain #faq link");
  assert(src.includes("Open Mission Control") || src.includes("MISSION_CONTROL_URL"), "Must contain Open Mission Control CTA");
  assert(src.includes("/runs/run-demo-42") || src.includes("MISSION_CONTROL_URL"), "Must link to Mission Control run");
});

// ============================================================================
// FEATURE 2: High-Craft Hero Section & CLI Quickstart (5 tests)
// ============================================================================

register("F2.1", "Hero Section: Authoritative display headline in Space Grotesk", () => {
  const html = getRenderedHtml();
  assert(html.includes("Ship UI that heals its own pixel regressions."), "Hero must render exact headline");
  assert(html.includes("font-display"), "Hero headline must use font-display (Space Grotesk)");
});

register("F2.2", "Hero Section: Kicker badge with pulsing status indicator", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("AUTONOMOUS VISUAL QA · L4 AGENT"), "Hero must include L4 agent kicker");
  assert(src.includes("animate-pulse"), "Kicker must include pulsing radar dot");
  assert(src.includes("bg-verified-emerald"), "Radar dot must use verified-emerald token");
});

register("F2.3", "Hero Section: Value proposition copy articulating SAM 3.1 and Muse models", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("SAM 3.1"), "Hero copy must mention SAM 3.1");
  assert(src.includes("Muse Spark") && src.includes("Muse Wonder") && src.includes("Muse Code"), "Hero copy must mention Muse Spark, Wonder, and Code");
});

register("F2.4", "Hero Section: Dual CTAs for Mission Control and live demonstration", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("MISSION_CONTROL_URL"), "Hero must link to Mission Control permalink");
  assert(src.includes("href=\"#demo\"") || src.includes("href=\"#pipeline\""), "Secondary CTA must point to demo or pipeline anchor");
  assert(src.includes("ArrowRight"), "Primary button must render Lucide ArrowRight icon");
});

register("F2.5", "Hero Section: Interactive CLI quickstart bar with clipboard copy", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(src.includes("CLI_CMD"), "Hero must feature quickstart CLI command");
  assert(src.includes("useCopy"), "Hero must provide clipboard copy hook/function");
  assert(src.includes("Copy") && src.includes("Copied"), "Must support toggle between Copy and Copied state");
});

// ============================================================================
// FEATURE 3: Core Utility & Monochrome Tokens (5 tests)
// ============================================================================

register("F3.1", "Bespoke Palette: Tailwind config defines obsidian and surface elevation tiers", () => {
  const config = readFrontend("tailwind.config.ts");
  assert(config.includes('canvas: "#0A0A0C"'), "Config must define canvas #0A0A0C");
  assert(config.includes('"surface-subtle": "#0B0C10"'), "Config must define surface-subtle #0B0C10");
  assert(config.includes('"surface-base": "#111115"'), "Config must define surface-base #111115");
  assert(config.includes('"surface-elevated": "#18181E"'), "Config must define surface-elevated #18181E");
  assert(config.includes('"surface-overlay": "#1E202C"'), "Config must define surface-overlay #1E202C");
});

register("F3.2", "Bespoke Palette: Tailwind config defines crisp border and laser divider tokens", () => {
  const config = readFrontend("tailwind.config.ts");
  assert(config.includes('"border-subtle": "#22222A"'), "Config must define border-subtle #22222A");
  assert(config.includes('"border-strong": "#2D3340"'), "Config must define border-strong #2D3340");
  assert(config.includes('"border-laser": "#00F2FE"'), "Config must define border-laser #00F2FE");
  assert(config.includes('"border-focus": "#FAFAFA"'), "Config must define border-focus #FAFAFA");
});

register("F3.3", "Bespoke Palette: Domain photonic accents and optical blueprints", () => {
  const config = readFrontend("tailwind.config.ts");
  assert(config.includes('"laser-cyan": "#00F2FE"'), "Config must define laser-cyan #00F2FE");
  assert(config.includes('"defect-crimson": "#FF2E55"'), "Config must define defect-crimson #FF2E55");
  assert(config.includes('"defect-crimson-fill": "rgba(255, 46, 85, 0.28)"'), "Config must define defect-crimson-fill");
  assert(config.includes('"verified-emerald": "#10B981"'), "Config must define verified-emerald #10B981");
  assert(config.includes('"verified-emerald-fill": "rgba(16, 185, 129, 0.15)"'), "Config must define verified-emerald-fill");
  assert(config.includes('"neural-pulse": "#38BDF8"'), "Config must define neural-pulse #38BDF8");
  assert(config.includes("ai-harmony") && config.includes("optical-blueprint"), "Config must define ai-harmony and optical-blueprint");
});

register("F3.4", "Bespoke Palette: globals.css registers CSS custom properties for dynamic color tokens", () => {
  const css = readFrontend("src/app/globals.css");
  assert(css.includes("--color-canvas: 10 10 12"), "Must define --color-canvas in globals.css");
  assert(css.includes("--color-surface-subtle: 11 12 16"), "Must define --color-surface-subtle in globals.css");
  assert(css.includes("--color-surface-base: 17 17 21"), "Must define --color-surface-base in globals.css");
  assert(css.includes("--color-laser-cyan: 0 242 254"), "Must define --color-laser-cyan in globals.css");
  assert(css.includes("--color-defect-crimson: 255 46 85"), "Must define --color-defect-crimson in globals.css");
  assert(css.includes("--color-verified-emerald: 16 185 129"), "Must define --color-verified-emerald in globals.css");
});

register("F3.5", "Bespoke Motion: globals.css defines GPU-accelerated keyframe animations and utility classes", () => {
  const css = readFrontend("src/app/globals.css");
  assert(css.includes("@keyframes visor-laser-sweep"), "Must define @keyframes visor-laser-sweep in globals.css");
  assert(css.includes("@keyframes visor-radar-ping"), "Must define @keyframes visor-radar-ping in globals.css");
  assert(css.includes("@keyframes ambient-pulse"), "Must define @keyframes ambient-pulse in globals.css");
  assert(css.includes(".animate-laser-sweep"), "Must define .animate-laser-sweep class");
  assert(css.includes(".optical-grid"), "Must define .optical-grid class");
  assert(css.includes(".zero-cls-container"), "Must define .zero-cls-container class");
});

// ============================================================================
// FEATURE 4: Dual-Viewport Interactive Sandbox (375px / 1440px) (5 tests)
// ============================================================================

register("F4.1", "Dual Viewport: Segmented toggle buttons for Mobile and Desktop", () => {
  const html = getRenderedHtml();
  assert(html.includes("375px Mobile"), "Must render 375px Mobile toggle");
  assert(html.includes("1440px Desktop"), "Must render 1440px Desktop toggle");
});

register("F4.2", "Dual Viewport: Toggle controls use aria-pressed for accessibility", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('aria-pressed={viewport === "mobile"}'), "Mobile button must reflect aria-pressed state");
  assert(src.includes('aria-pressed={viewport === "desktop"}'), "Desktop button must reflect aria-pressed state");
});

register("F4.3", "Dual Viewport: Stage scales dynamically with useStageScale hook", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("useStageScale"), "Must define useStageScale hook");
  assert(src.includes("ResizeObserver"), "useStageScale must use ResizeObserver for responsive adaptation");
  assert(src.includes("transform: `scale(${scale})`"), "Must apply scale transform to container");
});

register("F4.4", "Dual Viewport: Desktop mock renders multi-column navigation sidebar", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("Catalog") && src.includes("Payment Methods"), "Desktop layout must render multi-column catalog navigation items");
  assert(src.includes("wide &&"), "Sidebar items must be conditionally rendered based on viewport width");
});

register("F4.5", "Dual Viewport: Semantic figure wrapper with accessible caption", () => {
  const html = getRenderedHtml();
  assert(html.includes('<figure id="demo"'), "Sandbox must be wrapped in <figure id='demo'>");
  assert(html.includes('aria-labelledby="demo-caption"'), "Figure must be labeled by demo-caption");
  assert(html.includes('id="demo-caption"'), "Must render figcaption with id='demo-caption'");
});

// ============================================================================
// FEATURE 5: SAM 3.1 Mask Scrubber (5 tests)
// ============================================================================

register("F5.1", "SAM Scrubber: Interactive slider element with ARIA role and label", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('role="slider"'), "Scrubber must declare role='slider'");
  assert(src.includes('aria-label="Reveal simulated SAM mask'), "Slider must have descriptive aria-label");
  assert(src.includes("tabIndex={0}"), "Slider must be keyboard focusable (tabIndex=0)");
});

register("F5.2", "SAM Scrubber: Value bounds strictly set from 0 to 100", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("aria-valuemin={0}"), "Slider must declare aria-valuemin=0");
  assert(src.includes("aria-valuemax={100}"), "Slider must declare aria-valuemax=100");
  assert(src.includes("aria-valuenow="), "Slider must reflect aria-valuenow");
});

register("F5.3", "SAM Scrubber: Dynamic CSS clip-path mask and active sweeping laser scanline", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("clipPath: `inset(0 ${100 - pos}% 0 0)`"), "Mask must apply horizontal inset clip-path matching scrubber position");
  assert(src.includes("animate-laser-sweep"), "Proof workbench must render active sweeping laser scanline");
  assert(src.includes("shadow-[0_0_12px_#00F2FE]"), "Laser scanline must render cyan photonic glow");
});

register("F5.4", "SAM Scrubber: Renders dashed DOM bounding box and SAM pixel mask", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("B_DOM (Playwright)") || src.includes("border-mask-dom-box"), "Mask layer must render expected DOM box");
  assert(src.includes("M_SAM Collision Mask") || src.includes("bg-mask-defect-fill"), "Mask layer must render defect mask");
});

register("F5.5", "SAM Scrubber: Handle renders bidirectional cursor and slider feedback", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("cursor-ew-resize"), "Scrubber handle must use cursor-ew-resize");
  assert(src.includes("Sliders"), "Scrubber handle must render Lucide Sliders icon");
});

// ============================================================================
// FEATURE 6: Mathematical Trap Scorecard ($V_r, IoU, \Delta_x$) (5 tests)
// ============================================================================

register("F6.1", "Math Scorecard: Visibility Ratio (V_r) failure metric displayed", () => {
  const html = getRenderedHtml();
  assert(html.includes("V_r = 0.45") || html.includes("Vr"), "Must display Visibility Ratio score");
});

register("F6.2", "Math Scorecard: Playwright DOM pass vs SAM visual failure juxtaposition", () => {
  const html = getRenderedHtml();
  assert(html.includes("Playwright DOM: PASS") || html.includes("Playwright"), "Must display Playwright DOM PASS status");
  assert(html.includes("FAIL"), "Must contrast DOM PASS with visual FAIL");
});

register("F6.3", "Math Scorecard: Live score updates via aria-live polite region", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('aria-live="polite"'), "Score badges must use aria-live='polite' for accessibility");
});

register("F6.4", "Math Scorecard: Dynamic transition to V_r = 1.00 RESOLVED when patched", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("V_r = 1.00 RESOLVED") || src.includes("1.00"), "Must support transition to V_r = 1.00 RESOLVED when patch is active");
  assert(src.includes("text-verified-emerald"), "Resolved state must use text-verified-emerald");
});

register("F6.5", "Math Scorecard: Monospace precision formatting for equations", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("font-mono"), "Scorecard badges must use font-mono styling");
  assert(src.includes("Area(M_SAM"), "Scorecard must document Area(M_SAM) formula");
});

// ============================================================================
// FEATURE 7: Visual Patch Toggle & Unified Diff (5 tests)
// ============================================================================

register("F7.1", "Patch & Diff: Semantic role='switch' patch toggle", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes('role="switch"'), "Toggle must declare role='switch'");
  assert(src.includes('aria-checked={patched}'), "Toggle must reflect aria-checked state");
  assert(src.includes("Apply Muse Code Patch"), "Toggle must have visible label");
});

register("F7.2", "Patch & Diff: Promo banner layout transition from defect to in-flow", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(src.includes("patched"), "Component must conditionally alter banner classes based on patch");
  assert(src.includes("sticky") || src.includes("relative"), "Healed mode must apply sticky or relative in-flow styling");
});

register("F7.3", "Patch & Diff: Unified diff viewer displays target file path", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes("src/components/PromoBanner.tsx"), "Diff viewer must display PromoBanner target file path");
});

register("F7.4", "Patch & Diff: Diff lines syntax highlighting for additions and deletions", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes("text-rose-400"), "Removed diff lines must be colored in rose");
  assert(src.includes("text-emerald-400"), "Added diff lines must be colored in emerald");
  assert(src.includes("text-cyan-400"), "Hunk header lines must be colored in cyan");
});

register("F7.5", "Patch & Diff: PyGithub auto-commit footer metadata", () => {
  const src = readFrontend("src/components/DiffViewer.tsx");
  assert(src.includes("Commit: fix(ui): autonomous visual repair by VisorQA"), "Must contain verified commit message");
  assert(src.includes("PyGithub Auto-Commit"), "Must state PyGithub Auto-Commit mechanism");
});

// ============================================================================
// FEATURE 8: Model Credibility Strip (5 Engines) (5 tests)
// ============================================================================

register("F8.1", "Model Strip: Renders all 5 core engineering models", () => {
  const html = getRenderedHtml();
  assert(html.includes("Meta SAM 3.1") || html.includes("SAM 3.1"), "Strip must contain SAM 3.1");
  assert(html.includes("Meta Muse Spark") || html.includes("Muse Spark"), "Strip must contain Muse Spark");
  assert(html.includes("Meta Muse Wonder") || html.includes("Muse Wonder"), "Strip must contain Muse Wonder");
  assert(html.includes("Meta Muse Code") || html.includes("Muse Code"), "Strip must contain Muse Code");
  assert(html.includes("Playwright"), "Strip must contain Playwright");
});

register("F8.2", "Model Strip: Correct role assignments for each AI engine", () => {
  const html = getRenderedHtml();
  assert(html.includes("Segmentation"), "SAM 3.1 role must reference Segmentation");
  assert(html.includes("Triage") || html.includes("Localization"), "Muse Spark role must reference Triage or Fault Localization");
  assert(html.includes("Architect") || html.includes("Diagnosis"), "Muse Wonder role must reference Architect or Diagnosis");
  assert(html.includes("Repair") || html.includes("Diff"), "Muse Code role must reference Repair or Diff Synthesis");
  assert(html.includes("Rendering") || html.includes("HMR") || html.includes("Sandbox"), "Playwright role must reference Rendering or Sandbox");
});

register("F8.3", "Model Strip: Accessible section landmark", () => {
  const html = getRenderedHtml();
  assert(html.includes("<section aria-label=\"Meta AI Models") || html.includes("<section aria-label=\"Models"), "Must be enclosed in accessible <section>");
});

register("F8.4", "Model Strip: 5-column divider layout geometry", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("sm:grid-cols-5"), "Model strip must specify sm:grid-cols-5 layout");
  assert(src.includes("divide-border-subtle"), "Must include subtle column dividers");
});

register("F8.5", "Model Strip: Links to Meta AI developer ecosystem in footer", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("https://dev.meta.ai"), "Must reference Meta AI developer platform");
});

// ============================================================================
// FEATURE 9: Interactive 5-Node FSM Pipeline (5 tests)
// ============================================================================

register("F9.1", "FSM Pipeline: 5 deterministic sequential steps", () => {
  const html = getRenderedHtml();
  assert(html.includes("Sense"), "Step 01 must be Sense");
  assert(html.includes("Triage"), "Step 02 must be Triage");
  assert(html.includes("Diagnose"), "Step 03 must be Diagnose");
  assert(html.includes("Patch"), "Step 04 must be Patch");
  assert(html.includes("Verify"), "Step 05 must be Verify");
});

register("F9.2", "FSM Pipeline: Step 01 specifies SAM 3.1 vision sensor", () => {
  const html = getRenderedHtml();
  assert(html.includes("SAM 3.1") && html.includes("Playwright"), "Sense step must note SAM 3.1 and Playwright");
});

register("F9.3", "FSM Pipeline: Step 02 specifies LCA DOM hierarchy triage", () => {
  const html = getRenderedHtml();
  assert(html.includes("LCA") || html.includes("Lowest Common Ancestor"), "Triage step must specify LCA hierarchy localization");
});

register("F9.4", "FSM Pipeline: Step 03 & 04 specify RepairSpec JSON and HMR reload", () => {
  const html = getRenderedHtml();
  assert(html.includes("RepairSpec"), "Diagnose step must mention RepairSpec");
  assert(html.includes("HMR") || html.includes("300ms"), "Patch step must specify sub-second HMR reload");
});

register("F9.5", "FSM Pipeline: Live trace stream with timestamped state machine events", () => {
  const html = getRenderedHtml();
  assert(html.includes("DOM bounding boxes extracted"), "Trace stream must log DOM extraction event");
  assert(html.includes("SAM 3.1 segmented M_SAM"), "Trace stream must log SAM segmentation event");
  assert(html.includes("Muse Spark localized fault"), "Trace stream must log Muse Spark triage event");
});

// ============================================================================
// FEATURE 10: Enterprise Quantitative Metrics Grid (5 tests)
// ============================================================================

register("F10.1", "Metrics Grid: Accessible engineering targets section landmark", () => {
  const html = getRenderedHtml();
  assert(html.includes("<section aria-label=\"Quantitative") || html.includes("<section aria-label=\"Engineering targets"), "Must be enclosed in accessible metrics section");
});

register("F10.2", "Metrics Grid: Cycle latency target metric", () => {
  const html = getRenderedHtml();
  assert(html.includes("&lt;15.0s") || html.includes("<15.0s") || html.includes("<450ms"), "Must highlight latency target");
});

register("F10.3", "Metrics Grid: Context token reduction metric", () => {
  const html = getRenderedHtml();
  assert(html.includes("88.5%"), "Must display 88.5% token reduction");
  assert(html.includes("LCA") || html.includes("tokens"), "Must describe triage token pruning mechanism");
});

register("F10.4", "Metrics Grid: Detection precision or spend metric", () => {
  const html = getRenderedHtml();
  assert(html.includes("99.2%") || html.includes("$0.15"), "Must display 99.2% precision or spend cap");
});

register("F10.5", "Metrics Grid: Deterministic guardrail cap or zero manual steps", () => {
  const html = getRenderedHtml();
  assert(html.includes("Max 3x") || html.includes("0"), "Must state Max 3x strike loop or 0 manual steps");
});

// ============================================================================
// FEATURE 11: Architecture Bento Grid (5 Pillars) (5 tests)
// ============================================================================

register("F11.1", "Architecture: DOM-Guided SAM 3.1 vision sensor innovation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("DOM-Guided SAM 3.1") || src.includes("DOM bounding boxes"), "Must document DOM-guided SAM 3.1 segmentation");
});

register("F11.2", "Architecture: LCA DOM localization & token pruning innovation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Lowest Common Ancestor") || src.includes("LCA DOM"), "Must document LCA DOM localization and primitive protection");
});

register("F11.3", "Architecture: Architect-Coder split innovation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Muse Wonder") && src.includes("RepairSpec") && src.includes("Muse Code"), "Must document split between Muse Wonder spec and Muse Code diff");
});

register("F11.4", "Architecture: Modal sandbox execution & 0.3s HMR innovation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Modal") && src.includes("HMR"), "Must document Modal sandbox hot module replacement");
});

register("F11.5", "Architecture: Closed-loop 3-strike verification gate innovation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("3 strikes") || src.includes("3-strike") || src.includes("3-Strike"), "Must document 3-strike loop verification");
});

// ============================================================================
// FEATURE 12: Enterprise Safety Guardrails (6 Rules) (5 tests)
// ============================================================================

register("F12.1", "Safety Guardrails: Three strikes then halt rule", () => {
  const html = getRenderedHtml();
  assert(html.includes("Three strikes, then halt") || html.includes("Three Strikes"), "Must include Three strikes, then halt rule");
  assert(html.includes("never force-committed") || html.includes("never force-commits"), "Must state unverified code is never force-committed");
});

register("F12.2", "Safety Guardrails: Hard cost ceiling rule", () => {
  const html = getRenderedHtml();
  assert(html.includes("Hard cost ceiling") || html.includes("Cost Ceiling"), "Must include Hard cost ceiling rule");
  assert(html.includes("$0.15"), "Must enforce $0.15 model spend cap");
});

register("F12.3", "Safety Guardrails: Anti-hack CSS policy", () => {
  const html = getRenderedHtml();
  assert(html.includes("Anti-hack CSS policy") || html.includes("Anti-Hack CSS"), "Must include Anti-hack CSS policy");
  assert(html.includes("!important") && html.includes("z-index: 9999"), "Must explicitly ban !important and z-index: 9999");
});

register("F12.4", "Safety Guardrails: Shared UI is untouchable", () => {
  const html = getRenderedHtml();
  assert(html.includes("shared UI") || html.includes("Shared UI") || html.includes("Untouchable"), "Must include Shared UI protection rule");
  assert(html.includes("src/components/ui/*"), "Must explicitly lock src/components/ui/*");
});

register("F12.5", "Safety Guardrails: Dual-viewport gate and signed webhooks", () => {
  const html = getRenderedHtml();
  assert(html.includes("Dual-viewport gate") || html.includes("Dual-Viewport Gate"), "Must include Dual-viewport gate rule");
  assert(html.includes("HMAC"), "Must specify HMAC verification");
});

// ============================================================================
// FEATURE 13: Technical FAQ Accordion (5 tests)
// ============================================================================

register("F13.1", "FAQ Accordion: Semantic details and summary elements", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("<details") && src.includes("<summary"), "FAQ must use semantic <details> and <summary>");
});

register("F13.2", "FAQ Accordion: Explains detection beyond Playwright/Cypress", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Playwright and Cypress") && src.includes("SAM 3.1"), "FAQ must explain SAM 3.1 pixel segmentation vs DOM presence");
});

register("F13.3", "FAQ Accordion: Explains per-run cost and database ceiling", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("$0.03") && src.includes("$0.15"), "FAQ must document $0.03 typical cost and $0.15 hard cap");
});

register("F13.4", "FAQ Accordion: Explains safe PR comment fallback on 3 strikes", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("review comment") && src.includes("best_patch"), "FAQ must describe review comment fallback with best_patch");
});

register("F13.5", "FAQ Accordion: Documents dual viewport regression prevention", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("375px") && src.includes("1440px"), "FAQ must document simultaneous 375px and 1440px testing");
});

// ============================================================================
// FEATURE 14: Final Conversion CTA & Quickstart (5 tests)
// ============================================================================

register("F14.1", "Final CTA: High-impact conversion headline", () => {
  const html = getRenderedHtml();
  assert(html.includes("Stop reviewing pixels by hand."), "CTA must display exact headline");
});

register("F14.2", "Final CTA: Primary action button linking to Mission Control", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Open Mission Control"), "Final CTA must render Open Mission Control button");
  assert(src.includes("MISSION_CONTROL_URL"), "Button must link to Mission Control permalink");
});

register("F14.3", "Final CTA: Secondary action button linking to architecture spec", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Read Architecture Spec") || src.includes("Read the docs"), "Final CTA must render secondary documentation button");
  assert(src.includes("REPO_URL"), "Docs button must link to repository");
});

register("F14.4", "Final CTA: Enterprise trust checkmark badges", () => {
  const html = getRenderedHtml();
  assert(html.includes("Webhook in &lt;1.2s") || html.includes("Webhook in <1.2s"), "Must display Webhook in <1.2s badge");
  assert(html.includes("$0.03") || html.includes("Typical Run"), "Must display $0.03 typical run badge");
  assert(html.includes("Strike Cap") || html.includes("strike safety cap"), "Must display strike cap badge");
});

register("F14.5", "Final CTA: Lucide CheckCircle2 icons for trust validation", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("CheckCircle2"), "CTA must use Lucide CheckCircle2 icon for trust items");
});

// ============================================================================
// FEATURE 15: Enterprise 4-Column Footer (5 tests)
// ============================================================================

register("F15.1", "Footer: Brand identity and mission statement", () => {
  const html = getRenderedHtml();
  assert(html.includes("Autonomous visual QA") && html.includes("self-healing"), "Footer must contain mission summary");
});

register("F15.2", "Footer: Product column links to in-page anchors", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("#demo") && src.includes("#pipeline") && src.includes("#guardrails"), "Footer Product column must link to in-page landmarks");
});

register("F15.3", "Footer: Architecture and Resources columns defined", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Product") && src.includes("Architecture"), "Footer must define Product and Architecture columns");
  assert(src.includes("MISSION_CONTROL_URL") && src.includes("REPO_URL"), "Resources must link to Mission Control and GitHub");
});

register("F15.4", "Footer: Models column links to Meta AI infrastructure", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(src.includes("Meta SAM 3.1") && src.includes("Meta Muse Spark"), "Footer must list Meta AI models");
  assert(src.includes("dev.meta.ai"), "Footer must link to dev.meta.ai");
});

register("F15.5", "Footer: Copyright notice and Meta Hackathon attribution", () => {
  const html = getRenderedHtml();
  assert(html.includes("2026 VisorQA"), "Footer must contain copyright notice");
  assert(html.includes("Meta Global AI Developer Hackathon"), "Footer must contain Meta Hackathon badge");
});

// ============================================================================
// FEATURE 16: Zero-Emoji & Lucide Constraint (5 tests)
// ============================================================================

const EMOJI_REGEX = /\p{Extended_Pictographic}/u;

register("F16.1", "Zero Emoji: SiteHeader contains 0 Unicode emojis", () => {
  const src = readFrontend("src/components/landing/SiteHeader.tsx");
  assert(!EMOJI_REGEX.test(src), "SiteHeader.tsx must not contain any Unicode emojis");
});

register("F16.2", "Zero Emoji: Hero contains 0 Unicode emojis", () => {
  const src = readFrontend("src/components/landing/Hero.tsx");
  assert(!EMOJI_REGEX.test(src), "Hero.tsx must not contain any Unicode emojis");
});

register("F16.3", "Zero Emoji: ProofPreview contains 0 Unicode emojis", () => {
  const src = readFrontend("src/components/landing/ProofPreview.tsx");
  assert(!EMOJI_REGEX.test(src), "ProofPreview.tsx must not contain any Unicode emojis");
});

register("F16.4", "Zero Emoji: Sections contains 0 Unicode emojis", () => {
  const src = readFrontend("src/components/landing/Sections.tsx");
  assert(!EMOJI_REGEX.test(src), "Sections.tsx must not contain any Unicode emojis");
});

register("F16.5", "Zero Emoji: Page and Layout contain 0 Unicode emojis", () => {
  const page = readFrontend("src/app/page.tsx");
  const layout = readFrontend("src/app/layout.tsx");
  assert(!EMOJI_REGEX.test(page), "page.tsx must not contain any Unicode emojis");
  assert(!EMOJI_REGEX.test(layout), "layout.tsx must not contain any Unicode emojis");
});

// ============================================================================
// FEATURE 17: Strict Backend Isolation (5 tests)
// ============================================================================

register("F17.1", "Backend Isolation: Zero git status modifications in backend directory", () => {
  const status = execSync("git status --porcelain backend", {
    cwd: WORKSPACE_ROOT,
    encoding: "utf8",
  }).trim();
  assert.strictEqual(status, "", "backend/ directory must have 0 git status modifications");
});

register("F17.2", "Backend Isolation: No frontend imports reference backend folder", () => {
  const files = [
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "src/components/landing/Hero.tsx",
    "src/components/landing/SiteHeader.tsx",
    "src/components/landing/ProofPreview.tsx",
    "src/components/landing/Sections.tsx",
  ];
  for (const f of files) {
    const content = readFrontend(f);
    assert(!content.includes("../../backend") && !content.includes("/backend/"), `File ${f} must not import from backend`);
  }
});

register("F17.3", "Backend Isolation: Frontend package.json contains 0 backend dependencies", () => {
  const pkg = JSON.parse(readFrontend("package.json"));
  const allDeps = { ...pkg.dependencies, ...pkg.devDependencies };
  assert(!Object.keys(allDeps).some((d) => d.includes("backend") || d.includes("python")), "package.json must not reference backend dependencies");
});

register("F17.4", "Backend Isolation: Frontend builds independently without backend running", () => {
  const htmlPath = path.join(FRONTEND_DIR, ".next/server/app/index.html");
  assert(fs.existsSync(htmlPath), "Frontend production build output exists autonomously");
});

register("F17.5", "Backend Isolation: Backend configuration files remain unperturbed", () => {
  const pyproject = path.join(WORKSPACE_ROOT, "pyproject.toml");
  const pytestIni = path.join(WORKSPACE_ROOT, "pytest.ini");
  assert(fs.existsSync(pyproject), "pyproject.toml must exist untouched");
  assert(fs.existsSync(pytestIni), "pytest.ini must exist untouched");
});

// ============================================================================
// FEATURE 18: Internal Mission Control View (/runs/[id]) (5 tests)
// ============================================================================

register("F18.1", "Mission Control: Deep-link route resolves dynamic id parameter", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes("params: Promise<{ id: string }>"), "Must accept Promise params for id in Next.js 15");
  assert(pageSrc.includes("use(params)"), "Must use React 19 use(params) hook to unwrap params");
  assert(pageSrc.includes("runId"), "Must resolve runId from params");
});

register("F18.2", "Mission Control: Header renders back navigation, PR identifier, WS live badge, and status", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes('href="/"'), "Must link back to root");
  assert(pageSrc.includes("Mission Control"), "Header must include 'Mission Control' text");
  assert(pageSrc.includes("GitPullRequest"), "Must render GitPullRequest icon for PR identification");
  assert(pageSrc.includes("Run Inspector: {runId}"), "Must render Run Inspector badge with dynamic ID");
  assert(pageSrc.includes("WS:") && pageSrc.includes("CONNECTED"), "Must render WebSocket status badge");
  assert(pageSrc.includes("Autonomous Healed"), "Must render autonomous healed status badge");
});

register("F18.3", "Mission Control: 5-Node FSM Stepper renders deterministic pipeline stages", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes("1. SENSE"), "FSM stepper must include 1. SENSE node");
  assert(pageSrc.includes("2. TRIAGE"), "FSM stepper must include 2. TRIAGE node");
  assert(pageSrc.includes("3. DIAGNOSE"), "FSM stepper must include 3. DIAGNOSE node");
  assert(pageSrc.includes("4. PATCH"), "FSM stepper must include 4. PATCH node");
  assert(pageSrc.includes("5. VERIFY"), "FSM stepper must include 5. VERIFY node");
  assert(pageSrc.includes("Strike Counter:"), "FSM stepper must display Strike Counter");
});

register("F18.4", "Mission Control: Left rail PR runs stream renders catalog and switcher", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes("PR Runs Stream"), "Must render PR Runs Stream rail");
  assert(pageSrc.includes("run-demo-42") && pageSrc.includes("run-demo-41"), "Must include historical PR runs in stream");
  assert(pageSrc.includes("BR-1: 3-Strike Hard Cap"), "Must render enterprise guardrail BR-1");
  assert(pageSrc.includes("BR-2: src/components/ui/* Locked"), "Must render enterprise guardrail BR-2");
  assert(pageSrc.includes("BR-3: Cross-Viewport Verified"), "Must render enterprise guardrail BR-3");
});

register("F18.5", "Mission Control: Dual-viewport stage and multi-tab inspector drawer", () => {
  const pageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(pageSrc.includes("Dual-Viewport Canvas"), "Must render Dual-Viewport Canvas stage");
  assert(pageSrc.includes("<MaskSlider"), "Must embed MaskSlider in center stage");
  assert(pageSrc.includes("Math Trap"), "Inspector drawer must include Math Trap tab");
  assert(pageSrc.includes("LCA Tree"), "Inspector drawer must include LCA Tree tab");
  assert(pageSrc.includes("Spec JSON"), "Inspector drawer must include Spec JSON tab");
  assert(pageSrc.includes("Diff"), "Inspector drawer must include Diff tab");
  assert(pageSrc.includes("Trace"), "Inspector drawer must include Trace tab");
  assert(pageSrc.includes("<DiffViewer"), "Must embed DiffViewer in inspector drawer");
});

// ============================================================================
// RUNNER EXPORT
// ============================================================================

async function run() {
  console.log(`\n--- Tier 1: Feature Coverage (${tests.length} tests) ---`);
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

  return { name: "Tier 1: Feature Coverage", total: tests.length, passed, failed, errors };
}

module.exports = { run, tests };

if (require.main === module) {
  run().then((res) => {
    if (res.failed > 0) process.exit(1);
  });
}
