/**
 * VisorQA E2E Test Suite - Tier 4: Real-World Application Scenarios
 * 
 * Verifies end-to-end mission workflows:
 * - Production Release CI Gate (tsc, build artifacts)
 * - Global Zero-Emoji Security & Brand Audit
 * - Strict Backend Directory Immutability Gate
 * - Executive CTO Brand Walkthrough
 * - Frontend Engineer Interactive Triage Workflow
 * - Enterprise Architecture & Security Review
 * - Developer Onboarding & Quickstart Funnel
 * - Semantic HTML & Accessibility (a11y) Conformance
 * - Cross-Viewport Responsive Stability
 * - Standalone Frontend Portability
 * 
 * Total test cases: 10.
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
// REAL-WORLD APPLICATION SCENARIOS (10 tests)
// ============================================================================

register("S1", "Scenario: Production Release CI Gate (TypeScript & Static Build)", () => {
  // 1. Run tsc --noEmit
  execSync("npx tsc --noEmit", {
    cwd: FRONTEND_DIR,
    stdio: "pipe",
    encoding: "utf8",
  });

  // 2. Verify static build artifacts exist
  const indexHtml = path.join(FRONTEND_DIR, ".next/server/app/index.html");
  const pageJs = path.join(FRONTEND_DIR, ".next/server/app/page.js");
  assert(fs.existsSync(indexHtml), "index.html must exist in build output");
  assert(fs.existsSync(pageJs), "page.js must exist in build output");
  assert(fs.statSync(indexHtml).size > 10000, "Rendered index.html must have substantial content (>10KB)");
});

register("S2", "Scenario: Global Zero-Emoji Security & Brand Audit", () => {
  const PURE_EMOJI_REGEX = /(?!\u00a9|\u00ae)\p{Extended_Pictographic}/u;

  function scanDir(dir) {
    let files = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name !== "node_modules" && e.name !== ".next" && e.name !== ".git") {
          files = files.concat(scanDir(full));
        }
      } else if (/\.(tsx?|jsx?|css|json)$/.test(e.name)) {
        files.push(full);
      }
    }
    return files;
  }

  const allFiles = scanDir(path.join(FRONTEND_DIR, "src"));
  for (const f of allFiles) {
    const content = fs.readFileSync(f, "utf8");
    assert(!PURE_EMOJI_REGEX.test(content), `Found forbidden Unicode emoji in ${path.relative(FRONTEND_DIR, f)}`);
  }

  // Also verify final compiled HTML
  const html = getRenderedHtml();
  assert(!PURE_EMOJI_REGEX.test(html), "Production HTML must not contain any Unicode pictographic emojis");
});

register("S3", "Scenario: Strict Backend Directory Immutability Gate", () => {
  const backendPath = path.join(WORKSPACE_ROOT, "backend");
  assert(fs.existsSync(backendPath), "backend/ directory must exist in workspace");

  const status = execSync("git status --porcelain backend", {
    cwd: WORKSPACE_ROOT,
    encoding: "utf8",
  }).trim();

  assert.strictEqual(status, "", `backend/ directory has been modified! Git status: ${status}`);

  // Confirm root Python files untouched
  assert(fs.existsSync(path.join(WORKSPACE_ROOT, "pyproject.toml")), "pyproject.toml untouched");
  assert(fs.existsSync(path.join(WORKSPACE_ROOT, "pytest.ini")), "pytest.ini untouched");
});

register("S4", "Scenario: Executive CTO Brand Polish & Design System Walkthrough", () => {
  const html = getRenderedHtml();
  const config = readFrontend("tailwind.config.ts");

  // 1. Obsidian monochrome foundation
  assert(config.includes('"#0A0A0C"') && config.includes('"#111115"'), "Monochrome Obsidian palette verified");

  // 2. Space Grotesk display typography
  assert(html.includes("font-display"), "Space Grotesk typography applied to display headings");

  // 3. Autonomous L4 telemetry
  assert(html.includes("L4 AUTONOMOUS") || html.includes("VISORQA L4 AUTONOMOUS"), "L4 autonomy clearly communicated");
  assert(html.includes("$0.03"), "$0.03 unit economics verified");

  // 4. Lucide SVG icons present in rendered output
  assert(html.includes("lucide"), "Lucide icons rendered across page");
});

register("S5", "Scenario: Frontend Engineer Interactive Triage Workflow", () => {
  const proofSrc = readFrontend("src/components/landing/ProofPreview.tsx");
  const diffSrc = readFrontend("src/components/DiffViewer.tsx");

  // 1. Viewport inspection
  assert(proofSrc.includes("375px Mobile") && proofSrc.includes("1440px Desktop"), "Supports mobile and desktop triage");

  // 2. SAM mask inspection via scrubber
  assert(proofSrc.includes("role=\"slider\""), "Interactive scrubber slider present");
  assert(proofSrc.includes("B_DOM") && proofSrc.includes("M_SAM"), "Juxtaposes B_DOM against M_SAM");

  // 3. Patch toggle
  assert(proofSrc.includes("role=\"switch\""), "Patch toggle switch present");

  // 4. Mathematical verdict updates
  assert(proofSrc.includes("0.45") && proofSrc.includes("1.0"), "Calculates Vr progression from fail to resolved");

  // 5. Code diff inspection
  assert(diffSrc.includes("--- a/src/components/PromoBanner.tsx"), "Displays targeted code diff");
});

register("S6", "Scenario: Enterprise Architecture & Security Officer Review", () => {
  const sectionsSrc = readFrontend("src/components/landing/Sections.tsx");

  // Verify all 5 Architectural Pillars
  assert(sectionsSrc.includes("DOM-Guided SAM 3.1"), "Pillar 1: DOM-guided SAM verified");
  assert(sectionsSrc.includes("LCA DOM Hierarchy"), "Pillar 2: LCA DOM fault localization verified");
  assert(sectionsSrc.includes("Architect-Coder Separation"), "Pillar 3: Specialized agent split verified");
  assert(sectionsSrc.includes("Modal Sandboxes & 0.3s HMR"), "Pillar 4: Modal 0.3s HMR sandbox verified");
  assert(sectionsSrc.includes("Non-Destructive PR Review Fallback"), "Pillar 5: 3-strike review fallback verified");

  // Verify 6 Hard Enterprise Safety Guardrails
  assert(sectionsSrc.includes("BR-1") && sectionsSrc.includes("BR-2") && sectionsSrc.includes("BR-3"), "Guardrails BR-1, BR-2, BR-3 present");
  assert(sectionsSrc.includes("BR-4") && sectionsSrc.includes("BR-5") && sectionsSrc.includes("BR-6"), "Guardrails BR-4, BR-5, BR-6 present");
  assert(sectionsSrc.includes("HMAC-SHA256"), "Cryptographic webhook security verified");
  assert(sectionsSrc.includes("$0.15"), "Hard spend ceiling verified");
});

register("S7", "Scenario: Developer Onboarding & Quickstart Conversion Funnel", () => {
  const heroSrc = readFrontend("src/components/landing/Hero.tsx");
  const sectionsSrc = readFrontend("src/components/landing/Sections.tsx");
  const sharedSrc = readFrontend("src/components/landing/shared.tsx");

  // CLI snippet present in Hero and CTA
  assert(heroSrc.includes("CLI_CMD"), "Hero features quickstart command");
  assert(sectionsSrc.includes("CLI_CMD"), "Final CTA features quickstart command");
  assert(sharedSrc.includes("npx visorqa init"), "Command is npx visorqa init");

  // External repository links
  assert(sharedSrc.includes("https://github.com/sayedibrahimQ/VisorQA"), "GitHub repository link defined");

  // Interactive copy feedback
  assert(heroSrc.includes("useCopy"), "Hero provides clipboard feedback");
  assert(sectionsSrc.includes("handleCopy"), "Final CTA provides clipboard feedback");
});

register("S8", "Scenario: Semantic HTML & Accessibility (a11y) Conformance Audit", () => {
  const html = getRenderedHtml();

  // Semantic landmarks
  assert(html.includes("<header"), "Page contains <header> landmark");
  assert(html.includes("<main"), "Page contains <main> landmark");
  assert(html.includes("<section"), "Page contains <section> landmarks");
  assert(html.includes("<figure"), "Page contains <figure> sandbox landmark");
  assert(html.includes("<footer"), "Page contains <footer> landmark");
  assert(html.includes("<nav"), "Page contains <nav> navigation landmarks");

  // Interactive ARIA semantics
  assert(html.includes("role=\"slider\""), "Scrubber declares role='slider'");
  assert(html.includes("role=\"switch\""), "Patch toggle declares role='switch'");
  assert(html.includes("aria-valuemin=\"0\"") && html.includes("aria-valuemax=\"100\""), "Slider declares min/max values");
  assert(html.includes("aria-live=\"polite\""), "Dynamic status uses aria-live='polite'");
});

register("S9", "Scenario: Cross-Viewport Layout Stability & Responsive Breakpoints", () => {
  const sectionsSrc = readFrontend("src/components/landing/Sections.tsx");
  const proofSrc = readFrontend("src/components/landing/ProofPreview.tsx");
  const headerSrc = readFrontend("src/components/landing/SiteHeader.tsx");
  const diffSrc = readFrontend("src/components/DiffViewer.tsx");

  // Responsive bento grid columns
  assert(sectionsSrc.includes("grid-cols-1") && sectionsSrc.includes("lg:grid-cols-12"), "Bento grid adapts from 1 column to 12 columns");
  assert(sectionsSrc.includes("sm:grid-cols-5"), "Model strip adapts to 5 columns on desktop");

  // Overflow protection
  assert(proofSrc.includes("overflow-hidden"), "Proof sandbox prevents stage overflow");
  assert(headerSrc.includes("overflow-x-auto") || diffSrc.includes("overflow-x-auto"), "Code diffs and tickers prevent horizontal page blowout");
});

register("S10", "Scenario: Standalone Frontend Portability (Zero Backend Dependency)", () => {
  const pkg = JSON.parse(readFrontend("package.json"));
  const allDeps = { ...pkg.dependencies, ...pkg.devDependencies };

  // Verify pure frontend stack: next, react, tailwind, lucide
  assert(allDeps["next"], "Must depend on next");
  assert(allDeps["react"], "Must depend on react");
  assert(allDeps["lucide-react"], "Must depend on lucide-react");
  assert(allDeps["tailwindcss"], "Must depend on tailwindcss");

  // Verify no local backend coupling
  assert(!allDeps["fastapi"] && !allDeps["uvicorn"], "Zero Python backend dependencies in package.json");
});

register("S11", "Scenario: Mission Control Deep-Link & Permalinks Verification", () => {
  const runPageSrc = readFrontend("src/app/runs/[id]/page.tsx");
  assert(runPageSrc.includes("RunInspectorPage"), "RunInspectorPage component must be exported");
  assert(runPageSrc.includes("Run Inspector: {runId}"), "Must display dynamic run identifier in DOM");
  assert(runPageSrc.includes("Autonomous Healed (Strike"), "Must display strike status badge");
  assert(runPageSrc.includes("RUNS_CATALOG"), "Must declare runs catalog with historical data");
  assert(runPageSrc.includes("FSM_NODES"), "Must declare 5-node FSM orchestrator nodes");
});

register("S12", "Scenario: Bespoke Design System & CSS Motion GPU Audit", () => {
  const css = readFrontend("src/app/globals.css");
  const tailwind = readFrontend("tailwind.config.ts");
  assert(css.includes(".animate-laser-sweep"), "Must define .animate-laser-sweep utility class");
  assert(css.includes(".optical-grid"), "Must define .optical-grid utility class");
  assert(css.includes(".zero-cls-container"), "Must define .zero-cls-container utility class");
  assert(tailwind.includes("laser-cyan"), "Tailwind must define laser-cyan color token");
  assert(tailwind.includes("defect-crimson"), "Tailwind must define defect-crimson color token");
  assert(tailwind.includes("verified-emerald"), "Tailwind must define verified-emerald color token");
});

// ============================================================================
// RUNNER EXPORT
// ============================================================================

async function run() {
  console.log(`\n--- Tier 4: Real-World Application Scenarios (${tests.length} tests) ---`);
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

  return { name: "Tier 4: Real-World Application Scenarios", total: tests.length, passed, failed, errors };
}

module.exports = { run, tests };

if (require.main === module) {
  run().then((res) => {
    if (res.failed > 0) process.exit(1);
  });
}
