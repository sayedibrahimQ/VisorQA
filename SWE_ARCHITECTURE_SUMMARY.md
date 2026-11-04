# 🛡️ VisorQA: Principal Software Engineer Architectural Brief & Evaluation Guide

> **Document Classification:** Untracked Engineering & Architectural Summary  
> **Target Audience:** Principal Software Engineers, Staff Architects, and Hackathon Judges  
> **System Purpose:** Autonomous, closed-loop optical QA and surgical layout self-healing circuit powered by Meta AI Foundation Models (Meta SAM 3.1 & Meta Muse) and isolated E2B Micro-VM sandboxes.

---

## 1. Executive Summary & Engineering Thesis

### The Fundamental Flaw of Modern Web Testing
In contemporary frontend CI/CD pipelines (Playwright, Cypress, Selenium, Jest/Testing Library), test suites inspect the **DOM tree** (Document Object Model), asserting that elements exist (`toBeInTheDocument()`), have text content, and are technically reachable. 

However, **browsers render pixels, not DOM nodes**. A web element can be 100% valid in the DOM while being completely unusable by human end-users due to:
1. **Z-Index & Stacking Context Collisions:** Fixed or sticky headers/banners covering critical action triggers.
2. **Mobile Viewport Overflow & Clipping:** Elements pushed off-screen or occluded by viewport bounds (`overflow: hidden`).
3. **Flexbox / Grid Layout Collapse:** Responsive breakpoint mismatch where elements overlap at intermediate aspect ratios.

Traditional visual regression tools (e.g., Percy, Chromatic) simply render pixel diffs and flag them for human review, creating massive noise and failing to act.

### The VisorQA Breakthrough
**VisorQA** closes this loop entirely. It operates as an autonomous, deterministic **Five-Node Finite State Machine (FSM)**:
- It **senses** optical occlusion using **Meta SAM 3.1** zero-shot segmentation.
- It **triages** candidate source files using **Meta Muse Spark** via Lowest Common Ancestor (LCA) tree pruning.
- It **diagnoses** root causes using **Meta Muse Wonder** multimodal optical reasoning.
- It **synthesizes** surgical responsive CSS patches using **Meta Muse Code**.
- It **verifies** fixes across dual viewports (Mobile `375×812` & Desktop `1440×900`) in an isolated **E2B Micro-VM Sandbox**, auto-committing the verified fix directly to the GitHub Pull Request.

---

## 2. End-to-End System Architecture

