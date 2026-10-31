# VisorQA

**Autonomous Visual QA and Self-Healing Frontend Agent**

VisorQA is a closed-loop autonomous agent that detects pixel-level UI regressions invisible to conventional DOM-based test suites (Playwright assertions, Cypress snapshots, Percy visual diffing), mathematically diagnoses their root cause, and commits verified CSS/React fixes to the originating pull request -- all without human intervention.

Built for the **Meta Global AI Developer Hackathon** using three Meta AI foundation models: **SAM 3.1**, **Muse Spark**, and **Muse Wonder**.

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Core Thesis](#core-thesis)
- [Mathematical Discrepancy Engine](#mathematical-discrepancy-engine)
- [Five-Node FSM Pipeline](#five-node-fsm-pipeline)
- [Three-Strike Self-Healing Loop](#three-strike-self-healing-loop)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Database Schema](#database-schema)
- [Getting Started](#getting-started)
- [Configuration Reference](#configuration-reference)
- [Design Constraints and Safety Guardrails](#design-constraints-and-safety-guardrails)
- [Documentation](#documentation)
- [License](#license)

---

## Problem Statement

Standard frontend testing tools operate at the DOM abstraction layer. They assert that elements exist, that attributes match expectations, and that text content is correct. They do not answer the question that matters to end users:

> **Is this component actually visible, unobstructed, and correctly positioned on the rendered screen?**

A `<button>` can pass every Playwright assertion (`toBeVisible`, `toHaveText`, `toHaveCSS`) while being completely hidden behind a promotional banner due to a `z-index` collision. A navigation grid can satisfy Cypress snapshot matching while its children overlap by 37 pixels on mobile viewports. These are real production defects that ship to users because no test in the existing pipeline inspects the *pixel-level rendering output* against the *expected DOM geometry*.

VisorQA closes this gap.

---

## Core Thesis

VisorQA introduces a formal verification layer between DOM geometry (what the browser *computes*) and pixel masks (what the user *sees*). For every interactive UI component, the system extracts two representations:

| Symbol | Definition | Source |
| :--- | :--- | :--- |
| $B_{DOM}$ | Expected DOM bounding box (x, y, width, height) | Playwright `element.boundingBox()` inside Modal sandbox |
| $M_{SAM}$ | Actual visible pixel mask at render time | Meta SAM 3.1 zero-shot segmentation |

Any measurable discrepancy between $B_{DOM}$ and $M_{SAM}$ constitutes a visual anomaly. The system classifies, triages, and repairs these anomalies autonomously.

---

## Mathematical Discrepancy Engine

All defect detection is grounded in three deterministic equations evaluated over NumPy arrays. No heuristics. No thresholds learned from training data. The math is explicit and auditable.

### 1. Occlusion Detection (Visibility Ratio)

$$V_r = \frac{\text{Area}(M_{SAM} \cap B_{DOM})}{\text{Area}(B_{DOM})}$$

An element is classified as **occluded** when $V_r < 0.85$. This captures z-index collisions, overflow clipping, and any scenario where a component's rendered pixel footprint is smaller than its computed DOM box.

**Verification threshold:** A patch is accepted when $V_r \geq 0.98$ on both viewports.

### 2. Layout Collision (Intersection over Union)

$$IoU(M_i, M_j) = \frac{\text{Area}(M_i \cap M_j)}{\text{Area}(M_i \cup M_j)}$$

Sibling components are classified as **colliding** when $IoU > 0.05$. This detects overlapping text, badges obscuring buttons, and flex-wrap failures where children share pixel territory.

**Verification threshold:** A patch is accepted when $IoU = 0$ across all sibling pairs.

### 3. Viewport Bleed (Overflow Detection)

$$\Delta_x = \max(0,\ X_{max} - W_{vp})$$

A component is classified as **bleeding** when $\Delta_x > 2\text{px}$. This detects horizontal overflow on constrained mobile viewports where content extends beyond the visible boundary.

**Verification threshold:** A patch is accepted when $\Delta_x \leq 2\text{px}$.

### Composite Health Score

The system computes a single scalar health metric per run:

$$H = \overline{V_r} - \max(IoU)$$

A run is marked `RESOLVED` when $H \geq 0.98$ across both the 375px (mobile) and 1440px (desktop) viewports simultaneously.

---

## Five-Node FSM Pipeline

VisorQA operates as a deterministic finite state machine with five sequential nodes. Each node maps to exactly one Meta AI model or infrastructure component. The FSM is triggered by a GitHub `pull_request` or `push` webhook event and requires zero human interaction.

```
SENSE --> TRIAGE --> DIAGNOSE --> PATCH --> VERIFY
  |                                          |
  |          3-Strike Loop (max 3)           |
  |         <--- if V_r < 0.98 or IoU > 0 --|
```

### Node 1: SENSE (Playwright + Meta SAM 3.1)

Boot the PR branch inside an isolated Modal container. Launch headless Playwright across two viewports (375x812 mobile, 1440x900 desktop). Extract $B_{DOM}$ bounding boxes and computed CSS styles for every `visor-el-*` annotated component. Prompt SAM 3.1 with DOM-guided point coordinates $(c_x, c_y)$ and bounding box priors to generate 1:1 pixel masks $M_{SAM}$. Evaluate $V_r$, $IoU$, and $\Delta_x$ against thresholds. Emit `SENSE_COMPLETE` with detected anomalies.

**Latency target:** < 450ms per viewport.

### Node 2: TRIAGE (Muse Spark)

Receive the anomaly list and the pruned DOM subtree. Compute the Lowest Common Ancestor (LCA) container in the DOM hierarchy. Map each defect to candidate repository source files. Distinguish between protected shared UI components (`src/components/ui/*`) that must not be modified and target layout files that are safe to patch. Emit `TRIAGE_COMPLETE` with `target_files[]`.

**Latency target:** < 600ms. **Token reduction:** 88.5% versus sending the full DOM tree.

### Node 3: DIAGNOSE (Muse Wonder)

Multi-modal visual reasoning. Receives the cropped mask overlay image, mathematical telemetry ($V_r$, $IoU$, $\Delta_x$), computed CSS properties, and target file contents. Produces a structured Pydantic `repair_spec` JSON specifying the exact CSS property changes required, the root-cause explanation, and layout constraints that must be preserved.

### Node 4: PATCH (Muse Code + Modal HMR)

Receives `repair_spec` and the current source file content. Synthesizes a unified diff patch. Applies the diff to the running Modal sandbox via Hot Module Replacement (HMR) with a target reload latency of 300ms. The patch is validated against safety constraints before application (see [Design Constraints](#design-constraints-and-safety-guardrails)).

### Node 5: VERIFY (Dual-Viewport Re-Segmentation)

Re-captures screenshots on both 375px and 1440px viewports. Re-runs SAM 3.1 segmentation and the full math engine. Evaluates whether $V_r \geq 0.98$, $IoU = 0$, and $\Delta_x \leq 2\text{px}$ on **both** viewports simultaneously (BR-3: Cross-Viewport Zero Regression). If verification passes, the FSM transitions to `RESOLVED` and commits the fix. If verification fails, the FSM increments the attempt counter and loops back to `DIAGNOSE`.

---

## Three-Strike Self-Healing Loop

The DIAGNOSE-PATCH-VERIFY cycle repeats up to three times. This is enforced at the database level:

```sql
CHECK (attempt >= 0 AND attempt <= 3)   -- chk_pr_runs_3_strike_cap
```

| Attempt | On Failure | On Success |
| :--- | :--- | :--- |
| 1 | Feed `new_anomalies` and previous diff back to DIAGNOSE. Loop. | Set `is_resolved = True`. Auto-commit to PR branch. |
| 2 | Feed updated context. Loop. | Same as above. |
| 3 | Halt. Post `best_patch` (highest $H$ score) as a non-destructive GitHub PR review comment for human inspection. | Same as above. |

The system always preserves the best-scoring patch across all attempts:

```
if score > best_score:
    best_patch = current_patch
    best_score = score
```

---

## System Architecture

VisorQA follows a 1-Level Clean Architecture with five distinct layers:

```
+--------------------+---------------------+--------------------------+------------------------+----------------------------+
| 1. Presentation    | 2. API & Persistence| 3. Core Domain & FSM     | 4. Infrastructure      | 5. External Services       |
| & Triggers         |                     |                          |    Adapters            |                            |
+--------------------+---------------------+--------------------------+------------------------+----------------------------+
| GitHub Repository  | api/webhooks.py     | core/state.py            | adapters/              | Modal Isolated Sandbox     |
|   Webhook Events   |   HMAC-SHA256       |   AgentState (Pydantic)  |   sandbox_runner.py    |   Playwright (375/1440px)  |
|                    |   < 1.2s trigger    |   FSM transitions        |   Strategy Pattern     |   HMR Patch Reload (0.3s)  |
| Next.js Dashboard  |                     |                          |                        |                            |
|   MaskSlider.tsx   | api/routes_ws.py    | core/orchestrator.py     |   muse_clients.py      | Meta SAM 3.1               |
|   LiveTrace.tsx    |   GET /api/runs/:id |   5-Node FSM Engine      |   Adapter Pattern      |   DOM-Guided Point Prompts |
|   DiffViewer.tsx   |   WS /ws/runs/:id   |   3-Strike Guardrail     |   AsyncOpenAI Client   |   1:1 Pixel Masks (0.45s)  |
|                    |                     |                          |                        |                            |
|                    | db/repository.py    | core/vision_math.py      |   github_client.py     | Muse Spark (2M TPM)        |
|                    |   PostgreSQL 16     |   NumPy V_r, IoU, Bleed  |   Adapter Pattern      |   LCA Tree Triage (0.6s)   |
|                    |   SQLModel+asyncpg  |   Composite Health Score |   PyGithub Commits     |   88.5% Token Reduction    |
|                    |   EER Constraints   |                          |   PR Review Fallback   |                            |
|                    |   GIN/Covering Idx  |                          |                        | Muse Wonder (Architect)    |
|                    |                     |                          |                        |   Multimodal Diagnosis     |
|                    |                     |                          |                        |   JSON repair_spec         |
|                    |                     |                          |                        |                            |
|                    |                     |                          |                        | Muse Code (Patcher)        |
|                    |                     |                          |                        |   Unified Diff Synthesis   |
+--------------------+---------------------+--------------------------+------------------------+----------------------------+
```

Detailed architecture diagrams are available in the [`Docs/`](Docs/) directory.

---

## Technology Stack

### Backend

| Component | Technology | Role |
| :--- | :--- | :--- |
| API Server | FastAPI + Uvicorn (ASGI) | Webhook ingestion, REST endpoints, WebSocket streaming |
| Database | PostgreSQL 16 + SQLModel + asyncpg | Persistence with EER CHECK constraints and GIN indexes |
| Vision Math | NumPy | Deterministic $V_r$, $IoU$, $\Delta_x$ computation |
| State Management | Pydantic v2 | `AgentState` FSM model with strict validation |
| Browser Automation | Playwright | DOM geometry extraction across dual viewports |
| Sandbox Isolation | Modal | Cloud container HMR with < 300ms reload |
| GitHub Integration | PyGithub | HMAC-SHA256 webhook verification, auto-commits, PR reviews |

### Frontend

| Component | Technology | Role |
| :--- | :--- | :--- |
| Framework | Next.js 15 (App Router) | Server-rendered dashboard with real-time updates |
| Styling | Tailwind CSS | Monochrome design system with AI Harmony accents |
| Typography | Space Grotesk / Inter / JetBrains Mono | Display, body, and mathematical/code rendering |
| Real-Time | Native WebSockets | Live FSM state streaming from backend |

### Meta AI Models

| Model | Pipeline Node | Function |
| :--- | :--- | :--- |
| **SAM 3.1** | SENSE | Zero-shot pixel-level component segmentation |
| **Muse Spark** | TRIAGE | Ultra-fast LCA DOM hierarchy mapping and file triage |
| **Muse Wonder** | DIAGNOSE | Multi-modal visual reasoning and CSS root-cause diagnosis |
| **Muse Code** | PATCH | Surgical unified diff generation for CSS/React repairs |

---

## Repository Structure

```
VisorQA/
|-- backend/
|   |-- adapters/
|   |   |-- github_client.py        # PyGithub: HMAC verification, auto-commit, PR review
|   |   |-- muse_clients.py         # SAM 3.1, Muse Spark, Muse Wonder, Muse Code adapters
|   |   |-- sandbox_runner.py       # Strategy pattern: Modal cloud / local Playwright sandbox
|   |-- api/
|   |   |-- webhooks.py             # POST /api/webhooks/github (HMAC-SHA256 verified)
|   |   |-- routes_ws.py            # GET /api/runs/:id, WS /ws/runs/:id
|   |-- core/
|   |   |-- orchestrator.py         # 5-node FSM engine with 3-strike self-healing loop
|   |   |-- state.py                # AgentState Pydantic model, FSMStep enum, domain schemas
|   |   |-- vision_math.py          # NumPy: V_r, IoU, viewport bleed calculations
|   |-- db/
|   |   |-- repository.py           # PostgreSQL 16 SQLModel schema + repository pattern DAL
|   |-- config.py                   # Pydantic Settings with mathematical threshold constants
|   |-- main.py                     # FastAPI entrypoint with lifespan hooks
|   |-- requirements.txt
|-- frontend/
|   |-- src/
|   |   |-- app/
|   |   |   |-- page.tsx            # Mission control dashboard (auto-selects active run)
|   |   |   |-- runs/[id]/page.tsx  # Deep-link PR run inspector (shareable via PR comment)
|   |   |-- components/
|   |   |   |-- MaskSlider.tsx      # Before/after SAM mask overlay with dual-viewport toggle
|   |   |   |-- LiveTrace.tsx       # Real-time WebSocket FSM step terminal
|   |   |   |-- DiffViewer.tsx      # Syntax-highlighted unified diff viewer
|   |   |-- types/
|   |       |-- index.ts            # TypeScript domain type definitions
|   |-- package.json
|   |-- tailwind.config.ts
|   |-- tsconfig.json
|-- demo-target-app/                # Sample storefront with 3 reproducible visual regressions
|-- Docs/                           # Architecture diagrams, SRS, ADR, technical design PDFs
|-- Design.md                       # UI/UX design specification
|-- docker-compose.yml              # PostgreSQL 16 Alpine container
|-- .env.example                    # Environment variable template
```

---

## Database Schema

Four tables with PostgreSQL 16 CHECK constraints, GIN indexes, and covering indexes:

### `repositories`

Multi-tenant repository configuration. Stores protected glob patterns (JSONB) and commit mode policy (`AUTO_COMMIT` or `SUGGEST_REVIEW`).

### `pr_runs`

Master FSM state record per webhook execution. Enforces the 3-strike cap and a per-run cost guardrail at the database level:

```sql
CHECK (attempt >= 0 AND attempt <= 3)       -- 3-strike cap
CHECK (total_cost_usd <= 0.15)              -- cost guardrail per run
```

Includes a partial index for active queue queries:

```sql
CREATE INDEX idx_pr_runs_active_queue
ON pr_runs (created_at ASC)
WHERE status NOT IN ('RESOLVED', 'FALLBACK', 'FAILED');
```

### `visual_anomalies`

EER-specialized anomaly records with conditional CHECK constraints enforcing the mathematical subtype equations at the persistence layer:

```sql
CHECK (
    (defect_type = 'OCCLUSION'  AND v_r IS NOT NULL      AND v_r < 0.85)      OR
    (defect_type = 'COLLISION'  AND iou IS NOT NULL       AND iou > 0.05)      OR
    (defect_type = 'BLEED'      AND bleed_px IS NOT NULL  AND bleed_px > 2.0)
)
```

### `repair_attempts`

Audit trail for the 3-strike loop. Enforces the anti-hack CSS policy (BR-4) directly in the database:

```sql
CHECK (
    unified_diff IS NULL OR (
        unified_diff NOT ILIKE '%!important%'       AND
        unified_diff NOT ILIKE '%z-index: 9999%'    AND
        unified_diff NOT ILIKE '%z-[9999]%'
    )
)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose
- PostgreSQL 16 (provided via Docker)
- Meta AI API key

### 1. Clone the Repository

```bash
git clone https://github.com/sayedibrahimQ/VisorQA.git
cd VisorQA
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your Meta AI API key, GitHub PAT, and webhook secret
```

### 3. Start PostgreSQL

```bash
docker compose up -d
```

### 4. Install Backend Dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 5. Start the Backend Server

```bash
python -m backend.main
```

The API server starts at `http://localhost:8000`. Database tables are created automatically on first startup.

### 6. Install and Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard starts at `http://localhost:3000`.

### 7. Verify the Setup

```bash
curl http://localhost:8000/health
```

Expected response:

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

All configuration is managed via environment variables with Pydantic Settings validation. See [`.env.example`](.env.example) for the full template.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `META_API_KEY` | -- | Meta Model API key for SAM 3.1, Muse Spark, Muse Wonder, Muse Code |
| `META_BASE_URL` | `https://api.meta.ai/v1` | Meta Model API base URL (Muse Spark triage) |
| `MUSE_SPARK_MODEL` | `muse-spark-1.3` | Muse Spark triage model |
| `MUSE_WONDER_MODEL` | `muse-wonder-1.0` | Muse Wonder diagnosis model |
| `MUSE_CODE_MODEL` | `muse-spark-1.3` | Muse Code patch model (built on Muse Spark) |
| `DATABASE_URL` | `postgresql+asyncpg://visorqa:visorqa@localhost:5432/visorqa` | PostgreSQL connection string |
| `GITHUB_PAT` | -- | GitHub Personal Access Token (repo + pull_request scopes) |
| `GITHUB_WEBHOOK_SECRET` | -- | HMAC-SHA256 secret for webhook signature verification |
| `MODAL_TOKEN` | -- | Modal token for isolated cloud sandbox execution |
| `VISIBILITY_RATIO_THRESHOLD` | `0.85` | $V_r$ occlusion detection threshold |
| `IOU_COLLISION_THRESHOLD` | `0.05` | $IoU$ collision detection threshold |
| `MAX_SELF_HEALING_ATTEMPTS` | `3` | Maximum iterations of the self-healing loop |

---

## Design Constraints and Safety Guardrails

VisorQA enforces several hard constraints to prevent the autonomous agent from producing destructive or low-quality patches:

| ID | Constraint | Enforcement Layer |
| :--- | :--- | :--- |
| BR-1 | Maximum 3 self-healing attempts per run | PostgreSQL CHECK + FSM logic |
| BR-2 | Per-run inference cost capped at $0.15 USD | PostgreSQL CHECK constraint |
| BR-3 | Cross-viewport zero regression: verification must pass on both 375px and 1440px simultaneously | VERIFY node dual-viewport re-segmentation |
| BR-4 | Anti-hack CSS policy: patches must not contain `!important`, `z-index: 9999`, or `z-[9999]` | PostgreSQL CHECK constraint on `repair_attempts.unified_diff` |
| BR-5 | Protected shared UI components (`src/components/ui/*`) are never modified | TRIAGE node glob exclusion |
| BR-6 | 3-strike fallback: if all attempts fail, the best patch is posted as a non-destructive PR review comment rather than committed | FSM terminal state logic |
| BR-7 | Viewport constraint: anomalies are only valid for `375px` or `1440px` viewports | PostgreSQL CHECK constraint |

---

## Documentation

Comprehensive documentation is available in the [`Docs/`](Docs/) directory:

| Document | Contents |
| :--- | :--- |
| [Architecture Decision Records and Engineering Blueprint](Docs/VisorQA%20Architecture%20Decision%20Records%20%26%20Engineering%20Blueprint.pdf) | ADRs, design rationale, and trade-off analysis |
| [Software Requirements Specification (SRS)](Docs/VisorQA%20Software%20Requirements%20Specification%20(SRS).pdf) | Functional and non-functional requirements, use cases |
| [Technical Design Specification](Docs/VisorQA%20Technical%20Design%20Specification.pdf) | Detailed component design, data flow, sequence diagrams |
| [Autonomous Visual QA and Self-Healing Frontend Agent](Docs/Autonomous%20Visual%20QA%20%26%20Self-Healing%20Frontend%20Agent.pdf) | Project overview and agent behavioral specification |
| [UI/UX Design Specification](Design.md) | Color system, typography, layout wireframes, component catalog |

---

## License

This project was built for the Meta Global AI Developer Hackathon.
