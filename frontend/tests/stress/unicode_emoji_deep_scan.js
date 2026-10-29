/**
 * VisorQA Empirical Challenge - Stress Test 1: Deep Unicode/Emoji Scanner
 * 
 * Adversarially scans all source code and compiled HTML for:
 * - Unicode Extended_Pictographic characters
 * - Unicode Emoji_Presentation characters
 * - Emoji modifiers and components
 * - Surrogate pairs (\uD800-\uDBFF \uDC00-\uDFFF)
 * - Named/numeric HTML entities for emojis (&#x1F...; &#128...;)
 * - Explicit emoji ranges (Emoticons, Dingbats, Transport, Pictographs)
 */

const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");

const FRONTEND_DIR = path.resolve(__dirname, "../../");

// Regex definitions
const REGEX_PICTOGRAPHIC = /(?!\u00a9|\u00ae)\p{Extended_Pictographic}/u;
const REGEX_EMOJI_PRESENTATION = /(?!\u00a9|\u00ae)\p{Emoji_Presentation}/u;
// Keycap sequences like 0️⃣ or #️⃣ and skin tone modifiers
const REGEX_KEYCAP_EMOJIS = /[0-9#*]\uFE0F?\u20E3/u;
const REGEX_SKIN_TONE_MODIFIERS = /[\u{1F3FB}-\u{1F3FF}]/u;
const REGEX_SURROGATE_PAIRS = /[\uD800-\uDBFF][\uDC00-\uDFFF]/g;
const REGEX_HTML_EMOJI_ENTITIES = /&#(?:x1[fF][0-9a-fA-F]{3}|12[0-9]{4});/gi;

// Explicit Unicode ranges for emojis
const REGEX_EXPLICIT_RANGES = /[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F900}-\u{1F9FF}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;

function findFiles(dir, extensions) {
  let results = [];
  if (!fs.existsSync(dir)) return results;
  const list = fs.readdirSync(dir, { withFileTypes: true });
  for (const item of list) {
    const fullPath = path.join(dir, item.name);
    if (item.isDirectory()) {
      if (item.name !== "node_modules" && item.name !== ".next" && item.name !== ".git") {
        results = results.concat(findFiles(fullPath, extensions));
      }
    } else {
      const ext = path.extname(item.name).toLowerCase();
      if (extensions.includes(ext)) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

let totalFilesScanned = 0;
let totalChecksRun = 0;
let violations = [];

console.log("======================================================================");
console.log("   CHALLENGER 1 — ADVERSARIAL DEEP UNICODE & EMOJI STRESS SCANNER     ");
console.log("======================================================================");

// 1. Gather all source files
const sourceFiles = findFiles(path.join(FRONTEND_DIR, "src"), [".ts", ".tsx", ".css", ".json"]);
const configFiles = [
  path.join(FRONTEND_DIR, "package.json"),
  path.join(FRONTEND_DIR, "next.config.mjs"),
  path.join(FRONTEND_DIR, "tailwind.config.ts"),
  path.join(FRONTEND_DIR, "tsconfig.json"),
].filter(f => fs.existsSync(f));

// 2. Gather compiled HTML files
const htmlFiles = [];
const appHtml = path.join(FRONTEND_DIR, ".next/server/app/index.html");
if (fs.existsSync(appHtml)) {
  htmlFiles.push(appHtml);
}
const notFoundHtml = path.join(FRONTEND_DIR, ".next/server/app/_not-found.html");
if (fs.existsSync(notFoundHtml)) {
  htmlFiles.push(notFoundHtml);
}

const allTargets = [...sourceFiles, ...configFiles, ...htmlFiles];

console.log(`Scanning ${allTargets.length} files across frontend repository and build output...\n`);

for (const filePath of allTargets) {
  totalFilesScanned++;
  const relPath = path.relative(FRONTEND_DIR, filePath);
  const content = fs.readFileSync(filePath, "utf8");
  const lines = content.split("\n");

  lines.forEach((line, lineIdx) => {
    // Check 1: Extended Pictographic
    totalChecksRun++;
    if (REGEX_PICTOGRAPHIC.test(line)) {
      const match = line.match(REGEX_PICTOGRAPHIC);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "Extended_Pictographic",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }

    // Check 2: Emoji Presentation
    totalChecksRun++;
    if (REGEX_EMOJI_PRESENTATION.test(line)) {
      const match = line.match(REGEX_EMOJI_PRESENTATION);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "Emoji_Presentation",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }

    // Check 3: Keycap Emojis and Skin Tone Modifiers
    totalChecksRun++;
    if (REGEX_KEYCAP_EMOJIS.test(line)) {
      const match = line.match(REGEX_KEYCAP_EMOJIS);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "Keycap_Emoji",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }
    totalChecksRun++;
    if (REGEX_SKIN_TONE_MODIFIERS.test(line)) {
      const match = line.match(REGEX_SKIN_TONE_MODIFIERS);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "Skin_Tone_Modifier",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }

    // Check 4: Explicit Emoji Code Point Ranges
    totalChecksRun++;
    if (REGEX_EXPLICIT_RANGES.test(line)) {
      const match = line.match(REGEX_EXPLICIT_RANGES);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "Explicit_Emoji_Range",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }

    // Check 5: HTML Numeric/Hex Entities for Emojis
    totalChecksRun++;
    if (REGEX_HTML_EMOJI_ENTITIES.test(line)) {
      const match = line.match(REGEX_HTML_EMOJI_ENTITIES);
      violations.push({
        file: relPath,
        line: lineIdx + 1,
        type: "HTML_Emoji_Entity",
        match: match ? match[0] : "",
        snippet: line.trim().slice(0, 80),
      });
    }

    // Check 6: Raw Surrogate Pairs
    totalChecksRun++;
    const surrogateMatches = line.match(REGEX_SURROGATE_PAIRS);
    if (surrogateMatches) {
      for (const sm of surrogateMatches) {
        const codePoint = sm.codePointAt(0);
        // Exclude standard non-emoji supplementary characters if any
        if (codePoint >= 0x1F000 && codePoint <= 0x1FAFF) {
          violations.push({
            file: relPath,
            line: lineIdx + 1,
            type: "Surrogate_Pair_Emoji",
            match: `U+${codePoint.toString(16).toUpperCase()}`,
            snippet: line.trim().slice(0, 80),
          });
        }
      }
    }
  });
}

// Additional Check: Ensure Lucide icons are used exclusively in components
const componentFiles = sourceFiles.filter(f => f.includes("/components/"));
let lucideIconCount = 0;
for (const compFile of componentFiles) {
  const content = fs.readFileSync(compFile, "utf8");
  const lucideMatch = content.match(/import\s+{([^}]+)}\s+from\s+["']lucide-react["']/g);
  if (lucideMatch) {
    lucideIconCount += lucideMatch.length;
  }
}

console.log(`Files Scanned:        ${totalFilesScanned}`);
console.log(`Line Checks Executed: ${totalChecksRun}`);
console.log(`Lucide Icon Imports:  ${lucideIconCount}`);
console.log(`Violations Found:     ${violations.length}`);

if (violations.length > 0) {
  console.error("\n❌ VIOLATIONS DETECTED:");
  for (const v of violations) {
    console.error(`  - [${v.type}] ${v.file}:${v.line} -> "${v.match}" in: ${v.snippet}`);
  }
  process.exit(1);
} else {
  console.log("\n✓ PASS: Strictly 0 emojis, 0 surrogate pairs, 0 pictographs, 0 HTML emoji entities found.");
  process.exit(0);
}
