# `DESIGN.md` — UI/UX Design Specification

**Project:** VisorQA — Autonomous Visual QA & Self-Healing Frontend Agent

**Design Philosophy:** High-Craft Monochrome Productivity with AI Harmony (Linear / Vercel precision)

**Frontend Stack:** Next.js 14+ (App Router), Tailwind CSS, Lucide Icons, Native WebSockets

---

## 1. Design Philosophy & Aesthetic Direction

* **Monochrome Structural Foundation:** 90% of the viewport uses high-contrast Obsidian Black (`#0A0A0C`) and Pure Alabaster White (`#FAFAFA`) with subtle `1px` borders (`#1E1E24`). This eliminates visual noise and keeps engineering focus on pixel masks, mathematical telemetry, and code diffs.


* **Contextual AI Harmony:** Color is strictly semantic and event-driven. Luminous gradients appear *only* when Meta AI models (**SAM 3.1**, **Muse Spark**, **Muse Wonder**, **Muse Code**) are actively computing or highlighting visual defects.


* **Zero Manual Clutter:** Strictly autonomous L4 telemetry. There are no manual URL inputs or "Trigger Scan" buttons; the UI reacts automatically in `< 1.2s` to GitHub Webhook events via WebSockets.



---

## 2. Color System, Typography & Spacing

### 2.1 Color Palette (Tailwind CSS Tokens)

| Token Category | Token Name | Hex / Value | Exact UI Usage |
| --- | --- | --- | --- |
| **Surfaces (Dark Primary)** | `bg-canvas` | `#0A0A0C` | Main application background |
|  | `bg-surface` | `#111115` | Cards, Sidebars, Inspector panels |
|  | `bg-elevated` | `#18181E` | Hover states, active tabs, code block headers |
| **Borders & Dividers** | `border-subtle` | `#22222A` | Standard `1px solid` layout grid dividers |
|  | `border-focus` | `#FAFAFA` | Active node ring / selected anomaly border |
| **Typography & Icons** | `text-primary` | `#FAFAFA` | Primary headings, active states, core metrics |
|  | `text-secondary` | `#A1A1AA` | File paths, PR metadata, secondary labels |
|  | `text-muted` | `#52525B` | Timestamps, inactive FSM nodes, disabled text |
| **AI Harmony Accents** | `ai-harmony-gradient` | `linear-gradient(135deg, #38BDF8 0%, #818CF8 50%, #C084FC 100%)` | Active FSM node border glow & Muse reasoning pulse |
| **SAM 3.1 Vision Overlays** | `mask-dom-box` | `#00F0FF` (`dashed 1.5px`) | Expected DOM Bounding Box ($B_{DOM}$)

 |
|  | `mask-defect-fill` | `rgba(244, 63, 94, 0.35)` + `#F43F5E` border | SAM 3.1 collision/occlusion pixel mask ($M_{SAM}$)

 |
|  | `triage-amber` | `#F59E0B` | LCA DOM hierarchy highlight & Retry Strike 1–2

 |
|  | `verified-emerald` | `#10B981` | Self-healed verification ($V_r \ge 0.98, IoU = 0$)

 |

### 2.2 Typography Scale

| Role | Font Family | Weight | Size / Line-Height | Usage |
| --- | --- | --- | --- | --- |
| **Display / Headers** | `Space Grotesk` | `600` (SemiBold) | `20px / 28px` (`-0.02em`) | Top bar title, PR title, Panel headers |
| **UI Body** | `Inter` (or `Geist Sans`) | `400` / `500` | `13px / 18px` | Descriptions, Muse Wonder repair specs, navigation |
| **Math & Code** | `JetBrains Mono` | `400` / `600` | `12px / 16px` | $V_r, IoU, \Delta_x$ equations, Unified Diffs, `visor-el-id` tags

 |

### 2.3 Spacing & Grid System