```
                                      ┌─────────────────────────────────────────────────────────┐
                                      │              VISORQA SYSTEM TOPOLOGY                    │
                                      └─────────────────────────────────────────────────────────┘

   GITHUB ECOSYSTEM                        FASTAPI INGESTION & REALTIME STORE                   META AI FOUNDATION MODELS
┌───────────────────────┐                 ┌───────────────────────────────────────┐            ┌───────────────────────────┐
│ • PR Open / Sync      │──Webhook (HMAC)─▶│ POST /api/webhooks/github             │            │ 01 SENSE: Meta SAM 3.1    │
│ • visorqa-agent[bot]  │                 │ • Validates X-Hub-Signature-256       │            │ • Zero-shot segmentation  │
│ • Telemetry Comments  │◀───Auto-Commit──│ • Spawns async FSM background task    │            │ • Binary mask M_SAM       │
│ • Signed Diff Patches │    & Telemetry  └──────────────────┬────────────────────┘            └─────────────┬─────────────┘
└───────────────────────┘                                    │                                               │
                                                             ▼                                               │
                                          ┌───────────────────────────────────────┐                          │
                                          │      5-NODE DETERMINISTIC FSM         │                          │
                                          │      (backend/core/orchestrator.py)   │                          │
                                          ├───────────────────────────────────────┤                          │
                                          │ [01 SENSE]    ──▶ E2B Sandbox + SAM3.1│◀─────────────────────────┘
                                          │     │                                 │
                                          │     ▼                                 │            ┌───────────────────────────┐
                                          │ [02 TRIAGE]   ──▶ DOM LCA + Spark 1.3 │◀───────────│ 02 TRIAGE: Meta Muse Spark│
                                          │     │                                 │            │ • Pydantic LCA isolation  │
                                          │     ▼                                 │            │ • Prunes repository tree  │
                                          │ [03 DIAGNOSE] ──▶ Wonder 1.0 (Visual) │◀───────────└─────────────┬─────────────┘
                                          │     │                                 │                          │
                                          │     ▼                                 │            ┌─────────────┴─────────────┐
                                          │ [04 PATCH]    ──▶ Muse Code (Tailwind)│◀───────────│ 03 DIAG: Meta Muse Wonder │
                                          │     │                                 │            │ • Multimodal Optical Spec │
                                          │     ▼                                 │            │ • Zero code, pure strategy│
                                          │ [05 VERIFY]   ──▶ E2B Dual-Viewport   │            └─────────────┬─────────────┘
                                          └──────────────────┬────────────────────┘                          │
                                                             │                                 ┌─────────────┴─────────────┐
                                                             ▼                                 │ 04 PATCH: Meta Muse Code  │
                                          ┌───────────────────────────────────────┐            │ • Minimal Unified Diff    │
                                          │        OBSERVABILITY & PERSISTENCE    │            │ • Responsive constraints  │
                                          ├───────────────────────────────────────┤            └───────────────────────────┘
                                          │ • Sub-10ms In-Memory Stage Store      │
                                          │ • PostgreSQL 16 + SQLModel Records    │
                                          │ • Next.js 15 Mission Control UI       │
                                          │   (500ms REST Polling + WebSockets)   │
                                          └───────────────────────────────────────┘
```

---

## 3. Mathematical Discrepancy Engine (`backend/core/vision_math.py`)

VisorQA rejects subjective visual inspection. It relies on a deterministic, vectorized **NumPy** math engine that evaluates pixel coordinates, bounding boxes, and rasterized segmentation masks:

### 1. Vectorized Definitions
- **DOM Bounding Box ($B_\text{DOM}$):** Extracted via browser `getBoundingClientRect()` as $(x, y, w, h)$ in viewport-relative CSS pixels.
- **Rasterized Half-Open Area:**
  $$\text{Cols} \in [\lfloor x \rfloor, \lceil x + w \rceil), \quad \text{Rows} \in [\lfloor y \rfloor, \lceil y + h \rceil)$$
- **SAM Mask ($M_\text{SAM}$):** 2D binary matrix $\{0, 1\}^{H \times W}$ produced by Meta SAM 3.1.

### 2. The Core Metrics
- **Visibility Ratio ($V_r$):** The fraction of the DOM element's expected pixel area that is genuinely visible to the user:
  $$V_r = \frac{\text{Area}(M_\text{SAM} \cap B_{\text{DOM\_raster}})}{\text{Area}(B_{\text{DOM\_raster}})}$$
  *Defect Trigger:* Flagged as an occlusion defect if $V_r < 0.85$. Healed state requires $V_r \ge 0.98$.

- **Sibling Collision IoU ($\text{IoU}$):** Intersection-over-Union between adjacent interactive elements:
  $$\text{IoU}(B_A, B_B) = \frac{\text{Area}(B_A \cap B_B)}{\text{Area}(B_A \cup B_B)}$$
  *Defect Trigger:* Flagged if $\text{IoU} > 0.05$.

- **Horizontal Viewport Bleed ($\Delta_x$):** Pixel overflow beyond viewport boundaries:
  $$\Delta_x = \max(0, (x + w) - W_\text{viewport})$$
  *Defect Trigger:* Flagged if $\Delta_x > 2.0\text{px}$.

- **Composite Viewport Health ($H$):**
  $$H = \text{mean}(V_r) - \max(\text{IoU}) - 0.01 \cdot \max(\Delta_x)$$
  *Resolution Gate:* Both Mobile (`375×812`) and Desktop (`1440×900`) must achieve $H \ge 0.98$ for the orchestrator to mark the run `RESOLVED` and auto-commit to GitHub.

