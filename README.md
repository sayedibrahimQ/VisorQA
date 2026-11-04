# VisorQA

**Autonomous Visual QA and Self-Healing Frontend Agent**

[![Meta Global AI Developer Hackathon](https://img.shields.io/badge/Meta%20AI%20Hackathon-100%25%20Meta%20Foundation%20Models-blue?style=for-the-badge&logo=meta)](https://meta.ai)
[![E2B Sandbox](https://img.shields.io/badge/Sandbox-E2B%20Cloud%20Micro--VMs-orange?style=for-the-badge)](https://e2b.dev)
[![FSM Architecture](https://img.shields.io/badge/Architecture-Deterministic%205--Node%20FSM-emerald?style=for-the-badge)]()

VisorQA is an enterprise-grade, closed-loop autonomous QA agent that detects pixel-level UI regressions invisible to conventional DOM-based test suites (Playwright assertions, Cypress snapshots, Percy visual diffing), mathematically diagnoses their root cause, and autonomously commits verified CSS/React fixes directly to the originating pull request -- with zero human intervention.

Built for the **Meta Global AI Developer Hackathon** powered exclusively by Meta AI foundation models (**SAM 3.1**, **Muse Spark**, **Muse Wonder**, and **Muse Code**) running against cloud-isolated **E2B Micro-VM Sandboxes**.

---

## Table of Contents

- [Problem Statement: The DOM Abstraction Blindspot](#problem-statement-the-dom-abstraction-blindspot)
- [Core Thesis: Mathematical Discrepancy Engine](#core-thesis-mathematical-discrepancy-engine)
- [Architectural Blueprints & Technical Diagrams](#architectural-blueprints--technical-diagrams)
  - [1. End-to-End System Architecture Blueprint](#1-end-to-end-system-architecture-blueprint)
  - [2. Five-Node FSM Lifecycle & 3-Strike Self-Healing Loop](#2-five-node-fsm-lifecycle--3-strike-self-healing-loop)
  - [3. PostgreSQL 16 Entity-Relationship Schema](#3-postgresql-16-entity-relationship-schema)
- [Meta AI Foundation Models: Deep-Dive Integration](#meta-ai-foundation-models-deep-dive-integration)
  - [1. Meta SAM 3.1 (Visual Component Segmentation)](#1-meta-sam-31-visual-component-segmentation)
  - [2. Meta Muse Spark (LCA DOM Triage & Pruning)](#2-meta-muse-spark-lca-dom-triage--pruning)
  - [3. Meta Muse Wonder (Multimodal Visual Reasoning & Diagnosis)](#3-meta-muse-wonder-multimodal-visual-reasoning--diagnosis)
  - [4. Meta Muse Code (Surgical Unified Diff Synthesis)](#4-meta-muse-code-surgical-unified-diff-synthesis)
- [E2B Cloud Sandbox Execution Environment](#e2b-cloud-sandbox-execution-environment)
- [Five-Node FSM Pipeline Walkthrough](#five-node-fsm-pipeline-walkthrough)
- [Three-Strike Self-Healing Protocol](#three-strike-self-healing-protocol)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Database Schema & Enterprise CHECK Constraints](#database-schema--enterprise-check-constraints)
- [Safety Guardrails and Hard Constraints (BR-1 to BR-7)](#safety-guardrails-and-hard-constraints-br-1-to-br-7)
- [Getting Started](#getting-started)
- [Configuration Reference](#configuration-reference)
- [Hackathon Evaluation: Why VisorQA Wins](#hackathon-evaluation-why-visorqa-wins)
- [Documentation & Engineering Blueprints](#documentation--engineering-blueprints)
- [License](#license)

---

## Problem Statement: The DOM Abstraction Blindspot

Standard frontend testing tools operate strictly at the DOM abstraction layer. They assert that elements exist in the tree, that attributes match expectations, and that text content is rendered. However, they are fundamentally incapable of answering the only question that matters to end users:

> **Is this component actually visible, unobstructed, and correctly positioned on the rendered screen?**

Consider these frequent real-world production defects:
- A `<button>` passes every Playwright assertion (`toBeVisible()`, `toHaveText()`, `toHaveCSS()`) while being completely invisible to the user because a fixed marketing banner with a higher `z-index` sits directly on top of it.
- A responsive product card grid satisfies Cypress snapshot tests on desktop viewports, but when resized to mobile viewports ($375\text{px}$), flexbox children bleed $48\text{px}$ off-screen horizontally or collide directly over neighboring checkout badges.
- CSS cascade overrides (`position: absolute` vs `overflow: hidden`) clip critical CTA buttons out of existence.

Because traditional CI/CD pipelines never inspect the *actual pixel rendering output* against the *expected DOM geometry*, visual defects slip into production unnoticed.

VisorQA solves this problem autonomously.

---

## Core Thesis: Mathematical Discrepancy Engine

VisorQA introduces a formal verification layer between DOM geometry (what the browser *computes*) and pixel masks (what the user *actually sees*). For every interactive component, the system computes two discrete spatial representations:

| Symbol | Definition | Source |
| :--- | :--- | :--- |
| $B_{DOM}$ | Expected DOM bounding box $(x, y, w, h)$ | Playwright `element.boundingBox()` inside E2B Cloud Sandbox |
| $M_{SAM}$ | Actual visible pixel mask at render time | Meta SAM 3.1 zero-shot point-guided segmentation |

Any measurable discrepancy between $B_{DOM}$ and $M_{SAM}$ constitutes a visual anomaly. All defect detection is grounded in three deterministic equations evaluated over NumPy arrays:

### 1. Occlusion Detection (Visibility Ratio)

$$V_r = \frac{\text{Area}(M_{SAM} \cap B_{DOM})}{\text{Area}(B_{DOM})}$$

An element is classified as **occluded** when $V_r < 0.85$. This captures $z$-index stacking collisions, overflow clipping, and situations where rendered pixels are obscured.
- **Verification Threshold:** A patch is accepted only when $V_r \ge 0.98$ across both mobile and desktop viewports simultaneously.

### 2. Layout Collision (Intersection over Union)

$$IoU(M_i, M_j) = \frac{\text{Area}(M_i \cap M_j)}{\text{Area}(M_i \cup M_j)}$$

Sibling components are classified as **colliding** when $IoU > 0.05$. This catches text overlapping badges, unconstrained flex-wrap breaks, and elements fighting for the same screen real estate.
- **Verification Threshold:** A patch is accepted only when $IoU = 0.00$ across all sibling pairs.

### 3. Viewport Bleed (Horizontal Overflow)

$$\Delta_x = \max(0, X_{max} - W_{vp})$$

A component is classified as **bleeding** when $\Delta_x > 2.0\text{px}$. This captures horizontal overflow on mobile viewports ($375\text{px}$) where content breaks container boundaries.
- **Verification Threshold:** A patch is accepted only when $\Delta_x \le 2.0\text{px}$.

### Composite Health Score

The system scores each execution run using an auditable, deterministic scalar:

$$H = \overline{V_r} - \max(IoU) - 0.01 \cdot \max(\Delta_x)$$

A pull request run is declared `RESOLVED` if and only if $H \ge 0.98$ on both the $375\text{px}$ (mobile) and $1440\text{px}$ (desktop) viewports simultaneously.

---

## Architectural Blueprints & Technical Diagrams

### 1. End-to-End System Architecture Blueprint

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                             VISORQA SYSTEM ARCHITECTURE                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  [ GitHub PR / Push Webhook ] ──( HMAC-SHA256 < 1.2s )──► [ FastAPI Ingestion Layer ] ◄──► [ Mission Control Dashboard ]
                                                                   │                       ( Next.js 15 + WebSockets )
                                                                   ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  CORE DOMAIN & DETERMINISTIC FSM ENGINE (backend/core/orchestrator.py)                                                 │
│                                                                                                                        │
│   Fast Live Store                     State Machine Controller                     Persistence & Telemetry             │
│  ┌───────────────────────┐           ┌───────────────────────────────┐           ┌────────────────────────────────┐    │
│  │ LIVE_RUN_STAGES       │ ◄───────► │ 5-Node Deterministic FSM      │ ────────► │ PostgreSQL 16 (SQLModel)       │    │
│  │ In-Memory (<10ms REST)│           │ (Asyncio + Pydantic v2)       │           │ EER Constraints & CHECK Guards │    │
│  └───────────────────────┘           └───────────────┬───────────────┘           └────────────────────────────────┘    │
│                                                      │                                     │                           │
│                                                      ▼                                     ▼                           │
│                                        3-Strike Self-Healing Loop                Disk Artifact Store                   │
│                                      (max_attempts = 3, cost < $0.15)         (JSON Telemetry + Raw Mask PNGs)         │
└──────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────┘
                                                       │
         ┌─────────────────────────────────────────────┴────────────────────────────────────────────┐
         ▼                                                                                          ▼
┌─────────────────────────────────────────────────────────┐  ┌─────────────────────────────────────────────────────────┐
│ 100% META AI FOUNDATION MODELS (Meta Model API)         │  │ E2B CLOUD SANDBOX EXECUTION (https://e2b.dev)           │
│                                                         │  │                                                         │
│  [1] Meta SAM 3.1 (Segment Anything Model 3.1)          │  │  Isolated Cloud Micro-VM (Ubuntu 22.04 + Node.js 20)    │
│      • Role: Node 1 SENSE & Node 5 VERIFY               │  │  ┌───────────────────────────────────────────────────┐  │
│      • Zero-shot component pixel mask (M_SAM)           │  │  │ Headless Playwright Dual-Viewport Runner          │  │
│      • DOM-guided center points (cx, cy) + B_DOM priors │  │  │   - Mobile Viewport:  375 x 812 px (iPhone 13)    │  │
│                                                         │  │  │   - Desktop Viewport: 1440 x 900 px (Standard)    │  │
│  [2] Meta Muse Spark (muse-spark-1.3)                   │  │  └─────────────────────────┬─────────────────────────┘  │
│      • Role: Node 2 TRIAGE                              │  │                            │                            │
│      • LCA DOM tree mapping & file localization         │  │  ┌─────────────────────────▼─────────────────────────┐  │
│      • 88.5% DOM token pruning; protects ui/*           │  │  │ Vite / Next.js Target Application Dev Server      │  │
│                                                         │  │  │   - Sub-second HMR patch application (<300ms)     │  │
│  [3] Meta Muse Wonder (muse-wonder-1.0)                 │  │  │   - Authenticated e2b-traffic-access-token tunnel │  │
│      • Role: Node 3 DIAGNOSE                            │  │  └───────────────────────────────────────────────────┘  │
│      • Multimodal visual reasoning over collision masks │  │                                                         │
│      • Generates structured declarative RepairSpec JSON │  │  Local Worktree Sandbox Fallback:                       │
│                                                         │  │  Shared SandboxRunner interface for offline/unit tests   │
│  [4] Meta Muse Code (muse-spark-1.3 / Code Persona)     │  └─────────────────────────────────────────────────────────┘
│      • Role: Node 4 PATCH                               │
│      • Surgical unified diff synthesis                  │
│      • Enforces anti-hack CSS (no !important, no z:9999)│
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ AUTONOMOUS GITHUB RESOLUTION (VisorQA GitHub App)                                                                      │
│                                                                                                                        │
│  [ Success (H >= 0.98 on both viewports) ] ──► Auto-commit signed fix directly to originating PR branch               │
│  [ 3-Strike Failure ]                      ──► Post best-scoring patch as a non-destructive GitHub PR review comment   │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Five-Node FSM Lifecycle & 3-Strike Self-Healing Loop

```text
 ┌──────────────┐
 │ WEBHOOK INIT │ ──► GitHub PR / Push Event Received (< 1.2s HMAC verification)
 └──────┬───────┘
        │
        ▼
 ┌──────────────┐     • E2B cloud sandbox micro-VM provisions in < 1.5s
 │   01 SENSE   │     • Dual-viewport headless Playwright capture (375px mobile & 1440px desktop)
 │  (SAM 3.1)   │     • Point-guided Meta SAM 3.1 zero-shot component mask generation (M_SAM)
 └──────┬───────┘     • NumPy Math Engine: Occlusion (V_r), Collision (IoU), Viewport Bleed (Δ_x)
        │
        ├────────────────────────────────────► [ No Anomalies Detected? ] ──► [ RESOLVED (Exit 0) ]
        ▼
 ┌──────────────┐     • Extract DOM subtree around detected anomaly coordinates
 │  02 TRIAGE   │     • Meta Muse Spark computes Lowest Common Ancestor (LCA) container
 │ (Muse Spark) │     • Prunes 88.5% of irrelevant DOM tokens; identifies 1-2 candidate source files
 └──────┬───────┘     • BR-5 Safeguard: Never targets shared primitives (src/components/ui/*)
        │
        ▼
 ╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
 ║                         3-STRIKE SELF-HEALING REPAIR LOOP (attempt 1..3)                     ║
 ║                                                                                               ║
 ║  ┌──────────────┐  • Multi-modal prompt: red collision overlay + CSS metrics + target files   ║
 ║  │ 03 DIAGNOSE  │  • Meta Muse Wonder reasons over visual geometry and root cause             ║
 ║  │(Muse Wonder) │  • Emits structured RepairSpec JSON (desktop preservation constraints)      ║
 ║  └──────┬───────┘                                                                             ║
 ║         │                                                                                     ║
 ║         ▼                                                                                     ║
 ║  ┌──────────────┐  • Synthesizes surgical Unified Diff patch adhering to RepairSpec           ║
 ║  │   04 PATCH   │  • BR-4 Safety Check: Rejects !important, z-index: 9999, and z-[9999]       ║
 ║  │ (Muse Code)  │  • Hot-reloads patch into E2B micro-VM via HMR in < 300ms                   ║
 ║  └──────┬───────┘                                                                             ║
 ║         │                                                                                     ║
 ║         ▼                                                                                     ║
 ║  ┌──────────────┐  • Re-captures 375px and 1440px viewports inside E2B sandbox                ║
 ║  │  05 VERIFY   │  • Meta SAM 3.1 re-segments components; NumPy re-evaluates V_r, IoU, Δ_x   ║
 ║  │  (SAM 3.1)   │  • Composite Health Score evaluated: H = mean(V_r) - max(IoU) - 0.01*Δ_x    ║
 ║  └──────┬───────┘                                                                             ║
 ╚═════════╪═════════════════════════════════════════════════════════════════════════════════════╝
           │
           ├─────────────────► [ H >= 0.98 on BOTH Viewports? ] ──► [ RESOLVED: Auto-Commit Fix ]
           │
           ▼ (H < 0.98)
     [ Strike < 3? ] ──► Feed strike feedback + diff back to Node 03 (DIAGNOSE)
           │
           ▼ (Strike 3 Exhausted)
   [ FAILED / FALLBACK ] ──► Post best-scoring patch as a non-destructive PR review comment
```

---

### 3. PostgreSQL 16 Entity-Relationship Schema

```text
┌───────────────────────────┐                 ┌────────────────────────────────────────────────────────┐
│       REPOSITORIES        │                 │                        PR_RUNS                         │
├───────────────────────────┤                 ├────────────────────────────────────────────────────────┤
│ id:           UUID [PK]   │1               *│ id:                 UUID [PK]                          │
│ repo_full_name: TEXT [UK] │─────────────────│ repo_id:            UUID [FK -> repositories.id]       │
│ owner:        TEXT        │                 │ github_delivery_id: UUID [UK]                          │
│ name:         TEXT        │                 │ repo_full_name:     TEXT [IDX]                         │
│ default_branch: TEXT      │                 │ pr_number:          INT [IDX]                          │
│ protected_globs: JSONB    │                 │ pr_title:           TEXT                               │
│ commit_mode:  TEXT        │                 │ branch:             TEXT                               │
│ is_active:    BOOL        │                 │ commit_sha:         TEXT [IDX]                         │
│ created_at:   TIMESTAMPTZ │                 │ status:             TEXT [IDX] (QUEUED..RESOLVED..FAIL)│
│ updated_at:   TIMESTAMPTZ │                 │ attempt:            INT  CHECK (0 <= attempt <= 3)     │
└───────────────────────────┘                 │ max_attempts:       INT  DEFAULT 3                     │
                                              │ target_files:       JSONB                              │
                                              │ initial_score:      FLOAT                              │
                                              │ best_score:         FLOAT                              │
                                              │ best_patch:         TEXT                               │
                                              │ is_resolved:        BOOL [IDX]                         │
                                              │ total_cost_usd:     FLOAT CHECK (total_cost_usd <= 0.15│
                                              │ total_latency_ms:   INT                                │
                                              │ created_at:         TIMESTAMPTZ [IDX DESC]             │
                                              │ updated_at:         TIMESTAMPTZ                        │
                                              └───────────────────┬────────────────────────────────────┘
                                                                  │
                                      ┌───────────────────────────┴───────────────────────────┐
                                      │ 1                                                     │ 1
                                      ▼ *                                                     ▼ *
┌─────────────────────────────────────────────────────────┐ ┌─────────────────────────────────────────────────────────┐
│                    VISUAL_ANOMALIES                     │ │                     REPAIR_ATTEMPTS                     │
├─────────────────────────────────────────────────────────┤ ├─────────────────────────────────────────────────────────┤
│ id:              UUID [PK]                              │ │ id:                UUID [PK]                            │
│ run_id:          UUID [FK -> pr_runs.id]                │ │ run_id:            UUID [FK -> pr_runs.id]              │
│ visor_el_id:     TEXT                                   │ │ attempt_number:    INT CHECK (1 <= attempt_number <= 3) │
│ defect_type:     TEXT (OCCLUSION | COLLISION | BLEED)   │ │ repair_spec:       JSONB (Pydantic Schema)              │
│ v_r:             FLOAT                                  │ │ unified_diff:      TEXT (CHECK anti-hack CSS policy)    │
│ iou:             FLOAT                                  │ │ mobile_v_r_min:    FLOAT                                │
│ bleed_px:        FLOAT                                  │ │ desktop_v_r_min:   FLOAT                                │
│ b_dom_box:       JSONB (x, y, w, h)                     │ │ verified_iou:      FLOAT                                │
│ secondary_el_id: TEXT                                   │ │ verified_bleed_px: FLOAT                                │
│ viewport:        TEXT (375px | 1440px)                  │ │ post_score:        FLOAT                                │
│ attempt_num:     INT                                    │ │ hmr_latency_ms:    INT                                  │
│ mask_url:        TEXT                                   │ │ passed:            BOOL                                 │
│ is_resolved:     BOOL                                   │ │ error_message:     TEXT                                 │
│ created_at:      TIMESTAMPTZ                            │ │ telemetry:         JSONB                                │
├─────────────────────────────────────────────────────────┤ │ created_at:        TIMESTAMPTZ                          │
│ CHECK (defect_type = 'OCCLUSION' AND v_r < 0.85) OR     │ ├─────────────────────────────────────────────────────────┤
│       (defect_type = 'COLLISION' AND iou > 0.05) OR     │ │ CHECK (unified_diff NOT ILIKE '%!important%' AND        │
│       (defect_type = 'BLEED' AND bleed_px > 2.0)        │ │        unified_diff NOT ILIKE '%z-index: 9999%' AND     │
└─────────────────────────────────────────────────────────┘ │        unified_diff NOT ILIKE '%z-[9999]%')             │
                                                            └─────────────────────────────────────────────────────────┘
```

---

## Meta AI Foundation Models: Deep-Dive Integration

VisorQA calls the official **Meta Model API** directly (`https://api.meta.ai/v1`) using OpenAI SDK-compatible async interfaces with strictly typed JSON Schema decoding (`beta.chat.completions.parse`). Each model is mapped to a dedicated engineering responsibility where its unique architectural strengths solve an otherwise intractable challenge:

| Model | Model Identifier | Pipeline Stage | Primary Responsibility | Strategic Value to VisorQA |
| :--- | :--- | :--- | :--- | :--- |
| **Meta SAM 3.1** | `sam-3.1` | **Node 1 (Sense) & Node 5 (Verify)** | Point-guided zero-shot visual segmentation | Eliminates visual heuristics. Derives exact pixel-perfect ground-truth masks from center coordinates $(c_x, c_y)$ and $B_{DOM}$ priors. |
| **Meta Muse Spark** | `muse-spark-1.3` | **Node 2 (Triage)** | Source localization & DOM tree pruning | Fast inference & huge context efficiency. Prunes 88.5% of irrelevant DOM tokens and redirects targets away from protected UI primitives. |
| **Meta Muse Wonder** | `muse-wonder-1.0` | **Node 3 (Diagnose)** | Multimodal visual reasoning & diagnosis | Interprets collision masks and dual-viewport CSS styles to generate structured `RepairSpec` JSONs with zero code hallucination. |
| **Meta Muse Code** | `muse-spark-1.3` | **Node 4 (Patch)** | Surgical code synthesis & unified diffs | Generates minimal unified diffs that fix mobile layout breaks without causing cross-viewport desktop regressions. |

---

### 1. Meta SAM 3.1 (Visual Component Segmentation)
- **Role in Pipeline:** Node 1 (SENSE) & Node 5 (VERIFY).
- **Endpoint:** Meta Vision API with DOM-guided prompt transport.
- **Input:** Native resolution viewport screenshots ($375\text{px}$ and $1440\text{px}$) + DOM bounding box centers $(c_x, c_y)$ for every annotated `visor-el-*` component.
- **How It Is Used:** Unlike unprompted "Everything Mode" grid inference (which is slow and ungrounded), VisorQA prompts SAM 3.1 with specific DOM bounding box centers and geometric priors. SAM 3.1 returns 1:1 binary pixel masks ($M_{SAM}$) for each element.
- **Why It Matters for Judges:** Traditional computer vision models struggle with fine typography, transparent buttons, and overlapping gradients. SAM 3.1 provides sub-pixel segmentation fidelity, allowing VisorQA's NumPy engine to compute exact intersection areas ($\text{Area}(M_{SAM} \cap B_{DOM})$) and declare mathematical occlusion with zero guessing.

---

### 2. Meta Muse Spark (LCA DOM Triage & Pruning)
- **Role in Pipeline:** Node 2 (TRIAGE).
- **Model:** `muse-spark-1.3` via `https://api.meta.ai/v1`.
- **Input:** List of detected mathematical anomalies, repository source tree, and the DOM hierarchy tree.
- **How It Is Used:** Muse Spark computes the Lowest Common Ancestor (LCA) container for all colliding elements. It prunes away 88.5% of unaffected DOM tokens and localizes the exact 1–2 repository files responsible for the defect.
- **Architectural Safeguard (BR-5):** Shared design-system components (`src/components/ui/*`) are strictly protected. Muse Spark recognizes that while a defect may physically appear on an atomic button primitive, the root-cause responsibility lies in the parent grid or consuming layout component, and automatically redirects the patch target.

---

### 3. Meta Muse Wonder (Multimodal Visual Reasoning & Diagnosis)
- **Role in Pipeline:** Node 3 (DIAGNOSE).
- **Model:** `muse-wonder-1.0` via `https://api.meta.ai/v1`.
- **Input:** Multi-modal payload consisting of:
  1. Base64 red collision-mask overlay image.
  2. Mathematical telemetry vector: $[V_r, IoU, \Delta_x, H]$.
  3. Computed CSS signatures for affected elements across mobile and desktop.
  4. Contents of the localized target files.
- **How It Is Used:** Muse Wonder performs spatial reasoning to diagnose *why* the layout broke (e.g. "missing `flex-wrap` causes child badges to overflow on viewports under $400\text{px}$" or "relative child inside an overflow-hidden card is clipped").
- **Output:** Outputs a structured Pydantic `RepairSpec` JSON specifying affected selectors, suggested CSS properties, and desktop preservation constraints. It intentionally produces *zero code*, preventing syntax hallucinations during diagnosis.

---

### 4. Meta Muse Code (Surgical Unified Diff Synthesis)
- **Role in Pipeline:** Node 4 (PATCH).
- **Model:** `muse-spark-1.3` (Muse Code Persona) via `https://api.meta.ai/v1`.
- **Input:** Muse Wonder's `RepairSpec` + target source file content + Tailwind configuration.
- **How It Is Used:** Synthesizes a minimal, valid unified diff patch (e.g., `--- a/src/components/ProductCard.tsx`, `+++ b/src/components/ProductCard.tsx`).
- **Anti-Hack Policy (BR-4):** Strictly forbidden from emitting brittle overrides (`!important`, `z-index: 9999`, `z-[9999]`). Instead, it leverages responsive Tailwind utility classes (`flex-wrap`, `gap-2`, `md:flex-nowrap`) that heal the mobile defect while guaranteeing zero regressions on desktop.

---

## E2B Cloud Sandbox Execution Environment

VisorQA executes all browser automation, dev server builds, and hot reloads inside **E2B Micro-VM Sandboxes** (`https://e2b.dev`). 

```
+-------------------------------------------------------------------------+
| E2B Cloud Micro-VM Sandbox (e2b / AsyncSandbox)                        |
|                                                                         |
|  +--------------------+     +-------------------+     +---------------+ |
|  | Vite / Next.js Dev | <-> | Headless Chromium | <-> | HMR Watcher   | |
|  | Server (Port 3001) |     | Playwright Runner |     | Sub-300ms App | |
|  +--------------------+     +-------------------+     +---------------+ |
|           ^                                                   ^         |
|           | Secure Tunnel: e2b-traffic-access-token           |         |
+-----------|---------------------------------------------------|---------+
            |                                                   |
            v                                                   v
   VisorQA Backend Engine                               Surgical Patch Diff
```

### Why E2B Sandboxes?
1. **Sub-1.5s Cold Start:** Micro-VMs boot in under 1.5 seconds, allowing on-demand per-PR provisioning without maintaining costly idle container pools.
2. **True Kernel-Level Isolation:** Each pull request runs in its own micro-VM with dedicated filesystem and memory namespaces. Malicious repository code can never touch host infrastructure.
3. **Sub-300ms HMR Reloads:** Patches synthesized by Muse Code are streamed directly into the E2B container filesystem. The active dev server hot-reloads in `< 300ms`, enabling rapid re-segmentation without restarting the application.
4. **Secure Traffic Tunneling:** E2B preview endpoints (`*.e2b.dev`) are authenticated via `e2b-traffic-access-token` request headers, ensuring preview instances are accessible only to the VisorQA test harness.
5. **Fast Local Worktree Fallback:** For offline local development and deterministic unit testing, VisorQA provides a shared `SandboxRunner` interface backed by a local Git worktree runner.

---

## Five-Node FSM Pipeline Walkthrough

VisorQA operates as an asynchronous, deterministic finite state machine implemented in pure Python (no LangChain, CrewAI, AutoGen, or opaque agent loops).

```
01 SENSE  ==>  02 TRIAGE  ==>  03 DIAGNOSE  ==>  04 PATCH  ==>  05 VERIFY
```

### Node 1: SENSE
- Spins up an E2B micro-VM sandbox with the target PR branch.
- Launches headless Playwright to capture screenshots at dual viewports:
  - **Mobile:** $375 \times 812\text{px}$ (iPhone 13 viewport)
  - **Desktop:** $1440 \times 900\text{px}$ (Standard desktop viewport)
- Extracts DOM bounding boxes $B_{DOM}$ and computed styles for `visor-el-*` elements.
- Invokes Meta SAM 3.1 with DOM-guided center points to extract pixel masks $M_{SAM}$.
- Computes $V_r$, $IoU$, and $\Delta_x$. If no anomalies are detected, the run exits cleanly as `RESOLVED`.

### Node 2: TRIAGE
- Groups detected anomalies and extracts the surrounding DOM subtree.
- Meta Muse Spark computes the Lowest Common Ancestor (LCA) container.
- Maps visual defects to concrete repository source files (`target_files[]`).
- Enforces BR-5: excludes protected UI primitives (`src/components/ui/*`).

### Node 3: DIAGNOSE
- Assembles multi-modal prompt: red collision mask overlay, computed CSS, and metrics.
- Meta Muse Wonder reasons over the defect geometry.
- Emits a declarative `RepairSpec` JSON with zero code hallucination.

### Node 4: PATCH
- Meta Muse Code synthesizes a surgical unified diff against the target file.
- Validates the diff against safety guardrails (anti-hack CSS rules, protected globs).
- Streams the diff into the running E2B sandbox via HMR.

### Node 5: VERIFY
- Playwright re-renders both $375\text{px}$ and $1440\text{px}$ viewports inside the E2B sandbox.
- Meta SAM 3.1 re-segments the components.
- Evaluates the composite health score:
  - If $V_r \ge 0.98$, $IoU = 0.00$, and $\Delta_x \le 2.0\text{px}$ on **both** viewports, the FSM transitions to `RESOLVED` and commits the fix to GitHub.
  - If verification fails and attempts remain, the FSM increments the strike counter and loops back to **Node 3 (DIAGNOSE)** with updated strike feedback.

---

## Three-Strike Self-Healing Protocol

The 3-Strike Loop is enforced at both the FSM orchestration layer and the PostgreSQL database layer via an explicit SQL CHECK constraint:

```sql
CHECK (attempt >= 0 AND attempt <= 3)   -- chk_pr_runs_3_strike_cap
```

| Attempt | On Verification Failure | On Verification Success |
| :--- | :--- | :--- |
| **Strike 1** | Ingest re-segmented feedback and previous diff back into Muse Wonder. Loop to Node 3. | Set `is_resolved = True`. Push signed commit via GitHub App. |
| **Strike 2** | Accumulate multi-attempt context and re-diagnose with Muse Wonder. Loop to Node 3. | Same as above. |
| **Strike 3** | **Halt Loop.** Fallback to BR-6: Post the highest-scoring `best_patch` as a GitHub PR review comment. | Same as above. |

VisorQA always tracks and preserves the best-scoring patch across all attempts:

```python
if current_score > state.best_score:
    state.best_score = current_score
    state.best_patch = state.current_patch
```

---

## Technology Stack

### Core Technologies

| Layer | Component | Technology | Role |
| :--- | :--- | :--- | :--- |
| **AI Models** | Segmentation | **Meta SAM 3.1** | Point-guided zero-shot visual component segmentation |
| **AI Models** | Triage | **Meta Muse Spark** (`muse-spark-1.3`) | LCA DOM hierarchy localization & 88.5% token reduction |
| **AI Models** | Reasoning | **Meta Muse Wonder** (`muse-wonder-1.0`) | Multimodal root-cause visual diagnosis (`RepairSpec`) |
| **AI Models** | Code Synthesis | **Meta Muse Code** (`muse-spark-1.3`) | Surgical unified diff synthesis adhering to anti-hack CSS |
| **Sandbox** | Cloud Micro-VM | **E2B Sandbox** (`e2b`) | Kernel-isolated micro-VM, dev server, and <300ms HMR |
| **Automation** | Browser Driver | **Playwright** (Headless Chromium) | Dual-viewport rendering ($375\text{px}$ and $1440\text{px}$) |
| **Math Engine** | Vision Math | **NumPy** | Deterministic $V_r$, $IoU$, and $\Delta_x$ vector calculations |
| **Backend** | API & Streaming | **FastAPI + Uvicorn** | Webhook verification, REST endpoints, and WebSocket feed |
| **Backend** | State Machine | **Pure Python + Pydantic v2** | Deterministic 5-Node FSM (`orchestrator.py`) |
| **Database** | Relational Store | **PostgreSQL 16 + SQLModel** | Async persistence with EER CHECK constraints & GIN indexes |
| **Frontend** | Mission Control | **Next.js 15 (App Router)** | Real-time visual QA dashboard with SAM mask comparison |
| **Frontend** | Styling | **Tailwind CSS** | Monochrome mission-control interface with AI Harmony |
| **Git / CI** | PR Automation | **GitHub App + PyGithub** | HMAC-SHA256 verification, auto-commits, review comments |

---

## Repository Structure

```
VisorQA/
|-- backend/
|   |-- adapters/
|   |   |-- spark_client.py         # Meta Muse Spark client (Meta Model API direct)
|   |   |-- wonder_client.py        # Meta Muse Wonder multimodal client
|   |   |-- code_client.py          # Meta Muse Code patch client
|   |   |-- sam31.py                # Point-guided Meta SAM 3.1 client
|   |   |-- sandbox_runner.py       # E2B Cloud Micro-VM / Local worktree runner
|   |   |-- github_app.py           # GitHub App installation token resolution
|   |   |-- github_client.py        # Git commit, PR comment, and review publisher
|   |-- api/
|   |   |-- webhooks.py             # POST /api/webhooks/github (HMAC-SHA256 verified)
|   |   |-- routes_ws.py            # GET /api/runs/:id, WS /ws/mission-control
|   |   |-- github_repos.py         # PR telemetry auto-publisher & duplicate cleaner
|   |-- core/
|   |   |-- orchestrator.py         # Deterministic 5-node FSM & in-memory live store
|   |   |-- state.py                # AgentState, FSMStep, Anomaly, SelfHealingAttempt
|   |   |-- sense.py                # Playwright dual-viewport capture & SAM segmentation
|   |   |-- triage.py               # LCA DOM calculation & protected glob filtering
|   |   |-- diagnose.py             # Multimodal reasoning & RepairSpec generation
|   |   |-- patch.py                # Unified diff parsing, validation, & HMR application
|   |   |-- verify.py               # Re-segmentation, score evaluation, & 3-strike checks
|   |   |-- vision_math.py          # NumPy: Vr, IoU, Delta_x, and Health Score
|   |   |-- artifacts.py            # Telemetry JSON and screenshot registry store
|   |-- db/
|   |   |-- repository.py           # PostgreSQL 16 SQLModel schema & async repository
|   |-- config.py                   # Pydantic Settings & mathematical constants
|   |-- main.py                     # FastAPI entrypoint with ASGI lifecycle hooks
|   |-- requirements.txt
|-- frontend/
|   |-- src/
|   |   |-- app/
|   |   |   |-- page.tsx            # Landing page with interactive proof workbench
|   |   |   |-- mission-control/    # Live multi-run inspection dashboard
|   |   |   |-- runs/[id]/page.tsx  # Deep-link individual PR run inspector
|   |   |-- components/
|   |   |   |-- mission-control/    # FSMOrchestratorBar, ViewportStage, TelemetryDrawer
|   |   |   |-- landing/            # Hero, ProofPreview, MaskComparisonSlider
|   |   |-- hooks/
|   |   |   |-- useMissionControlStream.ts  # Real-time WebSocket + 500ms polling
|   |   |   |-- useRunDetails.ts            # Run telemetry hydration hook
|   |   |-- lib/
|   |   |   |-- fsmSelectors.ts     # FSM node states, latencies, and step indexing
|   |   |-- types/                  # TypeScript domain type definitions
|   |-- package.json
|   |-- tailwind.config.ts
|-- demo-target-app/                # Sample React storefront with reproducible visual bugs
|-- Docs/                           # Architecture Decision Records (ADRs) & Specifications
|-- docker-compose.yml              # PostgreSQL 16 Alpine container
|-- .env.example                    # Environment variable configuration template
```

---

## Database Schema & Enterprise CHECK Constraints

VisorQA enforces business rules and mathematical invariants directly at the database persistence layer using PostgreSQL 16 CHECK constraints:

### 1. `pr_runs` (3-Strike Cap & Cost Bound)
```sql
ALTER TABLE pr_runs ADD CONSTRAINT chk_pr_runs_3_strike_cap 
    CHECK (attempt >= 0 AND attempt <= 3);

ALTER TABLE pr_runs ADD CONSTRAINT chk_pr_runs_cost_guardrail 
    CHECK (total_cost_usd <= 0.15);
```

### 2. `visual_anomalies` (Mathematical Subtype Invariants)
```sql
ALTER TABLE visual_anomalies ADD CONSTRAINT chk_visual_anomalies_math 
    CHECK (
        (defect_type = 'OCCLUSION'  AND v_r IS NOT NULL      AND v_r < 0.85)     OR
        (defect_type = 'COLLISION'  AND iou IS NOT NULL       AND iou > 0.05)     OR
        (defect_type = 'BLEED'      AND bleed_px IS NOT NULL  AND bleed_px > 2.0)
    );
```

### 3. `repair_attempts` (Anti-Hack CSS Defense)
```sql
ALTER TABLE repair_attempts ADD CONSTRAINT chk_repair_attempts_no_hacks 
    CHECK (
        unified_diff IS NULL OR (
            unified_diff NOT ILIKE '%!important%'    AND
            unified_diff NOT ILIKE '%z-index: 9999%' AND
            unified_diff NOT ILIKE '%z-[9999]%'
        )
    );
```

---

## Safety Guardrails and Hard Constraints (BR-1 to BR-7)

| Rule ID | Business Rule | Enforcement Mechanism |
| :--- | :--- | :--- |
| **BR-1** | **3-Strike Self-Healing Cap** | PostgreSQL `chk_pr_runs_3_strike_cap` + FSM counter guard. |
| **BR-2** | **Inference Cost Guardrail ($0.15/run)** | Database CHECK constraint on `total_cost_usd`. |
| **BR-3** | **Cross-Viewport Zero Regression** | Verification passes only if $H \ge 0.98$ on **both** $375\text{px}$ and $1440\text{px}$ simultaneously. |
| **BR-4** | **Anti-Hack CSS Policy** | Database CHECK constraint rejecting `!important` and `z-index: 9999`. |
| **BR-5** | **Protected UI Primitives** | Glob exclusion preventing direct mutations to `src/components/ui/*`. |
| **BR-6** | **Non-Destructive Review Fallback** | After Strike 3 fails, the best patch is posted as a PR review comment instead of committed. |
| **BR-7** | **Strict Viewport Confinement** | Anomalies and metrics are validated only against calibrated $375\text{px}$ and $1440\text{px}$ frames. |

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker and Docker Compose
- Meta AI Model API Key (`https://api.meta.ai`)
- E2B API Key (`https://e2b.dev`)
- GitHub App or Personal Access Token (PAT)

### 1. Clone the Repository
```bash
git clone https://github.com/sayedibrahimQ/VisorQA.git
cd VisorQA
```

### 2. Configure Environment Variables
```bash
cp .env.example .env
```
Edit `.env` with your API credentials:
```ini
META_API_KEY=your_meta_model_api_key
META_BASE_URL=https://api.meta.ai/v1
E2B_API_KEY=your_e2b_api_key
SANDBOX_PROVIDER=e2b
GITHUB_PAT=your_github_token
```

### 3. Launch PostgreSQL 16
```bash
docker compose up -d
```

### 4. Setup and Start Backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
playwright install chromium
python -m backend.main
```
The API server starts at `http://localhost:8000`.

### 5. Setup and Start Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` to access Mission Control.

### 6. Verify Health Status
```bash
curl http://localhost:8000/health
```
```json
{
  "status": "healthy",
  "service": "VisorQA Backend",
  "version": "1.0.0",
  "math_thresholds": {
    "v_r_occlusion": 0.85,
    "iou_collision": 0.05,
    "max_attempts": 3
  }
}
```

---

## Configuration Reference

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `META_API_KEY` | *required* | Meta Model API key for SAM 3.1, Muse Spark, Muse Wonder, Muse Code |
| `META_BASE_URL` | `https://api.meta.ai/v1` | Meta Model API base endpoint |
| `MUSE_SPARK_MODEL` | `muse-spark-1.3` | Model identifier for LCA DOM hierarchy triage |
| `MUSE_WONDER_MODEL` | `muse-wonder-1.0` | Model identifier for multimodal visual diagnosis |
| `MUSE_CODE_MODEL` | `muse-spark-1.3` | Model identifier for unified diff synthesis |
| `SANDBOX_PROVIDER` | `e2b` | Cloud sandbox provider (`e2b`, `local`, `stub`) |
| `E2B_API_KEY` | *required for cloud* | E2B Cloud Sandbox API key |
| `E2B_SANDBOX_TIMEOUT_SECONDS` | `180` | Maximum micro-VM container lifetime bound |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL asyncpg connection string |
| `GITHUB_APP_ID` | -- | GitHub App ID for bot authentication |
| `GITHUB_APP_PRIVATE_KEY` | -- | GitHub App private key PEM |
| `GITHUB_PAT` | -- | GitHub Personal Access Token (fallback) |
| `GITHUB_WEBHOOK_SECRET` | -- | HMAC-SHA256 signature verification secret |
| `VISIBILITY_RATIO_THRESHOLD` | `0.85` | $V_r$ occlusion detection threshold |
| `IOU_COLLISION_THRESHOLD` | `0.05` | $IoU$ layout collision threshold |
| `BLEED_PX_THRESHOLD` | `2.0` | $\Delta_x$ horizontal overflow threshold |
| `MAX_SELF_HEALING_ATTEMPTS`| `3` | Maximum iterations in the 3-strike loop |

---

## Hackathon Evaluation: Why VisorQA Wins

1. **100% Meta Foundation Models:**
   Unlike projects that wrap generic commercial APIs, VisorQA harnesses the specific specialized capabilities of Meta's lineup: **SAM 3.1** for zero-shot pixel masks, **Muse Spark** for LCA tree triage, **Muse Wonder** for multi-modal diagnosis, and **Muse Code** for surgical diff generation.
2. **Deterministic Vision Math, Not Hallucination:**
   No subjective LLM visual assertions. Every defect is computed deterministically with pure NumPy over pixel masks ($V_r < 0.85$, $IoU > 0.05$, $\Delta_x > 2\text{px}$).
3. **True Autonomous Closed Loop:**
   From GitHub webhook arrival $\rightarrow$ E2B cloud micro-VM provisioning $\rightarrow$ visual capture $\rightarrow$ Meta AI diagnosis $\rightarrow$ HMR testing $\rightarrow$ verified git commit pushed back to GitHub, the entire pipeline executes with zero human intervention in under 45 seconds.
4. **Enterprise Safety & Anti-Hack Policy:**
   VisorQA is engineered for real production teams. Database CHECK constraints reject quick-and-dirty hack patches (`!important`, `z-index: 9999`), and protected UI component globs prevent core design-system corruption.
5. **Architectural Cleanliness:**
   Built on standard asyncio, Pydantic v2, and FastAPI without heavy or unpredictable agent wrappers.

---

## Documentation & Engineering Blueprints

Comprehensive architectural blueprints and specification documents are included in the repository:

| Document | Description |
| :--- | :--- |
| [Architecture Decision Records & Blueprint](Docs/VisorQA%20Architecture%20Decision%20Records%20%26%20Engineering%20Blueprint.pdf) | ADRs, design rationale, and engineering trade-offs |
| [Software Requirements Specification (SRS)](Docs/VisorQA%20Software%20Requirements%20Specification%20(SRS).pdf) | Functional requirements, system invariants, and use cases |
| [Technical Design Specification (TDS)](Docs/VisorQA%20Technical%20Design%20Specification.pdf) | Complete component specs, sequence flows, and contracts |
| [Autonomous Visual QA Agent Overview](Docs/Autonomous%20Visual%20QA%20%26%20Self-Healing%20Frontend%20Agent.pdf) | High-level system overview and agent behavioral spec |
| [UI/UX Design Specification](Design.md) | Complete design tokens, typography, and wireframe specs |

---

## License

This project was developed for the **Meta Global AI Developer Hackathon** under the MIT License.