* **Viewport Lock:** `100vw x 100vh` (`overflow-hidden`) split-pane workspace on desktop for zero-scroll productivity during live demos.
* **Base Unit:** `4px` grid (`p-3` = `12px`, `p-4` = `16px`, `gap-4` = `16px`).
* **Border Radius:** Crisp technical geometry — `rounded-md` (`6px`) for inner badges/buttons, `rounded-lg` (`8px`) for panels.

---

## 3. Screen List & Navigation Flow

### 3.1 Next.js App Router Structure

1. **`/` (Live Mission Control Workspace):** The primary single-screen command center. Automatically locks onto the latest active GitHub Webhook PR run or allows selecting recent historical runs from the left rail.


2. **`/runs/[runId]` (Deep-Link PR Run Permalink):** Direct shareable link placed inside automated GitHub PR comments so reviewers can inspect the exact SAM 3.1 masks and HMR diffs.



### 3.2 Autonomous Navigation Flow

`GitHub Webhook Event` ➔ `FastAPI WS Broadcast (SENSE_STARTED)` ➔ `Left Rail auto-selects New Run` ➔ `Top FSM Stepper animates Node 1 to 5` ➔ `Center Canvas updates live masks (375px & 1440px)` ➔ `Right Drawer streams LCA Triage, Muse Wonder JSON, and Muse Code HMR Diff`.

---

## 4. Wireframe & Workspace Layout (ASCII Blueprint)

```text
+--------------------------------------------------------------------------------------------------+
| [VisorQA]  PR #42: feat/checkout-banner (branch: fix/ui)     [WS: LIVE ●] [Latency: 8.4s] [$0.03]|
+------------------+------------------------------------------------------------+------------------+
| PR RUNS STREAM   | 1.SENSE(SAM) ──> 2.TRIAGE(Spark) ──> 3.DIAGNOSE ──> 4.PATCH ──> 5.VERIFY(1/3) |
| (Width: 260px)   +------------------------------------------------------------+------------------+
|                  | VIEWPORT: [📱 Mobile 375px (1 Defect)] [🖥 Desktop 1440px (Pass)] [Overlay: ON]|
| ● #42 checkout   | +--------------------------------------------------------+ | TELEMETRY & CODE |
|   ⚡ Healing 1/3 | |                                                        | | (Width: 380px)   |
|   375px | 1440px | |   +------------------------------------------------+   | |                  |
|                  | |   | Sticky Promo Banner (visor-el-04)              |   | | [MATH TELEMETRY] |
| ○ #41 nav-grid   | |   + - - - - - - - - - - - - - - - - - - - - - - - -+   | | V_r : 0.45 (FAIL)|
|   ✔ Healed (9.2s)| |   |████████████████████████████████████████████████|   | | IoU : 0.16 (FAIL)|
|                  | |   |██ SAM 3.1 COLLISION MASK (M_i ∩ M_j = 0.16) ███|   | | Δ_x : 0.0px (OK) |
| ○ #40 modal-clip | |   +------------------------------------------------+   | |                  |
|   ⚠ 3-Strike Cmt | |   | [ Buy Now CTA (visor-el-09) ] (B_DOM Dashed)   |   | | [LCA & SPARK]    |
|                  | |   +------------------------------------------------+   | | CheckoutPage.tsx |
|                  | |                                                        | | (src/ui/ Locked) |
|                  | +--------------------------------------------------------+ |                  |
|                  | [Slider: Before (Defect) <========|========> After (HMR)]  | | [MUSE WONDER/CODE|
|                  |                                                            | | - z-index: 50    |
|                  |                                                            | | + flex-wrap:wrap |
+------------------+------------------------------------------------------------+------------------+

```

---

## 5. Core Reusable UI Components

1. **`<FSMOrchestratorBar/>` (Top Pipeline Stepper):**
* Renders the 5 deterministic nodes: `1. Sense (Playwright/SAM 3.1)` ➔ `2. Triage (Muse Spark)` ➔ `3. Diagnose (Muse Wonder)` ➔ `4. Patch (Muse Code + HMR)` ➔ `5. Verify & Commit`.


