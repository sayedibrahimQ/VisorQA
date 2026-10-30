#!/usr/bin/env node
/**
 * Master E2E Test Suite Runner for VisorQA
 * 
 * Executes all 4 tiers of tests:
 * - Tier 1: Feature Coverage (90 tests across 18 features)
 * - Tier 2: Boundary & Corner Cases (90 tests across 18 features)
 * - Tier 3: Cross-Feature Combinations (20 tests)
 * - Tier 4: Real-World Application Scenarios (12 tests)
 * 
 * Total: 212 test assertions.
 * 
 * Exit Codes:
 * - 0: All tests passed (100% pass rate)
 * - 1: Any test assertion failed
 */

const path = require("node:path");

const ANSI = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  cyan: "\x1b[36m",
  yellow: "\x1b[33m",
  magenta: "\x1b[35m",
};

async function main() {
  const startTime = Date.now();

  console.log(`\n${ANSI.bold}${ANSI.cyan}======================================================================${ANSI.reset}`);
  console.log(`${ANSI.bold}${ANSI.cyan}             VISORQA E2E AUTOMATED TEST SUITE RUNNER                 ${ANSI.reset}`);
  console.log(`${ANSI.dim}        Opaque-Box · Category-Partition · BVA · Workload Testing       ${ANSI.reset}`);
  console.log(`${ANSI.bold}${ANSI.cyan}======================================================================${ANSI.reset}`);

  const tierFiles = [
    { tier: 1, file: "./tier1_features.test.js", expected: 90 },
    { tier: 2, file: "./tier2_boundaries.test.js", expected: 90 },
    { tier: 3, file: "./tier3_combinations.test.js", expected: 20 },
    { tier: 4, file: "./tier4_application.test.js", expected: 12 },
  ];

  const results = [];
  let totalTests = 0;
  let totalPassed = 0;
  let totalFailed = 0;
  const allErrors = [];

  for (const item of tierFiles) {
    const suitePath = path.resolve(__dirname, item.file);
    const suite = require(suitePath);

    const suiteStartTime = Date.now();
    const suiteResult = await suite.run();
    const suiteDuration = ((Date.now() - suiteStartTime) / 1000).toFixed(2);

    totalTests += suiteResult.total;
    totalPassed += suiteResult.passed;
    totalFailed += suiteResult.failed;
    if (suiteResult.errors && suiteResult.errors.length > 0) {
      allErrors.push(...suiteResult.errors.map(e => ({ ...e, tier: item.tier })));
    }

    results.push({
      tier: item.tier,
      name: suiteResult.name,
      total: suiteResult.total,
      passed: suiteResult.passed,
      failed: suiteResult.failed,
      duration: suiteDuration,
    });
  }

  const totalDuration = ((Date.now() - startTime) / 1000).toFixed(2);

  console.log(`\n${ANSI.bold}${ANSI.cyan}======================================================================${ANSI.reset}`);
  console.log(`${ANSI.bold}                      TEST EXECUTION SUMMARY                          ${ANSI.reset}`);
  console.log(`${ANSI.bold}${ANSI.cyan}======================================================================${ANSI.reset}`);

  for (const res of results) {
    const statusColor = res.failed === 0 ? ANSI.green : ANSI.red;
    const statusIcon = res.failed === 0 ? "✓" : "✗";
    const pct = ((res.passed / res.total) * 100).toFixed(1);
    console.log(
      `  ${statusColor}${statusIcon}${ANSI.reset} ${ANSI.bold}Tier ${res.tier}${ANSI.reset} (${res.name.padEnd(38, " ")}): ` +
      `${statusColor}${res.passed} / ${res.total} passed (${pct}%)${ANSI.reset} ${ANSI.dim}[${res.duration}s]${ANSI.reset}`
    );
  }

  console.log(`${ANSI.dim}----------------------------------------------------------------------${ANSI.reset}`);
  const overallColor = totalFailed === 0 ? ANSI.green : ANSI.red;
  const overallIcon = totalFailed === 0 ? "✓ ALL TESTS PASSED" : "✗ TESTS FAILED";
  const overallPct = ((totalPassed / totalTests) * 100).toFixed(1);

  console.log(
    `  ${ANSI.bold}TOTAL ASSERTIONS:${ANSI.reset}    ${overallColor}${totalPassed} / ${totalTests} (${overallPct}%)${ANSI.reset}`
  );
  console.log(`  ${ANSI.bold}EXECUTION TIME:${ANSI.reset}      ${ANSI.cyan}${totalDuration}s${ANSI.reset}`);
  console.log(`  ${ANSI.bold}SUITE STATUS:${ANSI.reset}        ${overallColor}${overallIcon} (EXIT CODE ${totalFailed === 0 ? 0 : 1})${ANSI.reset}`);
  console.log(`${ANSI.bold}${ANSI.cyan}======================================================================${ANSI.reset}\n`);

  if (totalFailed > 0) {
    console.error(`${ANSI.red}${ANSI.bold}FAILURES SUMMARY (${allErrors.length} failed tests):${ANSI.reset}`);
    for (const err of allErrors) {
      console.error(`  - [Tier ${err.tier} - ${err.id}] ${err.name}`);
      console.error(`    ${ANSI.dim}${err.error}${ANSI.reset}`);
    }
    console.log("");
    process.exit(1);
  } else {
    process.exit(0);
  }
}

main().catch((err) => {
  console.error("Fatal error running test suite:", err);
  process.exit(1);
});
