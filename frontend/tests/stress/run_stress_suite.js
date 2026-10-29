/**
 * VisorQA Challenger 1 - Master Adversarial Stress Suite Runner
 */

const { execSync } = require("node:child_process");
const path = require("node:path");

const STRESS_DIR = __dirname;
const tests = [
  "unicode_emoji_deep_scan.js",
  "slider_boundary_stress.js",
  "dual_viewport_stress.js",
];

console.log("======================================================================");
console.log("       VISORQA CHALLENGER 1 — MASTER ADVERSARIAL STRESS SUITE          ");
console.log("======================================================================\n");

let allPassed = true;

for (const t of tests) {
  const scriptPath = path.join(STRESS_DIR, t);
  console.log(`>>> Executing Adversarial Stress Harness: ${t} ...`);
  try {
    const output = execSync(`node ${scriptPath}`, { stdio: "inherit" });
    console.log(`>>> Harness ${t} completed successfully.\n`);
  } catch (err) {
    allPassed = false;
    console.error(`>>> Harness ${t} FAILED with exit code ${err.status}\n`);
  }
}

if (!allPassed) {
  console.error("❌ Master Adversarial Stress Suite: ONE OR MORE HARNESSES FAILED.");
  process.exit(1);
} else {
  console.log("======================================================================");
  console.log("✓ ALL ADVERSARIAL STRESS HARNESSES PASSED EMPIRICALLY (EXIT CODE 0)");
  console.log("======================================================================");
  process.exit(0);
}