---

## 4. Meta AI Foundation Models: Exact Roles & Architecture

VisorQA does **NOT** use a generic chat prompt to blindly edit code. It distributes tasks across specialized Meta Foundation Models using strict typed schemas and separation of concerns:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              META AI MODEL ALLOCATION MATRIX                                           │
├─────────────────┬──────────────────┬─────────────────────────────┬─────────────────────────────────────┤
│ Model Name      │ API Identifier   │ Persona & Configuration     │ Concrete Architectural Duty         │
├─────────────────┼──────────────────┼─────────────────────────────┼─────────────────────────────────────┤
│ Meta SAM 3.1    │ `sam-3.1`        │ Zero-Shot Segmentation      │ Accepts raw PNG screenshot + boxes; │
│                 │                  │ Binary raster generation    │ returns 2D pixel mask (M_SAM).      │
├─────────────────┼──────────────────┼─────────────────────────────┼─────────────────────────────────────┤
│ Meta Muse Spark │ `muse-spark-1.3` │ Triage Engine               │ Receives DOM tree + CSS signatures; │
│                 │                  │ `response_format`:          │ computes LCA; isolates target files;│
│                 │                  │ `SparkTriageSchema`         │ banned from touching UI primitives. │
├─────────────────┼──────────────────┼─────────────────────────────┼─────────────────────────────────────┤
│ Meta Muse Wonder│ `muse-spark-1.3` │ Multimodal Diagnostic Spec  │ Analyzes red collision-mask overlay │
│                 │ (wonder persona) │ `response_format`:          │ image; produces declarative         │
│                 │                  │ `RepairSpec` (Pydantic)     │ RepairSpec JSON (writes NO code).   │
├─────────────────┼──────────────────┼─────────────────────────────┼─────────────────────────────────────┤
│ Meta Muse Code  │ `muse-spark-1.3` │ Surgical Patch Synthesizer  │ Ingests target source + RepairSpec; │
│                 │ (code persona)   │ Verbatim Unified Diff       │ generates minimal patch enforcing   │
│                 │                  │ (Free-text hunk stream)     │ responsive Tailwind & anti-hacks.   │
└─────────────────┴──────────────────┴─────────────────────────────┴─────────────────────────────────────┘
```

### Why This Distribution Excels
1. **No Hallucinated File Edits:** Muse Spark localizes the file; Muse Code is strictly prohibited from touching any other file in the repository.
2. **Component Shielding:** `src/components/ui/*` (shared atomic primitives like buttons, cards) are explicitly blacklisted. Muse Spark must target the layout container, never breaking app-wide primitives.
3. **Anti-Hack CSS Constraints:** Muse Code prompts forbid `!important`, `z-index: 9999`, and hardcoded `margin-top: -300px` hacks. It requires standard CSS flow (`static`, `relative`, `md:static`, `gap-y-4`).
4. **Desktop Preservation Guarantee:** The model is tested against both 375px and 1440px viewports. A fix that cures mobile but breaks desktop is rejected and triggers the next strike attempt.

---

## 5. The 3-Strike Self-Healing Circuit

Rather than guessing endlessly or crashing on unexpected regressions, VisorQA implements a bounded feedback loop:

```
         ┌───────────────┐
         │ Webhook Ingest│
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │   01 SENSE    │ ──▶ E2B Sandbox + Meta SAM 3.1
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │   02 TRIAGE   │ ──▶ Meta Muse Spark (LCA Tree)
         └───────┬───────┘
                 │
                 ▼
    ┌───▶┌───────────────┐
    │    │  03 DIAGNOSE  │ ──▶ Meta Muse Wonder (Multimodal Spec)
    │    └───────┬───────┘
    │            │
    │            ▼
    │    ┌───────────────┐
3 Strikes │   04 PATCH    │ ──▶ Meta Muse Code (Unified Diff)
Max │    └───────┬───────┘
    │            │
    │            ▼
    │    ┌───────────────┐
    │    │   05 VERIFY   │ ──▶ Dual-Viewport Re-Sense (375px + 1440px)
    │    └───────┬───────┘
    │            │
    │   H < 0.98 │ Strikes < 3
    └────────────┤
                 │
       ┌─────────┴───────────────────────┐
       │                                 │
H >= 0.98 on Both Viewports        Strike 3 Exhausted
       │                                 │
       ▼                                 ▼
┌─────────────────────────┐   ┌───────────────────────────────┐
│ RESOLVED                │   │ FAILED / FALLBACK             │
│ • Auto-commit to PR     │   │ • Keep PR clean               │
│ • Rich Telemetry Report │   │ • Post highest-scoring patch  │
│ • Signed by bot         │   │   as non-destructive review   │
└─────────────────────────┘   └───────────────────────────────┘
```

---

## 6. Comprehensive Codebase Map

```
VisorQA/
├── backend/
│   ├── adapters/
│   │   ├── sam31.py             # Meta SAM 3.1 zero-shot segmentation client
│   │   ├── spark_client.py      # Meta Muse Spark LCA triage client (structured output)
│   │   ├── wonder_client.py     # Meta Muse Wonder multimodal diagnostic client
│   │   ├── code_client.py       # Meta Muse Code unified diff patch client
│   │   ├── muse_clients.py      # Abstract adapter interfaces & mock fallbacks
│   │   ├── sandbox_runner.py    # E2B cloud micro-VM runner
│   │   ├── github_app.py        # GitHub App JWT RS256 authentication & token manager
│   │   └── github_client.py     # GitHub REST API client (PR comments & commit pusher)
│   ├── api/
│   │   ├── webhooks.py          # HMAC-SHA256 verified GitHub webhook receiver
│   │   ├── github_repos.py      # Repository management & telemetry comment publishers
│   │   ├── routes_ws.py         # Real-time WebSocket streaming for FSM node transitions
│   │   └── auth.py              # JWT authentication for Mission Control API
│   ├── browser/
│   │   ├── renderer.py          # Headless Playwright capture engine (375x812 & 1440x900)
│   │   ├── overlay.py           # SAM 3.1 visual discrepancy mask generator (Red tint)
│   │   └── schemas.py           # DOM node & bounding box serialization schemas
│   ├── core/
│   │   ├── orchestrator.py      # Deterministic FSM state machine & 3-strike self-healing
│   │   ├── vision_math.py       # NumPy mathematical discrepancy evaluation (Vr, IoU, bleed)
│   │   ├── sense.py             # Node 01: Capture & SAM 3.1 segmentation execution
│   │   ├── triage.py            # Node 02: LCA DOM tree calculation & Spark dispatch
│   │   ├── diagnose.py          # Node 03: Multimodal image cropping & Wonder dispatch
│   │   ├── patch.py             # Node 04: Diff validation, anti-hack filters & Code dispatch
│   │   ├── verify.py            # Node 05: Sandbox patch application & dual re-sensing
│   │   ├── state.py             # Immutable domain dataclasses (RepairSpec, TriageCandidate)
│   │   └── github_publish.py    # Deduplicated PR telemetry report builder
│   ├── db/
│   │   ├── models.py            # SQLModel/SQLAlchemy PostgreSQL 16 schema
│   │   └── repository.py        # Transactional database access layer
│   ├── sandbox/
│   │   ├── e2b_executor.py      # Isolated E2B micro-VM container manager
│   │   └── patch_utils.py       # Atomic unified diff application & syntax validator
│   ├── config.py                # Pydantic Settings (Meta API keys, GitHub App IDs, E2B)
│   └── main.py                  # FastAPI application entrypoint & middleware
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx                    # Production landing page with Proof Preview
│   │   │   └── mission-control/page.tsx    # Live FSM Operations Dashboard
│   │   ├── components/
│   │   │   ├── landing/ProofPreview.tsx    # Interactive Before/After slider preview
│   │   │   ├── mission-control/
│   │   │   │   ├── FSMOrchestratorBar.tsx  # 5-Node live stepper with animated SVG states
│   │   │   │   ├── VisualEvidenceCard.tsx  # Split before/after image comparison widget
│   │   │   │   ├── UnifiedDiffViewer.tsx   # Syntax-highlighted git diff display
│   │   │   │   └── TelemetryMetrics.tsx    # Math Traps scorecard (Vr, IoU, Bleed, H)
│   │   │   └── ui/                         # Clean, atomic Tailwind/Radix UI components
│   │   └── hooks/
│   │       └── useMissionControlStream.ts  # 500ms REST polling + WebSocket state sync
│
├── scripts/
│   ├── prep_video.sh            # One-click environment reset for demo recordings
│   └── reset_pr3_for_demo.py    # Idempotent GitHub PR #3 branch & comment reset tool
│
├── tests/                       # Complete pytest suite (FSM, Math, Sandbox, Regression)
└── DEMO_RUNBOOK.md              # 150-second screen-recording presentation script
```

---

## 7. Critical SWE Signals for Technical Evaluation

When evaluating the engineering quality of this project, look for these specific software design indicators:

| Engineering Signal | Why It Demonstrates Senior/Principal Engineering Rigour |
| :--- | :--- |
| **Deterministic FSM vs Unbounded Agent Loops** | Instead of an unpredictable LangChain/AutoGPT loop that burns tokens and drifts, VisorQA executes a strictly bounded 5-stage state machine with max 3 attempts. State transitions are deterministic and testable. |
| **Mathematical Grounding ($V_r$, $\text{IoU}$, $\Delta_x$)** | Decisions are not based on LLM "feelings." Every bug detection and patch verification is backed by exact float64 raster-pixel mathematics. |
| **Dual-Viewport Regression Testing** | Most AI code generators fix mobile by destroying desktop layouts. VisorQA guarantees desktop preservation by enforcing dual-viewport ($375\text{px} + 1440\text{px}$) re-verification on every patch attempt. |
| **Anti-Hack Patch Constraints** | Rejects brute-force LLM escapes like `!important`, `z-index: 9999`, or negative margins. Enforces modern CSS stacking context and responsive Tailwind flow (`md:static`, `gap-y-4`). |
| **Sandbox Security Isolation** | Code modification and execution happen inside isolated **E2B Micro-VMs**, completely decoupling untrusted user repositories from the host infrastructure. |
| **Idempotent GitHub Integration** | Deduplicates PR comments by cleaning up prior bot reports before posting, eliminating comment spam. Auto-commits are signed and pushed cleanly via GitHub App installation tokens. |
| **Sub-10ms UI State Sync** | An in-memory atomic live store ensures that UI polling (`GET /api/runs/{id}`) returns stage transitions in `<10ms` without blocking the asyncio loop during heavy Playwright or Playbook execution. |

---

## 8. Summary Checklist for Reviewers

- [x] **Meta SAM 3.1:** Active in Node 01 (`sense.py`) for zero-shot pixel mask segmentation.
- [x] **Meta Muse Spark:** Active in Node 02 (`triage.py`) for LCA component mapping with structured JSON output.
- [x] **Meta Muse Wonder:** Active in Node 03 (`diagnose.py`) for multimodal visual reasoning and `RepairSpec` production.
- [x] **Meta Muse Code:** Active in Node 04 (`patch.py`) for responsive unified diff synthesis.
- [x] **E2B Sandbox:** Active in Node 01 & 05 for isolated headless browser rendering & hot-reload verification.
- [x] **GitHub Bot:** Active in Node 05 for automated PR telemetry reporting and verified fix commits.
- [x] **Safety Circuit:** 3-strike limit with highest-$H$ score review fallback prevents destructive commits.