* Displays a real-time **3-Strike Loop Badge** (`Attempt 1/3`, `2/3`, `3/3`) and step latency in milliseconds (e.g., `SAM: 420ms`, `Spark: 580ms`, `HMR: 300ms`).




2. **`<DualViewportStage/>` (Center Interactive Canvas):**
* **Viewport Switcher & Split View:** Instant toggle or side-by-side sync between **Mobile (`375px`)** and **Desktop (`1440px`)** to prove zero cross-viewport regression.


* **SVG/Canvas Mask Layer:** Renders interactive `visor-el-id` bounding boxes ($B_{DOM}$ in dashed cyan) and SAM 3.1 pixel masks ($M_{SAM}$ in translucent crimson) over the Playwright screenshot.


* **Before / After Scrubber:** Smooth draggable slider comparing the broken PR render against the Modal HMR self-healed render.




3. **`<MathTrapScorecard/>` (Right Panel — Card 1):**
* Displays the 3 deterministic NumPy formulas per defective element in `JetBrains Mono`:


* **Visibility Ratio ($V_r$):** Progress bar + value (`0.45 < 0.85` ➔ Red Badge; `1.00 >= 0.98` ➔ Emerald Badge).


* **Sibling Collision ($IoU$):** Value badge (`0.16 > 0.05` ➔ Fail; `0.00` ➔ Pass).


* **Viewport Bleed ($\Delta_x$):** Pixel overflow readout (`37px > 2px` ➔ Fail; `0px` ➔ Pass).






4. **`<LCATriageTree/>` (Right Panel — Card 2):**
* Visualizes the Lowest Common Ancestor DOM path extracted by Playwright and triaged by **Muse Spark**.


* Explicitly shows a `[🔒 Protected Shared UI]` badge next to atomic components (`src/components/ui/Button.tsx`) and a `[🎯 Target File]` badge on the parent container (`CheckoutPage.tsx`).




5. **`<ArchitectCoderInspector/>` (Right Panel — Card 3):**
* **Tab 1 (`Muse Wonder Spec`):** Formatted Pydantic JSON viewer showing root-cause diagnosis and layout constraints.


* **Tab 2 (`Muse Code Diff`):** Syntax-highlighted Unified Diff (`-` red / `+` green lines) with HMR reload status (`Applied in 0.3s`).





---

## 6. UI States (Loading, Empty, Success, Error / 3-Strike)

| State | Visual Behavior & Micro-Interactions |
| --- | --- |
| **1. Empty / Idle State (Listening for Webhook)** | Monochrome minimal canvas displaying a subtle pulsing radar dot (`#FAFAFA`) with text: *"Listening for GitHub Pull Request Webhooks..."* and a summary of sprint capacity saved (`28.4%`) and average PR cost (`$0.03`).

 |
| **2. Loading / Active Node Streaming** | Active FSM node border illuminates with `ai-harmony-gradient`. While SAM 3.1 segments the page (`0.45s`), a subtle horizontal laser scanline sweeps once across the viewport screenshot.

 |
| **3. Retry Feedback State (Strike 1 or 2 Failed)** | If verification yields $V_r < 0.98$ or $IoU > 0$, the FSM loops back from `Verify` to `Diagnose` with an Amber (`#F59E0B`) animated arc, incrementing the badge to `Attempt 2/3` and updating the telemetry diff.

 |
| **4. Success State (`RESOLVED`)** | Triggered when $V_r \ge 0.98$, $IoU = 0$, and $\Delta_x \le 2\text{px}$ on both `375px` and `1440px`. All red masks transition to Emerald (`#10B981`), and a top banner confirms: *"Verified Fix Committed to PR Branch (Commit `a8f92d1`) in 11.4s"*.

 |
| **5. Guardrail / Error State (`3-STRIKE HALT`)** | If `attempt == 3` fails verification, the loop halts cleanly. Status badge turns Amber-Red (`Suggested Review Posted`), displaying `best_patch` (`best_score`) with a link to the non-destructive GitHub PR comment.
